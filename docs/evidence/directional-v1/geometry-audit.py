"""Independent formal-only directional geometry audit; no runtime claims.

Uses only the standard library. Does not import solvefinite or the directional
reference producer. Cover projection, transported walks, Floyd-Warshall,
orientation-cover distance and guarded arithmetic provide distinct checks.
"""
from collections import deque
from hashlib import sha256
import json
from math import gcd
from pathlib import Path


DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))
GAINS = ((1, 1), (-1, 1), (-1, -1), (1, -1))


def canonical(width, height, x, y):
    q, u = divmod(x, width)
    return u * height + ((-y if q & 1 else y) % height)


def adjacency(width, height):
    return [tuple(canonical(width, height, u + dx, v + dy) for dx, dy in DIRECTIONS)
            for u in range(width) for v in range(height)]


def distances(adj, seeds):
    result = [-1] * len(adj)
    pending = deque(seeds)
    for vertex in pending:
        result[vertex] = 0
    while pending:
        current = pending.popleft()
        for neighbor in adj[current]:
            if result[neighbor] < 0:
                result[neighbor] = result[current] + 1
                pending.append(neighbor)
    return result


def footprint(width, height, apex, axis, eta, extent, numerator, denominator, *, lift=(0, 0)):
    x, y = divmod(apex, height)
    m, n = lift
    x, y = x + m * width, (-y if m & 1 else y) + n * height
    eu, ev = DIRECTIONS[axis]
    tu, tv = -ev * (-1 if eta else 1), eu * (-1 if eta else 1)
    if m & 1:
        ev, tv = -ev, -tv
    result = []
    for s in range(extent + 1):
        radius = numerator * s // denominator
        for t in range(-radius, radius + 1):
            result.append(canonical(width, height, x + s * eu + t * tu, y + s * ev + t * tv))
    return result


def transported_walk(width, height, apex, axis, eta, s, t):
    node = apex
    e = DIRECTIONS[axis]
    transverse = (-e[1] * (-1 if eta else 1), e[0] * (-1 if eta else 1))
    for category, count in ((0, s), (1, abs(t))):
        for _ in range(count):
            du, dv = e if category == 0 else transverse
            if category and t < 0:
                du, dv = -du, -dv
            u, v = divmod(node, height)
            crossings = (u + du) // width
            node = canonical(width, height, u + du, v + dv)
            if crossings & 1:
                e, transverse = (e[0], -e[1]), (transverse[0], -transverse[1])
    return node


def field(width, height, occupied):
    adj = adjacency(width, height)
    inside = set(occupied)
    boundary = sorted(vertex for vertex in inside if any(neighbor not in inside for neighbor in adj[vertex]))
    if not boundary:
        raise ValueError("Empty interface boundary")
    d = distances(adj, boundary)
    boundary = set(boundary)
    signs = [0 if vertex in boundary else -1 if vertex in inside else 1 for vertex in range(width * height)]
    phi = [sign * length for sign, length in zip(signs, d)]
    assert all(abs(phi[u] - phi[v]) <= 1 for u, row in enumerate(adj) for v in row)
    return {"occupancy": sorted(inside), "boundary": sorted(boundary), "interior": sorted(inside - boundary),
            "signs": signs, "fields": phi, "zero_without_negative_neighbor":
                sorted(u for u in boundary if not any(signs[v] < 0 for v in adj[u]))}


def initial_ball_field(width, height, center=0):
    adj = adjacency(width, height)
    d = distances(adj, (center,))
    signs = [(v > 2) - (v < 2) for v in d]
    redistance = distances(adj, [i for i, value in enumerate(d) if value == 2])
    return [s * d for s, d in zip(signs, redistance)]


def select_axis(width, height, fields, node, phase, eta):
    neighbors = adjacency(width, height)[node]
    gu, gv = fields[neighbors[0]] - fields[neighbors[2]], fields[neighbors[1]] - fields[neighbors[3]]
    divisor = gcd(abs(gu), abs(gv))
    pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
    bank = ((-phase if eta else phase) % 256) // 64
    au, av = GAINS[bank]
    q = (au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv)
    priority = [(bank + i) % 4 for i in range(4)]
    selected = max(priority, key=lambda i: q[0] * DIRECTIONS[i][0] + q[1] * DIRECTIONS[i][1])
    return {"gradient": [gu, gv], "primitive_axis": [pu, pv], "bank": bank,
            "guided_vector": list(q), "shaft_direction": selected}


