"""Independent cell, covering-space and intrinsic-field checks for K1-K5."""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from solvefinite.field import evaluate_field
from solvefinite.klein import KleinDomain, audit_surface


SIZES = ((3, 3), (3, 4), (4, 3), (4, 4), (5, 7), (8, 8),
         (3, 85), (85, 3), (16, 16))


def edge_key(left, right):
    return min(left, right), max(left, right)


def cycle_key(corners):
    """Identify a cell boundary without choosing a first corner or orientation."""
    corners = tuple(corners)
    reverse = corners[::-1]
    return min(row[offset:] + row[:offset]
               for row in (corners, reverse) for offset in range(len(row)))


def rectangular_quotient(width, height):
    """Glue just the boundary of one rectangle, without using canonical()."""
    def corner(column, row):
        if column == width:
            return (-row) % height
        return column * height + row % height

    faces = tuple((corner(column, row), corner(column + 1, row),
                   corner(column + 1, row + 1), corner(column, row + 1))
                  for column in range(width) for row in range(height))
    edges = {edge_key(face[index], face[(index + 1) % 4])
             for face in faces for index in range(4)}
    seams = {edge_key((width - 1) * height + row, (-row) % height)
             for row in range(height)}
    return tuple((*edge, 1) for edge in sorted(edges)), tuple(sorted(seams)), faces


def torus_cells(width, height):
    def node(column, row):
        return (column % width) * height + row % height

    faces = tuple((node(column, row), node(column + 1, row),
                   node(column + 1, row + 1), node(column, row + 1))
                  for column in range(width) for row in range(height))
    edges = {edge_key(face[index], face[(index + 1) % 4])
             for face in faces for index in range(4)}
    return tuple((*edge, 1) for edge in sorted(edges)), faces


def bfs_distances(vertex_count, edges, sources):
    adjacency = [set() for _ in range(vertex_count)]
    for edge in edges:
        left, right = edge[:2]
        adjacency[left].add(right)
        adjacency[right].add(left)
    distances = [None] * vertex_count
    pending = deque(sources)
    for source in pending:
        distances[source] = 0
    while pending:
        source = pending.popleft()
        for target in adjacency[source]:
            if distances[target] is None:
                distances[target] = distances[source] + 1
                pending.append(target)
    return tuple(distances)


def surface_properties(vertex_count, edges, faces):
    """Independent graph/cell oracle; each corner is an edge in its vertex link."""
    declared = {tuple(edge[:2]) for edge in edges}
    assert len(declared) == len(edges)
    assert all(0 <= left < right < vertex_count for left, right in declared)
    incidence = defaultdict(list)
    links = [Counter() for _ in range(vertex_count)]
    for face_index, face in enumerate(faces):
        assert len(face) == len(set(face)) == 4
        for index, source in enumerate(face):
            destination = face[(index + 1) % 4]
            edge = edge_key(source, destination)
            assert edge in declared
            incidence[edge].append((face_index, 1 if source < destination else -1))
            link_edge = edge_key(face[index - 1], destination)
            links[source][link_edge] += 1
    assert set(incidence) == declared
    assert all(len(rows) == 2 for rows in incidence.values())
    assert None not in bfs_distances(vertex_count, edges, (0,))

    for link in links:
        neighbors = defaultdict(list)
        for (left, right), multiplicity in link.items():
            neighbors[left].extend([right] * multiplicity)
            neighbors[right].extend([left] * multiplicity)
        assert neighbors and all(len(row) == 2 for row in neighbors.values())
        visited, pending = set(), [next(iter(neighbors))]
        while pending:
            source = pending.pop()
            if source not in visited:
                visited.add(source)
                pending.extend(neighbors[source])
        assert visited == set(neighbors)

    # Treat a chosen face orientation as a two-coloring of the signed dual.
    dual = defaultdict(list)
    for (first, first_sign), (second, second_sign) in incidence.values():
        relation = -first_sign * second_sign
        dual[first].append((second, relation))
        dual[second].append((first, relation))
    orientations = {}
    orientable = True
    for root in range(len(faces)):
        if root in orientations:
            continue
        orientations[root] = 1
        pending = [root]
        while pending:
            source = pending.pop()
            for destination, relation in dual[source]:
                expected = orientations[source] * relation
                if destination in orientations:
                    if orientations[destination] != expected:
                        orientable = False
                else:
                    orientations[destination] = expected
                    pending.append(destination)
    return vertex_count - len(edges) + len(faces), orientable


