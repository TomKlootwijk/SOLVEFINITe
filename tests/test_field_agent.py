"""Independent end-to-end checks for the committed FI1-FI8 field-agent binding."""

from collections import deque
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from heapq import heappop, heappush
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.field_agent import FieldAgentManifest
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.live import PROTOCOL, LiveConfig, LiveSession, load_live
from solvefinite.session import Scenario, load_session, run_session
from solvefinite.tomigidt import AgentManifest, Tomigidt


ROOT = Path(__file__).resolve().parents[1]
POLICY = "tomigidt-field-observe-plan-act-v1"
WORD_PROFILE = "RP32-relational-sdf-v2"
MANIFEST_KEYS = {"identity", "target", "world", "initial_node", "initial_phase",
                 "initial_orientation", "initial_energy", "repair_cost",
                 "max_search_expansions", "max_hops", "max_cycles", "policy",
                 "word_profile", "perspective"}
RECIPE_KEYS = {"format", "width", "height", "center", "radius", "turns", "baseline_id"}
MISSION_PAIRS = ("91FE000601FE00FA", "11FF04FB01FF0405", "81001010910010F0",
                 "81011145910111BB", "06011145160111BB")
MISSION_ENERGIES = (100, 98, 97, 95, 90)


def word(phase, node, field, metadata):
    value = phase | node << 8 | (field % 256) << 16 | metadata << 24
    return value | (value.bit_count() % 2) << 31


def packed(phase, node, field, orientation, opcode=1):
    return (word(phase, node, field, opcode | orientation << 4)
            | word((-phase) % 256, node, field, opcode | (orientation ^ 1) << 4) << 32)


def lanes(value):
    left = value & 0xFFFFFFFF
    field = (left >> 16) & 255
    return left & 255, (left >> 8) & 255, field - 256 if field >= 128 else field, (left >> 24) & 127


def swapped(value):
    return value >> 32 | (value & 0xFFFFFFFF) << 32


def zero_frame(agent):
    return {name: 0 for name in agent.visible_paths}


def mission_scenario(manifest=None):
    return Scenario(FieldAgentManifest() if manifest is None else manifest,
                    changes=((2, "k:0:3", 70),))


def finish(agent, scenario=None, limit=512):
    decisions = []
    for _ in range(limit):
        if agent.status == "COMPLETE":
            return decisions
        frame = zero_frame(agent) if scenario is None else scenario.observe(agent.position, agent.cycle + 1)
        decisions.append(agent.step(frame))
    raise AssertionError("The finite field mission did not finish")


def cache_state(world):
    return world.active_paths, world.evicted_paths, world.hit_count, world.regeneration_count


def independent_fields(manifest):
    graph = dict(manifest.graph)

    def distances(starts):
        result = {name: 0 for name in starts}
        queue = deque(starts)
        while queue:
            source = queue.popleft()
            for target in graph[source]:
                if target not in result:
                    result[target] = result[source] + 1
                    queue.append(target)
        return result

    recipe = manifest.world
    u, v = divmod(recipe.center, recipe.height)
    radial = distances((f"k:{u}:{v}",))
    signs = {name: (distance > recipe.radius) - (distance < recipe.radius)
             for name, distance in radial.items()}
    boundary = tuple(name for name, sign in signs.items() if sign == 0)
    exact = distances(boundary)
    return {name: signs[name] * exact[name] for name in graph}


def independent_route(manifest, start, hazards):
    fields = independent_fields(manifest)
    graph = dict(manifest.graph)
    pending = [(0, (), start)]
    settled = set()
    while pending:
        cost, route, node = heappop(pending)
        if node in settled:
            continue
        settled.add(node)
        if node == manifest.target:
            return route, cost
        for destination in graph[node]:
            heappush(pending, (cost + 1 + abs(fields[destination]) + hazards.get(destination, 0),
                               (*route, destination), destination))
    raise AssertionError("Connected quotient unexpectedly has no route")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def observe_request(response, observations=None):
    context = response["next"]
    return {"protocol": PROTOCOL, "type": "observe", "producer": response["producer"],
            "epoch": response["epoch"], "seq": context["seq"], "position": context["position"],
            "observations": ({name: 0 for name in context["paths"]}
                             if observations is None else observations)}


