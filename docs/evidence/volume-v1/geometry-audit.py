"""Independent, preimplementation audit of the proposed three-dimensional binding.

Only the Python standard library is used.  No runtime module, reference producer,
device API, or generated fixture is imported.  These are mathematical reference
checks, not evidence of an implemented CPU/GPU geometry pipeline.
"""
from collections import Counter, defaultdict, deque
from hashlib import sha256
from itertools import combinations, product
import json
from math import gcd
from pathlib import Path
import random


AXES = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
DIRECTIONS = AXES + tuple(tuple(-x for x in a) for a in AXES)
MASK16 = 65535
MAX_I32 = 2147483647


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def scale(a, n):
    return tuple(n * x for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def projection(shape, point):
    width, height, depth = shape
    x, y, z = point
    winding, u = divmod(x, width)
    return u, (-y if winding & 1 else y) % height, z % depth


def index(shape, point):
    _, height, depth = shape
    x, y, z = projection(shape, point)
    return (x * height + y) * depth + z


def position(shape, vertex):
    _, height, depth = shape
    x, yz = divmod(vertex, height * depth)
    return x, yz // depth, yz % depth


def volume(shape):
    return shape[0] * shape[1] * shape[2]


def adjacency(shape):
    return [tuple(index(shape, add(position(shape, n), direction))
                  for direction in DIRECTIONS) for n in range(volume(shape))]


def cell(shape, anchor, axes):
    """Canonicalize the entire unit cell, including a reflected interval anchor."""
    width, height, depth = shape
    x, y, z = anchor
    winding, u = divmod(x, width)
    if winding & 1:
        y = -y - (1 if 1 in axes else 0)
    return (u, y % height, z % depth), tuple(axes)


def cell_boundary(shape, descriptor):
    anchor, axes = descriptor
    return tuple(cell(shape, add(anchor, scale(AXES[axis], side)),
                      tuple(i for i in axes if i != axis))
                 for axis in axes for side in (0, 1))


def cube_parts(shape, anchor, dimension):
    result = set()
    for free in combinations(range(3), dimension):
        fixed = tuple(i for i in range(3) if i not in free)
        for bits in product((0, 1), repeat=len(fixed)):
            offset = [0, 0, 0]
            for axis, bit in zip(fixed, bits):
                offset[axis] = bit
            result.add(cell(shape, add(anchor, offset), free))
    return result


def topology_audit():
    totals = Counter()
    dimension_digest = sha256()
    for width in range(3, 29):
        for height in range(3, 29):
            for depth in range(3, 29):
                shape = width, height, depth
                if volume(shape) > 256:
                    continue
                n = volume(shape)
                anchors = [position(shape, v) for v in range(n)]
                cells = [{cell(shape, a, free) for a in anchors
                          for free in combinations(range(3), k)} for k in range(4)]
                assert tuple(map(len, cells)) == (n, 3 * n, 3 * n, n)
                assert sum((-1) ** k * len(cells[k]) for k in range(4)) == 0
                cofaces = [defaultdict(set) for _ in range(3)]
                for k in (1, 2, 3):
                    for descriptor in cells[k]:
                        boundary = cell_boundary(shape, descriptor)
                        assert len(set(boundary)) == 2 * k
                        assert all(part in cells[k - 1] for part in boundary)
                        for part in boundary:
                            cofaces[k - 1][part].add(descriptor)
                        if k >= 2:
                            twice = Counter(part for face in boundary
                                            for part in cell_boundary(shape, face))
                            assert all(count == 2 for count in twice.values())
                            totals['boundary_squared_zero'] += 1
                assert all(len(x) == 6 for x in cofaces[0].values())
                assert all(len(x) == 4 for x in cofaces[1].values())
                assert all(len(x) == 2 for x in cofaces[2].values())
                cubes_at = defaultdict(list)
                for anchor in anchors:
                    parts = [cube_parts(shape, anchor, k) for k in range(3)]
                    assert tuple(map(len, parts)) == (8, 12, 6)
                    for vertex in parts[0]:
                        edges = frozenset(edge for edge in parts[1]
                                          if vertex in cell_boundary(shape, edge))
                        assert len(edges) == 3
                        cubes_at[vertex].append(edges)
                for vertex in cells[0]:
                    triangles = set(cubes_at[vertex])
                    vertices = set().union(*triangles)
                    edges = Counter(frozenset(pair) for tri in triangles
                                    for pair in combinations(tri, 2))
                    assert (len(vertices), len(edges), len(triangles)) == (6, 12, 8)
                    assert all(count == 2 for count in edges.values())
                    assert all(sum(v in tri for tri in triangles) == 4 for v in vertices)
                    opposite = [frozenset(pair) for pair in combinations(vertices, 2)
                                if frozenset(pair) not in edges]
                    assert len(opposite) == 3
                    assert len(set().union(*opposite)) == 6
                    assert all(len(tri & pair) == 1 for tri in triangles for pair in opposite)
                    totals['octahedral_vertex_links'] += 1
                adj = adjacency(shape)
                assert all(len(set(row)) == 6 for row in adj)
                assert all(u in adj[v] for u, row in enumerate(adj) for v in row)
                reached = {0}
                pending = [0]
                while pending:
                    for dest in adj[pending.pop()]:
                        if dest not in reached:
                            reached.add(dest)
                            pending.append(dest)
                assert len(reached) == n
                # Explicit periodic 2W x H x D cover: each fiber has exactly two
                # points and its six edges map bijectively onto base adjacency.
                fibers = Counter()
                for x, y, z in product(range(2 * width), range(height), range(depth)):
                    base = index(shape, (x, y, z))
                    fibers[base] += 1
                    images = []
                    for direction in DIRECTIONS:
                        point = add((x, y, z), direction)
                        periodic = point[0] % (2 * width), point[1] % height, point[2] % depth
                        images.append(index(shape, periodic))
                    assert set(images) == set(adj[base])
                    totals['orientation_cover_vertices'] += 1
                assert set(fibers) == set(range(n)) and set(fibers.values()) == {2}
                # The cover is cubical, not merely a graph cover.  Periodic
                # cover cells have two images per base cell, and their face
                # maps commute with projection, including reflected intervals.
                for dimension in range(4):
                    cell_fibers = Counter()
                    for anchor in product(range(2 * width), range(height), range(depth)):
                        for free in combinations(range(3), dimension):
                            image = cell(shape, anchor, free)
                            cell_fibers[image] += 1
                            projected_faces = set()
                            for axis in free:
                                for side in (0, 1):
                                    corner = add(anchor, scale(AXES[axis], side))
                                    periodic = corner[0] % (2 * width), corner[1] % height, corner[2] % depth
                                    projected_faces.add(cell(shape, periodic, tuple(i for i in free if i != axis)))
                            assert projected_faces == set(cell_boundary(shape, image))
                            totals['orientation_cover_cells'] += 1
                    assert set(cell_fibers) == cells[dimension]
                    assert set(cell_fibers.values()) == {2}
                # The x loop at y=0 closes after W steps but reverses its frame.
                cursor, parity = (0, 0, 0), 0
                for _ in range(width):
                    nxt = add(cursor, AXES[0])
                    parity ^= int(nxt[0] == width)
                    cursor = projection(shape, nxt)
                assert cursor == (0, 0, 0) and parity == 1
                totals['domains'] += 1
                totals['vertices'] += n
                totals['edges'] += 3 * n
                totals['faces'] += 3 * n
                totals['cubes'] += n
                dimension_digest.update(f'{width},{height},{depth}\n'.encode())
    assert totals['domains'] == 523
    return dict(totals), dimension_digest.hexdigest()


def frame(shaft, eta):
    axis, sign = shaft % 3, (1 if shaft < 3 else -1)
    return scale(AXES[axis], sign), scale(AXES[(axis + 1) % 3], (-1) ** eta), scale(AXES[(axis + 2) % 3], sign)


def transported(shape, apex, vectors, lift):
    m, n, ell = lift
    width, height, depth = shape
    sign = -1 if m & 1 else 1
    anchor = apex[0] + m * width, sign * apex[1] + n * height, apex[2] + ell * depth
    return anchor, tuple((v[0], sign * v[1], v[2]) for v in vectors)


def member(kind, s, t, r, extent, p, q):
    if kind == 'sphere':
        return s * s + t * t + r * r <= extent * extent
    if not 0 <= s <= extent:
        return False
    if kind == 'cone':
        return q * q * (t * t + r * r) <= p * p * s * s
    if kind == 'pyramid':
        return q * max(abs(t), abs(r)) <= p * s
    raise ValueError(kind)


def local_bounds(kind, extent, p, q):
    transverse = extent if kind == 'sphere' else (p * extent) // q
    return ((-extent if kind == 'sphere' else 0, extent),
            (-transverse, transverse), (-transverse, transverse))


def local_sites(kind, extent, p, q):
    bounds = local_bounds(kind, extent, p, q)
    return [v for v in product(*(range(lo, hi + 1) for lo, hi in bounds))
            if member(kind, *v, extent, p, q)]


def cover_point(apex, vectors, coordinates):
    return tuple(apex[i] + sum(c * v[i] for c, v in zip(coordinates, vectors)) for i in range(3))


def site_projection(shape, apex, vectors, sites):
    return {index(shape, cover_point(apex, vectors, local)) for local in sites}


def walk(shape, apex, vectors, coordinates, order):
    """Repeated quotient steps; does not call the cover projection function."""
    width, height, depth = shape
    point = tuple(apex)
    directions = tuple(vectors)
    for component in order:
        count = coordinates[component]
        for _ in range(abs(count)):
            direction = scale(directions[component], 1 if count >= 0 else -1)
            x, y, z = add(point, direction)
            crossed = x < 0 or x >= width
            if crossed:
                x = width - 1 if x < 0 else 0
                y = -y
                directions = tuple((v[0], -v[1], v[2]) for v in directions)
            point = x, y % height, z % depth
    return (point[0] * height + point[1]) * depth + point[2]


def ceiling_div(a, b):
    return -((-a) // b)


def inverse_lift(shape, apex, vectors, kind, extent, p, q):
    """Test each canonical vertex's inverse deck lifts inside a bounding box."""
    width, height, depth = shape
    corners = [cover_point(apex, vectors, point)
               for point in product(*local_bounds(kind, extent, p, q))]
    lower = tuple(min(c[i] for c in corners) for i in range(3))
    upper = tuple(max(c[i] for c in corners) for i in range(3))
    occupied, inspected = set(), 0
    for vertex in range(volume(shape)):
        u, v, w = position(shape, vertex)
        for m in range(ceiling_div(lower[0] - u, width), (upper[0] - u) // width + 1):
            v_lift = (-v if m & 1 else v)
            for n in range(ceiling_div(lower[1] - v_lift, height), (upper[1] - v_lift) // height + 1):
                for ell in range(ceiling_div(lower[2] - w, depth), (upper[2] - w) // depth + 1):
                    displacement = (u + m * width - apex[0], v_lift + n * height - apex[1], w + ell * depth - apex[2])
                    s, t, r = (dot(displacement, vector) for vector in vectors)
                    inspected += 1
                    if member(kind, s, t, r, extent, p, q):
                        occupied.add(vertex)
    return occupied, inspected


def redistance(shape, occupancy):
    adj = adjacency(shape)
    inside = set(occupancy)
    boundary = {u for u in inside if any(v not in inside for v in adj[u])}
    if not boundary:
        raise ValueError('No boundary for empty or full occupancy')
    distance = [None] * volume(shape)
    pending = deque(sorted(boundary))
    for u in pending:
        distance[u] = 0
    while pending:
        u = pending.popleft()
        for v in adj[u]:
            if distance[v] is None:
                distance[v] = distance[u] + 1
                pending.append(v)
    signs = [0 if u in boundary else -1 if u in inside else 1 for u in range(volume(shape))]
    phi = [s * d for s, d in zip(signs, distance)]
    assert all(abs(phi[u] - phi[v]) <= 1 for u, row in enumerate(adj) for v in row)
    assert all(d == 0 or any(distance[v] + 1 == d for v in adj[u]) for u, d in enumerate(distance))
    assert max(map(abs, phi)) <= 127
    # Independent all-pairs relaxation verifies exact magnitudes, not just signs.
    inf = volume(shape) + 1
    paths = [[0 if a == b else 1 if b in adj[a] else inf for b in range(volume(shape))] for a in range(volume(shape))]
    for pivot in range(volume(shape)):
        pivot_row = paths[pivot]
        for row in paths:
            to_pivot = row[pivot]
            for dest, value in enumerate(pivot_row):
                candidate = to_pivot + value
                if candidate < row[dest]:
                    row[dest] = candidate
    assert distance == [min(row[b] for b in boundary) for row in paths]
    occupied_cubes = []
    for u in range(volume(shape)):
        anchor = position(shape, u)
        vertices = {index(shape, add(anchor, bits)) for bits in product((0, 1), repeat=3)}
        if vertices <= inside:
            occupied_cubes.append(u)
    return {'occupancy': sorted(inside), 'boundary': sorted(boundary),
            'interior': sorted(inside - boundary), 'signs': signs, 'fields': phi,
            'complete_occupied_cubes': occupied_cubes}


def geometry_audit():
    totals = Counter()
    checksum = sha256()
    domains = ((3, 3, 3), (4, 5, 6), (5, 4, 6), (7, 6, 6), (4, 8, 8))
    primitives = (('sphere', 2, 1, 1), ('cone', 3, 1, 2), ('cone', 3, 2, 1), ('pyramid', 3, 1, 1))
    lifts = ((-3, 2, -2), (-2, -1, 3), (1, -2, 1), (2, 1, -1), (0, 0, 0))
    for shape in domains:
        for apex in ((0, 0, 0), tuple(d - 1 for d in shape)):
            for shaft, eta in product(range(6), (0, 1)):
                vectors = frame(shaft, eta)
                assert all(dot(a, b) == (i == j) for i, a in enumerate(vectors) for j, b in enumerate(vectors))
                mirror = frame(shaft, 1 - eta)
                assert mirror == (vectors[0], scale(vectors[1], -1), vectors[2])
                for kind, extent, p, q in primitives:
                    sites = local_sites(kind, extent, p, q)
                    expected = site_projection(shape, apex, vectors, sites)
                    for coordinates in sites:
                        dest = index(shape, cover_point(apex, vectors, coordinates))
                        for order in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
                            assert walk(shape, apex, vectors, coordinates, order) == dest
                            totals['transported_walk_endpoints'] += 1
                    assert site_projection(shape, apex, mirror, sites) == expected
                    totals['full_mirror_occupancy_comparisons'] += 1
                    for lift in lifts:
                        anchor, moved = transported(shape, apex, vectors, lift)
                        assert site_projection(shape, anchor, moved, sites) == expected
                        inverse, inspected = inverse_lift(shape, anchor, moved, kind, extent, p, q)
                        assert inverse == expected
                        totals['deck_occupancy_comparisons'] += 1
                        totals['inverse_lift_occupancy_comparisons'] += 1
                        totals['inverse_lift_candidates'] += inspected
                    checksum.update(json.dumps([shape, apex, shaft, eta, kind, extent, p, q, sorted(expected)], separators=(',', ':')).encode())
                    totals['primitive_cases'] += 1
                    totals['accepted_local_sites'] += len(sites)
    # Independent nonwrapping 6x6x6 witnesses, with actual occupied 3-cells.
    shape, apex, vectors = (6, 6, 6), (0, 3, 3), frame(0, 0)
    witnesses = {}
    for kind, extent, denominator in (('sphere', 2, 1), ('cone', 4, 2), ('pyramid', 4, 2)):
        center = (3, 3, 3) if kind == 'sphere' else apex
        occupied = site_projection(shape, center, vectors, local_sites(kind, extent, 1, denominator))
        witness = redistance(shape, occupied)
        assert witness['interior'] and witness['complete_occupied_cubes']
        witness.update({'shape': list(shape), 'apex': list(center), 'shaft': 0, 'eta': 0, 'extent': extent, 'numerator': 1, 'denominator': denominator,
                        'local_axial_layer_counts': [sum(point[0] == s for point in local_sites(kind, extent, 1, denominator)) for s in range(-extent if kind == 'sphere' else 0, extent + 1)]})
        witnesses[kind] = witness
    separating = index(shape, cover_point(apex, vectors, (2, 1, 1)))
    assert separating in witnesses['pyramid']['occupancy'] and separating not in witnesses['cone']['occupancy']
    cone_section = {index(shape, cover_point(apex, vectors, local)) for local in local_sites('cone', 4, 1, 2) if local[2] == 0}
    pyramid_section = {index(shape, cover_point(apex, vectors, local)) for local in local_sites('pyramid', 4, 1, 2) if local[2] == 0}
    assert cone_section == pyramid_section
    sphere = set(witnesses['sphere']['occupancy'])
    cone = set(witnesses['cone']['occupancy'])
    pyramid = set(witnesses['pyramid']['occupancy'])
    assert sphere != cone and sphere != pyramid and cone != pyramid
    full_cube = [index(shape, cover_point(apex, vectors, point)) for point in product((3, 4), (0, 1), (0, 1))]
    assert set(full_cube) <= cone
    witnesses['separation'] = {'local_point': [2, 1, 1], 'canonical_vertex': separating,
                               'in_pyramid': True, 'in_cone': False,
                               'shared_axial_section': sorted(cone_section),
                               'cone_complete_cube_vertices': sorted(full_cube)}
    witnesses['mixed_union'] = redistance(shape, sphere | cone)
    return dict(totals), checksum.hexdigest(), witnesses


def limbs(value):
    assert 0 <= value < 1 << 64
    return tuple((value >> (16 * i)) & MASK16 for i in range(4))


def unlimbs(value):
    return sum(lane << (16 * i) for i, lane in enumerate(value))


def square32(value):
    """Schoolbook 16-bit lanes; each multiply-add fits an unsigned 32-bit lane."""
    assert 0 <= value <= MAX_I32
    operand = (value & MASK16, value >> 16)
    output = [0, 0, 0, 0]
    for i in range(2):
        carry = 0
        for j in range(2):
            total = output[i + j] + operand[i] * operand[j] + carry
            assert 0 <= total <= 4294967295
            output[i + j] = total & MASK16
            carry = total >> 16
        k = i + 2
        while carry:
            assert k < 4
            total = output[k] + carry
            assert total <= 131070
            output[k], carry = total & MASK16, total >> 16
            k += 1
    return tuple(output)


def add64(left, right):
    result, carry = [], 0
    for a, b in zip(left, right):
        total = a + b + carry
        assert 0 <= total <= 131071
        result.append(total & MASK16)
        carry = total >> 16
    return tuple(result), carry


def compare64(left, right):
    for a, b in zip(reversed(left), reversed(right)):
        if a != b:
            return (a > b) - (a < b)
    return 0


def arithmetic_audit():
    rng = random.Random(0x3D16B17)
    values = sorted({0, 1, 2, 3, 255, 256, 257, 32767, 32768, 46340, 46341,
                     65534, 65535, 65536, 65537, 131071, 131072,
                     16777215, 16777216, 1073741823, 1073741824,
                     MAX_I32 - 2, MAX_I32 - 1, MAX_I32,
                     *(rng.randrange(MAX_I32 + 1) for _ in range(2000))})
    totals = Counter()
    for value in values:
        assert unlimbs(square32(value)) == value * value
        totals['squares'] += 1
    pairs = list(product(values[:24] + values[-24:], repeat=2))
    pairs += [(rng.randrange(MAX_I32 + 1), rng.randrange(MAX_I32 + 1)) for _ in range(20000)]
    for a, b in pairs:
        sa, sb = square32(a), square32(b)
        total, carry = add64(sa, sb)
        assert carry == 0 and unlimbs(total) == a * a + b * b
        assert compare64(sa, sb) == ((a * a > b * b) - (a * a < b * b))
        totals['square_sum_and_comparison_pairs'] += 1
    # Exercise every carry lane and the explicit overflow result independently.
    boundary = [0, 1, (1 << 64) - 1]
    for bit in (16, 32, 48, 63):
        boundary += [(1 << bit) - 1, 1 << bit, (1 << bit) + 1]
    for a, b in product(boundary, repeat=2):
        result, carry = add64(limbs(a), limbs(b))
        assert unlimbs(result) + (carry << 64) == a + b
        assert compare64(limbs(a), limbs(b)) == ((a > b) - (a < b))
        totals['full_u64_carry_pairs'] += 1
    # The geometric operands q|t|, q|r| and p*s may approach MAX_I32;
    # membership squares must not be narrowed to native u32 arithmetic.
    triples = []
    for p, q in ((1, 1), (32767, 32768), (65535, 65534), (65534, 65535), (65535, 1), (1, 65535)):
        assert gcd(p, q) == 1
        limit_s = MAX_I32 // p
        limit_t = MAX_I32 // q
        for s in {1, min(65535, limit_s), limit_s - 1, limit_s}:
            if s < 0:
                continue
            for t, r in ((0, 0), (limit_t, 0), (limit_t, limit_t), (limit_t - 1, limit_t), (1, 1)):
                triples.append((p, q, s, t, r))
    for _ in range(10000):
        p, q = rng.randrange(1, 65536), rng.randrange(1, 65536)
        if gcd(p, q) != 1:
            continue
        triples.append((p, q, rng.randrange(MAX_I32 // p + 1), rng.randrange(MAX_I32 // q + 1), rng.randrange(MAX_I32 // q + 1)))
    overflow_witnesses = []
    for p, q, s, t, r in triples:
        a, b, c = q * abs(t), q * abs(r), p * s
        total, carry = add64(square32(a), square32(b))
        assert carry == 0
        actual = compare64(total, square32(c)) <= 0
        expected = q * q * (t * t + r * r) <= p * p * s * s
        assert actual == expected
        narrowed = ((a * a + b * b) & 4294967295) <= ((c * c) & 4294967295)
        if narrowed != expected and len(overflow_witnesses) < 8:
            overflow_witnesses.append({'p': p, 'q': q, 's': s, 't': t, 'r': r,
                                      'left_integer': a * a + b * b, 'right_integer': c * c,
                                      'left_limbs': list(total), 'right_limbs': list(square32(c)),
                                      'exact_inside': expected, 'wrong_u32_inside': narrowed})
        totals['geometric_square_sum_membership_cases'] += 1
    assert overflow_witnesses
    return dict(totals), overflow_witnesses


def budget_audit():
    """Evaluate the stated bounds with unbounded integers before any enumeration."""
    rng = random.Random(0xC0B1C)
    counts = Counter()
    candidates = [(h, p, q, power) for h, power in product((1, 2, 3, 32767, 32768, 65535), (0, 1, 4))
                  for p, q in ((1, 1), (1, 65535), (65535, 1), (65535, 65534), (65534, 65535), (32767, 32768))]
    candidates += [(rng.randrange(1, 65536), rng.randrange(1, 65536), rng.randrange(1, 65536), rng.randrange(5)) for _ in range(10000)]
    examples = []
    for h, p, q, power in candidates:
        counts['candidates'] += 1
        if gcd(p, q) != 1:
            counts['not_reduced'] += 1
            continue
        length = h << power
        radial_product = p * length
        breadth = radial_product // q
        width_guard = max(6, 6, 6) - 1 + length + breadth
        work = (length + 1) * (2 * breadth + 1) ** 2
        reason = ('p_times_length' if radial_product > MAX_I32 else
                  'q_times_breadth' if q * breadth > MAX_I32 else
                  'coordinate_bound' if width_guard > MAX_I32 else
                  'site_budget' if work > 16777216 else 'admitted')
        counts[reason] += 1
        if reason == 'admitted':
            assert 1 <= length <= 65535 * 16
            assert 0 <= breadth and q * breadth <= radial_product <= MAX_I32
            assert width_guard <= MAX_I32 and work <= 16777216
            # Sampling the complete rectangle endpoints proves the operand bounds
            # relevant to square32 without enumerating a huge accepted rectangle.
            for s in {0, length // 2, length}:
                for t, r in product((-breadth, 0, breadth), repeat=2):
                    a, b, c = q * abs(t), q * abs(r), p * s
                    assert 0 <= min(a, b, c) and max(a, b, c) <= MAX_I32
                    result, carry = add64(square32(a), square32(b))
                    assert carry == 0 and unlimbs(result) == a * a + b * b
                    assert (compare64(result, square32(c)) <= 0) == member('cone', s, t, r, length, p, q)
                    counts['admitted_rectangle_operand_samples'] += 1
            if len(examples) < 8:
                examples.append({'h': h, 'p': p, 'q': q, 'scale': power, 'length': length,
                                 'breadth': breadth, 'charged_sites': work})
    # This valid, tiny primitive defeats a u32-only square comparison.  Its
    # original parameters remain admitted; no narrowing of p or q is permitted.
    h, p, q, power = 2, 65535, 65534, 0
    length, breadth = h << power, p * (h << power) // q
    charged = (length + 1) * (2 * breadth + 1) ** 2
    assert charged == 75
    failures = []
    for s, t, r in product(range(length + 1), range(-breadth, breadth + 1), range(-breadth, breadth + 1)):
        a, b, c = q * abs(t), q * abs(r), p * s
        lhs, carry = add64(square32(a), square32(b))
        assert not carry
        exact = compare64(lhs, square32(c)) <= 0
        assert exact == member('cone', s, t, r, length, p, q)
        wrong = ((a * a + b * b) & 4294967295) <= ((c * c) & 4294967295)
        if wrong != exact:
            failures.append({'s': s, 't': t, 'r': r, 'exact_inside': exact, 'wrong_u32_inside': wrong})
    assert failures
    sphere_charges = [(2 * radius + 1) ** 3 for radius in range(1, 128)]
    assert sphere_charges[-1] == 16581375 < 16777216
    assert (2 * 128 + 1) ** 3 > 16777216
    for charge in sphere_charges:
        # Admission charges rejected sites too, not just actual lattice members.
        assert charge > 0 and charge <= 16777216
    counts['sphere_radius_charges'] = len(sphere_charges)
    counts['small_valid_wide_operand_sites'] = charged
    counts['small_valid_native_u32_wrong_memberships'] = len(failures)
    assert sum(counts[k] for k in ('not_reduced', 'p_times_length', 'q_times_breadth', 'coordinate_bound', 'site_budget', 'admitted')) == counts['candidates']
    assert counts['coordinate_bound'] > 0
    assert counts['q_times_breadth'] == 0  # q*floor(pL/q) <= pL is proved by integer division.
    return {'counts': dict(counts), 'admitted_examples': examples,
            'derived_bound': 'q*floor(pL/q) <= pL; the qB guard cannot fail after a valid pL guard',
            'coordinate_guard_witness': {'shape': [6, 6, 6], 'h': 32768, 'p': 65535, 'q': 1, 'scale': 0,
                                         'p_times_length': 2147450880, 'coordinate_bound': 2147483653,
                                         'rejected_before_enumeration': True},
            'maximum_radius_sphere_charge': sphere_charges[-1],
            'small_valid_wide_operand_primitive': {'h': h, 'p': p, 'q': q, 'scale': power,
                                                   'length': length, 'breadth': breadth,
                                                   'charged_sites': charged, 'u32_failures': failures}}


def literal_fixture_audit():
    """Separately reconstructed literals; no reference-producer output is read."""
    fixtures = (
        ('cone_6_cubed', (6, 6, 6), 57, 0, 0, 'cone', 2, 1, 1),
        ('pyramid_6_cubed', (6, 6, 6), 57, 0, 0, 'pyramid', 2, 1, 1),
        ('sphere_6_cubed', (6, 6, 6), 129, 0, 0, 'sphere', 2, 1, 1),
        ('negative_u_cone', (4, 5, 3), 4, 3, 0, 'cone', 3, 1, 2),
        ('multiwrap_pyramid', (5, 4, 3), 53, 0, 0, 'pyramid', 9, 1, 4),
        ('zero_breadth_cone', (4, 5, 3), 21, 2, 0, 'cone', 4, 1, 9),
    )
    report = []
    for name, shape, vertex, shaft, eta, kind, extent, p, q in fixtures:
        apex = position(shape, vertex)
        vectors = frame(shaft, eta)
        sites = local_sites(kind, extent, p, q)
        occupancy = site_projection(shape, apex, vectors, sites)
        inverse, _ = inverse_lift(shape, apex, vectors, kind, extent, p, q)
        assert occupancy == inverse
        data = redistance(shape, occupancy)
        data.update({'name': name, 'shape': list(shape), 'apex': vertex, 'shaft': shaft,
                     'eta': eta, 'kind': kind, 'extent': extent, 'numerator': p,
                     'denominator': q, 'accepted_cover_sites': len(sites),
                     'charged_sites': (2 * extent + 1) ** 3 if kind == 'sphere' else
                     (extent + 1) * (2 * (p * extent // q) + 1) ** 2})
        report.append(data)
    return report


def main():
    topology, domains_sha = topology_audit()
    geometry, occupancy_sha, witnesses = geometry_audit()
    arithmetic, overflow = arithmetic_audit()
    budgets = budget_audit()
    literals = literal_fixture_audit()
    report = {
        'format': 'solvefinite-volume-geometry-audit-v1',
        'status': 'preimplementation mathematical expectations; no CPU/GPU runtime conformance asserted',
        'producer_independence': 'Python standard library only; no runtime or reference-producer imports',
        'script_sha256_lf': sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        'dimension_triples_sha256': domains_sha,
        'primitive_occupancy_matrix_sha256': occupancy_sha,
        'topology_counts': topology, 'geometry_counts': geometry,
        'arithmetic_counts': arithmetic, 'native_u32_failure_witnesses': overflow,
        'literal_geometry_witnesses': witnesses, 'bound_audit': budgets,
        'independent_literal_fixtures': literals,
        'checks': {
            'all_523_admissible_domains_are_closed_connected_cubical_3_complexes': True,
            'cell_boundary_squared_is_zero': True,
            'every_vertex_link_is_an_octahedral_2_sphere': True,
            'each_face_has_exactly_two_incident_cubes': True,
            'explicit_orientation_double_cover_preserves_six_neighbors': True,
            'cubical_orientation_cover_has_two_cell_fibers_and_commuting_face_maps': True,
            'reversing_closed_loop_exists': True,
            'site_projection_equals_independently_transported_unit_walks': True,
            'translated_reflected_deck_frames_preserve_occupancy': True,
            'inverse_lift_membership_equals_projected_sites': True,
            'full_mirror_flips_only_first_transverse_axis_and_preserves_occupancy': True,
            'sphere_cone_and_pyramid_have_distinct_3d_occupancy': True,
            'cone_and_pyramid_share_axial_section_but_differ_off_axis': True,
            'all_three_solids_have_interior_and_complete_occupied_3_cells': True,
            'union_boundary_redistance_matches_all_pairs_relaxation': True,
            'four_u16_limb_square_add_compare_match_bigints': True,
            'geometric_membership_exercises_native_u32_overflow_failures': True,
            'original_operand_domains_are_preserved_under_preflight_bounds': True,
            'small_admitted_75_site_cone_requires_wide_square_arithmetic': True,
            'full_sphere_enumeration_is_charged_through_radius_127': True,
        },
        'scope_limits': ['No continuum Euclidean-distance claim: the field metric is six-neighbor graph distance.',
                         'No CPU/GPU pipeline, performance, physical adapter, or universality evidence.',
                         'Numerical realization choices must be incorporated into the consolidated PDF before runtime implementation.'],
    }
    output = Path(__file__).with_name('geometry-audit.json')
    encoded = (json.dumps(report, indent=2, sort_keys=True) + '\n').encode()
    output.write_bytes(encoded)
    print(json.dumps({'output': str(output), 'sha256': sha256(encoded).hexdigest(),
                      'topology': topology, 'geometry': geometry, 'arithmetic': arithmetic,
                      'checks': len(report['checks'])}, sort_keys=True))


if __name__ == '__main__':
    main()
