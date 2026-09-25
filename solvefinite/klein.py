"""Finite Klein quotient, its orientation cover, and intrinsic ball boundaries.

The integer chart labels describe a finite cell complex, not an embedding in
physical space. Surface claims are checked from edge incidences and vertex
links, independently of the expected Euler characteristic.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .runtime import _integer

if TYPE_CHECKING:
    from .field import FieldManifest


def _edge(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


def _cycle(face: tuple[int, ...]) -> tuple[int, ...]:
    """Canonicalize a cell boundary up to rotation and reversal."""
    reverse = face[::-1]
    return min(sequence[offset:] + sequence[:offset]
               for sequence in (face, reverse) for offset in range(len(face)))


def _connected(neighbors: list) -> bool:
    seen, pending = {0}, [0]
    while pending:
        for neighbor in neighbors[pending.pop()]:
            if neighbor not in seen:
                seen.add(neighbor)
                pending.append(neighbor)
    return len(seen) == len(neighbors)


def audit_surface(vertex_count: int, edges: object, faces: object) -> dict:
    """Validate a connected, closed quadrilateral 2-manifold.

    Edges are canonical endpoint pairs or positive-weight triples; faces are
    ordered quadruples. Tuple and list inputs are accepted for independent
    audits. Invalid incidences, disconnected vertex links and unused cells
    raise ``ValueError``. Orientability is measured by solving every dual-edge
    orientation constraint, not assumed from counts or a topology label.
    """
    if type(vertex_count) is not int or vertex_count < 1:
        raise ValueError("vertex_count must be a positive strict integer")
    if type(edges) not in (tuple, list) or type(faces) not in (tuple, list):
        raise ValueError("Surface edges and faces must be sequences")
    neighbors = [set() for _ in range(vertex_count)]
    incidence: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for edge in edges:
        if type(edge) not in (tuple, list) or len(edge) not in (2, 3):
            raise ValueError("A surface edge requires two endpoints and optional weight")
        u, v = edge[:2]
        _integer(u, 0, vertex_count - 1, "edge source")
        _integer(v, 0, vertex_count - 1, "edge destination")
        if u >= v or (u, v) in incidence:
            raise ValueError("Surface edges must have distinct unique canonical endpoints")
        if len(edge) == 3 and (type(edge[2]) is not int or edge[2] < 1):
            raise ValueError("Surface edge weights must be positive strict integers")
        incidence[u, v] = []
        neighbors[u].add(v)
        neighbors[v].add(u)
    if not _connected(neighbors):
        raise ValueError("Surface graph must be connected")

    # A vertex link has one vertex for each incident graph edge. Each corner
    # contributes one link edge between the incoming and outgoing neighbors.
    # Keep multiplicities: a two-edge cycle is different from one link edge.
    links: list[dict[int, list[int]]] = [
        {neighbor: [] for neighbor in adjacent} for adjacent in neighbors
    ]
    for index, face in enumerate(faces):
        if type(face) not in (tuple, list) or len(face) != 4:
            raise ValueError("Every surface face must be an ordered quadruple")
        for vertex in face:
            _integer(vertex, 0, vertex_count - 1, "face vertex")
        if len(set(face)) != 4:
            raise ValueError("Every surface face must have four distinct corners")
        for corner, u in enumerate(face):
            v = face[(corner + 1) % 4]
            edge = _edge(u, v)
            if edge not in incidence:
                raise ValueError("A face boundary uses an undeclared edge")
            incidence[edge].append((index, 1 if u < v else -1))
        for corner, vertex in enumerate(face):
            previous, following = face[corner - 1], face[(corner + 1) % 4]
            links[vertex][previous].append(following)
            links[vertex][following].append(previous)
    if not incidence or any(len(rows) != 2 for rows in incidence.values()):
        raise ValueError("Every surface edge must have exactly two incident faces")
    for link in links:
        if not link or any(len(adjacent) != 2 for adjacent in link.values()):
            raise ValueError("Every vertex link must be one cycle")
        first = next(iter(link))
        seen, pending = {first}, [first]
        while pending:
            for neighbor in link[pending.pop()]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    pending.append(neighbor)
        if len(seen) != len(link):
            raise ValueError("Every vertex link must be one connected cycle")

    dual: list[list[tuple[int, int]]] = [[] for _ in faces]
    for (f, d_f), (g, d_g) in incidence.values():
        multiplier = -d_f * d_g
        dual[f].append((g, multiplier))
        dual[g].append((f, multiplier))
    orientations: dict[int, int] = {}
    orientable = True
    for seed in range(len(faces)):
        if seed in orientations:
            continue
        orientations[seed] = 1
        pending = [seed]
        while pending:
            f = pending.pop()
            for g, multiplier in dual[f]:
                candidate = multiplier * orientations[f]
                if g not in orientations:
                    orientations[g] = candidate
                    pending.append(g)
                elif orientations[g] != candidate:
                    orientable = False
    return {
        "vertices": vertex_count, "edges": len(edges), "faces": len(faces),
        "euler_characteristic": vertex_count - len(edges) + len(faces),
        "connected": True, "closed": True, "edge_incidence": True,
        "vertex_links": True, "orientable": orientable,
    }


def _lift_faces(faces: tuple, seams: frozenset) -> tuple[tuple[int, ...], ...]:
    result = []
    for face in faces:
        for orientation in (0, 1):
            eta = orientation
            lifted = []
            for index, vertex in enumerate(face):
                lifted.append(2 * vertex + eta)
                eta ^= int(_edge(vertex, face[(index + 1) % 4]) in seams)
            if eta != orientation:
                raise ValueError("Seam cocycle does not close around a face")
            result.append(tuple(lifted))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class KleinDomain:
    """An immutable ``W by H`` Klein grid with its actual cells and cover.

    Base and cover edges are sorted ``(u,v,1)`` triples. Seam entries are
    sorted ``(u,v)`` pairs. Faces retain their ordered boundary corners.
    Construction generates the cells; ``audit()`` checks the surface claim.
    """

    width: int = 8
    height: int = 8
    nodes: tuple[str, ...] = field(init=False)
    edges: tuple[tuple[int, int, int], ...] = field(init=False)
    seams: tuple[tuple[int, int], ...] = field(init=False)
    faces: tuple[tuple[int, ...], ...] = field(init=False)
    cover_edges: tuple[tuple[int, int, int], ...] = field(init=False)
    cover_faces: tuple[tuple[int, ...], ...] = field(init=False)

    def __post_init__(self) -> None:
        _integer(self.width, 3, 256, "width")
        _integer(self.height, 3, 256, "height")
        if self.width * self.height > 256:
            raise ValueError("Klein grid must contain at most 256 nodes")
        nodes = tuple(f"k:{u}:{v}" for u in range(self.width)
                      for v in range(self.height))
        edges, seams, faces = set(), set(), []
        for u in range(self.width):
            for v in range(self.height):
                source = self.node(u, v)
                horizontal = _edge(source, self.node(u + 1, v))
                edges.add(horizontal)
                edges.add(_edge(source, self.node(u, v + 1)))
                if u == self.width - 1:
                    seams.add(horizontal)
                faces.append((source, self.node(u + 1, v),
                              self.node(u + 1, v + 1), self.node(u, v + 1)))
        lifted_edges = {
            _edge(2 * u + eta, 2 * v + (eta ^ int((u, v) in seams)))
            for u, v in edges for eta in (0, 1)
        }
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", tuple((u, v, 1) for u, v in sorted(edges)))
        object.__setattr__(self, "seams", tuple(sorted(seams)))
        object.__setattr__(self, "faces", tuple(faces))
        object.__setattr__(self, "cover_edges",
                           tuple((u, v, 1) for u, v in sorted(lifted_edges)))
        object.__setattr__(self, "cover_faces", _lift_faces(self.faces, frozenset(seams)))

    def canonical(self, u: int, v: int, orientation: int = 0) -> tuple[int, int, int]:
        """Reduce any strict integer chart labels, transporting orientation."""
        if type(u) is not int or type(v) is not int:
            raise ValueError("Chart labels must be strict integers")
        _integer(orientation, 0, 1, "orientation")
        quotient, u0 = divmod(u, self.width)
        reversed_frame = quotient % 2
        return u0, (-v if reversed_frame else v) % self.height, orientation ^ reversed_frame

    def node(self, u: int, v: int) -> int:
        """Return the canonical base-node index of chart labels."""
        u0, v0, _ = self.canonical(u, v)
        return u0 * self.height + v0

    def step(self, node: int, direction: str) -> tuple[int, int]:
        """Follow one chart-local unit step and return destination and seam bit."""
        _integer(node, 0, self.width * self.height - 1, "node")
        if type(direction) is not str or direction not in ("u+", "u-", "v+", "v-"):
            raise ValueError("direction must be u+, u-, v+ or v-")
        u, v = divmod(node, self.height)
        du, dv = {"u+": (1, 0), "u-": (-1, 0),
                  "v+": (0, 1), "v-": (0, -1)}[direction]
        u0, v0, seam = self.canonical(u + du, v + dv)
        return u0 * self.height + v0, seam

    def ball_signs(self, center: int, radius: int) -> tuple[int, ...]:
        """Classify graph distance from a center relative to an integer radius."""
        count = len(self.nodes)
        _integer(center, 0, count - 1, "center")
        neighbors = [[] for _ in self.nodes]
        for u, v, _ in self.edges:
            neighbors[u].append(v)
            neighbors[v].append(u)
        distances = [-1] * count
        distances[center] = 0
        pending = deque([center])
        while pending:
            node = pending.popleft()
            for neighbor in neighbors[node]:
                if distances[neighbor] == -1:
                    distances[neighbor] = distances[node] + 1
                    pending.append(neighbor)
        _integer(radius, 1, max(distances), "radius")
        return tuple((distance > radius) - (distance < radius) for distance in distances)

    def audit(self) -> dict:
        """Independently check the base, cocycle, cover, torus map and holonomy."""
        count = self.width * self.height
        base = audit_surface(count, self.edges, self.faces)
        cover = audit_surface(2 * count, self.cover_edges, self.cover_faces)
        for report, vertices, orientable in ((base, count, False),
                                             (cover, 2 * count, True)):
            if (report["vertices"], report["edges"], report["faces"]) != (
                    vertices, 2 * vertices, vertices):
                raise ValueError("Klein base or cover has incorrect cell counts")
            if report["euler_characteristic"] != 0 or report["orientable"] != orientable:
                raise ValueError("Klein base or cover has incorrect surface invariants")
        if self.nodes != tuple(f"k:{u}:{v}" for u in range(self.width)
                               for v in range(self.height)):
            raise ValueError("Klein node names disagree with the quotient")
        if any(weight != 1 for _, _, weight in self.edges + self.cover_edges):
            raise ValueError("Klein base and cover require unit edges")
        base_edges = {(u, v) for u, v, _ in self.edges}
        if (type(self.seams) is not tuple
                or any(type(edge) is not tuple or len(edge) != 2 for edge in self.seams)):
            raise ValueError("Seams must be immutable endpoint pairs")
        for u, v in self.seams:
            _integer(u, 0, count - 1, "seam source")
            _integer(v, 0, count - 1, "seam destination")
            if u >= v or (u, v) not in base_edges:
                raise ValueError("Seams must be canonical declared edges")
        seams = frozenset(self.seams)
        if self.seams != tuple(sorted(seams)):
            raise ValueError("Seams must be unique and sorted")
        lifted_faces = _lift_faces(self.faces, seams)
        lifted_edges = tuple(sorted(
            (*_edge(2 * u + eta, 2 * v + (eta ^ int((u, v) in seams))), 1)
            for u, v in base_edges for eta in (0, 1)
        ))
        if lifted_edges != self.cover_edges or lifted_faces != self.cover_faces:
            raise ValueError("Cover cells disagree with the declared seam lift")

        # This coordinate map is checked against a separately generated torus,
        # for every edge and face, including the seam and both cover sheets.
        mapping = []
        for node in range(count):
            u, v = divmod(node, self.height)
            for eta in (0, 1):
                mapping.append((u + eta * self.width) * self.height
                               + ((-v if eta else v) % self.height))
        if set(mapping) != set(range(2 * count)):
            raise ValueError("Cover-to-torus vertex map is not a bijection")
        torus_width = 2 * self.width

        def torus_node(u: int, v: int) -> int:
            return (u % torus_width) * self.height + v % self.height

        torus_edges, torus_faces = set(), set()
        for u in range(torus_width):
            for v in range(self.height):
                source = torus_node(u, v)
                torus_edges.add(_edge(source, torus_node(u + 1, v)))
                torus_edges.add(_edge(source, torus_node(u, v + 1)))
                torus_faces.add(_cycle((source, torus_node(u + 1, v),
                                       torus_node(u + 1, v + 1), torus_node(u, v + 1))))
        mapped_edges = {_edge(mapping[u], mapping[v]) for u, v, _ in self.cover_edges}
        mapped_faces = {_cycle(tuple(mapping[v] for v in face)) for face in self.cover_faces}
        if mapped_edges != torus_edges:
            raise ValueError("Cover edge map disagrees with the periodic torus")
        if mapped_faces != torus_faces:
            raise ValueError("Cover face map disagrees with the periodic torus")

        holonomy = {}
        cover_edges = {(u, v) for u, v, _ in self.cover_edges}
        for name, direction, steps, expected in (
                ("horizontal", "u+", self.width, 1),
                ("double_horizontal", "u+", 2 * self.width, 0),
                ("vertical", "v+", self.height, 0)):
            node, eta = 0, 0
            for _ in range(steps):
                destination, tau = self.step(node, direction)
                if tau != int(_edge(node, destination) in seams):
                    raise ValueError("Local step disagrees with its geometric seam")
                if _edge(2 * node + eta, 2 * destination + (eta ^ tau)) not in cover_edges:
                    raise ValueError("Holonomy witness does not follow cover edges")
                node, eta = destination, eta ^ tau
            if node != 0 or eta != expected:
                raise ValueError("Klein loop has incorrect holonomy")
            holonomy[name] = eta
        return {"width": self.width, "height": self.height, "base": base, "cover": cover,
                "seam_cocycle": True, "toroidal_cover_edges": True,
                "toroidal_cover_faces": True, "holonomy": holonomy}

    def field_manifest(self, center: int = 0, radius: int = 2, initial_node: int = 0,
                       initial_phase: int = 250, initial_orientation: int = 0,
                       turns: tuple[int, int, int] = (11, 53, 137),
                       max_ticks: int = 65536, identity: str = "TOMIGIDt") -> FieldManifest:
        """Bind an intrinsic ball to a v2 field whose three routes all use u+."""
        from .field import FieldManifest, PROFILE_V2

        if type(turns) is not tuple or len(turns) != 3:
            raise ValueError("turns must be an immutable triple")
        for turn in turns:
            _integer(turn, 0, 255, "turn")
        routes = tuple((self.step(node, "u+")[0],) * 3 for node in range(len(self.nodes)))
        return FieldManifest(
            identity=identity, nodes=self.nodes, edges=self.edges,
            signs=self.ball_signs(center, radius), routes=routes,
            turns=(turns,) * len(self.nodes), initial_node=initial_node,
            initial_phase=initial_phase, initial_orientation=initial_orientation,
            max_ticks=max_ticks, profile=PROFILE_V2, seams=self.seams,
            topology=(self.width, self.height),
        )