I32_MAX = (1 << 31) - 1
SITE_LIMIT = 1 << 24


def strict(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name)


def mathematical_budget(width, height, h, p, q, scale, *, limit=SITE_LIMIT, used=0, balls=0):
    """Big-int specification: calculate exact expressions then check bounds."""
    strict(h, 1, 65535, "h")
    strict(p, 1, 65535, "p")
    strict(q, 1, 65535, "q")
    strict(scale, 0, 4, "scale")
    strict(limit, 1, SITE_LIMIT, "limit")
    strict(used, 0, limit, "used")
    strict(balls, 0, 64, "balls")
    assert width >= 3 and height >= 3 and width * height <= 256
    if gcd(p, q) != 1:
        raise ValueError("slope is not reduced")
    H = h << scale
    pH = p * H
    if not (1 <= H <= I32_MAX and 1 <= pH <= I32_MAX):
        raise ValueError("H or pH overflow")
    B = pH // q
    qB = q * B
    if qB > I32_MAX:
        raise ValueError("qB overflow")
    if max(width - 1 + H + B, height - 1 + H + B) > I32_MAX:
        raise ValueError("coordinate bound overflow")
    K = (H + 1) * (2 * B + 1)
    total = used + K + balls * width * height
    if total > limit:
        raise ValueError("primitive sites exceeded")
    return {"H": H, "pH": pH, "B": B, "qB": qB, "K": K, "total_sites": total,
            "u_bound": width - 1 + H + B, "v_bound": height - 1 + H + B}


def guarded_device_budget(width, height, h, p, q, scale, *, limit=SITE_LIMIT, used=0, balls=0):
    """Independent no-overflow ordering; no multiplication before division guard."""
    for value, low, high, name in ((h, 1, 65535, "h"), (p, 1, 65535, "p"),
                                  (q, 1, 65535, "q"), (scale, 0, 4, "scale"),
                                  (limit, 1, SITE_LIMIT, "limit"), (used, 0, limit, "used"),
                                  (balls, 0, 64, "balls")):
        strict(value, low, high, name)
    if gcd(p, q) != 1:
        raise ValueError("slope is not reduced")
    assert width >= 3 and height >= 3 and width * height <= 256
    if h > I32_MAX >> scale:
        raise ValueError("H or pH overflow")
    H = h << scale
    if p > I32_MAX // H:
        raise ValueError("H or pH overflow")
    pH = p * H
    B = pH // q
    if B and q > I32_MAX // B:
        raise ValueError("qB overflow")
    qB = q * B
    if H > I32_MAX - B or max(width - 1, height - 1) > I32_MAX - (H + B):
        raise ValueError("coordinate bound overflow")
    N = width * height  # The inherited <=256-node domain was already admitted.
    remaining = limit - used
    if balls > remaining // N:
        raise ValueError("primitive sites exceeded")
    remaining -= balls * N
    if not remaining or B > (remaining - 1) // 2:
        raise ValueError("primitive sites exceeded")
    span = 2 * B + 1
    if H >= remaining or H + 1 > remaining // span:
        raise ValueError("primitive sites exceeded")
    K = (H + 1) * span
    total = used + K + balls * N
    return {"H": H, "pH": pH, "B": B, "qB": qB, "K": K, "total_sites": total,
            "u_bound": width - 1 + H + B, "v_bound": height - 1 + H + B}