def pinched_euler_zero_complex():
    """Wedge two tori and a sphere: chi=0, but the wedge link has three cycles."""
    _, torus_faces = torus_cells(3, 3)
    cube_faces = ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
                  (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3))
    faces = list(torus_faces)
    for component, offset in ((torus_faces, 8), (cube_faces, 16)):
        faces.extend(tuple(0 if node == 0 else node + offset for node in face)
                     for face in component)
    edges = {edge_key(face[index], face[(index + 1) % 4])
             for face in faces for index in range(4)}
    return 24, tuple((*edge, 1) for edge in sorted(edges)), tuple(faces)


class KleinQuotientTests(unittest.TestCase):
    def test_default_and_nested_geometry_are_immutable(self):
        domain = KleinDomain()
        self.assertEqual((domain.width, domain.height), (8, 8))
        for name in ("nodes", "edges", "seams", "faces", "cover_edges", "cover_faces"):
            values = getattr(domain, name)
            self.assertIs(type(values), tuple)
            if name != "nodes":
                self.assertTrue(all(type(value) is tuple for value in values))
            with self.subTest(attribute=name), self.assertRaises((FrozenInstanceError, AttributeError)):
                setattr(domain, name, ())
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            domain.width = 4

    def test_negative_and_large_labels_have_floor_based_representatives(self):
        domain = KleinDomain(5, 7)
        examples = ((-1, 2, 0, (4, 5, 1)), (-5, 2, 1, (0, 5, 0)),
                    (-6, 2, 0, (4, 2, 0)), (5, -2, 1, (0, 2, 0)),
                    (10, -8, 0, (0, 6, 0)), (0, -1, 1, (0, 6, 1)))
        for u, v, orientation, expected in examples:
            with self.subTest(labels=(u, v, orientation)):
                self.assertEqual(domain.canonical(u, v, orientation), expected)
                self.assertEqual(domain.node(u, v), expected[0] * 7 + expected[1])

        # Generate equivalent charts by the two deck generators from every node.
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            for u in range(width):
                for v in range(height):
                    for wraps in (-1_000_001, -2, -1, 0, 1, 2, 1_000_002):
                        for orientation in (0, 1):
                            transported = orientation ^ (wraps & 1)
                            chart_v = (-v if wraps & 1 else v) + (wraps + 3) * height
                            self.assertEqual(domain.canonical(u + wraps * width, chart_v,
                                                              transported),
                                             (u, v, orientation))
                            self.assertEqual(domain.node(u + wraps * width, chart_v),
                                             u * height + v)

    def test_entire_quotient_matches_rectangle_boundary_gluing(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            with self.subTest(size=(width, height)):
                expected_edges, expected_seams, expected_faces = rectangular_quotient(width, height)
                self.assertEqual(domain.nodes, tuple(f"k:{u}:{v}" for u in range(width)
                                                    for v in range(height)))
                self.assertEqual(domain.edges, expected_edges)
                self.assertEqual(domain.seams, expected_seams)
                self.assertEqual(domain.faces, expected_faces)
                self.assertEqual(len(domain.edges), 2 * width * height)
                self.assertEqual(len(domain.faces), width * height)
                self.assertEqual(len(domain.seams), height)

    def test_every_local_step_and_reverse_traversal_follow_declared_relations(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            observed_edges, observed_seams = set(), set()
            for source in range(width * height):
                u, v = divmod(source, height)
                expected = {"u+": (((u + 1) * height + v, 0) if u + 1 < width else
                                   ((-v) % height, 1)),
                            "u-": (((u - 1) * height + v, 0) if u else
                                   ((width - 1) * height + (-v) % height, 1)),
                            "v+": (u * height + (v + 1) % height, 0),
                            "v-": (u * height + (v - 1) % height, 0)}
                for direction, inverse in (("u+", "u-"), ("u-", "u+"),
                                           ("v+", "v-"), ("v-", "v+")):
                    destination, tau = domain.step(source, direction)
                    self.assertEqual((destination, tau), expected[direction])
                    self.assertEqual(domain.step(destination, inverse), (source, tau))
                    observed_edges.add((*edge_key(source, destination), 1))
                    if tau:
                        observed_seams.add(edge_key(source, destination))
            self.assertEqual(observed_edges, set(domain.edges))
            self.assertEqual(observed_seams, set(domain.seams))

    def test_base_is_closed_connected_nonorientable_with_cyclic_links(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            with self.subTest(size=(width, height)):
                self.assertEqual(surface_properties(width * height, domain.edges, domain.faces),
                                 (0, False))

    def test_strict_dimension_chart_node_and_direction_validation(self):
        for invalid in (True, False, 3.0, "3", None, -1, 0, 1, 2, 86):
            for change in ({"width": invalid, "height": 3}, {"width": 3, "height": invalid}):
                with self.subTest(dimensions=change), self.assertRaises(ValueError):
                    KleinDomain(**change)
        with self.assertRaises(ValueError):
            KleinDomain(17, 16)
        domain = KleinDomain(3, 3)
        for invalid in (True, 1.0, "1", None, []):
            for labels in ((invalid, 0), (0, invalid)):
                with self.subTest(labels=labels), self.assertRaises(ValueError):
                    domain.canonical(*labels)
                with self.assertRaises(ValueError):
                    domain.node(*labels)
        for orientation in (True, -1, 2, 0.0, "0", None):
            with self.subTest(orientation=orientation), self.assertRaises(ValueError):
                domain.canonical(0, 0, orientation)
        for node in (True, -1, 9, 1.0, "0", None):
            with self.subTest(node=node), self.assertRaises(ValueError):
                domain.step(node, "u+")
        for direction in ("", "u", "U+", "x+", 0, True, None, []):
            with self.subTest(direction=direction), self.assertRaises(ValueError):
                domain.step(0, direction)


class OrientationCoverTests(unittest.TestCase):
    def test_every_edge_and_face_lifts_with_closed_seam_transport(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            seams = set(domain.seams)
            expected_edges = set()
            for left, right, length in domain.edges:
                tau = int((left, right) in seams)
                for orientation in (0, 1):
                    expected_edges.add((*edge_key(2 * left + orientation,
                                                  2 * right + (orientation ^ tau)), length))
            expected_faces = []
            for face in domain.faces:
                for initial in (0, 1):
                    orientation = initial
                    lifted = []
                    for index, node in enumerate(face):
                        lifted.append(2 * node + orientation)
                        orientation ^= int(edge_key(node, face[(index + 1) % 4]) in seams)
                    self.assertEqual(orientation, initial)
                    expected_faces.append(tuple(lifted))
            with self.subTest(size=(width, height)):
                self.assertEqual(set(domain.cover_edges), expected_edges)
                self.assertEqual(domain.cover_edges, tuple(sorted(expected_edges)))
                self.assertEqual(Counter(map(cycle_key, domain.cover_faces)),
                                 Counter(map(cycle_key, expected_faces)))

    def test_full_cover_edge_and_face_sets_are_bijective_with_periodic_torus(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)

            def torus_vertex(lifted):
                node, orientation = divmod(lifted, 2)
                u, v = divmod(node, height)
                return (u + orientation * width) * height + ((-v if orientation else v) % height)

            with self.subTest(size=(width, height)):
                self.assertEqual({torus_vertex(node) for node in range(2 * width * height)},
                                 set(range(2 * width * height)))
                mapped_edges = {(*edge_key(torus_vertex(left), torus_vertex(right)), weight)
                                for left, right, weight in domain.cover_edges}
                mapped_faces = Counter(cycle_key(tuple(map(torus_vertex, face)))
                                       for face in domain.cover_faces)
                torus_edges, torus_faces = torus_cells(2 * width, height)
                self.assertEqual(mapped_edges, set(torus_edges))
                self.assertEqual(mapped_faces, Counter(map(cycle_key, torus_faces)))
                self.assertEqual(len(domain.cover_edges), 4 * width * height)
                self.assertEqual(len(domain.cover_faces), 2 * width * height)

    def test_cover_is_connected_closed_orientable_with_cyclic_links(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            with self.subTest(size=(width, height)):
                self.assertEqual(surface_properties(2 * width * height,
                                                    domain.cover_edges, domain.cover_faces),
                                 (0, True))

    def test_nontrivial_horizontal_and_trivial_vertical_holonomy(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            cover_edges = {tuple(edge[:2]) for edge in domain.cover_edges}
            for direction in ("u+", "u-"):
                node, orientation = 0, 0
                for tick in range(2 * width):
                    destination, tau = domain.step(node, direction)
                    next_orientation = orientation ^ tau
                    self.assertIn(edge_key(2 * node + orientation,
                                           2 * destination + next_orientation), cover_edges)
                    node, orientation = destination, next_orientation
                    if tick == width - 1:
                        self.assertEqual((node, orientation), (0, 1))
                self.assertEqual((node, orientation), (0, 0))
            for start in range(width * height):
                for direction in ("v+", "v-"):
                    node, orientation = start, 1
                    for _ in range(height):
                        node, tau = domain.step(node, direction)
                        orientation ^= tau
                    self.assertEqual((node, orientation), (start, 1))

    def test_public_audit_agrees_with_independently_established_properties(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            result = domain.audit()
            self.assertEqual((result["width"], result["height"]), (width, height))
            for name, factor, orientable in (("base", 1, False), ("cover", 2, True)):
                surface = result[name]
                self.assertEqual((surface["vertices"], surface["edges"], surface["faces"]),
                                 (factor * width * height, 2 * factor * width * height,
                                  factor * width * height))
                self.assertEqual(surface["euler_characteristic"], 0)
                self.assertIs(surface["orientable"], orientable)
                for check in ("connected", "closed", "edge_incidence", "vertex_links"):
                    self.assertIs(surface[check], True)
            for check in ("seam_cocycle", "toroidal_cover_edges", "toroidal_cover_faces"):
                self.assertIs(result[check], True)
            self.assertEqual(result["holonomy"],
                             {"horizontal": 1, "double_horizontal": 0, "vertical": 0})


class KleinFieldTests(unittest.TestCase):
    def test_exact_field_does_not_substitute_radial_distance_minus_radius(self):
        domain = KleinDomain(4, 3)
        radial = bfs_distances(12, domain.edges, (1,))
        manifest = domain.field_manifest(center=1, radius=3)
        self.assertEqual(radial[2], 1)
        boundary = tuple(node for node, sign in enumerate(manifest.signs) if sign == 0)
        self.assertEqual(bfs_distances(12, domain.edges, boundary)[2], 3)
        self.assertEqual(evaluate_field(manifest)[2], -3)
        self.assertNotEqual(evaluate_field(manifest)[2], radial[2] - 3)

    def test_intrinsic_ball_signs_and_exact_field_match_independent_bfs(self):
        for width, height in SIZES:
            domain = KleinDomain(width, height)
            count = width * height
            for center in sorted({0, height - 1, count // 2, count - 1}):
                radial = bfs_distances(count, domain.edges, (center,))
                for radius in sorted({1, 2, max(radial)}):
                    with self.subTest(size=(width, height), center=center, radius=radius):
                        expected_signs = tuple((distance > radius) - (distance < radius)
                                               for distance in radial)
                        signs = domain.ball_signs(center, radius)
                        self.assertEqual(signs, expected_signs)
                        self.assertIs(type(signs), tuple)
                        self.assertIn(0, signs)
                        self.assertIn(-1, signs)
                        for left, right, _ in domain.edges:
                            self.assertNotEqual(signs[left] * signs[right], -1)
                        boundary = tuple(node for node, sign in enumerate(signs) if sign == 0)
                        exact_distances = bfs_distances(count, domain.edges, boundary)
                        expected = tuple(sign * distance for sign, distance in zip(signs, exact_distances))
                        manifest = domain.field_manifest(center=center, radius=radius)
                        self.assertEqual(manifest.signs, signs)
                        self.assertEqual(evaluate_field(manifest), expected)
                        cover_boundary = tuple(2 * node + orientation for node in boundary
                                               for orientation in (0, 1))
                        lifted_distances = bfs_distances(2 * count, domain.cover_edges, cover_boundary)
                        lifted_fields = tuple(signs[node // 2] * distance
                                              for node, distance in enumerate(lifted_distances))
                        self.assertEqual(lifted_fields, tuple(value for value in expected for _ in (0, 1)))

    def test_generated_manifest_retains_quotient_and_parameterized_program(self):
        domain = KleinDomain(5, 7)
        manifest = domain.field_manifest(center=9, radius=3, initial_node=33,
                                         initial_phase=19, initial_orientation=1,
                                         turns=(0, 128, 255), max_ticks=42, identity="klein-test")
        self.assertEqual(manifest.profile, "relational-sdf-v2")
        self.assertEqual(manifest.topology, (5, 7))
        self.assertEqual((manifest.nodes, manifest.edges, manifest.seams),
                         (domain.nodes, domain.edges, domain.seams))
        self.assertEqual(manifest.signs, domain.ball_signs(9, 3))
        self.assertEqual((manifest.initial_node, manifest.initial_phase, manifest.initial_orientation,
                          manifest.max_ticks, manifest.identity), (33, 19, 1, 42, "klein-test"))
        for node in range(35):
            self.assertEqual(manifest.routes[node], (domain.step(node, "u+")[0],) * 3)
            self.assertEqual(manifest.turns[node], (0, 128, 255))
        with self.assertRaises(FrozenInstanceError):
            manifest.topology = (3, 3)

    def test_ball_rejects_invalid_centers_and_radii(self):
        domain = KleinDomain(3, 4)
        diameter = max(bfs_distances(12, domain.edges, (0,)))
        for center in (-1, 12, True, 0.0, "0", None):
            with self.subTest(center=center), self.assertRaises(ValueError):
                domain.ball_signs(center, 1)
            with self.assertRaises(ValueError):
                domain.field_manifest(center=center, radius=1)
        for radius in (-1, 0, diameter + 1, True, 1.0, "1", None):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                domain.ball_signs(0, radius)
            with self.assertRaises(ValueError):
                domain.field_manifest(center=0, radius=radius)


class SurfaceAuditRejectionTests(unittest.TestCase):
    def test_domain_audit_rejects_damaged_cells_seams_and_cover(self):
        domain = KleinDomain(4, 5)
        damaged_values = (
            ("nodes", ("changed", *domain.nodes[1:])),
            ("edges", domain.edges[:-1]),
            ("faces", domain.faces[:-1]),
            ("seams", ()),
            ("seams", (*domain.seams, domain.seams[0])),
            ("seams", tuple(reversed(domain.seams))),
            ("seams", ((0, 0),)),
            ("seams", ((True, domain.seams[0][1]), *domain.seams[1:])),
            ("cover_edges", domain.cover_edges[:-1]),
            ("cover_faces", domain.cover_faces[:-1]),
        )
        for name, values in damaged_values:
            damaged = deepcopy(domain)
            # Deliberately bypass immutability to exercise audit failure paths.
            object.__setattr__(damaged, name, values)
            with self.subTest(attribute=name, values=values[:2]), self.assertRaises(ValueError):
                damaged.audit()

    def test_malformed_edges_faces_and_vertex_counts_are_rejected(self):
        domain = KleinDomain(4, 4)
        edges, faces = domain.edges, domain.faces
        malformed = (
            (16, edges[:-1], faces),
            (16, (*edges, edges[0]), faces),
            (16, ((0, 0, 1), *edges[1:]), faces),
            (16, ((edges[0][1], edges[0][0], 1), *edges[1:]), faces),
            (16, ((0, 16, 1), *edges[1:]), faces),
            (16, ((True, edges[0][1], 1), *edges[1:]), faces),
            (16, ((edges[0][0], edges[0][1], 0), *edges[1:]), faces),
            (16, edges, faces[:-1]),
            (16, edges, (*faces, faces[0])),
            (16, edges, (faces[0], *faces[2:], faces[0])),
            (16, edges, ((0, 0, 1, 2), *faces[1:])),
            (16, edges, ((0, 1, 2), *faces[1:])),
            (16, edges, ((0, 1, 2, 16), *faces[1:])),
            (16, edges, ((True, *faces[0][1:]), *faces[1:])),
            (17, edges, faces),
        )
        for index, arguments in enumerate(malformed):
            with self.subTest(case=index), self.assertRaises(ValueError):
                audit_surface(*arguments)
        for count in (True, 16.0, "16", None, 0, -1):
            with self.subTest(vertex_count=count), self.assertRaises(ValueError):
                audit_surface(count, edges, faces)

    def test_disconnected_closed_components_are_rejected(self):
        edges, faces = torus_cells(3, 3)
        doubled_edges = (*edges, *((left + 9, right + 9, weight) for left, right, weight in edges))
        doubled_faces = (*faces, *(tuple(node + 9 for node in face) for face in faces))
        self.assertEqual(18 - len(doubled_edges) + len(doubled_faces), 0)
        with self.assertRaises(ValueError):
            audit_surface(18, doubled_edges, doubled_faces)

    def test_correct_counts_edge_incidence_and_connectivity_do_not_excuse_pinched_link(self):
        count, edges, faces = pinched_euler_zero_complex()
        self.assertEqual(count - len(edges) + len(faces), 0)
        self.assertNotIn(None, bfs_distances(count, edges, (0,)))
        incidences = Counter(edge_key(face[index], face[(index + 1) % 4])
                             for face in faces for index in range(4))
        self.assertEqual(set(incidences), {tuple(edge[:2]) for edge in edges})
        self.assertEqual(set(incidences.values()), {2})
        with self.assertRaises(AssertionError):
            surface_properties(count, edges, faces)
        with self.assertRaises(ValueError):
            audit_surface(count, edges, faces)

    def test_audit_accepts_valid_cells_independently_of_face_order_and_orientation(self):
        domain = KleinDomain(3, 4)
        for count, edges, faces, orientable in ((12, domain.edges, domain.faces, False),
                                               (24, domain.cover_edges, domain.cover_faces, True)):
            changed = tuple(tuple(reversed(face)) if index % 2 else face[1:] + face[:1]
                            for index, face in enumerate(reversed(faces)))
            result = audit_surface(count, edges, changed)
            self.assertIs(result["orientable"], orientable)
            self.assertEqual(result["euler_characteristic"], 0)


if __name__ == "__main__":
    unittest.main()
