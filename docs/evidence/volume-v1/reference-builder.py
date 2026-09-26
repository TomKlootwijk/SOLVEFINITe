"""Independent finite 3D solid, field, mission and Wv3 arithmetic.

This reference imports only standard-library modules and SHA-pinned earlier
independent mathematical helpers. It imports no solvefinite module and makes
no claim of measured runtime behavior, physical units or Euclidean SDFs.
"""

from collections import deque
from copy import deepcopy
from hashlib import sha256
from heapq import heappop, heappush
import importlib.util
from itertools import product
import json
from math import gcd
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PINS = {
    "docs/evidence/growth-v1/reference-builder.py": "b9be4e73dcfd81eb3daa7507f6a991208c1ba82abc3c009d4a2193cda75c1d7d",
    "docs/evidence/organogram-v1/reference-builder.py": "987c0adced856312fc3581d921ec1badaec236c0230c63f25ef6f024959f32d8",
    "docs/evidence/organogram-v1/formal-reference.json": "21df28af479fbae2c70a7390a71b0baf9322fcbf38de3ce9db8ff5e5f3b4a6fe",
    "docs/evidence/welip-v1/reference-builder.py": "369c4f4f9d81cdbf5e897c20a06a08fd0d9949deadefb6f9c42975c9063c7eb7",
    "docs/evidence/welip-v1/formal-reference.json": "0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210",
}


def lf_digest(path):
    return sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


for relative, expected in PINS.items():
    if lf_digest(ROOT / relative) != expected:
        raise ValueError("Independent helper identity changed: " + relative)


def load_helper(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OG = load_helper("independent_volume_og", "docs/evidence/organogram-v1/reference-builder.py")
W = load_helper("independent_volume_w", "docs/evidence/welip-v1/reference-builder.py")
BASE = OG.BASE
canonical, digest, integer, token = OG.canonical, OG.digest, OG.integer, OG.token
I32_MAX = (1 << 31) - 1
CARDINAL = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0), (0, -1, 0), (0, 0, -1))
GAINS = ((1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1),
         (1, 1, -1), (-1, 1, -1), (-1, -1, -1), (1, -1, -1))
TERMINALS = {"F": 1, "+": 1, "-": 1, "[": 0, "]": 0, "R": 1, "SPHERE": 0, "SCALE": 1,
             "CONE": 3, "PYRAMID": 3}
PROFILE = "klein-volume-organogram-v1"
POLICY = "tomigidt-field-volume-plan-act-v1"
BASE_PROFILE = "klein-volume-sphere-world-v1"
WORLD_PROFILE = "klein-volume-world-v1"
DERIVATION_PROFILE = "klein-volume-derivation-v1"
TAPE_PROFILE = "VP-TAPE32-v1"
ROUTING_PROFILE = "hadamard-klein-volume-routing-v1"
INDEX_PROFILE = "f8-klein-volume-sdf-v1"
STATE_PROFILE = "RP32-relational-sdf-v3"
W_PROTOCOL = "welip-field-agent-v3"


class Quotient:
    """Cubic lattice quotient K(W,H) times a D-cycle, with actual cells."""

    def __init__(self, width, height, depth):
        self.width, self.height, self.depth = width, height, depth
        for extent in (width, height, depth):
            integer(extent, 3, 256)
        self.count = integer(width * height * depth, 27, 256)
        self.names = tuple(f"v:{u}:{v}:{w}" for u in range(width)
                           for v in range(height) for w in range(depth))
        self.indices = {name: index for index, name in enumerate(self.names)}
        self.adj = tuple(tuple(sorted(self.step(i, e)[0] for e in CARDINAL))
                         for i in range(self.count))
        self.edge_directions = {(i, self.step(i, e)[0]): e
                                for i in range(self.count) for e in CARDINAL}
        assert all(len(set(row)) == 6 for row in self.adj)

    def coordinates(self, node):
        u, rest = divmod(node, self.height * self.depth)
        v, w = divmod(rest, self.depth)
        return u, v, w

    def canonical(self, u, v, w, orientation=0):
        wraps, u = divmod(u, self.width)
        reverse = wraps & 1
        return u, (-v if reverse else v) % self.height, w % self.depth, orientation ^ reverse

    def project(self, u, v, w):
        u, v, w, _ = self.canonical(u, v, w)
        return (u * self.height + v) * self.depth + w

    def step(self, node, direction):
        xyz = self.coordinates(node)
        u, v, w, seam = self.canonical(*(a + b for a, b in zip(xyz, direction)))
        return (u * self.height + v) * self.depth + w, seam

    distance = BASE.Quotient.distance

    def cells(self):
        edges = sorted({tuple(sorted((i, j))) for i in range(self.count) for j in self.adj[i]})
        faces, cubes = set(), []
        for node in range(self.count):
            xyz = self.coordinates(node)
            corners = tuple(self.project(*(xyz[j] + corner[j] for j in range(3)))
                            for corner in product((0, 1), repeat=3))
            assert len(set(corners)) == 8
            cube_faces = []
            for axis in range(3):
                for side in (0, 1):
                    face = tuple(sorted(corners[i] for i, bits in enumerate(product((0, 1), repeat=3))
                                        if bits[axis] == side))
                    assert len(set(face)) == 4
                    faces.add(face)
                    cube_faces.append(face)
            cubes.append((corners, tuple(cube_faces)))
        return edges, sorted(faces), cubes

    def topology_certificate(self):
        edges, faces, cubes = self.cells()
        face_incidence = {face: [] for face in faces}
        for cell, (_, boundary) in enumerate(cubes):
            for face in boundary:
                face_incidence[face].append(cell)
        assert all(len(cells) == 2 for cells in face_incidence.values())
        # Each vertex link is the boundary of an octahedron: six vertices
        # (incident edges), twelve edges (incident face corners), eight faces
        # (incident cube corners). Checking these actual incidences also
        # catches a fake layered 2D grid with the right global counts.
        links = []
        for node in range(self.count):
            adjacent = set(self.adj[node])
            link_edges = set()
            for face in faces:
                if node in face:
                    ends = tuple(sorted(adjacent.intersection(face)))
                    assert len(ends) == 2
                    link_edges.add(ends)
            link_faces = set()
            for corners, _ in cubes:
                if node in corners:
                    ends = tuple(sorted(adjacent.intersection(corners)))
                    assert len(ends) == 3
                    link_faces.add(ends)
            assert (len(adjacent), len(link_edges), len(link_faces)) == (6, 12, 8)
            assert all(sum(set(edge) <= set(face) for face in link_faces) == 2 for edge in link_edges)
            assert all(sum(vertex in edge for edge in link_edges) == 4 for vertex in adjacent)
            links.append({"node": node, "vertices": sorted(adjacent), "edges": sorted(link_edges), "faces": sorted(link_faces)})
        assert (len(edges), len(faces), len(cubes)) == (3 * self.count, 3 * self.count, self.count)
        seam_edges = sorted((i, j) for i, j in edges if self.step(i, self.edge_directions[i, j])[1])
        cover_adj = [[] for _ in range(2 * self.count)]
        for i, j in edges:
            seam = int((i, j) in seam_edges)
            for eta in (0, 1):
                a, b = 2 * i + eta, 2 * j + (eta ^ seam)
                cover_adj[a].append(b); cover_adj[b].append(a)
        reached, pending = {0}, [0]
        while pending:
            for neighbor in cover_adj[pending.pop()]:
                if neighbor not in reached:
                    reached.add(neighbor); pending.append(neighbor)
        assert len(reached) == 2 * self.count
        # The reversing u loop at v=0 is a literal nontrivial cocycle witness.
        node, eta, loop = 0, 0, [0]
        for _ in range(self.width):
            node, seam = self.step(node, (1, 0, 0))
            eta ^= seam; loop.append(node)
        assert node == 0 and eta == 1
        return {"dimensions": [self.width, self.height, self.depth], "vertices": self.count,
                "edges": len(edges), "faces": len(faces), "cubes": len(cubes),
                "euler_characteristic": self.count - len(edges) + len(faces) - len(cubes),
                "face_incidence_two": True, "octahedral_vertex_links": True,
                "vertex_links_sha256": digest(links), "connected_orientation_cover": True,
                "nonorientable": True, "reversing_loop": loop, "seam_edges": seam_edges}