def budget_vectors():
    inputs = [dict(h=3, p=1, q=1, scale=0), dict(h=3, p=1, q=4, scale=0),
              dict(h=200, p=1, q=1, scale=0), dict(h=65535, p=1, q=65535, scale=3),
              dict(h=65534, p=1, q=65535, scale=0), dict(h=65535, p=1, q=65535, scale=4),
              dict(h=32768, p=65535, q=1, scale=0), dict(h=32769, p=65535, q=1, scale=0),
              dict(h=3, p=1, q=1, scale=0, limit=28), dict(h=3, p=1, q=1, scale=0, limit=27),
              dict(h=3, p=1, q=1, scale=0, limit=92, balls=1),
              dict(h=3, p=1, q=1, scale=0, limit=91, balls=1),
              dict(h=3, p=2, q=2, scale=0), dict(h=True, p=1, q=1, scale=0),
              dict(h=65536, p=1, q=1, scale=0), dict(h=1, p=1, q=1, scale=5)]
    result = []
    for parameters in inputs:
        outputs = []
        for implementation in (mathematical_budget, guarded_device_budget):
            try:
                outputs.append({"admitted": True, "values": implementation(8, 8, **parameters)})
            except ValueError as failure:
                outputs.append({"admitted": False, "reason": str(failure)})
        assert outputs[0] == outputs[1]
        result.append({"input": parameters, **outputs[0]})
    # Independent boundary grid includes sparse slopes, overflow edges and all scales.
    count = 0
    for h in (1, 2, 3, 127, 128, 200, 32767, 32768, 32769, 65534, 65535):
        for p in (1, 2, 127, 128, 32767, 65534, 65535):
            for q in (1, 2, 127, 128, 32767, 65534, 65535):
                for scale in range(5):
                    for limit in (27, 28, 92, 4096, SITE_LIMIT):
                        values = []
                        for implementation in (mathematical_budget, guarded_device_budget):
                            try:
                                values.append((True, implementation(8, 8, h, p, q, scale, limit=limit)))
                            except ValueError as failure:
                                values.append((False, str(failure)))
                        assert values[0] == values[1], (h, p, q, scale, limit, values)
                        count += 1
    return {"literal_cases": result, "guarded_vs_bigint_cases": count,
            "B_zero_admitted": True, "no_extra_127_cap": True}


