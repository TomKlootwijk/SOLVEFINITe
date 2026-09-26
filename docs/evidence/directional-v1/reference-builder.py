"""Independent finite tapered-section, field, mission and Wv2 expectations.

No solvefinite module is imported. The new geometry is a closed 2D axial
section on a Klein quotient, not a claim of distinct 3D cones and pyramids.
Pinned earlier independent references supply integer packing, quotient BFS,
HP route arithmetic/layered checking and W carrier/FIFO arithmetic only.
"""

from copy import deepcopy
from hashlib import sha256
import importlib.util
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


# Check all helper bytes before importing the OG helper, which imports GD.
for relative, expected in PINS.items():
    if lf_digest(ROOT / relative) != expected:
        raise ValueError("Independent helper identity changed: " + relative)


def load_helper(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OG = load_helper("independent_taper_og", "docs/evidence/organogram-v1/reference-builder.py")
W = load_helper("independent_taper_w", "docs/evidence/welip-v1/reference-builder.py")
BASE = OG.BASE
I32_MAX = (1 << 31) - 1
TERMINALS = {**OG.TERMINALS, "TAPER": 3}
CARDINAL = ((1, 0), (0, 1), (-1, 0), (0, -1))
PROFILE = "klein-taper-organogram-v1"
POLICY = "tomigidt-field-taper-plan-act-v1"
WORLD_PROFILE = "klein-taper-world-v1"
DERIVATION_PROFILE = "klein-taper-derivation-v1"
TAPE_PROFILE = "TP-TAPE32-v1"
W_PROTOCOL = "welip-field-agent-v2"
canonical, digest, integer, token = OG.canonical, OG.digest, OG.integer, OG.token


def default_binding(max_epochs=1):
    binding = OG.default_binding(max_epochs)
    binding["format"] = PROFILE
    for rule in binding["rules"][:2]:
        # The nested SCALE applies to an actual taper; R2 before POP makes
        # radius restoration nontrivial as well as orientation/phase/scale.
        nested = rule["rhs"]
        position = next(i for i, item in enumerate(nested) if item["symbol"] == "S")
        nested[position] = token("TAPER", 1, 1, 2)
    binding["rules"][2]["rhs"] = [token("F", OG.arg()), token("TAPER", OG.arg(add=2), 1, 2)]
    binding["limits"] = {"max_symbols": 128, "max_steps": 128, "max_primitives": 16,
                         "max_stack": 8, "max_primitive_sites": 1 << 20}
    return binding


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


def taper_bounds(width, height, h, p, q, scale):
    integer(h, 1, 65535); integer(p, 1, 65535); integer(q, 1, 65535)
    integer(scale, 0, 4)
    if gcd(p, q) != 1:
        raise ValueError("slope must be reduced")
    extent = integer(h << scale, 1, I32_MAX)
    product = integer(p * extent, 1, I32_MAX)
    breadth = product // q
    integer(q * breadth, 0, I32_MAX)
    integer(width - 1 + extent + breadth, 1, I32_MAX)
    integer(height - 1 + extent + breadth, 1, I32_MAX)
    # Host widened arithmetic: compare the full rectangle count before any
    # cover enumeration or GPU allocation, not a wrapped i32 product.
    sites = (extent + 1) * (2 * breadth + 1)
    return {"height": extent, "transverse_bound": breadth, "pH": product,
            "qB": q * breadth, "rectangle_sites": sites}


def preflight(world, binding, tape):
    limits = binding["limits"]
    for key, low, high in (("max_symbols", 1, 1024), ("max_steps", 1, 4096),
                           ("max_primitives", 1, 64), ("max_stack", 0, 32),
                           ("max_primitive_sites", 1, 1 << 24)):
        integer(limits[key], low, high)
    if len(tape) > limits["max_symbols"]:
        raise ValueError("logical symbol budget")
    radius, scale, stack = 1, 0, []
    steps = primitives = sites = high_water = texels = 0
    for item in tape:
        symbol, args = item["symbol"], item["args"]
        if symbol not in TERMINALS or type(args) is not list or len(args) != TERMINALS[symbol]:
            raise ValueError("terminal arity")
        texels += 3 if symbol == "TAPER" else 1
        if symbol == "F":
            steps += integer(args[0], 1, 256) << scale
        elif symbol in ("+", "-"):
            integer(args[0], 1, 16)
        elif symbol == "R":
            radius = integer(args[0], 1, 127)
        elif symbol == "SCALE":
            scale = integer(args[0], 0, 4)
        elif symbol == "S":
            integer(radius << scale, 1, 127)
            primitives += 1
            sites += world.count
        elif symbol == "TAPER":
            bounded = taper_bounds(world.width, world.height, *args, scale)
            primitives += 1
            sites += bounded["rectangle_sites"]
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
    integer(code, 0, 10); integer(operand, 0, 65535)
    raw = operand | (code << 24)
    return raw | ((raw.bit_count() & 1) << 31)


def encode_tape(tape):
    codes = tuple(OG.TERMINALS)
    words, offsets = [], []
    for item in tape:
        offsets.append(len(words))
        symbol, args = item["symbol"], item["args"]
        if len(args) != TERMINALS[symbol]:
            raise ValueError("terminal arity")
        parts = zip((8, 9, 10), args) if symbol == "TAPER" else [(codes.index(symbol), args[0] if args else 0)]
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
        if code > 10:
            raise ValueError("unknown instruction code")
        decoded.append((code, operand))
    result, offsets, index = [], [], 0
    bounds = {0: (1, 256), 1: (1, 16), 2: (1, 16), 5: (1, 127), 7: (0, 4)}
    while index < len(decoded):
        code, operand = decoded[index]
        offsets.append(index)
        if code == 8:
            if index + 2 >= len(decoded) or [p[0] for p in decoded[index:index + 3]] != [8, 9, 10]:
                raise ValueError("TAPER continuation order/truncation")
            args = [integer(p[1], 1, 65535) for p in decoded[index:index + 3]]
            if gcd(args[1], args[2]) != 1:
                raise ValueError("slope must be reduced")
            result.append(token("TAPER", *args))
            index += 3
            continue
        if code in (9, 10):
            raise ValueError("stray TAPER continuation")
        if code in (3, 4, 6):
            if operand != 0:
                raise ValueError("nonzero no-argument operand")
            args = []
        else:
            integer(operand, *bounds[code])
            args = [operand]
        result.append(token(tuple(OG.TERMINALS)[code], *args))
        index += 1
    return result, offsets


def shaft_choice(world, node, r, eta):
    intrinsic = BASE.intrinsic(r, eta)
    bank = intrinsic >> 6
    priority = tuple(range(bank, 4)) + tuple(range(bank))
    gu, gv = world.gradient[node]
    pu, pv = world.axis[node]
    au, av = BASE.GAINS[bank]
    vector = (au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv)
    scores = tuple(vector[0] * u + vector[1] * v for u, v in CARDINAL)
    selected = next(i for i in priority if scores[i] == max(scores))
    return {"shaft": selected, "gradient": [gu, gv], "psi": [pu, pv], "phase_bank": bank,
            "guided_vector": list(vector), "scores": list(scores), "tie_priority": list(priority)}


def cover_sites(world, apex, shaft, eta, extent, numerator, denominator, lift=(0, 0)):
    x, y = divmod(apex, world.height)
    m, n = lift
    x, y = x + m * world.width, (-y if m & 1 else y) + n * world.height
    eu, ev = CARDINAL[shaft]
    tu, tv = (-ev, eu) if eta == 0 else (ev, -eu)
    if m & 1:
        ev, tv = -ev, -tv
    projected, coordinates = [], []
    for s in range(extent + 1):
        radius = numerator * s // denominator
        for t in range(-radius, radius + 1):
            u, v, _ = world.canonical(x + s * eu + t * tu, y + s * ev + t * tv)
            projected.append(u * world.height + v)
            coordinates.append([s, t])
    return projected, coordinates


def walk_site(world, apex, shaft, eta, s, t):
    node, e = apex, CARDINAL[shaft]
    transverse = (-e[1], e[0]) if eta == 0 else (e[1], -e[0])
    for kind, count in ((0, s), (1, abs(t))):
        for _ in range(count):
            direction = e if kind == 0 else transverse
            if kind and t < 0:
                direction = (-direction[0], -direction[1])
            node, seam = world.step(node, direction)
            if seam:
                e, transverse = (e[0], -e[1]), (transverse[0], -transverse[1])
    return node


def primitive_occupancy(world, primitive):
    if primitive["kind"] == "ball":
        distances = world.distance((primitive["center"],))
        return sorted(i for i, distance in enumerate(distances) if distance <= primitive["radius"])
    _, _, _, metadata = OG.unpack_pair(primitive["pair"])
    projected, _ = cover_sites(world, primitive["apex"], primitive["shaft"], (metadata >> 4) & 1,
                               primitive["height"], primitive["numerator"], primitive["denominator"])
    return sorted(set(projected))


def field_from_occupancy(world, occupied):
    inside = set(occupied)
    if not inside or len(inside) == world.count:
        raise ValueError("empty or full projected occupancy")
    boundary = sorted(i for i in inside if any(j not in inside for j in world.adj[i]))
    if not boundary:
        raise ValueError("empty separating boundary")
    distance = world.distance(boundary)
    zero = set(boundary)
    signs = tuple(0 if i in zero else -1 if i in inside else 1 for i in range(world.count))
    fields = tuple(s * d for s, d in zip(signs, distance))
    assert all(signs[i] * signs[j] != -1 for i in range(world.count) for j in world.adj[i])
    assert all(abs(fields[i] - fields[j]) <= 1 for i in range(world.count) for j in world.adj[i])
    assert all(-127 <= value <= 127 for value in fields)
    return {"occupancy": sorted(inside), "boundary": boundary, "interior": sorted(inside - zero),
            "signs": list(signs), "field": list(fields),
            "zero_without_negative_neighbor": [i for i in boundary if all(signs[j] >= 0 for j in world.adj[i])]}


def union_field(world, primitives):
    parts = [primitive_occupancy(world, primitive) for primitive in primitives]
    result = field_from_occupancy(world, set().union(*map(set, parts)))
    return {"primitive_occupancies": parts, **result}


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
        elif symbol in ("S", "TAPER"):
            common = {"address": list(address), "branch_path": deepcopy(branch), "pair": world.packed(r, node, eta)}
            if symbol == "S":
                primitives.append({"kind": "ball", **common, "center": node, "radius": radius << scale})
            else:
                choice = shaft_choice(world, node, r, eta)
                shafts.append({"address": list(address), **choice})
                primitives.append({"kind": "taper", **common, "apex": node, "height": args[0] << scale,
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


def mission(max_epochs=1, mirrored=False, binding=None):
    binding = default_binding(max_epochs) if binding is None else deepcopy(binding)
    max_epochs = binding["max_epochs"]
    world = OG.Field()
    initial_recipe = world.recipe()
    r, node, eta, energy, epoch, target = (6 if mirrored else 250), 0, int(mirrored), 100, 0, 17
    initial = world.state(r, node, eta, energy)
    known, events, stages = {}, [], []
    pending_growth = False
    worlds = [{"epoch": 0, "field": list(world.phi), "target": target}]
    for cycle in range(1, 501):
        visible = sorted((node, *world.adj[node]), key=world.names.__getitem__)
        frame = {j: 70 if epoch == 0 and cycle >= 2 and j == 3 else 0 for j in visible}
        known.update(frame)
        reserve = 5 + (max_epochs - epoch) * (binding["cost"] + 5)
        event = {"cycle": cycle, "input_epoch": epoch, "input": {world.names[j]: h for j, h in frame.items()},
                 "target_before": target, "reserve_before": reserve}
        if pending_growth:
            context = {"epoch": epoch + 1, "tick": cycle, "start_pair": world.packed(r, node, eta, 6),
                       "prefix_sha256": digest(events)}
            derivation = interpret(world, binding, context)
            old_world = world
            world = OG.Field(values=derivation["union"]["field"])
            selection = OG.target_selection(world, node, BASE.intrinsic(r, eta))
            target = selection["target"]
            epoch += 1
            energy -= binding["cost"]
            known, pending_growth = {}, False
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
            result = BASE.route(world, node, target, BASE.intrinsic(r, eta), known)
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
        event.update(epoch=epoch, target_after=target)
        events.append(event)
        if event["status"] == "COMPLETE":
            break
    else:
        raise AssertionError("finite mission failed to terminate")
    return {"initial": initial, "initial_recipe": initial_recipe, "initial_target": 17, "binding": binding,
            "worlds": worlds, "events": events, "stages": stages, "cycles": len(events), "final": events[-1]["state"],
            "prefix_hash_scope": "Independent mathematical event transcript, not a canonical runtime archive."}


def inverse_occupancy(world, apex, shaft, eta, extent, numerator, denominator):
    """Independent membership check: test node lifts, not forward sites."""
    ax, ay = divmod(apex, world.height)
    eu, ev = CARDINAL[shaft]
    tu, tv = (-ev, eu) if eta == 0 else (ev, -eu)
    reach = extent + numerator * extent // denominator
    occupied = []
    ceildiv = lambda a, b: -((-a) // b)
    for node in range(world.count):
        u, v = divmod(node, world.height)
        found = False
        for m in range(ceildiv(ax - reach - u, world.width), (ax + reach - u) // world.width + 1):
            reflected = -v if m & 1 else v
            for n in range(ceildiv(ay - reach - reflected, world.height),
                           (ay + reach - reflected) // world.height + 1):
                dx, dy = u + m * world.width - ax, reflected + n * world.height - ay
                s, t = dx * eu + dy * ev, dx * tu + dy * tv
                if 0 <= s <= extent and denominator * abs(t) <= numerator * s:
                    found = True
                    break
            if found:
                break
        if found:
            occupied.append(node)
    return occupied


def taper_descriptor(world, apex, shaft, h, p, q, *, eta=0, phase=0):
    return {"kind": "taper", "address": [0], "branch_path": [], "apex": apex,
            "height": h, "numerator": p, "denominator": q, "shaft": shaft,
            "pair": world.packed(phase, apex, eta)}


def geometry_vectors():
    world = OG.Field(8, 8)
    specs = (("unwrapped", 11, 0, 3, 1, 1, 0), ("reversing_seam", 58, 0, 3, 1, 1, 73),
             ("thin_zero_width", 11, 0, 1, 1, 2, 0), ("slender_reduced_slope", 11, 0, 3, 1, 2, 0),
             ("opposite_shaft", 11, 2, 3, 1, 1, 0), ("transverse_shaft", 11, 1, 3, 1, 1, 0))
    vectors = []
    for name, apex, shaft, h, p, q, phase in specs:
        fixture_world = OG.Field(8, 8, center=6) if name == "reversing_seam" else world
        descriptor = taper_descriptor(fixture_world, apex, shaft, h, p, q, phase=phase)
        projected, coordinates = cover_sites(fixture_world, apex, shaft, 0, h, p, q)
        expected = inverse_occupancy(fixture_world, apex, shaft, 0, h, p, q)
        assert sorted(set(projected)) == expected
        result = union_field(fixture_world, [descriptor])
        choice = shaft_choice(fixture_world, apex, phase, 0)
        selected = name not in ("opposite_shaft", "transverse_shaft")
        if selected:
            assert shaft == choice["shaft"]
        vectors.append({"name": name, "width": 8, "height": 8, "prior_recipe": fixture_world.recipe(),
                        "prior_field": list(fixture_world.phi),
                        "scope": "Prior-context-selected shaft" if selected else "Fixed-frame geometric probe; not an admitted grammar primitive at this recorded phase",
                        "primitive": descriptor, "local_sites": coordinates, "projected_sites": projected,
                        "shaft_choice_at_recorded_phase": choice, **result})
    unwrapped, seam = vectors[:2]
    assert unwrapped["interior"] == [19, 26, 27, 28]
    assert 38 in unwrapped["zero_without_negative_neighbor"]
    assert len(unwrapped["occupancy"]) == 16 and len(unwrapped["boundary"]) == 12
    first = unwrapped["primitive"]
    second = taper_descriptor(world, 19, 0, 3, 1, 1)
    union = union_field(world, [first, second])
    a, b = union_field(world, [first]), union_field(world, [second])
    residual_min = [min(x, y) for x, y in zip(a["field"], b["field"])]
    assert a["field"][35] == 0 and union["field"][35] < 0
    differing = [i for i, (x, y) in enumerate(zip(residual_min, union["field"])) if x != y]
    assert differing
    seam_site = cover_sites(world, 58, 0, 0, 3, 1, 1)
    offset = seam_site[1].index([1, 1])
    assert seam_site[0][offset] == walk_site(world, 58, 0, 0, 1, 1) == 5
    # Deliberately failing to transport the transverse frame after the u seam.
    after_axis = world.step(58, (1, 0))[0]
    naive = world.step(after_axis, (0, 1))[0]
    assert naive == 7
    return {"fixtures": vectors,
            "overlap": {"width": 8, "height": 8, "primitives": [first, second],
                        "separate_fields": [a["field"], b["field"]], "minimum_separate_fields": residual_min,
                        "differing_nodes": differing, **union},
            "seam_transport_counterexample": {"apex": 58, "shaft": 0, "s": 1, "t": 1,
                                               "correct_node": 5, "untransported_wrong_node": naive},
            "old_ball_union_separation_witness": {
                "fixture": "unwrapped", "boundary_node": 38,
                "adjacent_nodes": list(world.adj[38]), "adjacent_fields": [unwrapped["field"][j] for j in world.adj[38]],
                "claim": "Old OG union zero nodes always have a negative neighbor: for an active positive-radius ball at d=R, take a decreasing geodesic step. This new zero node has no negative neighbor, so this field is not any old OG ball-union field on this same quotient."}}


def projection_certificate():
    domains = ((3, 3), (4, 5), (8, 8), (3, 85), (85, 3), (16, 16))
    record = sha256()
    deck_checks = walk_checks = mirror_checks = inverse_checks = 0
    for width, height in domains:
        world = BASE.Quotient(width, height)
        for apex in range(world.count):
            for shaft in range(4):
                for eta in (0, 1):
                    nodes, coords = cover_sites(world, apex, shaft, eta, 3, 1, 1)
                    for lift in ((-3, -2), (1, 2), (4, -1)):
                        changed, _ = cover_sites(world, apex, shaft, eta, 3, 1, 1, lift)
                        assert changed == nodes
                        deck_checks += 1
                    walked = [walk_site(world, apex, shaft, eta, s, t) for s, t in coords]
                    assert walked == nodes
                    walk_checks += len(coords)
                    mirrored, _ = cover_sites(world, apex, shaft, eta ^ 1, 3, 1, 1)
                    assert set(mirrored) == set(nodes)
                    mirror_checks += 1
                    if apex in (0, world.count // 2, world.count - 1):
                        assert sorted(set(nodes)) == inverse_occupancy(world, apex, shaft, eta, 3, 1, 1)
                        inverse_checks += world.count
                    record.update(canonical([width, height, apex, shaft, eta, nodes]))
    return {"domains": [list(pair) for pair in domains], "all_apices_each_domain": True,
            "deck_representative_checks": deck_checks, "transported_site_checks": walk_checks,
            "mirror_occupancy_checks": mirror_checks, "inverse_node_membership_checks": inverse_checks,
            "projection_transcript_sha256": record.hexdigest(),
            "scope": "These finite domains/parameters are tested exhaustively in apices, four shafts and two orientations; the general deck argument is a separate proof."}


def instructions(*items):
    return [{"address": [i], **item} for i, item in enumerate(items)]


def rejection_vectors():
    world, binding = OG.Field(), default_binding()
    cases = []
    def rejected(name, function, *args):
        try:
            function(*args)
        except ValueError as exc:
            cases.append({"name": name, "expected": str(exc)})
        else:
            raise AssertionError("Expected rejection: " + name)
    for name, params in (("bool height", (True, 1, 1, 0)), ("float slope", (1, 1.0, 1, 0)),
                         ("zero height", (0, 1, 1, 0)), ("height over raw u16", (65536, 1, 1, 0)),
                         ("zero numerator", (1, 0, 1, 0)), ("zero denominator", (1, 1, 0, 0)),
                         ("unreduced slope", (3, 2, 4, 0)), ("pH i32 overflow", (65535, 65535, 1, 4)),
                         ("cover coordinate bound overflow", (32768, 65535, 1, 0))):
        rejected(name, taper_bounds, 4, 5, *params)
    for name, tape in (("primitive sites exceed budget", instructions(token("TAPER", 65535, 32767, 65535))),
                       ("scaled sphere radius overflow", instructions(token("R", 127), token("SCALE", 1), token("S"))),
                       ("stack underflow", instructions(token("]"), token("S"))),
                       ("unclosed branch", instructions(token("["), token("S"))),
                       ("no boundary primitive", instructions(token("F", 1))),
                       ("TAPER missing argument", instructions(token("TAPER", 1, 1)))):
        rejected(name, preflight, world, binding, tape)
    rejected("empty projected occupancy", field_from_occupancy, world, [])
    rejected("full projected occupancy", field_from_occupancy, world, range(world.count))
    full = taper_descriptor(world, 0, 0, 20, 1, 1)
    rejected("full projected taper", union_field, world, [full])
    words, _ = encode_tape(instructions(token("TAPER", 3, 1, 2)))
    malformed = {
        "truncated height": words[:1], "truncated numerator": words[:2],
        "reversed continuation": [words[0], words[2], words[1]],
        "stray numerator": [words[1]], "stray denominator": [words[2]],
        "noarg operand": [f"{carrier(6, 1):08X}"],
        "zero taper operand": [f"{carrier(8, 0):08X}", *words[1:]],
        "unknown code": [f"{(11 << 24) | (((11 << 24).bit_count() & 1) << 31):08X}"],
        "lowercase word": ["8a000002"], "texture too long": [f"{carrier(7, 0):08X}"] * 1153,
    }
    valid = int(words[0], 16)
    malformed["odd parity"] = [f"{valid ^ 1:08X}", *words[1:]]
    reserved = (valid & 0x7FFFFFFF) | (1 << 16)
    malformed["reserved B lane with valid parity"] = [f"{reserved | ((reserved.bit_count() & 1) << 31):08X}", *words[1:]]
    for name, encoded in malformed.items():
        rejected(name, decode_tape, encoded)
    # A complete grammar preflight counts ball candidates and taper rectangle
    # candidates together, before geometry enumeration.
    sample = instructions(token("TAPER", 3, 1, 2), token("S"))
    edge = deepcopy(binding)
    edge["limits"]["max_primitive_sites"] = 32
    assert preflight(world, edge, sample)["primitive_sites"] == 32
    edge["limits"]["max_primitive_sites"] = 31
    rejected("summed mixed primitive sites exceed by one", preflight, world, edge, sample)
    return cases


def encoding_vectors():
    tape = instructions(token("F", 256), token("+", 16), token("-", 16), token("["), token("]"),
                        token("R", 127), token("S"), token("SCALE", 4), token("TAPER", 65535, 65534, 65535))
    words, offsets = encode_tape(tape)
    assert decode_tape(words) == ([token(x["symbol"], *x["args"]) for x in tape], offsets)
    maximum = instructions(*([token("TAPER", 1, 1, 65535)] * 64 + [token("SCALE", 0)] * 960))
    binding = default_binding()
    binding["limits"].update(max_symbols=1024, max_primitives=64)
    work = preflight(OG.Field(), binding, maximum)
    encoded, mapped = encode_tape(maximum)
    assert len(encoded) == 1152 and mapped[64] == 192 and mapped[-1] == 1151
    assert decode_tape(encoded)[1] == mapped
    return {"profile": TAPE_PROFILE, "literal_logical_instructions": tape,
            "literal_words": words, "word_offsets": offsets,
            "maximum_texture": {"preflight": work, "words_sha256": digest(encoded),
                                "first_taper_offsets": mapped[:4], "first_following_offset": mapped[64],
                                "last_offset": mapped[-1]},
            "thin_bounds": taper_bounds(4, 5, 1, 1, 65535, 0),
            "maximum_raw_height_thin_bounds": taper_bounds(4, 5, 65535, 1, 65535, 0)}


def mutation_vectors():
    world = OG.Field(8, 8)
    context = {"epoch": 1, "tick": 5, "start_pair": world.packed(0, 11, 0, 6),
               "prefix_sha256": "1" * 64}
    binding = default_binding()
    binding.update(symbols=[{"name": "P", "arity": 1}],
                   axiom=[token("P", {"context": "tick", "mul": 1, "add": -2})],
                   rules=[{"symbol": "P", "guards": [], "rhs": [token("TAPER", OG.arg(), 1, 1)]}], generations=1)
    original = interpret(world, binding, context)
    later = interpret(world, binding, dict(context, tick=6))
    phase_context = dict(context, start_pair=world.packed(128, 11, 0, 6))
    phase = interpret(world, binding, phase_context)
    narrower = deepcopy(binding)
    narrower["rules"][0]["rhs"][0]["args"][2] = 2
    slope = interpret(world, narrower, context)
    mirrored_context = dict(context, start_pair=world.packed(0, 11, 1, 6))
    mirrored = interpret(world, binding, mirrored_context)
    assert original["union"]["field"] != later["union"]["field"]
    assert original["union"]["field"] != phase["union"]["field"]
    assert original["union"]["field"] != slope["union"]["field"]
    assert original["union"] == mirrored["union"]
    return {"binding": binding, "context_parameter_baseline": original, "later_original_tick": later,
            "different_intrinsic_phase": phase, "narrower_slope_binding": narrower, "narrower_slope": slope,
            "full_mirror": mirrored,
            "scope": "Original tick changes a parameter substitution; phase changes the selected shaft; slope changes the actual closed section. Full mirror preserves geometry and exchanges owned channels."}


def w_lifecycle(mission, postgrowth_capacity=4):
    config = W.config_for(mission)
    config["format"] = "welip-field-config-v2"
    config["agent"].update(policy=POLICY, taper=config["agent"].pop("organogram"))
    config["producer"] = "taper-reference"
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
    def cursor(sequence, ignited):
        context = W.cursor(sequence, cycle, epoch, state, status, fifo, ignited)
        context.update(protocol=W_PROTOCOL, producer=config["producer"])
        return context
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
            assert sorted(event["input"]) == W.visible(state["path"])
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
            records.append(W.record(config, sequence, 0, operation, cycle, epoch, state, bytes.fromhex(W.PAYLOAD)))
        records.append(W.record(config, sequence, len(records), operation, cycle, epoch, state))
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
    return {"format": "taper-welip-independent-lifecycle-v2", "session_format": "welip-field-session-v2",
            "config": config, "genesis": genesis, "ready": ready, "schedule": [list(item) for item in schedule],
            "operations": rows, "results": results, "latest_retry_receipts": duplicates, "expected": expected,
            "projected_owner_transitions": projection, "final_owner": state,
            "record_count": len(identities), "fragment_count": sum(r["fragment_count"] for row in rows for r in row["records"]),
            "executor_action_tick_expectations": counters, "operation_transcript_sha256": digest(rows),
            "scope": "Expected Wv2 protocol/lifecycle around the independent tapered mission; no canonical runtime archive hash or measured GPU result."}


def branch_restoration(result, prior_fields):
    document = result["document"]
    initial = {"pair": document["context"]["start_pair"], "radius": 1, "scale": 0, "branch_path": []}
    # Interpreter starts as STEP at the owned EMIT location; branch restores
    # local STEP cursor state without admitting that cursor as the owner.
    r, node, field, meta = OG.unpack_pair(initial["pair"])
    world = OG.Field(values=prior_fields)
    assert world.phi[node] == field
    initial["pair"] = world.packed(r, node, (meta >> 4) & 1)
    stack, restores, prior = [], [], initial
    for index, (instruction, current) in enumerate(zip(document["tape"], document["trace"])):
        if instruction["symbol"] == "[":
            stack.append({key: deepcopy(prior[key]) for key in ("pair", "radius", "scale", "branch_path")})
        elif instruction["symbol"] == "]":
            saved = stack.pop()
            actual = {key: current[key] for key in saved}
            assert actual == saved
            restores.append({"logical_instruction": index, "before_pop": deepcopy(prior),
                             "restored": actual, "expected_saved_context": saved})
        prior = current
    assert not stack
    return restores


def cross_profile_identity_vector(new_lifecycle):
    old_reference = json.loads((ROOT / "docs/evidence/organogram-v1/formal-reference.json").read_text(encoding="utf-8"))
    old_config = W.config_for(old_reference["default_mission"])
    new_config = deepcopy(new_lifecycle["config"])
    old_config["producer"] = new_config["producer"]
    initial = old_reference["default_mission"]["initial"]
    old_record = W.record(old_config, 1, 1, "IGNITE", 0, 0, initial)
    new_record = new_lifecycle["operations"][0]["records"][1]
    assert old_record == new_record
    assert canonical(old_config) != canonical(new_config)
    return {"v1_protocol": "welip-field-agent-v1", "v2_protocol": W_PROTOCOL,
            "v1_config": old_config, "v2_config": new_config,
            "v1_canonical_config_sha256": digest(old_config), "v2_canonical_config_sha256": digest(new_config),
            "identical_state_record": new_record,
            "expected_admission": "Reject cross-profile or cross-config reuse despite identical carrier/LUS bytes. Comparison is scoped to retained protocol plus exact canonical configuration; baseline_id alone is only the original recipe label."}


def main():
    default, mirrored, two, zero = mission(), mission(mirrored=True), mission(2), mission(0)
    for left, right in zip(default["events"], mirrored["events"]):
        assert left["kind"] == right["kind"] and left["state"]["energy"] == right["state"]["energy"]
        assert all(left[key] == right[key] for key in ("route", "cost", "input", "target_before", "target_after", "status"))
        assert left["state"]["pair"] == right["state"]["pair"][8:] + right["state"]["pair"][:8]
    assert [stage["result"]["union"] for stage in default["stages"]] == [stage["result"]["union"] for stage in mirrored["stages"]]
    lifecycle = w_lifecycle(default)
    reference = {
        "format": "directional-independent-formal-reference-v1",
        "scope": "Formal-only independent expected arithmetic for a finite shared 2D tapered axial section; not separate 3D cone/pyramid solids, physical hardware measurements, or canonical runtime archive identities.",
        "generator_sha256_lf": lf_digest(Path(__file__)), "independent_source_sha256_lf": PINS,
        "binding": default_binding(), "geometry_vectors": geometry_vectors(),
        "projection_certificate": projection_certificate(), "encoding_vectors": encoding_vectors(),
        "rejection_vectors": rejection_vectors(), "mutation_vectors": mutation_vectors(),
        "default_mission": default, "mirrored_default_mission": mirrored,
        "two_epoch_mission": two, "zero_epoch_mission": zero,
        "branch_restoration_vectors": branch_restoration(default["stages"][0]["result"], default["stages"][0]["prior_field"]),
        "w_v2_lifecycle": lifecycle, "w_v2_mirrored_lifecycle": w_lifecycle(mirrored),
        "w_v2_capacity8_lifecycle": w_lifecycle(default, 8),
        "cross_profile_identity_vector": cross_profile_identity_vector(lifecycle),
    }
    destination = Path(__file__).with_name("formal-reference.json")
    destination.write_text(json.dumps(reference, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"path": str(destination), "sha256_lf": lf_digest(destination),
                      "generator_sha256_lf": reference["generator_sha256_lf"],
                      "default": {"cycles": default["cycles"], "final": default["final"]},
                      "two_epoch": {"cycles": two["cycles"], "final": two["final"]},
                      "w_operations": len(reference["w_v2_lifecycle"]["operations"]),
                      "w_records": reference["w_v2_lifecycle"]["record_count"],
                      "projection": reference["projection_certificate"]}, indent=2))


if __name__ == "__main__":
    main()