def frame(shaft, eta):
    integer(shaft, 0, 5); integer(eta, 0, 1)
    e = CARDINAL[shaft]
    axis = next(j for j, value in enumerate(e) if value)
    sign = e[axis]
    f = tuple((-1 if eta else 1) if j == (axis + 1) % 3 else 0 for j in range(3))
    h = tuple(sign if j == (axis + 2) % 3 else 0 for j in range(3))
    return e, f, h


def solid_bounds(world, height, numerator, denominator, scale):
    integer(height, 1, 65535); integer(numerator, 1, 65535); integer(denominator, 1, 65535)
    integer(scale, 0, 4)
    if gcd(numerator, denominator) != 1:
        raise ValueError("slope must be reduced")
    extent = integer(height << scale, 1, I32_MAX)
    product = integer(numerator * extent, 1, I32_MAX)
    breadth = product // denominator
    integer(denominator * breadth, 0, I32_MAX)
    integer(max(world.width, world.height, world.depth) - 1 + extent + breadth, 1, I32_MAX)
    sites = (extent + 1) * (2 * breadth + 1) ** 2
    return {"height": extent, "transverse_bound": breadth, "pH": product,
            "qB": denominator * breadth, "box_sites": sites}


def cover_sites(world, apex, shaft, eta, extent, numerator, denominator, kind, lift=(0, 0, 0)):
    xyz = list(world.coordinates(apex))
    m, n, ell = lift
    xyz = [xyz[0] + m * world.width, (-xyz[1] if m & 1 else xyz[1]) + n * world.height,
           xyz[2] + ell * world.depth]
    axes = [list(axis) for axis in frame(shaft, eta)]
    if m & 1:
        for axis in axes:
            axis[1] = -axis[1]
    projected, coordinates = [], []
    for s in range(extent + 1):
        radius = numerator * s // denominator
        for t, r in product(range(-radius, radius + 1), repeat=2):
            if kind == "cone" and denominator ** 2 * (t * t + r * r) > (numerator * s) ** 2:
                continue
            if kind not in ("cone", "pyramid"):
                raise ValueError("unknown solid")
            point = [xyz[j] + s * axes[0][j] + t * axes[1][j] + r * axes[2][j] for j in range(3)]
            projected.append(world.project(*point)); coordinates.append([s, t, r])
    return projected, coordinates


def sphere_sites(world, center, radius):
    xyz = world.coordinates(center)
    projected = []
    for offset in product(range(-radius, radius + 1), repeat=3):
        if sum(value * value for value in offset) <= radius * radius:
            projected.append(world.project(*(a + b for a, b in zip(xyz, offset))))
    return projected


def field_from_occupancy(world, occupied):
    inside = set(occupied)
    if not inside or len(inside) == world.count:
        raise ValueError("empty or full projected occupancy")
    boundary = sorted(i for i in inside if any(j not in inside for j in world.adj[i]))
    if not boundary:
        raise ValueError("empty separating boundary")
    distances, zero = world.distance(boundary), set(boundary)
    signs = [0 if i in zero else -1 if i in inside else 1 for i in range(world.count)]
    fields = [sign * distance for sign, distance in zip(signs, distances)]
    assert all(abs(fields[i] - fields[j]) <= 1 for i in range(world.count) for j in world.adj[i])
    assert all(signs[i] * signs[j] != -1 for i in range(world.count) for j in world.adj[i])
    assert all(-127 <= value <= 127 for value in fields)
    return {"occupancy": sorted(inside), "boundary": boundary, "interior": sorted(inside - zero),
            "signs": signs, "field": fields}


