"""Independent OG grammar, quotient, field and mission reference arithmetic.

No solvefinite module is imported. The retained independent GD generator
supplies quotient BFS, integer HP planning and its separate layered-DP check.
Standalone StageContext prefix hashes are declared inputs. Mission context
hashes name this generator's mathematical transcript, not a runtime archive.
"""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from math import gcd
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BASE_PATH = ROOT / "docs/evidence/growth-v1/reference-builder.py"
SPEC = importlib.util.spec_from_file_location("independent_dyadic_reference", BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1
TERMINALS = {"F": 1, "+": 1, "-": 1, "[": 0, "]": 0, "R": 1, "S": 0, "SCALE": 1}
CARDINAL = ((1, 0), (0, 1), (-1, 0), (0, -1))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def integer(value, low=I32_MIN, high=I32_MAX):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("strict integer range")
    return value


def token(symbol, *args):
    return {"symbol": symbol, "args": list(args)}


def arg(index=0, mul=1, add=0):
    return {"arg": index, "mul": mul, "add": add}


def default_binding(max_epochs=1):
    # Generation one chooses a time-sensitive A production; generation two
    # expands B parameters. D erases. Nested brackets restore complete state.
    first = [token("["), token("R", 1), token("+", 1), token("B", 1),
             token("["), token("SCALE", 1), token("-", 10), token("F", 2), token("S"), token("R", 2), token("]"),
             token("]"), token("["), token("-", 1), token("B", 2), token("]")]
    later = [token("["), token("R", 1), token("-", 1), token("B", 1),
             token("["), token("SCALE", 1), token("+", 1), token("F", 1), token("S"), token("R", 2), token("]"),
             token("]"), token("["), token("+", 1), token("B", 2), token("]")]
    return {"format": "klein-branch-organogram-v1", "max_epochs": max_epochs, "cost": 1,
            "symbols": [{"name": "A", "arity": 1}, {"name": "B", "arity": 1}, {"name": "D", "arity": 0}],
            "axiom": [token("A", {"context": "tick", "mul": 1, "add": 0}), token("D")],
            "rules": [
                {"symbol": "A", "guards": [{"arg": 0, "op": "xor_eq", "mask": 1, "value": 4}], "rhs": first},
                {"symbol": "A", "guards": [], "rhs": later},
                {"symbol": "B", "guards": [{"arg": 0, "op": "eq", "value": 1}],
                 "rhs": [token("F", arg()), token("S")]},
                {"symbol": "B", "guards": [{"arg": 0, "op": "ge", "value": 1}],
                 "rhs": [token("F", arg()), token("S"), token("R", 2)]},
                {"symbol": "D", "guards": [], "rhs": []}],
            "generations": 2,
            "limits": {"max_symbols": 128, "max_steps": 128, "max_balls": 16, "max_stack": 8}}


def unpack_pair(encoded):
    if type(encoded) is not str or len(encoded) != 16 or any(c not in "0123456789ABCDEF" for c in encoded):
        raise ValueError("pair representation")
    value = int(encoded, 16)
    left, right = value & 0xFFFFFFFF, value >> 32
    if left.bit_count() % 2 or right.bit_count() % 2:
        raise ValueError("pair parity")
    def lanes(word):
        b = (word >> 16) & 255
        return word & 255, (word >> 8) & 255, b if b < 128 else b - 256, (word >> 24) & 127
    r, g, b, meta = lanes(left)
    if lanes(right) != ((-r) % 256, g, b, meta ^ 16):
        raise ValueError("full mirror")
    return r, g, b, meta


class Field(BASE.World):
    def __init__(self, width=4, height=5, center=0, radius=2, values=None):
        super().__init__(width, height, center, radius)
        if values is None:
            return
        self.phi = tuple(values)
        self.signs = tuple((value > 0) - (value < 0) for value in values)
        self.boundary = tuple(i for i, value in enumerate(values) if value == 0)
        self.gradient = tuple((values[self.step(i, (1, 0))[0]] - values[self.step(i, (-1, 0))[0]],
                               values[self.step(i, (0, 1))[0]] - values[self.step(i, (0, -1))[0]])
                              for i in range(self.count))
        self.axis = tuple((u // g, v // g) if g else (1, 0)
                          for u, v in self.gradient for g in (gcd(abs(u), abs(v)),))
        self.penalties = {}
        for i, ((gu, gv), (pu, pv)) in enumerate(zip(self.gradient, self.axis)):
            for bank, (au, av) in enumerate(BASE.GAINS):
                qu, qv = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
                maximum = max(abs(qu), abs(qv))
                for j in self.adj[i]:
                    eu, ev = self.edge_directions[i, j]
                    self.penalties[i, bank, j] = maximum - qu * eu - qv * ev


def closed_distance(width, height, source, destination):
    u, v = divmod(source, height)
    a, b = divmod(destination, height)
    def cyclic(value):
        remainder = value % height
        return min(remainder, height - remainder)
    horizontal = abs(u - a)
    return min(horizontal + cyclic(v - b), width - horizontal + cyclic(v + b))


def union_field(world, balls):
    if not balls:
        raise ValueError("empty sphere output")
    radii = [(world.distance((sphere["center"],)), sphere["radius"]) for sphere in balls]
    margin = tuple(min(distances[i] - radius for distances, radius in radii) for i in range(world.count))
    boundary = tuple(i for i, value in enumerate(margin) if value == 0)
    if not boundary:
        raise ValueError("empty union boundary")
    signs = tuple((value > 0) - (value < 0) for value in margin)
    distances = world.distance(boundary)
    values = tuple(sign * distance for sign, distance in zip(signs, distances))
    assert all(signs[i] * signs[j] != -1 for i in range(world.count) for j in world.adj[i])
    assert all(abs(values[i] - values[j]) <= 1 for i in range(world.count) for j in world.adj[i])
    return {"margin": list(margin), "signs": list(signs), "boundary": list(boundary), "field": list(values)}


def expression(value, inputs, kind):
    if type(value) is int:
        return integer(value)
    if type(value) is not dict or set(value) != {kind, "mul", "add"}:
        raise ValueError("expression shape")
    integer(value["mul"], -32768, 32767)
    integer(value["add"])
    key = value[kind]
    if kind == "arg":
        integer(key, 0, len(inputs) - 1)
    elif type(key) is not str or key not in ("tick", "epoch", "phase", "field"):
        raise ValueError("context name")
    return integer(inputs[key] * value["mul"] + value["add"])


def guard_matches(guard, args):
    value = args[guard["arg"]]
    operator, rhs = guard["op"], guard["value"]
    if operator == "xor_eq":
        return ((value % (1 << 32)) ^ guard["mask"]) == rhs
    return {"eq": lambda: value == rhs, "ne": lambda: value != rhs,
            "lt": lambda: value < rhs, "le": lambda: value <= rhs,
            "gt": lambda: value > rhs, "ge": lambda: value >= rhs}[operator]()


def rewrite(binding, context):
    r, _, b, metadata = unpack_pair(context["start_pair"])
    inputs = {"tick": context["tick"], "epoch": context["epoch"],
              "phase": BASE.intrinsic(r, (metadata >> 4) & 1), "field": b}
    word = [{"address": [i], "symbol": item["symbol"],
             "args": [expression(value, inputs, "context") for value in item["args"]]}
            for i, item in enumerate(binding["axiom"])]
    generations = [deepcopy(word)]
    limit = binding["limits"]["max_symbols"]
    if len(word) > limit:
        raise ValueError("word budget")
    for generation in range(1, binding["generations"] + 1):
        following = []
        for item in word:
            match = next((index for index, rule in enumerate(binding["rules"])
                          if rule["symbol"] == item["symbol"]
                          and all(guard_matches(guard, item["args"]) for guard in rule["guards"])), None)
            if match is None:
                following.append({**item, "address": item["address"] + [generation, -1, 0]})
            else:
                for offset, output in enumerate(binding["rules"][match]["rhs"]):
                    following.append({"address": item["address"] + [generation, match, offset],
                                      "symbol": output["symbol"],
                                      "args": [expression(value, item["args"], "arg") for value in output["args"]]})
            if len(following) > limit:
                raise ValueError("word budget")
        word = following
        generations.append(deepcopy(word))
    if any(item["symbol"] not in TERMINALS for item in word):
        raise ValueError("final unmatched nonterminal")
    return word, generations


def preflight(binding, tape):
    radius, scale, stack = 1, 0, []
    steps = balls = high_water = 0
    for item in tape:
        symbol, args = item["symbol"], item["args"]
        if len(args) != TERMINALS[symbol]:
            raise ValueError("terminal arity")
        if symbol == "F":
            steps += integer(args[0], 1, 256) * 2 ** scale
        elif symbol in ("+", "-"):
            integer(args[0], 1, 16)
        elif symbol == "R":
            radius = integer(args[0], 1, 127)
        elif symbol == "SCALE":
            scale = integer(args[0], 0, 4)
        elif symbol == "S":
            integer(radius * 2 ** scale, 1, 127)
            balls += 1
        elif symbol == "[":
            stack.append((radius, scale))
            high_water = max(high_water, len(stack))
        elif symbol == "]":
            if not stack:
                raise ValueError("stack underflow")
            radius, scale = stack.pop()
        if steps > binding["limits"]["max_steps"] or balls > binding["limits"]["max_balls"]:
            raise ValueError("work budget")
        if len(stack) > binding["limits"]["max_stack"]:
            raise ValueError("stack budget")
    if stack or not balls:
        raise ValueError("unbalanced stack or no sphere")
    return {"effective_steps": steps, "balls": balls, "stack_high_water": high_water}


def encode_tape(tape):
    """OG-TAPE32-v1, a tagged instruction carrier rather than an RP32 pair."""
    order = ("F", "+", "-", "[", "]", "R", "S", "SCALE")
    result = []
    for instruction in tape:
        operand = instruction["args"][0] if instruction["args"] else 0
        integer(operand, 0, 65535)
        code = order.index(instruction["symbol"])
        raw = (operand & 255) | (((operand >> 8) & 255) << 8) | (code << 24)
        word = raw | ((raw.bit_count() & 1) << 31)
        assert word.bit_count() % 2 == 0 and word & 0x78FF0000 == 0
        result.append(f"{word:08X}")
    return result


def interpret(world, binding, context):
    tape, generations = rewrite(binding, context)
    work = preflight(binding, tape)
    r, node, field, metadata = unpack_pair(context["start_pair"])
    if metadata not in (6, 22) or world.phi[node] != field:
        raise ValueError("stage source context")
    eta, radius, scale, branch, stack = (metadata >> 4) & 1, 1, 0, [], []
    trace, segments, balls = [], [], []
    for item in tape:
        symbol, args, address = item["symbol"], item["args"], item["address"]
        if symbol == "F":
            for step in range(1, args[0] * 2 ** scale + 1):
                phase = BASE.intrinsic(r, eta)
                bank = phase >> 6
                priority = CARDINAL[bank:] + CARDINAL[:bank]
                minimum = min(world.penalties[node, bank, neighbor] for neighbor in world.adj[node])
                direction = next(edge for edge in priority
                                 if world.penalties[node, bank, world.step(node, edge)[0]] == minimum)
                destination, _ = world.step(node, direction)
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
        elif symbol == "S":
            balls.append({"address": list(address), "branch_path": deepcopy(branch), "center": node,
                          "radius": radius * 2 ** scale, "pair": world.packed(r, node, eta)})
        elif symbol == "[":
            stack.append((r, node, eta, radius, scale, deepcopy(branch)))
            branch = branch + [list(address)]
        elif symbol == "]":
            r, node, eta, radius, scale, branch = stack.pop()
        trace.append({"address": list(address), "branch_path": deepcopy(branch),
                      "pair": world.packed(r, node, eta), "radius": radius, "scale": scale})
    assert not stack and not branch
    document = {"format": "klein-organogram-derivation-v1", "context": deepcopy(context),
                "tape": tape, "trace": trace, "segments": segments, "balls": balls,
                "final_context": {"branch_path": branch, "pair": world.packed(r, node, eta),
                                  "radius": radius, "scale": scale}}
    return {"document": document, "derivation_sha256": digest(document), "preflight": work,
            "parallel_generations": generations, "encoded_tape_words": encode_tape(tape),
            "union": union_field(world, balls)}


def target_selection(world, current, phase):
    candidates = [i for i in range(world.count) if i != current]
    minimum = min(abs(world.phi[i]) for i in candidates)
    near = [i for i in candidates if abs(world.phi[i]) == minimum]
    distances = world.distance((current,))
    maximum = max(distances[i] for i in near)
    tied = sorted(i for i in near if distances[i] == maximum)
    return {"minimum_absolute_field": minimum, "maximum_hop_distance": maximum,
            "tied_candidates": tied, "intrinsic_phase": phase, "selected_rank": phase % len(tied),
            "target": tied[phase % len(tied)], "target_path": world.names[tied[phase % len(tied)]]}


def mission(max_epochs=1, mirrored=False):
    binding = default_binding(max_epochs)
    world = Field()
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
            assert energy >= binding["cost"] + 5 + (max_epochs - epoch - 1) * (binding["cost"] + 5)
            context = {"epoch": epoch + 1, "tick": cycle, "start_pair": world.packed(r, node, eta, 6),
                       "prefix_sha256": digest(events)}
            derivation = interpret(world, binding, context)
            old_world = world
            world = Field(values=derivation["union"]["field"])
            selection = target_selection(world, node, BASE.intrinsic(r, eta))
            target = selection["target"]
            epoch += 1
            energy -= binding["cost"]
            known = {}
            pending_growth = False
            before = old_world.state(r, node, eta, energy + binding["cost"], 6)
            event.update(kind="GROW", route=[], cost=binding["cost"], before=before,
                         state=world.state(r, node, eta, energy), status="ACTIVE",
                         selection=selection, context=context, derivation_sha256=derivation["derivation_sha256"])
            worlds.append({"epoch": epoch, "field": list(world.phi), "target": target})
            counterfactual = BASE.route(old_world, node, target, BASE.intrinsic(r, eta), {})
            actual_next = BASE.route(world, node, target, BASE.intrinsic(r, eta), {})
            stages.append({"prior_field": list(old_world.phi), "result": derivation,
                           "selection": selection, "new_field_route": actual_next,
                           "old_field_counterfactual_route": counterfactual})
        elif node == target:
            assert energy >= reserve
            energy -= 5
            pending_growth = epoch < max_epochs
            event.update(kind="REPAIR", route=[], cost=5,
                         state=world.state(r, node, eta, energy, 6),
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
        raise AssertionError("Finite mission failed to terminate")
    return {"initial": initial, "initial_recipe": world.recipe(), "initial_target": 17,
            "binding": binding, "worlds": worlds, "events": events, "stages": stages,
            "cycles": len(events), "final": events[-1]["state"],
            "prefix_hash_scope": "Hashes the preceding independent mathematical events in this vector, not runtime canonical event objects."}


def metric_certificate():
    domains = nodes = comparisons = 0
    transcript = sha256()
    for width in range(3, 86):
        for height in range(3, 86):
            if width * height > 256:
                continue
            domain = BASE.Quotient(width, height)
            domains += 1
            nodes += domain.count
            for source in range(domain.count):
                expected = domain.distance((source,))
                for destination, value in enumerate(expected):
                    actual = closed_distance(width, height, source, destination)
                    assert actual == value, (width, height, source, destination, actual, value)
                    comparisons += 1
                transcript.update(bytes(expected))
    assert domains == 702 and nodes == 106045
    return {"domains": domains, "nodes": nodes, "ordered_node_pairs": comparisons,
            "BFS_distance_transcript_sha256": transcript.hexdigest(),
            "formula": "min(abs(u-a)+cyc_H(v-b), W-abs(u-a)+cyc_H(v+b))",
            "result": "Every pair in every supported Klein quotient agrees with independent BFS."}


def union_counterexample():
    world = Field(3, 3, 0, 1)
    spheres = [{"center": 0, "radius": 2}, {"center": 4, "radius": 2}]
    result = union_field(world, spheres)
    assert result["margin"][2] == -1 and result["field"][2] == -2
    return {"width": 3, "height": 3, "balls": spheres, **result,
            "differing_nodes": [i for i in range(9) if result["margin"][i] != result["field"][i]]}


def expression_vectors():
    context = {"tick": 5, "epoch": 2, "phase": 69, "field": -2}
    entries = []
    for name, mul, add in (("tick", 3, -2), ("epoch", -2, 7), ("phase", 1, -68), ("field", -3, 1)):
        source = {"context": name, "mul": mul, "add": add}
        entries.append({"expression": source, "inputs": context, "expected": expression(source, context, "context")})
    parameter_cases = []
    for args, source in (((-7, 3), arg(0, -2, 1)), ((I32_MAX,), arg(0, 1, 0)),
                         ((I32_MIN,), arg(0, 1, 0)), ((256,), arg(0, 0, 127))):
        parameter_cases.append({"expression": source, "args": list(args), "expected": expression(source, args, "arg")})
    rejected = []
    for args, source in (((I32_MAX,), arg(0, 1, 1)), ((I32_MIN,), arg(0, -1, 0)), ((65539,), arg(0, 32767, 0))):
        try:
            expression(source, args, "arg")
        except ValueError:
            rejected.append({"expression": source, "args": list(args), "expected": "reject signed i32 overflow"})
        else:
            raise AssertionError("Expected expression overflow")
    guards = []
    for guard, args in (({"arg": 0, "op": "xor_eq", "mask": 1, "value": 4}, (5,)),
                        ({"arg": 0, "op": "xor_eq", "mask": 0xFFFFFFFF, "value": 0}, (-1,)),
                        ({"arg": 0, "op": "lt", "value": 0}, (-1,)),
                        ({"arg": 0, "op": "ge", "value": 1}, (2,))):
        guards.append({"guard": guard, "args": list(args), "expected": guard_matches(guard, args)})
    return {"context_cases": entries, "parameter_cases": parameter_cases, "overflow_rejections": rejected,
            "guard_cases": guards}


def branch_certificate(result):
    document = result["document"]
    previous = {"pair": document["context"]["start_pair"], "radius": 1, "scale": 0, "branch_path": []}
    r, node, _, metadata = unpack_pair(previous["pair"])
    prior = Field(values=result["prior_field"]) if "prior_field" in result else Field()
    previous["pair"] = prior.packed(r, node, (metadata >> 4) & 1)
    stack, restores = [], []
    for instruction, state in zip(document["tape"], document["trace"]):
        if instruction["symbol"] == "[":
            stack.append(deepcopy(previous))
        elif instruction["symbol"] == "]":
            expected = stack.pop()
            actual = {key: state[key] for key in expected}
            assert expected == actual
            restores.append({"pop_address": instruction["address"], "restored": actual})
        previous = {key: state[key] for key in ("pair", "radius", "scale", "branch_path")}
    assert not stack
    nested = [segment for segment in document["segments"] if len(segment["branch_path"]) >= 2]
    orientations = [(unpack_pair(segment["pair"])[3] >> 4) & 1 for segment in nested]
    assert set(orientations) == {0, 1}
    return {"exact_pop_restorations": restores, "nested_segment_orientations": orientations,
            "nested_reversing_seam_exercised": True}


def main():
    binding = default_binding()
    context = {"epoch": 1, "tick": 5, "start_pair": "06011145160111BB", "prefix_sha256": digest([])}
    standalone = interpret(Field(), binding, context)
    time_variant = interpret(Field(), binding, {**context, "tick": 6})
    assert time_variant["union"]["field"] != standalone["union"]["field"]
    wrong_priority = deepcopy(binding)
    wrong_priority["rules"][2], wrong_priority["rules"][3] = wrong_priority["rules"][3], wrong_priority["rules"][2]
    priority_variant = interpret(Field(), wrong_priority, context)
    assert priority_variant["union"]["field"] != standalone["union"]["field"]
    assert priority_variant["document"]["balls"][1]["radius"] == 4
    mirrored_context = {**context, "start_pair": context["start_pair"][8:] + context["start_pair"][:8]}
    mirrored = interpret(Field(), binding, mirrored_context)
    for key in ("trace", "segments", "balls"):
        for left, right in zip(standalone["document"][key], mirrored["document"][key]):
            assert left["pair"] == right["pair"][8:] + right["pair"][:8]
            assert {k: v for k, v in left.items() if k != "pair"} == {k: v for k, v in right.items() if k != "pair"}
    assert standalone["union"] == mirrored["union"]
    default, mirror, twice, zero = mission(), mission(mirrored=True), mission(2), mission(0)
    for left, right in zip(default["events"], mirror["events"]):
        assert (left["kind"], left["route"], left["cost"], left["state"]["energy"]) == (
            right["kind"], right["route"], right["cost"], right["state"]["energy"])
        assert left["state"]["pair"] == right["state"]["pair"][8:] + right["state"]["pair"][:8]
    empty_balls = [{"center": i, "radius": 1} for i in range(9)]
    try:
        union_field(Field(3, 3, 0, 1), empty_balls)
    except ValueError as error:
        assert str(error) == "empty union boundary"
    else:
        raise AssertionError("Expected empty-boundary rejection")
    maximum_tape = [token("F", 256), token("+", 16), token("-", 16), token("["), token("]"),
                    token("R", 127), token("S"), token("SCALE", 4)]
    result = {"format": "organogram-independent-formal-reference-v1",
              "provenance": "Independent context expressions, parallel rewrite, branch interpreter, quotient BFS, union redistance, RP32 packing and HP lifted planning checked by layered DP. Imports no solvefinite runtime module.",
              "generator_sha256_lf": sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "independent_GD_generator_sha256_lf": sha256(BASE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "binding": binding, "standalone_stage": standalone, "mirrored_standalone_stage": mirrored,
              "original_tick_variant_stage": time_variant,
              "priority_mutation": {"swap_rules": [2, 3], "stage": priority_variant,
                                    "reason": "The general B rule also matches parameter1; its extra R2 changes the later nested scaled sphere radius from2 to4 and the exact field."},
              "instruction_profile": {"format": "OG-TAPE32-v1", "opcode_order": ["F", "+", "-", "[", "]", "R", "S", "SCALE"],
                                      "encoding_vectors": {"tokens": maximum_tape, "words": encode_tape(maximum_tape)}},
              "expression_vectors": expression_vectors(),
              "standalone_context_scope": "Declared mathematical context input; prefix SHA256 of [] is not a claim that this sequence-5 context was admitted by a runtime agent.",
              "branch_certificate": branch_certificate(standalone),
              "default_mission": default, "mirrored_default_mission": mirror,
              "two_epoch_mission": twice, "zero_epoch_mission": zero,
              "union_counterexample": union_counterexample(),
              "empty_boundary_vector": {"width": 3, "height": 3, "balls": empty_balls, "expected": "reject empty union boundary"},
              "metric_certificate": metric_certificate()}
    output = Path(__file__).with_name("formal-reference.json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "sha256": sha256(output.read_bytes()).hexdigest(),
                      "standalone_digest": standalone["derivation_sha256"],
                      "balls": [(sphere["center"], sphere["radius"]) for sphere in standalone["document"]["balls"]],
                      "missions": {name: {"cycles": value["cycles"], "final": value["final"],
                                           "targets": [stage["selection"]["target"] for stage in value["stages"]]}
                                   for name, value in (("default", default), ("mirror", mirror), ("twice", twice), ("zero", zero))},
                      "metric": result["metric_certificate"]}, indent=2))


if __name__ == "__main__":
    main()