class FieldAgentManifestTests(unittest.TestCase):
    def test_exact_manifest_retains_recipe_and_never_supplied_graph_or_fields(self):
        manifest = FieldAgentManifest()
        encoded = manifest.to_dict()
        self.assertEqual(set(encoded), MANIFEST_KEYS)
        self.assertEqual(set(encoded["world"]), RECIPE_KEYS)
        self.assertEqual(encoded["policy"], POLICY)
        self.assertEqual(encoded["word_profile"], WORD_PROFILE)
        self.assertEqual(encoded["perspective"], "local-observation-v1")
        self.assertEqual(encoded["world"]["format"], "klein-ball-world-v1")
        self.assertEqual((manifest.start, manifest.initial_node, manifest.target),
                         ("k:0:0", "k:0:0", "k:3:2"))
        self.assertEqual((manifest.max_hops, manifest.initial_energy), (255, 100))
        self.assertEqual(FieldAgentManifest.from_dict(json.loads(json.dumps(encoded))), manifest)
        for name in ("initial_energy", "initial_node", "world", "policy"):
            with self.subTest(attribute=name), self.assertRaises((FrozenInstanceError, AttributeError)):
                setattr(manifest, name, None)
        for missing in encoded:
            damaged = deepcopy(encoded)
            del damaged[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                FieldAgentManifest.from_dict(damaged)
        for extra in ("graph", "routes", "fields", "seams", "field_pair", "energy"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                FieldAgentManifest.from_dict({**encoded, extra: []})
        encoded["world"]["turns"][0] = 255
        self.assertEqual(manifest.world.turns, (11, 53, 137))

    def test_manifest_strict_ranges_names_profiles_and_nested_recipe(self):
        original = FieldAgentManifest()
        invalid = ({"initial_energy": -1}, {"initial_energy": 1 << 31}, {"initial_energy": True},
                   {"initial_energy": 100.0}, {"initial_phase": True}, {"initial_phase": 256},
                   {"initial_orientation": -1}, {"initial_orientation": 2},
                   {"repair_cost": 0}, {"repair_cost": 128}, {"repair_cost": True},
                   {"max_hops": 0}, {"max_hops": 256}, {"max_hops": 1.0},
                   {"max_cycles": 0}, {"max_cycles": 1_000_001}, {"max_cycles": False},
                   {"max_search_expansions": 0}, {"max_search_expansions": 65537},
                   {"identity": ""}, {"identity": " "}, {"identity": "x" * 129},
                   {"world": None}, {"world": {}}, {"policy": "tomigidt-observe-plan-act-v2"})
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(original, **changes)
        for name in ("", "0", "k:04:0", "k:0:05", "k:0:-1", "k:4:0", "k:0:5", 0, True, None):
            for field in ("initial_node", "target"):
                with self.subTest(field=field, name=name), self.assertRaises(ValueError):
                    replace(original, **{field: name})
        encoded = original.to_dict()
        for key, value in (("word_profile", "RP32-v1"), ("perspective", "future"),
                           ("policy", "future")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                FieldAgentManifest.from_dict({**encoded, key: value})
        for recipe_changes in ({"format": "future"}, {"center": 20}, {"radius": 0},
                               {"width": True}, {"turns": [11, 53]}, {"graph": {}},
                               {"fields": [0] * 20}):
            damaged = deepcopy(encoded)
            damaged["world"].update(recipe_changes)
            with self.subTest(recipe=recipe_changes), self.assertRaises(ValueError):
                FieldAgentManifest.from_dict(damaged)
        self.assertEqual(replace(original, initial_energy=(1 << 31) - 1).initial_energy,
                         (1 << 31) - 1)

    def test_quotient_graph_is_complete_and_globally_lexical(self):
        manifest = FieldAgentManifest(world=KleinFieldRecipe(width=12, height=3), target="k:11:2")
        graph = dict(manifest.graph)
        self.assertEqual(tuple(graph), tuple(sorted(graph)))
        self.assertLess(tuple(graph).index("k:10:0"), tuple(graph).index("k:2:0"))
        self.assertEqual(len(graph), 36)
        for name, neighbors in graph.items():
            self.assertEqual(neighbors, tuple(sorted(neighbors)))
            self.assertEqual(len(neighbors), 4)
            self.assertNotIn(name, neighbors)
            for neighbor in neighbors:
                self.assertIn(name, graph[neighbor])
        self.assertIn("k:11:2", graph["k:0:1"])


class FieldAgentBehaviorTests(unittest.TestCase):
    def test_entire_independent_packed_forecast_matches_unchanged_future_observations(self):
        agent = Tomigidt(FieldAgentManifest(), capacity=2)
        self.addCleanup(agent.close)
        first = agent.step(zero_frame(agent))
        expected = (packed(5, 4, -1, 0), packed(16, 3, 0, 0), packed(187, 17, 1, 1))
        self.assertEqual(first.forecast, expected)
        self.assertEqual(first.expected_pair, expected[0])
        for offset in (1, 2):
            decision = agent.step(zero_frame(agent))
            self.assertEqual(decision.forecast, expected[offset:])
            self.assertEqual(agent.agent_pair, expected[offset])
        self.assertEqual(agent.energy, 95)
        self.assertEqual(agent.step(zero_frame(agent)).kind, "REPAIR")
        self.assertEqual(agent.agent_pair, packed(187, 17, 1, 1, opcode=6))

    def test_reference_mission_replans_crosses_seam_and_keeps_energy_separate(self):
        scenario = mission_scenario()
        agent = Tomigidt(scenario.manifest, capacity=1)
        self.addCleanup(agent.close)
        fields = independent_fields(agent.manifest)
        self.assertEqual(f"{agent.agent_pair:016X}", MISSION_PAIRS[0])
        self.assertEqual(agent.energy, 100)
        routes = (("k:0:4", "k:0:3", "k:3:2"), ("k:3:1", "k:3:2"), ("k:3:2",), ())
        costs = (5, 3, 2, 5)
        expected_lanes = ((5, 4, -1, 1), (240, 16, 0, 17), (187, 17, 1, 17), (187, 17, 1, 22))
        original_forecast = None
        for cycle in range(1, 5):
            frame = scenario.observe(agent.position, cycle)
            previous = agent.position
            if cycle < 4:
                hazards = {name: lanes(int(value, 16))[2]
                           for name, value in agent.snapshot()["observations"].items()}
                hazards.update(frame)
                self.assertEqual(independent_route(agent.manifest, previous, hazards),
                                 (routes[cycle - 1], costs[cycle - 1]))
            decision = agent.step(frame)
            self.assertEqual((decision.kind, decision.route, decision.cost),
                             ("REPAIR" if cycle == 4 else "MOVE", routes[cycle - 1], costs[cycle - 1]))
            self.assertEqual(f"{agent.agent_pair:016X}", MISSION_PAIRS[cycle])
            self.assertEqual(agent.energy, MISSION_ENERGIES[cycle])
            self.assertEqual(lanes(agent.agent_pair), expected_lanes[cycle - 1])
            self.assertEqual(lanes(agent.agent_pair)[2], fields[agent.position])
            event = agent.events[-1]
            self.assertEqual(set(event), {"seq", "input", "decision", "output", "energy"})
            self.assertEqual(event["energy"], agent.energy)
            self.assertEqual(agent.snapshot()["energy"], agent.energy)
            self.assertEqual(agent.snapshot()["word_profile"], WORD_PROFILE)
            for name, encoded in event["input"].items():
                self.assertEqual(lanes(int(encoded, 16))[2:], (frame[name], 0))
            if cycle == 1:
                original_forecast = decision.forecast
            elif cycle == 2:
                self.assertNotEqual(agent.agent_pair, original_forecast[1])
                self.assertEqual(decision.forecast[0], agent.agent_pair)
        self.assertEqual((agent.status, agent.position), ("COMPLETE", "k:3:2"))
        self.assertEqual(lanes(int(agent.snapshot()["observations"]["k:0:3"], 16))[2], 70)
        self.assertGreater(agent.world.regeneration_count, 0)

    def test_changing_only_boundary_recipe_changes_actual_plan(self):
        manifests = (FieldAgentManifest(), FieldAgentManifest(world=KleinFieldRecipe(center=4)))
        expected = (("k:0:4", "k:0:3", "k:3:2"), ("k:3:0", "k:3:1", "k:3:2"))
        self.assertEqual(manifests[0].graph, manifests[1].graph)
        for manifest, route, cost in zip(manifests, expected, (5, 4)):
            agent = Tomigidt(manifest)
            self.addCleanup(agent.close)
            self.assertEqual(independent_route(manifest, manifest.start, {}), (route, cost))
            decision = agent.step(zero_frame(agent))
            self.assertEqual((decision.route, decision.cost), (route, cost))
            self.assertEqual(agent.position, route[0])

    def test_mirrored_seed_has_same_decisions_costs_and_full_mirrored_history(self):
        left = Tomigidt(FieldAgentManifest(), capacity=1)
        right = Tomigidt(FieldAgentManifest(initial_phase=6, initial_orientation=1), capacity=32)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        scenario = mission_scenario()
        self.assertEqual(right.agent_pair, swapped(left.agent_pair))
        while left.status != "COMPLETE":
            frame = scenario.observe(left.position, left.cycle + 1)
            a, b = left.step(frame), right.step(frame)
            self.assertEqual((a.kind, a.route, a.cost, a.expansions),
                             (b.kind, b.route, b.cost, b.expansions))
            self.assertEqual(b.forecast, tuple(map(swapped, a.forecast)))
            self.assertEqual(right.agent_pair, swapped(left.agent_pair))
            self.assertEqual((right.position, right.energy), (left.position, left.energy))

    def test_only_fresh_complete_local_hazards_authorize_action(self):
        agent = Tomigidt(FieldAgentManifest())
        self.addCleanup(agent.close)
        original_pair, original_energy = agent.agent_pair, agent.energy
        self.assertEqual(agent.step({"k:0:0": 0}).kind, "WAIT")
        self.assertEqual(agent.step({name: 0 for name in agent.visible_paths if name != "k:0:0"}).kind, "WAIT")
        self.assertEqual((agent.agent_pair, agent.energy, agent.position),
                         (original_pair, original_energy, "k:0:0"))
        original = agent.archive(), cache_state(agent.world)
        invalid_frames = (None, [], {"k:3:2": 0}, {"route": ["k:0:4"]},
                          {"action": "MOVE"}, {"phi": -2}, {"k:0:0": {"hazard": 0, "phi": -2}},
                          {"k:0:0": True}, {"k:0:0": 0.0}, {"k:0:0": -1}, {"k:0:0": 128})
        for frame in invalid_frames:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                agent.step(frame)
            self.assertEqual((agent.archive(), cache_state(agent.world)), original)
        self.assertEqual(agent.step(zero_frame(agent)).kind, "MOVE")

    def test_insufficient_reserve_recovers_after_new_hazards_and_exact_energy_completes(self):
        agent = Tomigidt(FieldAgentManifest(initial_energy=10))
        self.addCleanup(agent.close)
        original_pair = agent.agent_pair
        expensive = {name: 70 for name in agent.visible_paths}
        refused = agent.step(expensive)
        self.assertEqual(refused.kind, "INSUFFICIENT_ENERGY")
        self.assertEqual((agent.agent_pair, agent.energy, agent.position), (original_pair, 10, "k:0:0"))
        self.assertEqual(agent.step(zero_frame(agent)).kind, "MOVE")
        finish(agent)
        self.assertEqual((agent.status, agent.energy, lanes(agent.agent_pair)[2]), ("COMPLETE", 0, 1))
        at_target = Tomigidt(FieldAgentManifest(initial_node="k:3:2", initial_energy=4))
        self.addCleanup(at_target.close)
        self.assertEqual(at_target.step(zero_frame(at_target)).kind, "INSUFFICIENT_ENERGY")
        self.assertEqual(at_target.energy, 4)

    def test_forecast_derivation_and_fifo_churn_do_not_admit_observations_or_change_history(self):
        reference = Tomigidt(FieldAgentManifest(), capacity=32)
        small = Tomigidt(FieldAgentManifest(), capacity=1)
        self.addCleanup(reference.close)
        self.addCleanup(small.close)
        scenario = mission_scenario()
        cycle = 0
        while reference.status != "COMPLETE":
            before = small.archive()
            saved_cache = cache_state(small.world)
            sample = small.world.derive("k:3:2")
            self.assertEqual(lanes(sample.pair), (0, 17, 1, 0))
            self.assertEqual(cache_state(small.world), saved_cache)
            for path in ("k:0:0", "k:1:0", "k:0:0", "k:3:2"):
                small.world.get(path)
            small.world.resize(1 if cycle % 2 == 0 else 2)
            self.assertEqual(small.archive(), before)
            frame = scenario.observe(reference.position, reference.cycle + 1)
            self.assertEqual(small.step(frame).to_dict(), reference.step(frame).to_dict())
            self.assertEqual(small.archive(), reference.archive())
            self.assertLessEqual(len(small.world.active_paths), small.world.capacity)
            self.assertEqual(set(small.snapshot()["observations"]),
                             set().union(*(event["input"] for event in small.events)))
            cycle += 1
        self.assertGreater(small.world.regeneration_count, 0)
        self.assertTrue(small.world.evicted_paths)
        self.assertEqual(reference.world.evicted_paths, ())


class FieldAgentPlanningTests(unittest.TestCase):
    def test_deferred_search_retains_energy_and_replays_before_continuation(self):
        agent = Tomigidt(FieldAgentManifest(max_search_expansions=1), capacity=1)
        self.addCleanup(agent.close)
        original_pair = agent.agent_pair
        first = agent.step(zero_frame(agent))
        second = agent.step(zero_frame(agent))
        self.assertEqual((first.kind, first.expansions, second.kind, second.expansions),
                         ("DEFER", 1, "DEFER", 2))
        planning = agent.snapshot()["planning"]
        self.assertEqual(planning["energy"], 100)
        self.assertEqual(planning["agent_pair"], f"{original_pair:016X}")
        self.assertEqual(agent.step({}).kind, "WAIT")
        self.assertEqual(agent.snapshot()["planning"], planning)
        restored = Tomigidt.from_archive(agent.archive(), capacity=32)
        self.addCleanup(restored.close)
        self.assertEqual(restored.archive(), agent.archive())
        for _ in range(128):
            frame = zero_frame(agent)
            decision = agent.step(frame)
            self.assertEqual(restored.step(frame).to_dict(), decision.to_dict())
            self.assertEqual(restored.archive(), agent.archive())
            if decision.kind == "MOVE":
                self.assertEqual(decision.route, ("k:0:4", "k:0:3", "k:3:2"))
                break
        else:
            self.fail("Retained finite search failed to produce movement")

    def test_changed_partial_observation_discards_stale_search_before_action(self):
        agent = Tomigidt(FieldAgentManifest(max_search_expansions=1))
        self.addCleanup(agent.close)
        agent.step(zero_frame(agent))
        agent.step(zero_frame(agent))
        before_pair, before_energy = agent.agent_pair, agent.energy
        waited = agent.step({"k:0:4": 70})
        self.assertEqual(waited.kind, "WAIT")
        self.assertIsNone(agent.snapshot()["planning"])
        self.assertEqual((agent.agent_pair, agent.energy), (before_pair, before_energy))
        frame = zero_frame(agent)
        frame["k:0:4"] = 70
        restarted = agent.step(frame)
        self.assertEqual((restarted.kind, restarted.expansions), ("DEFER", 1))
        self.assertEqual(agent.snapshot()["planning"]["weights"]["k:0:4"], 72)
        for _ in range(128):
            decision = agent.step(frame)
            if decision.kind == "MOVE":
                self.assertEqual(decision.route, ("k:3:0", "k:3:1", "k:3:2"))
                self.assertEqual(agent.position, "k:3:0")
                break
        else:
            self.fail("Changed-cost search failed to produce the revised route")

    def test_invalid_frame_preserves_retained_search_and_all_admitted_state(self):
        agent = Tomigidt(FieldAgentManifest(max_search_expansions=1), capacity=1)
        self.addCleanup(agent.close)
        agent.step(zero_frame(agent))
        before = agent.archive(), cache_state(agent.world)
        for frame in ({"k:3:2": 70}, {"k:0:4": True}, {"k:0:4": 128}, {"action": "REPAIR"}):
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                agent.step(frame)
            self.assertEqual((agent.archive(), cache_state(agent.world)), before)


class FieldAgentReplayTests(unittest.TestCase):
    def test_replay_from_recipe_after_every_cycle_matches_complete_reference(self):
        scenario = mission_scenario()
        uninterrupted = Tomigidt(scenario.manifest, capacity=32)
        interrupted = Tomigidt(scenario.manifest, capacity=1)
        self.addCleanup(uninterrupted.close)
        try:
            while uninterrupted.status != "COMPLETE":
                frame = scenario.observe(uninterrupted.position, uninterrupted.cycle + 1)
                self.assertEqual(interrupted.step(frame).to_dict(), uninterrupted.step(frame).to_dict())
                archived = json.loads(json.dumps(interrupted.archive()))
                self.assertEqual(set(archived["manifest"]["world"]), RECIPE_KEYS)
                interrupted.close()
                interrupted = Tomigidt.from_archive(archived, capacity=1 + uninterrupted.cycle % 3)
                self.assertEqual(interrupted.archive(), uninterrupted.archive())
        finally:
            interrupted.close()

    def test_each_energy_record_snapshot_and_retained_context_are_recomputed(self):
        agent = Tomigidt(FieldAgentManifest())
        self.addCleanup(agent.close)
        finish(agent, mission_scenario())
        original = agent.archive()
        changes = {
            "event energy": lambda a: a["events"][0].update(energy=99),
            "event float energy": lambda a: a["events"][0].update(energy=98.0),
            "event bool energy": lambda a: a["events"][0].update(energy=True),
            "event missing energy": lambda a: a["events"][0].pop("energy"),
            "event extra": lambda a: a["events"][0].update(field=0),
            "final energy": lambda a: a["expected"].update(energy=91),
            "initial energy": lambda a: a["manifest"].update(initial_energy=99),
            "word profile": lambda a: a["expected"].update(word_profile="RP32-v1"),
            "field used as energy": lambda a: a["events"][0].update(energy=-1),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            with self.subTest(change=label), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged)
        pending = Tomigidt(FieldAgentManifest(max_search_expansions=1))
        self.addCleanup(pending.close)
        pending.step(zero_frame(pending))
        damaged = pending.archive()
        damaged["expected"]["planning"]["energy"] = 99
        with self.assertRaises(ValueError):
            Tomigidt.from_archive(damaged)

    def test_changed_recipe_observation_forecast_and_valid_parity_field_forgery_fail_replay(self):
        agent = Tomigidt(FieldAgentManifest())
        self.addCleanup(agent.close)
        finish(agent, mission_scenario())
        original = agent.archive()
        changes = {
            "boundary": lambda a: a["manifest"]["world"].update(center=4),
            "radius": lambda a: a["manifest"]["world"].update(radius=3),
            "dimensions": lambda a: a["manifest"]["world"].update(width=5, height=4),
            "turn": lambda a: a["manifest"]["world"]["turns"].__setitem__(0, 12),
            "supplied field": lambda a: a["manifest"]["world"].update(fields=[0] * 20),
            "observation": lambda a: a["events"][1]["input"].__setitem__(
                "k:0:3", f"{word(0, 3, 0, 0):08X}"),
            "energy in B": lambda a: a["events"][0].update(output=f"{packed(5, 4, 98, 0):016X}"),
            "phase not reflected": lambda a: a["events"][1].update(output=f"{packed(16, 16, 0, 1):016X}"),
            "forecast": lambda a: a["events"][0]["decision"]["forecast"].__setitem__(
                1, f"{packed(16, 3, 1, 0):016X}"),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            with self.subTest(change=label), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged)

    def test_fresh_process_continues_same_recipe_observations_and_energy(self):
        scenario = mission_scenario()
        agent = Tomigidt(scenario.manifest)
        self.addCleanup(agent.close)
        agent.step(scenario.observe(agent.position, 1))
        paused = agent.archive()
        finish(agent, scenario)
        script = ("import json,sys\n"
                  "from solvefinite.tomigidt import Tomigidt\n"
                  "from solvefinite.session import Scenario\n"
                  "a=Tomigidt.from_archive(json.load(sys.stdin),capacity=1)\n"
                  "s=Scenario(a.manifest,changes=((2,'k:0:3',70),))\n"
                  "while a.status!='COMPLETE': a.step(s.observe(a.position,a.cycle+1))\n"
                  "json.dump(a.archive(),sys.stdout,sort_keys=True)\n")
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps(paused),
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), agent.archive())

    def test_legacy_agent_event_snapshot_and_fixtures_keep_their_schema(self):
        agent = Tomigidt(AgentManifest())
        self.addCleanup(agent.close)
        agent.step(zero_frame(agent))
        self.assertEqual(set(agent.events[0]), {"seq", "input", "decision", "output"})
        self.assertNotIn("energy", agent.snapshot())
        self.assertNotIn("word_profile", agent.snapshot())
        fixture = read_json(ROOT / "tests/fixtures/tomigidt_v1_default_session.json")
        restored = Tomigidt.from_archive(fixture["agent"], capacity=1)
        self.addCleanup(restored.close)
        self.assertEqual(restored.archive(), fixture["agent"])


class FieldAgentPersistenceTests(unittest.TestCase):
    def test_scenario_sessions_resume_across_capacities_and_reject_replacement_recipe(self):
        scenario = mission_scenario()
        self.assertEqual(Scenario.from_dict(scenario.to_dict()), scenario)
        with TemporaryDirectory(prefix="field-agent-session-") as directory:
            directory = Path(directory)
            scenario_path, path, control = (directory / name for name in ("scenario.json", "state.json", "control.json"))
            scenario_path.write_text(json.dumps(scenario.to_dict()), encoding="utf-8")
            run_session(control, capacity=32, scenario_path=scenario_path)
            first = run_session(path, steps=1, capacity=1, scenario_path=scenario_path)
            self.assertEqual(first["state"]["energy"], 98)
            self.assertEqual(first["state"]["position"], "k:0:4")
            resumed = run_session(path, steps=64, capacity=3)
            self.assertEqual((resumed["status"], resumed["state"]["energy"]), ("COMPLETE", 90))
            self.assertEqual(read_json(path), read_json(control))
            retained_scenario, agent = load_session(path, capacity=1)
            self.addCleanup(agent.close)
            self.assertEqual(retained_scenario, scenario)
            self.assertEqual(agent.energy, 90)
            before = path.read_bytes()
            changed = mission_scenario(replace(scenario.manifest, world=KleinFieldRecipe(center=4)))
            scenario_path.write_text(json.dumps(changed.to_dict()), encoding="utf-8")
            with self.assertRaises(ValueError):
                run_session(path, scenario_path=scenario_path)
            self.assertEqual(path.read_bytes(), before)

    def test_nondefault_start_survives_live_wait_duplicate_retry_and_reopen(self):
        manifest = FieldAgentManifest(initial_node="k:0:4")
        config = LiveConfig(manifest, producer="field-sensor", epoch=3)
        self.assertEqual(LiveConfig.from_dict(config.to_dict()), config)
        with TemporaryDirectory(prefix="field-agent-live-") as directory:
            path = Path(directory) / "live.json"
            with LiveSession(path, config=config, capacity=1) as session:
                ready = session.ready()
                self.assertEqual(ready["next"]["position"], "k:0:4")
                first_request = observe_request(ready, {"k:0:4": 0})
                waited = session.handle(first_request)
                self.assertEqual(waited["event"]["decision"]["kind"], "WAIT")
                self.assertEqual(waited["state"]["energy"], 100)
                second_request = observe_request(waited)
                moved = session.handle(second_request)
                self.assertEqual(moved["event"]["decision"]["kind"], "MOVE")
            before = path.read_bytes()
            with LiveSession(path, capacity=32) as reopened:
                self.assertTrue(reopened.ready()["restored"])
                duplicate = reopened.handle(first_request)
                self.assertTrue(duplicate["duplicate"])
                self.assertEqual(duplicate["event"], waited["event"])
                self.assertEqual(duplicate["state"], moved["state"])
                self.assertEqual(path.read_bytes(), before)
                response = reopened.handle(second_request)
                self.assertTrue(response["duplicate"])
                while response["next"] is not None:
                    response = reopened.handle(observe_request(response))
                self.assertEqual(response["state"]["status"], "COMPLETE")
            saved_config, agent = load_live(path, capacity=1)
            self.addCleanup(agent.close)
            self.assertEqual(saved_config, config)
            self.assertEqual(agent.snapshot(), response["state"])

    def test_live_rejects_supplied_recipe_replacement_without_altering_durable_state(self):
        config = LiveConfig(FieldAgentManifest())
        with TemporaryDirectory(prefix="field-agent-live-recipe-") as directory:
            path = Path(directory) / "live.json"
            with LiveSession(path, config=config) as session:
                session.handle(observe_request(session.ready()))
            before = path.read_bytes()
            changed = replace(config, manifest=replace(config.manifest, world=KleinFieldRecipe(center=4)))
            with self.assertRaises(ValueError):
                with LiveSession(path, config=changed):
                    self.fail("A replacement recipe was admitted for a retained session")
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
