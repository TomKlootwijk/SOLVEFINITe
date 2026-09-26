"""Independent GD1-GD8 arithmetic references; imports no solvefinite module.

Run with Python 3.10+ from any directory. The output is deterministic UTF-8/LF
JSON beside this file. These are mathematical expected values, not measured
runtime conformance. Dijkstra routes are independently checked by layered DP.
"""

from collections import deque
from hashlib import sha256
from heapq import heappop, heappush
import json
from math import gcd
from pathlib import Path


TURNS = (11, 53, 137)
GAINS = ((1, 1), (-1, 1), (-1, -1), (1, -1))
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class Quotient:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.count = width * height
        self.names = tuple(f"k:{u}:{v}" for u in range(width)
                           for v in range(height))
        self.indices = {name: index for index, name in enumerate(self.names)}
        self.adj = tuple(tuple(sorted(self.step(i, e)[0] for e in DIRECTIONS))
                         for i in range(self.count))
        self.edge_directions = {(i, self.step(i, e)[0]): e
                                for i in range(self.count) for e in DIRECTIONS}
        assert all(len(set(row)) == 4 for row in self.adj)

    def canonical(self, u, v, orientation=0):
        wraps, u = divmod(u, self.width)
        reverse = wraps & 1
        return u, (-v if reverse else v) % self.height, orientation ^ reverse

    def step(self, index, direction):
        u, v = divmod(index, self.height)
        du, dv = direction
        u, v, seam = self.canonical(u + du, v + dv)
        return u * self.height + v, seam

    def distance(self, seeds):
        values = [-1] * self.count
        pending = deque(seeds)
        for index in seeds:
            values[index] = 0
        while pending:
            index = pending.popleft()
            for neighbor in self.adj[index]:
                if values[neighbor] == -1:
                    values[neighbor] = values[index] + 1
                    pending.append(neighbor)
        assert all(value >= 0 for value in values)
        return tuple(values)

    def doubled_node(self, index):
        u, v = divmod(index, self.height)
        return 2 * u * (2 * self.height) + 2 * v