def verify_field_independently(width, height, result):
    """Floyd-Warshall and cover pullback are independent from producer BFS."""
    adj = adjacency(width, height)
    N = width * height
    distance = [[0 if i == j else 1 if j in adj[i] else 10000 for j in range(N)] for i in range(N)]
    for k in range(N):
        for i in range(N):
            for j in range(N):
                distance[i][j] = min(distance[i][j], distance[i][k] + distance[k][j])
    expected = [sign * min(distance[i][b] for b in result["boundary"])
                for i, sign in enumerate(result["signs"])]
    assert expected == result["fields"]
    cover = []
    for node in range(N):
        u, v = divmod(node, height)
        for eta in (0, 1):
            cover.append(tuple(2 * canonical(width, height, u + du, v + dv)
                               + (eta ^ (((u + du) // width) & 1)) for du, dv in DIRECTIONS))
    lifted_distance = distances(cover, [2 * b + eta for b in result["boundary"] for eta in (0, 1)])
    assert [result["signs"][i // 2] * d for i, d in enumerate(lifted_distance)] == [v for value in expected for v in (value, value)]


def compare_reference_geometry(fixtures, union):
    """Read literal JSON only; never import the independent reference producer."""
    path = Path(__file__).with_name("formal-reference.json")
    source = path.read_bytes().replace(b"\r\n", b"\n")
    document = json.loads(source)
    geometry = document["geometry_vectors"]
    results = []
    names = []
    matched_contexts = []
    for item in geometry["fixtures"]:
        width, height = item["width"], item["height"]
        primitive = item["primitive"]
        pair = int(primitive["pair"], 16)
        eta, phase = (pair >> 28) & 1, pair & 255
        samples = footprint(width, height, primitive["apex"], primitive["shaft"], eta,
                            primitive["height"], primitive["numerator"], primitive["denominator"])
        assert samples == item["projected_sites"], item["name"]
        result = field(width, height, samples)
        for key in ("occupancy", "boundary", "interior", "signs", "zero_without_negative_neighbor"):
            assert result[key] == item[key], (item["name"], key)
        assert result["fields"] == item["field"], item["name"]
        verify_field_independently(width, height, result)
        choice = select_axis(width, height, item["prior_field"], primitive["apex"], phase, eta)
        reference_choice = item["shaft_choice_at_recorded_phase"]
        for key, reference_key in (("gradient", "gradient"), ("primitive_axis", "psi"),
                                   ("bank", "phase_bank"), ("guided_vector", "guided_vector"),
                                   ("shaft_direction", "shaft")):
            assert choice[key] == reference_choice[reference_key], (item["name"], key)
        if item["name"] in ("unwrapped", "reversing_seam"):
            assert choice["shaft_direction"] == primitive["shaft"], item["name"]
            own = fixtures[0 if item["name"] == "unwrapped" else 1]
            assert phase == own["phase"] and eta == own["orientation"]
            assert item["prior_field"] == own["prior_fields"]
            assert result["fields"] == own["fields"]
            matched_contexts.append(item["name"])
        results.append(result)
        names.append(item["name"])
    assert matched_contexts == ["unwrapped", "reversing_seam"]
    reference_union = geometry["overlap"]
    for key in ("occupancy", "boundary", "interior", "signs", "zero_without_negative_neighbor"):
        assert reference_union[key] == union[key], key
    assert reference_union["field"] == union["fields"]
    seam = geometry["seam_transport_counterexample"]
    assert seam == {"apex": 58, "shaft": 0, "s": 1, "t": 1,
                    "correct_node": 5, "untransported_wrong_node": 7}
    return {"reference": path.name, "reference_sha256_lf": sha256(source).hexdigest(),
            "reference_format": document["format"], "fixed_frame_geometry_fixtures": names,
            "context_selected_shaft_fixtures": matched_contexts,
            "exact_fields_checked": len(results) + 1,
            "scope": "Literal projected sites, signs, boundary and exact redistance; prior-field axis arithmetic; shared overlap and seam fixtures. Mission, instruction codec and W lifecycle are outside this geometry audit",
            "checks": {"literal_geometries_match_independent_projection_and_redistance": True,
                       "all_fixture_shaft_choice_records_match_independent_prior_field_arithmetic": True,
                       "shared_shaft_contexts_match": True,
                       "union_field_matches": True, "seam_counterexample_matches": True}}


def main():
    fixtures = []
    for name, apex, phase, center in (("unwrapped", 11, 0, 0), ("seam_crossing", 58, 73, 6)):
        prior = initial_ball_field(8, 8, center)
        choice = select_axis(8, 8, prior, apex, phase, 0)
        axis = choice["shaft_direction"]
        assert axis == 0
        raw = footprint(8, 8, apex, axis, 0, 3, 1, 1)
        result = field(8, 8, raw)
        assert footprint(8, 8, apex, axis, 1, 3, 1, 1) != raw
        assert set(footprint(8, 8, apex, axis, 1, 3, 1, 1)) == set(raw)
        assert select_axis(8, 8, prior, apex, (-phase) % 256, 1) == choice
        verify_field_independently(8, 8, result)
        fixtures.append({"name": name, "width": 8, "height": 8, "apex": apex, "phase": phase,
                         "prior_ball_center": center, "prior_ball_radius": 2, "prior_fields": prior,
                         "orientation": 0, "extent": 3, "slope": [1, 1], "axis_choice": choice,
                         "footprint_samples": len(raw), **result})
    assert fixtures[0]["interior"] == [19, 26, 27, 28]
    assert 38 in fixtures[0]["zero_without_negative_neighbor"]
    assert adjacency(8, 8)[38] == (46, 39, 30, 37)
    assert all(fixtures[0]["fields"][v] >= 0 for v in adjacency(8, 8)[38])
    union = field(8, 8, footprint(8, 8, 11, 0, 0, 3, 1, 1) + footprint(8, 8, 19, 0, 0, 3, 1, 1))
    assert fixtures[0]["fields"][35] == 0 and union["fields"][35] < 0
    verify_field_independently(8, 8, union)
    checks = 0
    for width, height in ((3, 3), (4, 5), (8, 8), (3, 85), (85, 3), (16, 16)):
        for apex in range(width * height):
            for axis in range(4):
                for eta in (0, 1):
                    original = footprint(width, height, apex, axis, eta, 3, 1, 1)
                    for lift in ((-3, -2), (1, 2), (4, -1)):
                        assert footprint(width, height, apex, axis, eta, 3, 1, 1, lift=lift) == original
                        checks += 1
                    walked = [transported_walk(width, height, apex, axis, eta, s, t)
                              for s in range(4) for t in range(-s, s + 1)]
                    assert walked == original
                    assert set(footprint(width, height, apex, axis, eta ^ 1, 3, 1, 1)) == set(original)
    source = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    result = {"format": "solvefinite-directional-geometry-audit-v1",
              "status": "formal-only independent mathematical audit; no runtime or device claims",
              "provenance": {"generator": Path(__file__).name,
                             "generator_sha256_lf": sha256(source).hexdigest(),
                             "imports": "Python standard library only; no solvefinite or directional reference producer",
                             "scope": "Bounded numerical checks of exact geometric identities and arithmetic safety; not exhaustive parameter enumeration"},
              "fixtures": fixtures,
              "overlap_union": union, "representative_change_checks": checks,
              "transported_walk_endpoint_checks": checks // 3 * 16,
              "mirror_occupancy_checks": checks // 3,
              "field_crosschecks": {"base_node_count": 64, "cover_node_count": 128,
                                    "fields_checked": 3,
                                    "methods": ["BFS", "Floyd-Warshall", "orientation-cover BFS pullback"]},
              "frozen_reference_geometry_crosscheck": compare_reference_geometry(fixtures, union),
              "naive_seam_counterexample": {"width": 8, "height": 8, "apex": 58, "shaft": "u+",
                  "s": 1, "t": 1, "projected_and_transported_node": 5, "untransported_wrong_node": 7},
              "not_an_old_ball_union": "Every old union zero vertex has a negative neighbor; taper inner boundary contains zero38 with none.",
              "invariants": {
                  "deck": "C(D(a)+s*J^m(e)+t*J^m(n))=C(a+s*e+t*n); transport the selected frame",
                  "walk": "Reflect both retained frame vectors at every u seam; induction matches lifted endpoints",
                  "mirror": "RP mirror preserves intrinsic phase and selected shaft; transverse reflection permutes the symmetric t interval",
                  "axis_tie_scope": "Select the shaft in the admitted prior context, then transport it. Re-running the unchanged cyclic tie priority in a reflected chart is not equivariant",
                  "union": "Union occupancies before computing inner vertex boundary; signed exact graph redistance is 1-Lipschitz",
                  "ball_union_obstruction": "Any old zero has a minimizing positive-radius ball and a negative neighboring vertex on a geodesic to its center",
                  "arithmetic": "Check each product against a division bound before evaluating it; qB may be zero",
                  "dimension": "One transverse axis implements a 2D axial section; it does not distinguish full 3D cone and pyramid volumes"},
              "budget_arithmetic": budget_vectors(),
              "bounds": {"raw_h_p_q": [1, 65535], "scale": [0, 4], "slope_reduced": True,
                         "intermediate_i32_max": I32_MAX, "max_primitive_sites": SITE_LIMIT,
                         "rectangular_cost": "K=(H+1)*(2*floor(p*H/q)+1); not occupied or quotient-deduplicated count"},
              "checks": {"witness_not_representable_by_old_ball_unions": True,
                         "floyd_warshall_redistance_matches_bfs": True,
                         "orientation_cover_pullback_matches_base": True,
                         "deck_representatives_preserve_ordered_samples": True,
                         "transported_walk_matches_projected_cover": True,
                         "mirror_preserves_occupancy": True,
                         "overlap_union_recomputes_interface": True,
                         "guarded_arithmetic_matches_unbounded_integers": True}}
    path = Path(__file__).with_suffix(".json")
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"file": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                      "representative_change_checks": checks, "fixtures": [
                          {"name": f["name"], "occupancy": f["occupancy"], "interior": f["interior"],
                           "boundary_count": len(f["boundary"]), "zero_without_negative_neighbor": f["zero_without_negative_neighbor"],
                           "axis_choice": f["axis_choice"]} for f in fixtures]}, indent=2))


if __name__ == "__main__":
    main()