class Field(Quotient, BASE.World):
    def __init__(self, width=4, height=5, depth=3, center=0, radius=1, values=None, gains=GAINS):
        Quotient.__init__(self, width, height, depth)
        self.center, self.radius, self.gains = center, radius, gains
        integer(center, 0, self.count - 1); integer(radius, 1, 127)
        if values is None:
            result = field_from_occupancy(self, sphere_sites(self, center, radius))
            values = result["field"]
        self.phi = tuple(values)
        assert len(self.phi) == self.count
        self.signs = tuple((value > 0) - (value < 0) for value in values)
        self.boundary = tuple(i for i, value in enumerate(values) if value == 0)
        self.gradient = tuple(tuple(values[self.step(i, CARDINAL[j])[0]] - values[self.step(i, CARDINAL[j + 3])[0]]
                                    for j in range(3)) for i in range(self.count))
        assert all(-2 <= lane <= 2 for gradient in self.gradient for lane in gradient)
        self.axis = tuple(tuple(lane // divisor for lane in gradient) if divisor else (1, 0, 0)
                          for gradient in self.gradient for divisor in (gcd(*map(abs, gradient)),))
        self.penalties = {}
        for i, (gradient, psi) in enumerate(zip(self.gradient, self.axis)):
            for bank, gain in enumerate(gains):
                guided = [a * (1 + p * p) * g for a, p, g in zip(gain, psi, gradient)]
                maximum = max(map(abs, guided))
                for j in self.adj[i]:
                    penalty = maximum - sum(z * e for z, e in zip(guided, self.edge_directions[i, j]))
                    integer(penalty, 0, 80)
                    self.penalties[i, bank, j] = penalty

    def recipe(self):
        return {"width": self.width, "height": self.height, "depth": self.depth,
                "center": self.center, "radius": self.radius, "turns": list(BASE.TURNS)}

    def cost(self, i, t, j, hazards):
        return 1 + abs(self.phi[j]) + hazards.get(j, 0) + self.penalties[i, t >> 5, j]

    def index_reference(self, epoch=0, psi_sign=1, phase_origin=0):
        distance = self.distance((self.center,))
        parents = [self.center if i == self.center else min(j for j in self.adj[i] if distance[j] == distance[i] - 1)
                   for i in range(self.count)]
        phases = [phase_origin] * self.count
        for i in sorted(range(self.count), key=lambda j: (distance[j], j)):
            if i != self.center:
                phases[i] = self.phase_after(parents[i], phases[parents[i]])
        records = [list((*(psi_sign * lane + 2 for lane in self.axis[i]),
                         (distance[i] + 1).bit_length() - 1, phases[i], i,
                         sum(g * g for g in self.gradient[i]), *(g + 2 for g in self.gradient[i])))
                   for i in range(self.count)]
        ordered, rows = sorted(record[:6] for record in records), []
        def emit(low, high):
            if low == high:
                return 256
            middle, row = (low + high - 1) // 2, len(rows)
            rows.append(None)
            left, right = emit(low, middle), emit(middle + 1, high)
            rows[row] = ordered[middle] + [left, right]
            return row
        emit(0, self.count)
        lookup_rows = []
        for record in records:
            row, path = 0, []
            while row != 256:
                path.append(row)
                if rows[row][:6] == record[:6]:
                    break
                row = rows[row][6 if record[:6] < rows[row][:6] else 7]
            assert row != 256 and rows[row][5] == record[5]
            lookup_rows.append(path)
        return {"epoch": epoch, "psi_sign": psi_sign, "phase_origin": phase_origin,
                "distances": list(distance), "parents": parents, "records": records, "rows": rows,
                "padded_records": [record + [0, 0] for record in records], "lookup_rows": lookup_rows}


def shaft_choice(world, node, r, eta):
    intrinsic = BASE.intrinsic(r, eta)
    bank, offset = intrinsic >> 5, (6 * intrinsic) // 256
    priority = tuple((offset + j) % 6 for j in range(6))
    gradient, psi, gain = world.gradient[node], world.axis[node], world.gains[bank]
    guided = [a * (1 + p * p) * g for a, p, g in zip(gain, psi, gradient)]
    scores = [sum(z * e for z, e in zip(guided, axis)) for axis in CARDINAL]
    selected = next(i for i in priority if scores[i] == max(scores))
    return {"shaft": selected, "gradient": list(gradient), "psi": list(psi), "phase_bank": bank,
            "tie_offset": offset, "guided_vector": guided, "scores": scores, "tie_priority": list(priority)}


def default_binding(max_epochs=1):
    binding = OG.default_binding(max_epochs)
    binding["format"] = PROFILE
    for rule in binding["rules"][:2]:
        position = next(i for i, item in enumerate(rule["rhs"]) if item["symbol"] == "S")
        rule["rhs"][position] = token("PYRAMID", 1, 1, 2)
    binding["rules"][2]["rhs"] = [token("F", OG.arg()), token("CONE", OG.arg(add=2), 1, 2)]
    binding["rules"][3]["rhs"] = [token("F", OG.arg()), token("SPHERE"), token("R", 2)]
    binding["limits"] = {"max_symbols": 128, "max_steps": 128, "max_primitives": 16,
                         "max_stack": 8, "max_primitive_sites": 1 << 20}
    return binding


def preflight(world, binding, tape):
    limits = binding["limits"]
    for key, low, high in (("max_symbols", 1, 1024), ("max_steps", 1, 4096),
                           ("max_primitives", 1, 64), ("max_stack", 0, 32),
                           ("max_primitive_sites", 1, 1 << 24)):
        integer(limits[key], low, high)
    if not 1 <= len(tape) <= limits["max_symbols"]:
        raise ValueError("logical symbol budget")
    radius, scale, stack = 1, 0, []
    steps = primitives = sites = high_water = texels = 0
    for item in tape:
        symbol, args = item["symbol"], item["args"]
        if symbol not in TERMINALS or type(args) is not list or len(args) != TERMINALS[symbol]:
            raise ValueError("terminal arity")
        texels += 3 if symbol in ("CONE", "PYRAMID") else 1
        if symbol == "F":
            steps += integer(args[0], 1, 256) << scale
        elif symbol in ("+", "-"):
            integer(args[0], 1, 16)
        elif symbol == "R":
            radius = integer(args[0], 1, 127)
        elif symbol == "SCALE":
            scale = integer(args[0], 0, 4)
        elif symbol == "SPHERE":
            effective = integer(radius << scale, 1, 127)
            integer(max(world.width, world.height, world.depth) - 1 + effective, 1, I32_MAX)
            primitives += 1
            sites += (2 * effective + 1) ** 3
        elif symbol in ("CONE", "PYRAMID"):
            bounded = solid_bounds(world, *args, scale)
            primitives += 1
            sites += bounded["box_sites"]
        elif symbol == "[":
            stack.append((radius, scale))
            high_water = max(high_water, len(stack))
        elif symbol == "]":
            if not stack:
                raise ValueError("stack underflow")
            radius, scale = stack.pop()
        if (steps > limits["max_steps"] or primitives > limits["max_primitives"]
                or sites > limits["max_primitive_sites"] or texels > 1152):
            raise ValueError("finite interpretation work budget")
        if len(stack) > limits["max_stack"]:
            raise ValueError("stack budget")
    if stack or not primitives:
        raise ValueError("unbalanced stack or no primitive")
    return {"effective_steps": steps, "primitives": primitives, "primitive_sites": sites,
            "stack_high_water": high_water, "logical_instructions": len(tape), "texels": texels}


def carrier(code, operand):
    integer(code, 0, 15); integer(operand, 0, 65535)
    raw = operand | (code << 24)
    return raw | ((raw.bit_count() & 1) << 31)


def encode_tape(tape):
    words, offsets = [], []
    for item in tape:
        offsets.append(len(words))
        symbol, args = item["symbol"], item["args"]
        if symbol not in TERMINALS or len(args) != TERMINALS[symbol]:
            raise ValueError("terminal arity")
        if symbol in ("CONE", "PYRAMID"):
            first = 8 if symbol == "CONE" else 11
            parts = zip(range(first, first + 3), args)
        else:
            parts = [(tuple(TERMINALS).index(symbol), args[0] if args else 0)]
        words.extend(f"{carrier(code, operand):08X}" for code, operand in parts)
    if len(words) > 1152:
        raise ValueError("instruction texture budget")
    return words, offsets


def decode_tape(words):
    if type(words) is not list or not 1 <= len(words) <= 1152:
        raise ValueError("instruction texture shape")
    decoded = []
    for text in words:
        if type(text) is not str or len(text) != 8 or any(c not in "0123456789ABCDEF" for c in text):
            raise ValueError("instruction word syntax")
        word = int(text, 16)
        if word.bit_count() % 2 or word & 0x70FF0000:
            raise ValueError("instruction parity/reserved bits")
        code, operand = (word >> 24) & 15, word & 65535
        if code > 13:
            raise ValueError("unknown instruction code")
        decoded.append((code, operand))
    result, offsets, index = [], [], 0
    bounds = {0: (1, 256), 1: (1, 16), 2: (1, 16), 5: (1, 127), 7: (0, 4)}
    while index < len(decoded):
        offsets.append(index)
        code, operand = decoded[index]
        if code in (8, 11):
            if index + 2 >= len(decoded) or [x[0] for x in decoded[index:index + 3]] != [code, code + 1, code + 2]:
                raise ValueError("truncated or unordered continuation")
            args = [integer(x[1], 1, 65535) for x in decoded[index:index + 3]]
            if gcd(args[1], args[2]) != 1:
                raise ValueError("slope must be reduced")
            result.append(token("CONE" if code == 8 else "PYRAMID", *args))
            index += 3
            continue
        if code >= 8:
            raise ValueError("isolated continuation")
        if code in (3, 4, 6):
            if operand:
                raise ValueError("no-argument operand must be zero")
            args = []
        else:
            args = [integer(operand, *bounds[code])]
        result.append(token(tuple(TERMINALS)[code], *args))
        index += 1
    return result, offsets


def primitive_occupancy(world, primitive):
    if primitive["kind"] == "sphere":
        return sorted(set(sphere_sites(world, primitive["center"], primitive["radius"])))
    _, _, _, metadata = OG.unpack_pair(primitive["pair"])
    projected, _ = cover_sites(world, primitive["apex"], primitive["shaft"], (metadata >> 4) & 1,
                               primitive["height"], primitive["numerator"], primitive["denominator"], primitive["kind"])
    return sorted(set(projected))


def union_field(world, primitives):
    parts = [primitive_occupancy(world, primitive) for primitive in primitives]
    return {"primitive_occupancies": parts, **field_from_occupancy(world, set().union(*map(set, parts)))}


def rewrite(binding, context):
    r, _, b, metadata = OG.unpack_pair(context["start_pair"])
    inputs = {"tick": context["tick"], "epoch": context["epoch"],
              "phase": BASE.intrinsic(r, (metadata >> 4) & 1), "field": b}
    word = [{"address": [i], "symbol": item["symbol"],
             "args": [OG.expression(value, inputs, "context") for value in item["args"]]}
            for i, item in enumerate(binding["axiom"])]
    generations = [deepcopy(word)]
    limit = integer(binding["limits"]["max_symbols"], 1, 1024)
    if len(word) > limit:
        raise ValueError("logical symbol budget")
    for generation in range(1, integer(binding["generations"], 0, 8) + 1):
        following = []
        for item in word:
            match = next((index for index, rule in enumerate(binding["rules"])
                          if rule["symbol"] == item["symbol"]
                          and all(OG.guard_matches(guard, item["args"]) for guard in rule["guards"])), None)
            if match is None:
                following.append({**item, "address": item["address"] + [generation, -1, 0]})
            else:
                for offset, output in enumerate(binding["rules"][match]["rhs"]):
                    following.append({"address": item["address"] + [generation, match, offset],
                                      "symbol": output["symbol"],
                                      "args": [OG.expression(value, item["args"], "arg") for value in output["args"]]})
            if len(following) > limit:
                raise ValueError("logical symbol budget")
        word = following
        generations.append(deepcopy(word))
    if any(item["symbol"] not in TERMINALS for item in word):
        raise ValueError("final unmatched nonterminal")
    return word, generations


def interpret(world, binding, context):
    tape, generations = rewrite(binding, context)
    work = preflight(world, binding, tape)
    r, node, field, metadata = OG.unpack_pair(context["start_pair"])
    if metadata not in (6, 22) or world.phi[node] != field:
        raise ValueError("stage source context")
    eta, radius, scale, branch, stack = (metadata >> 4) & 1, 1, 0, [], []
    trace, segments, primitives, shafts = [], [], [], []
    for item in tape:
        symbol, args, address = item["symbol"], item["args"], item["address"]
        if symbol == "F":
            for step in range(1, args[0] * 2 ** scale + 1):
                selected = shaft_choice(world, node, r, eta)["shaft"]
                destination, _ = world.step(node, CARDINAL[selected])
                r, node, eta = world.transport(r, node, eta, destination)
                segments.append({"address": list(address), "branch_path": deepcopy(branch), "step": step,
                                 "pair": world.packed(r, node, eta)})
        elif symbol in ("+", "-"):
            delta = args[0] * BASE.TURNS[world.signs[node] + 1] * (1 if symbol == "+" else -1)
            r = (r + (-1 if eta else 1) * delta) % 256
        elif symbol == "R":
            radius = args[0]
        elif symbol == "SCALE":
            scale = args[0]
        elif symbol in ("SPHERE", "CONE", "PYRAMID"):
            common = {"address": list(address), "branch_path": deepcopy(branch), "pair": world.packed(r, node, eta)}
            if symbol == "SPHERE":
                primitives.append({"kind": "sphere", **common, "center": node, "radius": radius << scale})
            else:
                choice = shaft_choice(world, node, r, eta)
                shafts.append({"address": list(address), **choice})
                primitives.append({"kind": symbol.lower(), **common, "apex": node, "height": args[0] << scale,
                                   "numerator": args[1], "denominator": args[2], "shaft": choice["shaft"]})
        elif symbol == "[":
            stack.append((r, node, eta, radius, scale, deepcopy(branch)))
            branch = branch + [list(address)]
        elif symbol == "]":
            r, node, eta, radius, scale, branch = stack.pop()
        trace.append({"address": list(address), "branch_path": deepcopy(branch),
                      "pair": world.packed(r, node, eta), "radius": radius, "scale": scale})
    assert not stack and not branch
    document = {"format": DERIVATION_PROFILE, "context": deepcopy(context), "tape": tape,
                "trace": trace, "segments": segments, "primitives": primitives,
                "final_context": {"branch_path": branch, "pair": world.packed(r, node, eta), "radius": radius, "scale": scale}}
    words, offsets = encode_tape(tape)
    assert decode_tape(words) == ([token(x["symbol"], *x["args"]) for x in tape], offsets)
    return {"document": document, "derivation_sha256": digest(document), "preflight": work,
            "parallel_generations": generations, "encoded_tape_words": words, "word_offsets": offsets,
            "shaft_certificates": shafts, "union": union_field(world, primitives)}


class RouteCursor:
    """Finite retained mathematical search, independently layer-checked."""
    def __init__(self, world, source, target, phase, hazards):
        self.world, self.source, self.target, self.phase = world, source, target, phase
        self.hazards = dict(hazards)
        self.remaining = world.distance((target,))
        self.heap = [(0, (), source, phase, 0)]
        self.best = {(source, phase, 0): (0, ())}
        self.expansions = 0

    def advance(self, quantum):
        start = self.expansions
        while self.heap:
            entry = heappop(self.heap)
            cost, paths, node, phase, hops = entry
            if self.best[node, phase, hops] != (cost, paths):
                continue
            if node == self.target:
                result = {"route": [self.world.indices[path] for path in paths], "paths": list(paths),
                          "cost": cost, "expansions": self.expansions}
                BASE.verify_by_layers(self.world, self.source, self.target, self.phase, self.hazards, result, 255)
                return result
            if self.expansions - start == quantum:
                heappush(self.heap, entry)
                return None
            self.expansions += 1
            for neighbor in self.world.adj[node]:
                if hops + 1 + self.remaining[neighbor] > 255:
                    continue
                candidate = (cost + self.world.cost(node, phase, neighbor, self.hazards),
                             paths + (self.world.names[neighbor],))
                state = (neighbor, self.world.phase_after(node, phase), hops + 1)
                if state not in self.best or candidate < self.best[state]:
                    self.best[state] = candidate
                    heappush(self.heap, (*candidate, *state))
        raise AssertionError("reachable route lost")

    def witness(self):
        return {"expansions": self.expansions, "frontier": deepcopy(self.heap),
                "best": sorted(self.best.items())}


def mission(max_epochs=1, mirrored=False, binding=None, quantum=4096, reindex_between_quanta=False):
    binding = default_binding(max_epochs) if binding is None else deepcopy(binding)
    max_epochs = binding["max_epochs"]
    world = Field()
    initial_recipe = world.recipe()
    r, node, eta, energy, epoch, target = (6 if mirrored else 250), 0, int(mirrored), 200, 0, 54
    initial = world.state(r, node, eta, energy)
    known, events, stages = {}, [], []
    pending_growth = False
    cursor = context_key = None
    deferred_cursors, reindex_witnesses = [], []
    worlds = [{"epoch": 0, "field": list(world.phi), "target": target}]
    for cycle in range(1, 501):
        visible = sorted((node, *world.adj[node]), key=world.names.__getitem__)
        frame = {j: 70 if epoch == 0 and cycle >= 2 and j == 6 else 0 for j in visible}
        known.update(frame)
        reserve = 5 + (max_epochs - epoch) * (binding["cost"] + 5)
        event = {"cycle": cycle, "input_epoch": epoch, "input": {world.names[j]: h for j, h in frame.items()},
                 "target_before": target, "reserve_before": reserve}
        if pending_growth:
            context = {"epoch": epoch + 1, "tick": cycle, "start_pair": world.packed(r, node, eta, 6),
                       "prefix_sha256": digest(events)}
            derivation = interpret(world, binding, context)
            old_world = world
            world = Field(values=derivation["union"]["field"])
            selection = OG.target_selection(world, node, BASE.intrinsic(r, eta))
            target = selection["target"]
            epoch += 1
            energy -= binding["cost"]
            known, pending_growth, cursor, context_key = {}, False, None, None
            before = old_world.state(r, node, eta, energy + binding["cost"], 6)
            event.update(kind="GROW", route=[], cost=binding["cost"], before=before,
                         state=world.state(r, node, eta, energy), status="ACTIVE", selection=selection,
                         context=context, derivation_sha256=derivation["derivation_sha256"])
            assert all(event["state"][key] == before[key] for key in ("node", "phase", "orientation", "intrinsic_phase"))
            worlds.append({"epoch": epoch, "field": list(world.phi), "target": target})
            stages.append({"prior_field": list(old_world.phi), "result": derivation, "selection": selection,
                           "new_field_route": BASE.route(world, node, target, BASE.intrinsic(r, eta), {}),
                           "old_field_counterfactual_route": BASE.route(old_world, node, target, BASE.intrinsic(r, eta), {})})
        elif node == target:
            assert energy >= reserve
            energy -= 5
            pending_growth = epoch < max_epochs
            event.update(kind="REPAIR", route=[], cost=5, state=world.state(r, node, eta, energy, 6),
                         status="GROWTH_PENDING" if pending_growth else "COMPLETE")
        else:
            current_key = (epoch, node, BASE.intrinsic(r, eta), energy, tuple(known.get(i, 0) for i in range(world.count)))
            if cursor is None or current_key != context_key:
                cursor = RouteCursor(world, node, target, BASE.intrinsic(r, eta), known)
                context_key = current_key
            result = cursor.advance(quantum)
            if result is None:
                witness = cursor.witness()
                deferred_cursors.append({"cycle": cycle, "epoch": epoch, "witness": witness,
                                         "witness_sha256": digest(witness)})
                if reindex_between_quanta:
                    rebound = world.index_reference(epoch=len(reindex_witnesses) + 1, psi_sign=-1, phase_origin=201)
                    assert digest(cursor.witness()) == digest(witness)
                    reindex_witnesses.append({"cycle": cycle, "index_sha256": digest(rebound),
                                             "cursor_sha256_before": digest(witness), "cursor_sha256_after": digest(cursor.witness())})
                event.update(kind="DEFER", route=[], cost=0, expansions=cursor.expansions,
                             state=world.state(r, node, eta, energy), status="SEARCH_DEFERRED",
                             epoch=epoch, target_after=target)
                events.append(event)
                continue
            assert result["cost"] + reserve <= energy, (cycle, energy, result, reserve)
            forecast, costs = [], []
            fr, fi, fe = r, node, eta
            for destination in result["route"]:
                costs.append(world.cost(fi, BASE.intrinsic(fr, fe), destination, known))
                fr, fi, fe = world.transport(fr, fi, fe, destination)
                forecast.append(world.packed(fr, fi, fe))
            assert sum(costs) == result["cost"]
            r, node, eta = world.transport(r, node, eta, result["route"][0])
            energy -= costs[0]
            event.update(kind="MOVE", **result, action_cost=costs[0], forecast=forecast,
                         forecast_costs=costs, state=world.state(r, node, eta, energy), status="ACTIVE")
            cursor = context_key = None
        event.update(epoch=epoch, target_after=target)
        events.append(event)
        if event["status"] == "COMPLETE":
            break
    else:
        raise AssertionError("finite mission failed to terminate")
    return {"initial": initial, "initial_recipe": initial_recipe, "initial_target": 54, "binding": binding,
            "worlds": worlds, "events": events, "stages": stages, "cycles": len(events), "final": events[-1]["state"],
            "max_search_expansions": quantum, "deferred_cursors": deferred_cursors,
            "reindex_witnesses": reindex_witnesses,
            "prefix_hash_scope": "Independent mathematical event transcript, not a canonical runtime archive."}


def geometry_vectors():
    specs = [
        ("cone-distinct-3d", (6, 6, 6), "cone", 21, 0, 4, 1, 2),
        ("pyramid-distinct-3d", (6, 6, 6), "pyramid", 21, 0, 4, 1, 2),
        ("cone-round-section", (6, 6, 6), "cone", 57, 0, 2, 1, 1),
        ("pyramid-square-section", (6, 6, 6), "pyramid", 57, 0, 2, 1, 1),
        ("negative-u-seam", (4, 5, 3), "cone", 4, 3, 3, 1, 2),
        ("multiple-wraps", (5, 4, 3), "pyramid", 53, 0, 9, 1, 4),
        ("zero-breadth-third-axis", (4, 5, 3), "cone", 21, 2, 4, 1, 9),
    ]
    result = []
    for name, dimensions, kind, apex, shaft, height, numerator, denominator in specs:
        world = Field(*dimensions)
        primitive = {"kind": kind, "address": [0], "branch_path": [], "apex": apex,
                     "height": height, "numerator": numerator, "denominator": denominator,
                     "shaft": shaft, "pair": world.packed(0, apex, 0)}
        projected, local = cover_sites(world, apex, shaft, 0, height, numerator, denominator, kind)
        vector = {"name": name, "dimensions": list(dimensions), "primitive": primitive,
                  "frame": frame(shaft, 0), "tested_box_sites": solid_bounds(world, height, numerator, denominator, 0)["box_sites"],
                  "accepted_cover_sites": len(local), "local_layer_counts": [sum(site[0] == s for site in local) for s in range(height + 1)],
                  "projected_sequence": projected, "local_sites": local,
                  "neighbors": [list(row) for row in world.adj], **field_from_occupancy(world, projected)}
        result.append(vector)
    world = Field(6, 6, 6)
    primitive = {"kind": "sphere", "address": [0], "branch_path": [], "center": 129,
                 "radius": 2, "pair": world.packed(0, 129, 0)}
    projected = sphere_sites(world, 129, 2)
    result.append({"name": "sphere-euclidean-lattice", "dimensions": [6, 6, 6], "primitive": primitive,
                   "tested_box_sites": 125, "accepted_cover_sites": len(projected),
                   "projected_sequence": projected, "neighbors": [list(row) for row in world.adj],
                   **field_from_occupancy(world, projected)})
    cone, pyramid = result[:2]
    assert cone["local_layer_counts"] == [1, 1, 5, 9, 13]
    assert pyramid["local_layer_counts"] == [1, 1, 9, 9, 25]
    assert [len(cone["occupancy"]), len(pyramid["occupancy"]), len(result[-1]["occupancy"])] == [29, 45, 33]
    assert [2, 1, 1] not in cone["local_sites"] and [2, 1, 1] in pyramid["local_sites"]
    cube = [list(x) for x in product((3, 4), (0, 1), (0, 1))]
    assert all(point in cone["local_sites"] for point in cube)
    assert [x for x in cone["local_sites"] if x[2] == 0] == [x for x in pyramid["local_sites"] if x[2] == 0]
    cone["complete_local_cube"] = cube
    pyramid["off_axis_distinguishing_site"] = [2, 1, 1]
    sphere_cube = [world.project(x, y, z) for x, y, z in product((3, 4), repeat=3)]
    assert set(sphere_cube) <= set(result[-1]["occupancy"])
    result[-1]["complete_cube_vertices"] = sphere_cube
    return result


def square_limbs(value):
    """A square of 0..i32max, with every intermediate fitting u32."""
    integer(value, 0, I32_MAX)
    low, high = value & 65535, value >> 16
    first = low * low
    middle = 2 * low * high + (first >> 16)
    final = high * high + (middle >> 16)
    assert max(first, middle, final) < 1 << 32
    return [first & 65535, middle & 65535, final & 65535, final >> 16]


def add_limbs(left, right):
    result, carry = [], 0
    for a, b in zip(left, right):
        total = a + b + carry
        assert 0 <= total <= 131071
        result.append(total & 65535)
        carry = total >> 16
    assert carry == 0
    return result


def limb_value(limbs):
    return sum(lane << (16 * i) for i, lane in enumerate(limbs))


def limb_cone(s, t, r, p, q):
    left = add_limbs(square_limbs(q * abs(t)), square_limbs(q * abs(r)))
    right = square_limbs(p * s)
    return tuple(reversed(left)) <= tuple(reversed(right))


def arithmetic_vectors():
    values = [0, 1, 2, 255, 256, 65534, 65535, 65536, 65537, 131070, 1 << 30, I32_MAX]
    random = 123456789
    for _ in range(2048):
        random = (1664525 * random + 1013904223) & ((1 << 31) - 1)
        values.append(random)
    for value in values:
        assert limb_value(square_limbs(value)) == value * value
    for a, b in zip(values, reversed(values)):
        assert limb_value(add_limbs(square_limbs(a), square_limbs(b))) == a * a + b * b
    s, t, r, p, q = 2, 2, 1, 65535, 65534
    left, right = q * q * (t * t + r * r), (p * s) ** 2
    assert left > right and (left & 0xFFFFFFFF) <= (right & 0xFFFFFFFF)
    assert not limb_cone(s, t, r, p, q)
    return {"square_checks": len(values), "two_square_sum_checks": len(values),
            "limb_order": "little endian, base65536, four u32 lanes each restricted to 0..65535",
            "maximum_input": I32_MAX, "maximum_two_square_sum": 2 * I32_MAX ** 2,
            "maximum_square": square_limbs(I32_MAX),
            "maximum_sum": add_limbs(square_limbs(I32_MAX), square_limbs(I32_MAX)),
            "u32_wrap_counterexample": {"height": 2, "numerator": p, "denominator": q,
                "site": [s, t, r], "preflight": solid_bounds(Field(), 2, p, q, 0),
                "lhs_exact": left, "rhs_exact": right, "lhs_u32_wrapped": left & 0xFFFFFFFF,
                "rhs_u32_wrapped": right & 0xFFFFFFFF, "lhs_limbs": add_limbs(square_limbs(q * abs(t)), square_limbs(q * abs(r))),
                "rhs_limbs": square_limbs(p * s), "exact_inside": False, "wrapped_inside": True}}


def walk_site(world, apex, shaft, eta, s, t, r):
    node, axes = apex, [list(axis) for axis in frame(shaft, eta)]
    for axis, count in enumerate((s, t, r)):
        for _ in range(abs(count)):
            direction = tuple((-1 if count < 0 else 1) * lane for lane in axes[axis])
            node, seam = world.step(node, direction)
            if seam:
                for vector in axes:
                    vector[1] = -vector[1]
    return node


def projection_certificate():
    deck_checks = mirror_checks = walk_checks = 0
    for dimensions in ((3, 3, 3), (4, 5, 3), (5, 4, 3), (6, 6, 6)):
        world = Quotient(*dimensions)
        for apex in (0, world.count // 2, world.count - 1):
            for shaft, eta, kind in product(range(6), (0, 1), ("cone", "pyramid")):
                expected, local = cover_sites(world, apex, shaft, eta, 4, 1, 2, kind)
                mirrored, _ = cover_sites(world, apex, shaft, eta ^ 1, 4, 1, 2, kind)
                assert set(expected) == set(mirrored)
                mirror_checks += 1
                for lift in product((-2, -1, 0, 1, 2), (-1, 0, 1), (-1, 0, 1)):
                    actual, _ = cover_sites(world, apex, shaft, eta, 4, 1, 2, kind, lift)
                    assert actual == expected
                    deck_checks += 1
                for site, destination in zip(local, expected):
                    assert walk_site(world, apex, shaft, eta, *site) == destination
                    walk_checks += 1
    return {"domains": 4, "deck_sequence_comparisons": deck_checks,
            "full_mirror_occupancy_comparisons": mirror_checks, "transported_edge_walk_endpoints": walk_checks,
            "deck_scope": "All fixture apex/frame combinations and 45 signed cover representatives; not an exhaustive theorem proof."}


def field_operators(world):
    psi = []
    for node, (g, axis) in enumerate(zip(world.gradient, world.axis)):
        tensor = [[a * b for b in g] for a in g]
        eigenvalue = sum(lane * lane for lane in g)
        assert [sum(a * p for a, p in zip(row, axis)) for row in tensor] == [eigenvalue * p for p in axis]
        assert gcd(*map(abs, axis)) == 1 and 0 <= eigenvalue <= 12
        psi.append({"node": node, "gradient": g, "tensor": tensor, "eigenvalue": eigenvalue,
                    "axis": axis, "degenerate": not any(g)})
    penalties = [world.penalties[i, bank, j] for i in range(world.count)
                 for bank in range(8) for j in world.adj[i]]
    increments = [BASE.TURNS[sign + 1] for sign in world.signs]
    return {"psi": psi, "routing": {"format": ROUTING_PROFILE, "gains": GAINS,
                 "neighbors": world.adj, "penalties": penalties, "increments": increments},
            "index_versions": [world.index_reference(*version) for version in ((0, 1, 0), (1, -1, 201), (7, 1, 53))]}


def config_for(mission):
    initial = mission["initial"]
    world = Field(**{k: v for k, v in mission["initial_recipe"].items() if k != "turns"})
    agent = {"identity": "TOMIGIDt", "target": world.names[mission["initial_target"]],
             "world": {"format": BASE_PROFILE, **mission["initial_recipe"], "baseline_id": "klein-volume-world-v1"},
             "initial_node": initial["path"], "initial_phase": initial["phase"],
             "initial_orientation": initial["orientation"], "initial_energy": initial["energy"],
             "repair_cost": 5, "max_search_expansions": mission["max_search_expansions"], "max_hops": 255, "max_cycles": 10000,
             "policy": POLICY, "word_profile": STATE_PROFILE, "perspective": "local-observation-v1",
             "routing": {"format": ROUTING_PROFILE, "gains": [list(bank) for bank in GAINS]},
             "volume": deepcopy(mission["binding"])}
    return {"format": "welip-field-config-v3", "agent": agent, "producer": "volume-reference",
            "producer_epoch": 7, "clock_origin": 65530, "max_events": 64, "initial_capacity": 3}


def w_lifecycle(mission, postgrowth_capacity=4):
    config, world = config_for(mission), Field()
    schedule = [("IGNITE", None)]
    for event in mission["events"]:
        cycle = event["cycle"]
        if cycle == 2:
            schedule += [("EMIT", None), ("RESIZE", 1), ("INVALIDATE", None)]
        if event["kind"] == "GROW":
            schedule.append(("EMIT", None))
        schedule.append(("ADVANCE", cycle))
        if event["kind"] == "GROW":
            schedule.append(("RESIZE", postgrowth_capacity))
        if cycle == 7:
            schedule.append(("INVALIDATE", None))
    schedule.append(("EMIT", None))
    fifo = W.Fifo(config["initial_capacity"])
    state, status, cycle, epoch = deepcopy(mission["initial"]), "ACTIVE", 0, 0
    def visible(path):
        node = world.indices[path]
        return sorted(world.names[i] for i in (node, *world.adj[node]))
    def cursor(sequence, ignited):
        head = {"seq": sequence, **W.clock(config["clock_origin"], config["max_events"], sequence),
                "agent_cycle": cycle, "geometry_epoch": epoch}
        following = None
        if sequence < config["max_events"]:
            allowed = ["IGNITE"] if not ignited else [op for op in W.OPERATIONS if op != "IGNITE"]
            if status == "COMPLETE" or cycle >= config["agent"]["max_cycles"]:
                allowed = [op for op in allowed if op != "ADVANCE"]
            if not fifo.active:
                allowed = [op for op in allowed if op != "INVALIDATE"]
            following = {"seq": sequence + 1, **W.clock(config["clock_origin"], config["max_events"], sequence + 1),
                         "agent_cycle": cycle, "geometry_epoch": epoch, "position": state["path"],
                         "visible_paths": visible(state["path"]), "active_paths": list(fifo.active),
                         "capacity": fifo.capacity, "agent_status": status, "allowed_ops": allowed}
        return {"protocol": W_PROTOCOL, "producer": config["producer"], "producer_epoch": config["producer_epoch"],
                "head": head, "next": following}
    def record(sequence, ordinal, operation, payload=None):
        output = W.record(config, sequence, ordinal, operation, cycle, epoch, state, payload)
        if payload is None:
            output["payload_profile"] = STATE_PROFILE
        return output
    genesis = {"seq": 0, **W.clock(config["clock_origin"], config["max_events"], 0),
               "ignited": False, "cache": fifo.witness()}
    ready = {**cursor(0, False), "type": "READY", "restored": False}
    rows, results, duplicates, projection, counters = [], [], [], [], []
    action_ticks = 0
    for sequence, (operation, argument) in enumerate(schedule, 1):
        request = {"protocol": W_PROTOCOL, "op": operation, "producer": config["producer"],
                   "producer_epoch": config["producer_epoch"], "seq": sequence,
                   **W.clock(config["clock_origin"], config["max_events"], sequence),
                   "agent_cycle": cycle, "geometry_epoch": epoch}
        removed = []
        if operation == "IGNITE":
            request["payload"] = W.PAYLOAD
        elif operation == "RESIZE":
            request["capacity"] = argument
            removed = fifo.resize(argument)
        elif operation == "INVALIDATE":
            request.update(paths=[fifo.active[0]], cause="release-original-local-copy" if epoch == 0 else "release-generated-local-copy")
            removed = fifo.invalidate(request["paths"])
        elif operation == "ADVANCE":
            event = mission["events"][argument - 1]
            assert argument == cycle + 1 and event["input_epoch"] == epoch
            assert sorted(event["input"]) == visible(state["path"])
            request.update(position=state["path"], observations=deepcopy(event["input"]))
            if event["kind"] == "GROW":
                fifo, action_ticks = W.Fifo(fifo.capacity), 0
            else:
                action_ticks += 1
                for path in sorted(event["input"]):
                    fifo.get(path)
            cycle, epoch, state, status = argument, event["epoch"], deepcopy(event["state"]), event["status"]
            projection.append({"cycle": cycle, "input_epoch": event["input_epoch"], "input": deepcopy(event["input"]),
                               "kind": event["kind"], "pair": state["pair"], "energy": state["energy"],
                               "geometry_epoch": epoch, "status": status})
        records = []
        if operation == "IGNITE":
            records.append(record(sequence, 0, operation, bytes.fromhex(W.PAYLOAD)))
        records.append(record(sequence, len(records), operation))
        cache = fifo.witness(removed)
        rows.append({"request": request, "records": records, "agent_pair": state["pair"],
                     "energy": state["energy"], "status": status, "cache": cache})
        context = cursor(sequence, True)
        results.append({**context, "type": "RESULT", "op": operation, "seq": sequence,
                        "records": deepcopy(records), "cache": cache, "agent_status": status})
        duplicates.append({**context, "type": "DUPLICATE", "seq": sequence})
        counters.append({"operation_seq": sequence, "agent_cycle": cycle,
                         "geometry_epoch": epoch, "executor_action_ticks": action_ticks})
    expected = {"seq": len(rows), **W.clock(config["clock_origin"], config["max_events"], len(rows)),
                "ignited": True, "cache": fifo.witness()}
    identities = [(record["producer"], record["producer_epoch"], record["clock_epoch"], record["tick16"],
                   record["operation_seq"], record["record_seq"]) for row in rows for record in row["records"]]
    assert len(identities) == len(set(identities)) == len(rows) + 1
    assert cycle == mission["cycles"] and state == mission["final"] and status == "COMPLETE"
    return {"format": "volume-welip-independent-lifecycle-v3", "session_format": "welip-field-session-v3",
            "config": config, "genesis": genesis, "ready": ready, "schedule": [list(item) for item in schedule],
            "operations": rows, "results": results, "latest_retry_receipts": duplicates, "expected": expected,
            "projected_owner_transitions": projection, "final_owner": state,
            "record_count": len(identities), "fragment_count": sum(r["fragment_count"] for row in rows for r in row["records"]),
            "executor_action_tick_expectations": counters, "operation_transcript_sha256": digest(rows),
            "scope": "Expected Wv3 lifecycle around an independent 3D mission; no canonical runtime archive hash or measured GPU result."}


def rejection_vectors():
    world, binding = Field(), default_binding()
    vectors = []
    def reject(label, action, input_value):
        try:
            action()
        except (ValueError, KeyError, TypeError) as exc:
            vectors.append({"name": label, "input": input_value, "expected": "REJECT", "reason": str(exc)})
        else:
            raise AssertionError("negative vector was accepted: " + label)
    def tape(*items):
        return [{"address": [i], **item} for i, item in enumerate(items)]
    for symbol in ("S", "TAPER"):
        data = tape(token(symbol))
        reject("legacy-alias-" + symbol, lambda data=data: preflight(world, binding, data), data)
    for symbol, args in (("CONE", (0, 1, 1)), ("CONE", (1, 0, 1)), ("PYRAMID", (1, 1, 0)),
                         ("CONE", (1, 2, 2)), ("PYRAMID", (65536, 1, 1)), ("CONE", (True, 1, 1)),
                         ("CONE", (1.0, 1, 1)), ("SPHERE", (1,)), ("F", (0,)), ("SCALE", (5,))):
        data = tape(token(symbol, *args))
        reject("invalid-terminal-" + str(len(vectors)), lambda data=data: preflight(world, binding, data), data)
    for data in ([], tape(token("["), token("SPHERE")), tape(token("]"), token("SPHERE")),
                 tape(token("F", 1)), tape(token("R", 127), token("SCALE", 1), token("SPHERE")),
                 tape(token("CONE", 65535, 65535, 1)), tape(token("PYRAMID", 127, 1, 1))):
        reject("preflight-limit-" + str(len(vectors)), lambda data=data: preflight(world, binding, data), data)
    valid, _ = encode_tape(tape(token("CONE", 2, 1, 2), token("PYRAMID", 2, 1, 2), token("SPHERE")))
    invalid_words = [valid[:2], [f"{carrier(9, 1):08X}"], [f"{carrier(12, 1):08X}"],
                     [f"{carrier(14, 1):08X}"], [f"{carrier(15, 1):08X}"], [f"{carrier(6, 1):08X}"],
                     [valid[0], valid[2], valid[1]], [f"{int(valid[0], 16) ^ 1:08X}"],
                     [f"{carrier(0, 1) ^ 0x10010000:08X}"], valid + ["00000000"]]
    for index, words in enumerate(invalid_words):
        reject("malformed-tape-" + str(index), lambda words=words: decode_tape(words), words)
    reject("empty-occupancy", lambda: field_from_occupancy(world, []), [])
    reject("full-occupancy", lambda: field_from_occupancy(world, range(world.count)), list(range(world.count)))
    for dimensions in ((2, 5, 3), (4, 5, 2), (7, 7, 7), (True, 5, 3)):
        reject("invalid-domain-" + str(dimensions), lambda dimensions=dimensions: Quotient(*dimensions), dimensions)
    return vectors


def cross_config_identity_vector(mission):
    """Equal wire records do not establish equality of retained worlds."""
    original = config_for(mission)
    changed = deepcopy(original)
    changed["agent"]["world"]["depth"] = 4
    initial = mission["initial"]
    alternate = Field(depth=4).state(initial["phase"], 0, initial["orientation"], initial["energy"])
    assert alternate == initial
    first = W.record(original, 1, 1, "IGNITE", 0, 0, initial)
    second = W.record(changed, 1, 1, "IGNITE", 0, 0, alternate)
    first["payload_profile"] = second["payload_profile"] = STATE_PROFILE
    assert first == second and canonical(original) != canonical(changed)
    return {"protocol": W_PROTOCOL, "original_config": original, "different_config": changed,
            "original_config_sha256": digest(original), "different_config_sha256": digest(changed),
            "identical_initial_state": initial, "identical_state_record": first,
            "expected_admission": "Reject cross-config reuse. The same producer/time, baseline_id and wire record must be compared only within the retained protocol and exact canonical configuration; depth3 and depth4 are different worlds."}


def main():
    default, mirrored, two, zero = mission(), mission(mirrored=True), mission(2), mission(0)
    BASE.verify_mirror({"events": [{**event, "geometry_epoch": event["epoch"]} for event in default["events"]], "cycles": default["cycles"]},
                       {"events": [{**event, "geometry_epoch": event["epoch"]} for event in mirrored["events"]], "cycles": mirrored["cycles"]})
    assert [stage["result"]["union"] for stage in default["stages"]] == [stage["result"]["union"] for stage in mirrored["stages"]]
    deferred = mission(quantum=7)
    rebuilt = mission(quantum=7, reindex_between_quanta=True)
    assert canonical(deferred["events"]) == canonical(rebuilt["events"])
    assert deferred["deferred_cursors"] == rebuilt["deferred_cursors"]
    assert any(row["epoch"] > 0 for row in deferred["deferred_cursors"])
    operators = []
    for record in two["worlds"]:
        operators.append({"epoch": record["epoch"], "fields": record["field"],
                          **field_operators(Field(values=record["field"]))})
    reference = {"format": "volume-independent-formal-reference-v1", "status": "formal-only",
        "scope": "Independent expected arithmetic for genuine finite 3D lattice sphere/cone/pyramid volumes on K times cycle, exact graph boundary distances, full agent continuation and Wv3. No measured runtime behavior, canonical runtime archive identity, physical metric or performance claim.",
        "generator_sha256_lf": lf_digest(Path(__file__)), "independent_source_sha256_lf": PINS,
        "binding": default_binding(), "base_recipe": config_for(default)["agent"]["world"],
        "routing": {"format": ROUTING_PROFILE, "gains": GAINS}, "word_profile": STATE_PROFILE,
        "geometry_vectors": geometry_vectors(), "arithmetic_vectors": arithmetic_vectors(),
        "topology_certificates": [Quotient(*dimensions).topology_certificate() for dimensions in ((3, 3, 3), (4, 5, 3), (6, 6, 6), (28, 3, 3))],
        "projection_certificate": projection_certificate(), "field_operator_vectors": operators,
        "rejection_vectors": rejection_vectors(),
        "default_mission": default, "mirrored_default_mission": mirrored, "two_epoch_mission": two,
        "zero_epoch_mission": zero, "deferred_mission": deferred,
        "same_quantum_index_rebuild": {"events_sha256": digest(rebuilt["events"]), "equal_to_deferred": True,
                                      "witnesses": rebuilt["reindex_witnesses"]},
        "w_v3_lifecycle": w_lifecycle(default), "w_v3_mirrored_lifecycle": w_lifecycle(mirrored),
        "w_v3_capacity8_lifecycle": w_lifecycle(default, 8),
        "cross_config_identity_vector": cross_config_identity_vector(default)}
    destination = Path(__file__).with_name("formal-reference.json")
    destination.write_text(json.dumps(reference, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"path": str(destination), "sha256_lf": lf_digest(destination),
        "generator_sha256_lf": reference["generator_sha256_lf"], "bytes": destination.stat().st_size,
        "default": {"cycles": default["cycles"], "final": default["final"]},
        "two_epoch": {"cycles": two["cycles"], "final": two["final"]},
        "deferred": {"cycles": deferred["cycles"], "final": deferred["final"], "deferred_count": len(deferred["deferred_cursors"])},
        "rejections": len(reference["rejection_vectors"]), "projection": reference["projection_certificate"],
        "w_operations": len(reference["w_v3_lifecycle"]["operations"]), "w_records": reference["w_v3_lifecycle"]["record_count"]}, indent=2))


if __name__ == "__main__":
    main()