class World(Quotient):
    def __init__(self, width, height, center, radius):
        super().__init__(width, height)
        self.center, self.radius = center, radius
        self.radial = self.distance((center,))
        assert 1 <= radius <= max(self.radial)
        self.signs = tuple((d > radius) - (d < radius) for d in self.radial)
        self.boundary = tuple(i for i, sign in enumerate(self.signs) if sign == 0)
        boundary_distance = self.distance(self.boundary)
        self.phi = tuple(s * d for s, d in zip(self.signs, boundary_distance))
        assert all(-128 <= value <= 127 for value in self.phi)
        assert all(self.signs[i] * self.signs[j] != -1
                   for i in range(self.count) for j in self.adj[i])
        self.gradient = tuple(
            (self.phi[self.step(i, (1, 0))[0]] - self.phi[self.step(i, (-1, 0))[0]],
             self.phi[self.step(i, (0, 1))[0]] - self.phi[self.step(i, (0, -1))[0]])
            for i in range(self.count))
        self.axis = tuple((u // g, v // g) if g else (1, 0)
                          for u, v in self.gradient
                          for g in (gcd(abs(u), abs(v)),))
        self.penalties = {}
        for i in range(self.count):
            gu, gv = self.gradient[i]
            pu, pv = self.axis[i]
            for bank, (au, av) in enumerate(GAINS):
                qu, qv = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
                magnitude = max(abs(qu), abs(qv))
                for j in self.adj[i]:
                    eu, ev = self.edge_directions[i, j]
                    self.penalties[i, bank, j] = magnitude - qu * eu - qv * ev

    def recipe(self):
        return {"width": self.width, "height": self.height,
                "center": self.center, "radius": self.radius,
                "turns": list(TURNS)}

    def refined(self):
        assert self.count * 4 <= 256
        return World(2 * self.width, 2 * self.height,
                     self.doubled_node(self.center), 2 * self.radius)

    def phase_after(self, i, t):
        return (t + TURNS[self.signs[i] + 1]) % 256

    def cost(self, i, t, j, hazards):
        return 1 + abs(self.phi[j]) + hazards.get(j, 0) + self.penalties[i, t // 64, j]

    def transport(self, r, i, eta, j):
        updated = (r + (-1 if eta else 1) * TURNS[self.signs[i] + 1]) % 256
        _, seam = self.step(i, self.edge_directions[i, j])
        return (-updated) % 256 if seam else updated, j, eta ^ seam

    def packed(self, r, i, eta, opcode=1):
        def lane(rr, ee):
            word = rr | (i << 8) | ((self.phi[i] & 255) << 16)
            word |= (opcode | (ee << 4)) << 24
            return word | ((word.bit_count() & 1) << 31)
        return f"{lane((-r) % 256, eta ^ 1):08X}{lane(r, eta):08X}"

    def state(self, r, i, eta, energy, opcode=1):
        return {"node": i, "path": self.names[i], "phase": r,
                "orientation": eta, "intrinsic_phase": intrinsic(r, eta),
                "field": self.phi[i], "pair": self.packed(r, i, eta, opcode),
                "energy": energy}


def intrinsic(r, eta):
    return (-r) % 256 if eta else r


def route(world, start, target, phase, hazards, max_hops=255):
    remaining = world.distance((target,))
    frontier = [(0, (), start, phase, 0)]
    best = {(start, phase, 0): (0, ())}
    expansions = 0
    while frontier:
        total, paths, i, t, hops = heappop(frontier)
        if best[i, t, hops] != (total, paths):
            continue
        if i == target:
            result = {"route": [world.indices[path] for path in paths],
                      "paths": list(paths), "cost": total,
                      "expansions": expansions}
            verify_by_layers(world, start, target, phase, hazards, result, max_hops)
            return result
        expansions += 1
        for j in world.adj[i]:
            if hops + 1 + remaining[j] > max_hops:
                continue
            candidate = (total + world.cost(i, t, j, hazards), paths + (world.names[j],))
            state = j, world.phase_after(i, t), hops + 1
            if state not in best or candidate < best[state]:
                best[state] = candidate
                heappush(frontier, (*candidate, *state))
    raise AssertionError("No admissible finite route")


def verify_by_layers(world, start, target, phase, hazards, result, max_hops):
    # Independent hop-layer dynamic programming has no priority queue and no
    # Dijkstra distance labels. Positive edge costs bound useful route length.
    limit = result["cost"]
    current = {(start, phase): (0, ())}
    optimum = None
    for _ in range(min(max_hops, limit) + 1):
        following = {}
        for (i, t), (total, paths) in current.items():
            if i == target:
                if optimum is None or (total, paths) < optimum:
                    optimum = total, paths
                continue
            for j in world.adj[i]:
                candidate = total + world.cost(i, t, j, hazards), paths + (world.names[j],)
                if candidate[0] > limit:
                    continue
                state = j, world.phase_after(i, t)
                if state not in following or candidate < following[state]:
                    following[state] = candidate
        current = following
    assert optimum == (result["cost"], tuple(result["paths"])), (optimum, result)


def select_target(world, current, phase):
    candidates = [i for i in range(world.count)
                  if any(coordinate & 1 for coordinate in divmod(i, world.height))]
    boundary_layer = min(abs(world.phi[i]) for i in candidates)
    near = [i for i in candidates if abs(world.phi[i]) == boundary_layer]
    distances = world.distance((current,))
    farthest = max(distances[i] for i in near)
    tied = sorted(i for i in near if distances[i] == farthest)
    selected = tied[phase % len(tied)]
    return {"generated_node_count": len(candidates), "minimum_absolute_field": boundary_layer,
            "maximum_hop_distance": farthest, "tied_candidates": tied,
            "intrinsic_phase": phase, "selected_rank": phase % len(tied),
            "target": selected, "target_path": world.names[selected]}


def mission(width=4, height=5, center=0, radius=2, target=17, max_epochs=1,
            initial_phase=250, initial_orientation=0, initial_energy=100,
            initial_hazard=True, growth_cost=1, repair_cost=5):
    assert width * height * 4 ** max_epochs <= 256
    world = World(width, height, center, radius)
    start_world = world
    epoch = 0
    r, i, eta, energy = initial_phase, 0, initial_orientation, initial_energy
    initial = world.state(r, i, eta, energy)
    known, events = {}, []
    pending_growth = False
    worlds = [{"geometry_epoch": epoch, "recipe": world.recipe(),
               "field": list(world.phi), "target": target,
               "target_path": world.names[target]}]

    def reserve():
        return repair_cost + (max_epochs - epoch) * (growth_cost + repair_cost)

    for cycle in range(1, 1001):
        visible = sorted((i, *world.adj[i]), key=world.names.__getitem__)
        frame = {j: 70 if initial_hazard and epoch == 0 and cycle >= 2 and j == 3 else 0
                 for j in visible}
        known.update(frame)
        event = {"cycle": cycle, "input_geometry_epoch": epoch,
                 "input": {world.names[j]: value for j, value in frame.items()},
                 "target_before": target, "reserve_before": reserve()}
        if pending_growth:
            assert energy >= growth_cost + repair_cost + (max_epochs - epoch - 1) * (growth_cost + repair_cost)
            previous = world
            candidate = world.refined()
            mapped = world.doubled_node(i)
            selection = select_target(candidate, mapped, intrinsic(r, eta))
            event.update({"kind": "GROW", "route": [], "cost": growth_cost,
                          "before": world.state(r, i, eta, energy, 6),
                          "source_recipe": world.recipe(), "next_recipe": candidate.recipe(),
                          "selection": selection})
            world, i, target = candidate, mapped, selection["target"]
            epoch += 1
            energy -= growth_cost
            pending_growth = False
            known = {}
            event.update({"status": "RUNNING", "geometry_epoch": epoch,
                          "target_after": target, "state": world.state(r, i, eta, energy)})
            assert all(world.signs[previous.doubled_node(j)] == previous.signs[j]
                       for j in range(previous.count))
            worlds.append({"geometry_epoch": epoch, "recipe": world.recipe(),
                           "field": list(world.phi), "target": target,
                           "target_path": world.names[target]})
        elif i == target:
            assert energy >= reserve()
            energy -= repair_cost
            pending_growth = epoch < max_epochs
            event.update({"kind": "REPAIR", "route": [], "cost": repair_cost,
                          "geometry_epoch": epoch, "target_after": target,
                          "status": "GROWTH_PENDING" if pending_growth else "COMPLETE",
                          "state": world.state(r, i, eta, energy, 6)})
        else:
            result = route(world, i, target, intrinsic(r, eta), known)
            assert result["cost"] + reserve() <= energy, (epoch, cycle, result, energy, reserve())
            forecast, costs = [], []
            fr, fi, fe = r, i, eta
            for j in result["route"]:
                costs.append(world.cost(fi, intrinsic(fr, fe), j, known))
                fr, fi, fe = world.transport(fr, fi, fe, j)
                forecast.append(world.packed(fr, fi, fe))
            assert sum(costs) == result["cost"]
            r, i, eta = world.transport(r, i, eta, result["route"][0])
            energy -= costs[0]
            event.update({"kind": "MOVE", **result, "action_cost": costs[0],
                          "forecast_costs": costs, "forecast": forecast,
                          "geometry_epoch": epoch, "target_after": target,
                          "status": "RUNNING", "state": world.state(r, i, eta, energy)})
        events.append(event)
        if event["status"] == "COMPLETE":
            break
    else:
        raise AssertionError("Mission did not finish within its finite reference budget")
    return {"initial_recipe": start_world.recipe(), "initial_target": worlds[0]["target"],
            "growth": {"format": "klein-dyadic-growth-v1", "max_epochs": max_epochs, "cost": growth_cost},
            "repair_cost": repair_cost, "initial": initial,
            "hazard_rule": "Node 3 becomes hazard 70 at global cycle 2 in epoch 0 only; all other hazards zero."
            if initial_hazard else "All hazards zero in all epochs.",
            "worlds": worlds, "events": events, "final": events[-1]["state"],
            "cycles": len(events), "final_geometry_epoch": epoch}


def verify_mirror(original, mirrored):
    assert original["cycles"] == mirrored["cycles"]
    for old, new in zip(original["events"], mirrored["events"]):
        for name in ("kind", "geometry_epoch", "route", "cost", "target_after", "status"):
            assert old[name] == new[name]
        a, b = old["state"], new["state"]
        for name in ("node", "field", "energy", "intrinsic_phase"):
            assert a[name] == b[name]
        assert a["phase"] == (-b["phase"]) % 256
        assert a["orientation"] == b["orientation"] ^ 1
        assert a["pair"] == b["pair"][8:] + b["pair"][:8]


def refinement_certificates():
    # Exhaust every old quotient capable of at least one dyadic generation
    # within RP32's 256-node bound. Every center supplies all pair distances.
    domains = directed_edges = pair_distances = aliases = 0
    transcript = sha256()
    for width in range(3, 22):
        for height in range(3, 22):
            if 4 * width * height > 256:
                continue
            domains += 1
            old, new = Quotient(width, height), Quotient(2 * width, 2 * height)
            for i in range(old.count):
                embedded = old.doubled_node(i)
                for direction in DIRECTIONS:
                    j, seam = old.step(i, direction)
                    midway, first_seam = new.step(embedded, direction)
                    finish, second_seam = new.step(midway, direction)
                    assert finish == old.doubled_node(j)
                    assert first_seam ^ second_seam == seam
                    assert first_seam + second_seam == seam
                    directed_edges += 1
                    transcript.update(f"E:{width},{height},{i},{direction},{finish},{seam};".encode())
                coarse = old.distance((i,))
                fine = new.distance((embedded,))
                for j in range(old.count):
                    assert fine[old.doubled_node(j)] == 2 * coarse[j]
                    pair_distances += 1
                u, v = divmod(i, height)
                for horizontal_wrap in range(-2, 3):
                    for vertical_wrap in range(-2, 3):
                        for eta in (0, 1):
                            alias_u = u + horizontal_wrap * width
                            alias_v = ((-v) if horizontal_wrap & 1 else v) + vertical_wrap * height
                            alias_eta = eta ^ (horizontal_wrap & 1)
                            cu, cv, ce = old.canonical(alias_u, alias_v, alias_eta)
                            nu, nv, ne = new.canonical(2 * alias_u, 2 * alias_v, alias_eta)
                            assert (cu, cv, ce) == (u, v, eta)
                            assert (nu, nv, ne) == (2 * u, 2 * v, eta)
                            aliases += 1
            transcript.update(f"D:{width},{height},{pair_distances},{aliases};".encode())
    return {"all_refinable_quotients_checked": domains,
            "directed_edge_two_step_and_seam_checks": directed_edges,
            "old_vertex_pair_distance_checks": pair_distances,
            "oriented_equivalent_representative_checks": aliases,
            "certificate_transcript_sha256": transcript.hexdigest(),
            "invariants": ["E commutes with quotient reduction and orientation transport",
                           "Each old edge has a two-edge image with the same seam XOR",
                           "distance_new(E(a),E(b)) = 2*distance_old(a,b)"]}


def field_counterexample():
    old = World(3, 5, 1, 3)
    new = old.refined()
    mapped = old.doubled_node(0)
    assert old.phi[0] == -3 and new.phi[mapped] == -4
    return {"old_recipe": old.recipe(), "new_recipe": new.recipe(),
            "old_node": 0, "new_node": mapped, "old_field": old.phi[0],
            "new_field": new.phi[mapped], "incorrect_doubled_old_field": 2 * old.phi[0],
            "old_boundary": list(old.boundary), "new_boundary": list(new.boundary),
            "old_fields": list(old.phi), "new_fields": list(new.phi),
            "explanation": "Newly generated boundary vertices may be nearer than embedded old boundary vertices; recompute B."}


def target_tie_vectors():
    world = World(4, 5, 0, 2).refined()
    for source in range(20):
        mapped = Quotient(4, 5).doubled_node(source)
        first = select_target(world, mapped, 0)
        if len(first["tied_candidates"]) > 1:
            return {"recipe": world.recipe(), "old_node": source, "mapped_node": mapped,
                    "selections": [select_target(world, mapped, phase) for phase in (0, 1, 2, 63, 64, 127, 128, 255)]}
    raise AssertionError("Expected a phase-selected target tie")


def main():
    default = mission()
    mirror = mission(initial_phase=6, initial_orientation=1)
    verify_mirror(default, mirror)
    two_epochs = mission(width=3, height=3, radius=1, target=4, max_epochs=2, initial_hazard=False)
    zero_epochs = mission(max_epochs=0)
    result = {
        "format": "growth-independent-formal-reference-v1",
        "provenance": "Independent quotient reduction, BFS field construction, integer Hadamard routing, lifted Dijkstra, layered-DP route verification and RP32 packing. Imports no solvefinite module.",
        "normative_contract": "TK-LPLUT-2.0 revision 7, GD1-GD8; these are formal expected vectors, not runtime measurements.",
        "generator_sha256_lf": sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "hadamard_gains": [list(bank) for bank in GAINS],
        "default_mission": default,
        "mirrored_default_mission": mirror,
        "two_epoch_mission": two_epochs,
        "zero_epoch_mission": zero_epochs,
        "field_recomputation_counterexample": field_counterexample(),
        "phase_selected_target_ties": target_tie_vectors(),
        "refinement_certificates": refinement_certificates(),
        "planner_cross_check": "Every MOVE route in every mission is independently checked by hop-layer dynamic programming; every positive edge costs at least one.",
    }
    output = Path(__file__).with_name("formal-reference.json")
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "sha256": sha256(output.read_bytes()).hexdigest(),
                      "missions": {name: {"cycles": value["cycles"], "final": value["final"],
                                           "growths": [{"cycle": event["cycle"], "selection": event["selection"],
                                                        "state": event["state"]} for event in value["events"]
                                                       if event["kind"] == "GROW"]}
                                   for name, value in (("default", default), ("mirror", mirror),
                                                       ("two_epochs", two_epochs), ("zero_epochs", zero_epochs))},
                      "certificates": result["refinement_certificates"]}, indent=2))


if __name__ == "__main__":
    main()
