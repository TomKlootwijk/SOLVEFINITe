"""Behavioral checks for TOMIGIDt's autonomous decisions and exact recovery.

The sensor helper exposes only the current location and outgoing neighbors.
No test supplies candidate routes or reads an environment on the agent's behalf.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.rp32 import Opcode, pack, unpack, unpair
from solvefinite.tomigidt import AgentManifest, Tomigidt
from solvefinite.world import WorldConfig


ROOT = Path(__file__).resolve().parent.parent


def zero_frame(agent):
    graph = dict(agent.manifest.graph)
    return {path: 0 for path in (agent.position, *graph[agent.position])}


def hazard_frame(agent):
    frame = zero_frame(agent)
    if "00" in frame:
        frame["00"] = 70
    return frame


def energy(agent):
    return unpack(unpair(agent.agent_pair)[0])[2]


def cache_state(agent):
    return (agent.world.active_paths, agent.world.evicted_paths,
            agent.world.hit_count, agent.world.regeneration_count)


def finish(agent, sensor=zero_frame):
    decisions = []
    for _ in range(32):
        if agent.status == "COMPLETE":
            return decisions
        decisions.append(agent.step(sensor(agent)))
    raise AssertionError("Agent failed to finish the finite test mission")


class AutonomousBehaviorTests(unittest.TestCase):
    def test_chooses_and_executes_one_legal_edge_toward_its_own_goal(self):
        agent = Tomigidt()
        self.assertEqual((agent.identity, agent.position, agent.cycle, agent.status),
                         ("TOMIGIDt", "", 0, "ACTIVE"))
        graph = dict(agent.manifest.graph)
        visited = [agent.position]
        decisions = []
        while agent.status != "COMPLETE":
            previous = agent.position
            before_energy = energy(agent)
            decision = agent.step(zero_frame(agent))
            decisions.append(decision)
            self.assertEqual(agent.cycle, len(decisions))
            self.assertTrue(decision.reason)
            self.assertIs(type(decision.cost), int)
            self.assertIs(type(decision.expansions), int)
            unpair(agent.agent_pair)
            if decision.kind == "MOVE":
                self.assertEqual(decision.expected_pair, agent.agent_pair)
                self.assertIn(agent.position, graph[previous])
                self.assertEqual(agent.position, decision.route[0])
                self.assertEqual(decision.route[-1], agent.manifest.target)
                self.assertLess(energy(agent), before_energy)
                for source, destination in zip((previous, *decision.route), decision.route):
                    self.assertIn(destination, graph[source])
                visited.append(agent.position)
            else:
                self.assertEqual(decision.kind, "REPAIR")
                self.assertEqual(decision.expected_pair, agent.agent_pair)
                self.assertEqual(previous, agent.manifest.target)
                self.assertEqual(agent.position, previous)
                self.assertEqual(before_energy - energy(agent), agent.manifest.repair_cost)
            self.assertLess(len(decisions), 16)
        self.assertEqual(visited, ["", "0", "00", "11"])
        self.assertEqual([decision.kind for decision in decisions],
                         ["MOVE", "MOVE", "MOVE", "REPAIR"])
        self.assertEqual(energy(agent), 86)
        self.assertEqual(unpack(unpair(agent.agent_pair)[0])[3] & 7, Opcode.EMIT)
        with self.assertRaises(FrozenInstanceError):
            decisions[0].kind = "REPAIR"

    def test_fresh_hazard_causes_replanning_and_backtracking(self):
        agent = Tomigidt()
        first = agent.step(zero_frame(agent))
        self.assertEqual(first.route, ("0", "00", "11"))
        self.assertEqual(agent.position, "0")
        second = agent.step(hazard_frame(agent))
        self.assertEqual(second.kind, "MOVE")
        self.assertEqual(second.route, ("", "1", "10", "11"))
        self.assertEqual(agent.position, "")
        # The costly node is now out of view, but the admitted observation
        # must still influence future planning.
        third = agent.step(zero_frame(agent))
        self.assertEqual(third.route, ("1", "10", "11"))
        self.assertEqual(agent.position, "1")
        finish(agent)
        self.assertEqual(agent.position, "11")
        self.assertEqual(agent.status, "COMPLETE")

    def test_entire_packed_forecast_matches_execution_with_unchanged_measurements(self):
        agent = Tomigidt(capacity=8)
        original_energy = energy(agent)
        first = agent.step(zero_frame(agent))
        self.assertIs(type(first.forecast), tuple)
        self.assertEqual(len(first.forecast), len(first.route))
        self.assertEqual(first.forecast[0], first.expected_pair)
        self.assertEqual(agent.agent_pair, first.forecast[0])
        for value in first.forecast:
            unpair(value)
        self.assertEqual(original_energy - unpack(unpair(first.forecast[-1])[0])[2], first.cost)
        for offset in range(1, len(first.forecast)):
            decision = agent.step(zero_frame(agent))
            self.assertEqual(decision.kind, "MOVE")
            self.assertEqual(decision.forecast, first.forecast[offset:])
            self.assertEqual(agent.agent_pair, first.forecast[offset])
        before_repair = agent.agent_pair
        self.assertEqual(agent.step(zero_frame(agent)).kind, "REPAIR")
        self.assertNotEqual(agent.agent_pair, before_repair)
        self.assertEqual(agent.status, "COMPLETE")

    def test_new_measurements_replace_stale_forecast_before_acting(self):
        agent = Tomigidt()
        original = agent.step(zero_frame(agent))
        revised = agent.step(hazard_frame(agent))
        self.assertEqual(agent.position, "")
        self.assertEqual(revised.route, ("", "1", "10", "11"))
        self.assertEqual(revised.expected_pair, revised.forecast[0])
        self.assertEqual(agent.agent_pair, revised.forecast[0])
        self.assertNotEqual(agent.agent_pair, original.forecast[1])
        for offset in range(1, len(revised.forecast)):
            decision = agent.step(zero_frame(agent))
            self.assertEqual(decision.forecast, revised.forecast[offset:])
            self.assertEqual(agent.agent_pair, revised.forecast[offset])

    def test_forecasting_does_not_cache_or_record_unobserved_world_nodes(self):
        agent = Tomigidt(capacity=8)
        frame = zero_frame(agent)
        first = agent.step(frame)
        self.assertIn("00", first.route)
        self.assertIn("11", first.route)
        self.assertEqual(set(agent.world.active_paths), set(frame))
        self.assertEqual(agent.world.evicted_paths, ())
        self.assertEqual(agent.world.hit_count, 0)
        self.assertEqual(set(agent.snapshot()["observations"]), set(frame))

    def test_footprint_tracks_persistent_identity_sequence_and_derivation(self):
        manifest = AgentManifest(identity="TOMIGIDt-test",
                                 world=WorldConfig(baseline_id="test-baseline"))
        agent = Tomigidt(manifest)
        for cycle in range(5):
            expected = {"profile": "tomigidt-agent-v1", "baseline": "test-baseline",
                        "agent": "TOMIGIDt-test", "epoch": 0,
                        "sequence": cycle, "derivation": agent.position}
            self.assertEqual(agent.snapshot()["footprint"], expected)
            restored = Tomigidt.from_archive(agent.archive(), capacity=1)
            self.assertEqual(restored.snapshot()["footprint"], expected)
            if agent.status == "COMPLETE":
                break
            agent.step(zero_frame(agent))
        self.assertEqual(agent.status, "COMPLETE")

    def test_partial_measurements_wait_without_combining_stale_frames(self):
        agent = Tomigidt()
        original_pair = agent.agent_pair
        first = agent.step({"": 0, "0": 0})
        self.assertEqual((first.kind, agent.status, agent.cycle), ("WAIT", "WAITING", 1))
        self.assertEqual((agent.position, agent.agent_pair), ("", original_pair))
        second = agent.step({"1": 0})
        self.assertEqual((second.kind, agent.status, agent.cycle), ("WAIT", "WAITING", 2))
        self.assertEqual((agent.position, agent.agent_pair), ("", original_pair))
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.position, agent.status), ("MOVE", "0", "ACTIVE"))

    def test_each_action_needs_current_frame_even_with_retained_observations(self):
        agent = Tomigidt()
        agent.step(zero_frame(agent))
        agent.step(zero_frame(agent))
        self.assertEqual(agent.position, "00")
        previous = (agent.position, agent.agent_pair)
        decision = agent.step({"00": 0, "11": 0})
        self.assertEqual((decision.kind, agent.status), ("WAIT", "WAITING"))
        self.assertEqual((agent.position, agent.agent_pair), previous)
        self.assertEqual(agent.step(zero_frame(agent)).kind, "MOVE")

    def test_root_goal_repairs_only_after_receiving_complete_local_frame(self):
        agent = Tomigidt(AgentManifest(target=""))
        self.assertEqual(agent.step({}).kind, "WAIT")
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.status, agent.position),
                         ("REPAIR", "COMPLETE", ""))
        self.assertEqual(energy(agent), 95)

    def test_complete_agent_rejects_new_input_without_state_changes(self):
        agent = Tomigidt()
        finish(agent)
        before = (agent.archive(), cache_state(agent))
        with self.assertRaises(ValueError):
            agent.step(zero_frame(agent))
        self.assertEqual((agent.archive(), cache_state(agent)), before)

    def test_cycle_budget_exhaustion_is_atomic_and_survives_restore(self):
        for wait_first in (False, True):
            with self.subTest(wait_first=wait_first):
                agent = Tomigidt(AgentManifest(max_cycles=1))
                agent.step({} if wait_first else zero_frame(agent))
                agent = Tomigidt.from_archive(agent.archive())
                before = (agent.archive(), cache_state(agent))
                with self.assertRaisesRegex(ValueError, "cycle budget"):
                    agent.step(zero_frame(agent))
                self.assertEqual((agent.archive(), cache_state(agent)), before)

    def test_entire_route_and_repair_must_fit_energy_before_first_move(self):
        # Default derivation gives entry costs 3, 2, 4 plus repair cost 5.
        agent = Tomigidt(AgentManifest(agent_seed=(250, 3, 13, 1)))
        before = (agent.position, agent.agent_pair)
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.status),
                         ("INSUFFICIENT_ENERGY", "INSUFFICIENT_ENERGY"))
        self.assertEqual((agent.position, agent.agent_pair), before)
        sufficient = Tomigidt(AgentManifest(agent_seed=(250, 3, 14, 1)))
        finish(sufficient)
        self.assertEqual((sufficient.status, energy(sufficient)), ("COMPLETE", 0))

    def test_insufficient_repair_energy_at_goal_cannot_complete(self):
        agent = Tomigidt(AgentManifest(target="", agent_seed=(250, 3, 4, 1)))
        before = agent.agent_pair
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.status),
                         ("INSUFFICIENT_ENERGY", "INSUFFICIENT_ENERGY"))
        self.assertEqual(agent.agent_pair, before)

    def test_disconnected_goal_is_explicitly_unreachable(self):
        manifest = AgentManifest(graph=(("", ("0",)), ("0", ("",)), ("11", ())))
        agent = Tomigidt(manifest)
        before = agent.agent_pair
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.status, agent.position),
                         ("UNREACHABLE", "UNREACHABLE", ""))
        self.assertEqual(agent.agent_pair, before)

    def test_bounded_search_defers_instead_of_claiming_no_route(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        before = agent.agent_pair
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, agent.status, agent.position),
                         ("DEFER", "SEARCH_DEFERRED", ""))
        self.assertEqual(decision.expansions, 1)
        self.assertEqual(agent.agent_pair, before)

    def test_cache_capacity_and_incidental_cache_eviction_do_not_change_decisions(self):
        reference = Tomigidt(capacity=1)
        decisions = finish(reference, hazard_frame)
        for capacity in (2, 8):
            with self.subTest(capacity=capacity):
                agent = Tomigidt(capacity=capacity)
                actual = []
                for expected in decisions:
                    agent.world.get("111")
                    agent.world.get("000")
                    agent.world.resize(capacity)
                    actual.append(agent.step(hazard_frame(agent)))
                    self.assertEqual(actual[-1], expected)
                self.assertEqual(agent.archive(), reference.archive())


class AutonomousValidationTests(unittest.TestCase):
    def test_invalid_measurements_are_rejected_atomically(self):
        agent = Tomigidt()
        invalid = [None, [], (), "", {"0": -1}, {"0": 128}, {"0": True},
                   {"0": 1.0}, {"0": "1"}, {"0": None}, {0: 0},
                   {"2": 0}, {"00": 0}, {"11": 0}, {"": 0, "0": 0, "1": 0, "10": 1}]
        before = (agent.archive(), cache_state(agent))
        for frame in invalid:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                agent.step(frame)
            self.assertEqual((agent.archive(), cache_state(agent)), before)

    def test_out_of_view_observation_rejected_after_moving(self):
        agent = Tomigidt()
        agent.step(zero_frame(agent))
        self.assertEqual(agent.position, "0")
        before = agent.archive()
        frame = zero_frame(agent)
        frame["1"] = 127
        with self.assertRaises(ValueError):
            agent.step(frame)
        self.assertEqual(agent.archive(), before)

    def test_manifest_is_frozen_and_has_strict_round_trip(self):
        manifest = AgentManifest()
        self.assertEqual(AgentManifest.from_dict(manifest.to_dict()), manifest)
        with self.assertRaises(FrozenInstanceError):
            manifest.target = "0"
        encoded = manifest.to_dict()
        for key in encoded:
            invalid = deepcopy(encoded)
            del invalid[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                AgentManifest.from_dict(invalid)
        encoded["unknown"] = True
        with self.assertRaises(ValueError):
            AgentManifest.from_dict(encoded)
        for malformed in ([], None, "", {}):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                AgentManifest.from_dict(malformed)

    def test_invalid_manifest_values_rejected(self):
        invalid = [
            {"identity": ""}, {"identity": None}, {"identity": True},
            {"target": "2"}, {"target": None}, {"target": "111111111"},
            {"world": {}}, {"agent_seed": [250, 3, 100, 1]},
            {"agent_seed": (250, 3, -1, 1)}, {"agent_seed": (250, 3, True, 1)},
            {"agent_seed": (250, 3, 100, 0)},
            {"repair_cost": 0}, {"repair_cost": 128}, {"repair_cost": True},
            {"max_search_expansions": 0}, {"max_search_expansions": True},
            {"max_cycles": 0}, {"max_cycles": True},
            {"graph": ()}, {"graph": (("", ("missing",)), ("11", ()))},
            {"graph": (("", ()), ("", ()), ("11", ()))},
            {"graph": (("0", ()), ("11", ()))},
            {"graph": (("", ()),)},
        ]
        for parameters in invalid:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                AgentManifest(**parameters)

    def test_input_manifest_encoding_events_and_snapshots_are_independent_copies(self):
        manifest = AgentManifest(world=WorldConfig())
        encoded = manifest.to_dict()
        encoded["world"]["seed"][0] = 0
        encoded["agent_seed"][2] = 1
        encoded["graph"][""].clear()
        self.assertEqual(manifest.world.seed[0], 250)
        self.assertEqual(manifest.agent_seed[2], 100)
        self.assertEqual(dict(manifest.graph)[""], ("0", "1"))
        agent = Tomigidt(manifest)
        frame = zero_frame(agent)
        agent.step(frame)
        original = agent.archive()
        frame["0"] = 127
        frame["hidden"] = 127
        events = agent.events
        events[0].clear()
        events.append({"new": "event"})
        snapshot = agent.snapshot()
        snapshot.clear()
        archive = agent.archive()
        archive["manifest"]["world"]["seed"][0] = 0
        archive["events"].clear()
        archive["expected"].clear()
        self.assertEqual(agent.archive(), original)

    def test_manifest_json_bindings_and_collection_shapes_are_strict(self):
        original = AgentManifest().to_dict()
        invalid_fields = [
            ("policy", "future-policy"), ("perspective", "omniscient"),
            ("word_profile", "RP64"), ("agent_seed", tuple(original["agent_seed"])),
            ("graph", list(original["graph"].items())),
            ("graph", {"": (), "11": []}),
            ("graph", {"": ["11", "11"], "11": []}),
            ("max_search_expansions", 1.0), ("max_cycles", "10000"),
        ]
        for field, value in invalid_fields:
            changed = deepcopy(original)
            changed[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                AgentManifest.from_dict(changed)


class AutonomousRecoveryTests(unittest.TestCase):
    def test_repeated_interruption_replays_each_decision_and_completed_state(self):
        reference = Tomigidt(capacity=8)
        resumed = Tomigidt(capacity=1)
        for index in range(16):
            decision = reference.step(hazard_frame(reference))
            self.assertEqual(resumed.step(hazard_frame(resumed)), decision)
            self.assertEqual(resumed.archive(), reference.archive())
            resumed = Tomigidt.from_archive(resumed.archive(), capacity=1 + index % 3)
            self.assertEqual(resumed.archive(), reference.archive())
            if reference.status == "COMPLETE":
                break
        self.assertEqual(reference.status, "COMPLETE")
        self.assertEqual(resumed.status, "COMPLETE")

    def test_wait_and_nonacting_planner_outcomes_replay(self):
        agents = [Tomigidt(), Tomigidt(AgentManifest(max_search_expansions=1)),
                  Tomigidt(AgentManifest(agent_seed=(250, 3, 0, 1))),
                  Tomigidt(AgentManifest(graph=(("", ()), ("11", ()))))]
        for index, agent in enumerate(agents):
            agent.step({} if index == 0 else zero_frame(agent))
            with self.subTest(status=agent.status):
                restored = Tomigidt.from_archive(agent.archive(), capacity=1)
                self.assertEqual(restored.archive(), agent.archive())

    def test_save_and_load_in_fresh_process_then_continue_exactly(self):
        agent = Tomigidt()
        agent.step(zero_frame(agent))
        agent.step(hazard_frame(agent))
        with TemporaryDirectory(prefix="tomigidt-") as directory:
            checkpoint = Path(directory) / "agent checkpoint.json"
            completed = Path(directory) / "agent complete.json"
            agent.save(checkpoint)
            self.assertEqual(json.loads(checkpoint.read_text(encoding="utf-8")), agent.archive())
            script = "\n".join([
                "import sys",
                "from solvefinite.tomigidt import Tomigidt",
                "agent = Tomigidt.load(sys.argv[1], capacity=1)",
                "for _ in range(32):",
                "    if agent.status == 'COMPLETE': break",
                "    graph = dict(agent.manifest.graph)",
                "    frame = {p: (70 if p == '00' else 0) for p in (agent.position, *graph[agent.position])}",
                "    agent.step(frame)",
                "assert agent.status == 'COMPLETE'",
                "agent.save(sys.argv[2])",
            ])
            result = subprocess.run([sys.executable, "-c", script, str(checkpoint), str(completed)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            finish(agent, hazard_frame)
            restored = Tomigidt.load(completed, capacity=8)
            self.assertEqual(restored.archive(), agent.archive())

    def test_archive_schema_history_and_expected_state_are_verified(self):
        agent = Tomigidt()
        finish(agent, hazard_frame)
        archive = agent.archive()
        self.assertEqual(archive["format"], "tomigidt-agent-v1")
        self.assertEqual(set(archive), {"format", "manifest", "events", "expected"})
        changes = {
            "wrong format": lambda a: a.update(format="future-agent"),
            "missing manifest": lambda a: a.pop("manifest"),
            "extra field": lambda a: a.update(extra=True),
            "missing events": lambda a: a.pop("events"),
            "non-array events": lambda a: a.update(events={}),
            "malformed event": lambda a: a["events"].__setitem__(0, None),
            "missing initial event": lambda a: a["events"].pop(0),
            "missing final event": lambda a: a["events"].pop(),
            "duplicated event": lambda a: a["events"].append(deepcopy(a["events"][-1])),
            "reordered history": lambda a: a["events"].reverse(),
            "extra event field": lambda a: a["events"][0].update(extra=True),
            "changed baseline": lambda a: a["manifest"]["world"]["seed"].__setitem__(0, 1),
            "wrong expected pair": lambda a: a["expected"].update(agent_pair="0000000000000000"),
            "empty expected": lambda a: a["expected"].clear(),
            "boolean cycle": lambda a: a["expected"].update(cycle=True),
            "extra expected field": lambda a: a["expected"].update(extra=True),
            "forged footprint agent": lambda a: a["expected"]["footprint"].update(agent="different-agent"),
            "forged footprint derivation": lambda a: a["expected"]["footprint"].update(derivation="0"),
            "forged footprint sequence": lambda a: a["expected"]["footprint"].update(sequence=0),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(archive)
            mutate(damaged)
            with self.subTest(case=label), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged)

    def test_duplicate_json_fields_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"format":"a","format":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                Tomigidt.load(path)

    def test_replay_recomputes_admitted_packets_decisions_and_output(self):
        agent = Tomigidt()
        agent.step(zero_frame(agent))
        agent.step(hazard_frame(agent))
        archive = agent.archive()
        original_word = int(archive["events"][0]["input"]["0"], 16)
        r, g, b, opcode = unpack(original_word)
        mutations = {
            "negative original hazard": lambda a: a["events"][0]["input"].update(
                {"0": f"{pack(r, g, -1, opcode):08X}"}),
            "observation changes selected route": lambda a: a["events"][0]["input"].update(
                {"0": f"{pack(r, g, 70, opcode):08X}"}),
            "wrong coordinate valid parity": lambda a: a["events"][0]["input"].update(
                {"0": f"{pack(r ^ 1, g, b, opcode):08X}"}),
            "wrong packet opcode": lambda a: a["events"][0]["input"].update(
                {"0": f"{pack(r, g, b, Opcode.STEP):08X}"}),
            "invalid packet parity": lambda a: a["events"][0]["input"].update(
                {"0": f"{original_word ^ 1:08X}"}),
            "oversized packet": lambda a: a["events"][0]["input"].update({"0": "000000000"}),
            "nonhex packet": lambda a: a["events"][0]["input"].update({"0": "ZZZZZZZZ"}),
            "integer packet": lambda a: a["events"][0]["input"].update({"0": original_word}),
            "out of view historical input": lambda a: a["events"][0]["input"].update(
                {"11": f"{original_word:08X}"}),
            "missing required historical measurement": lambda a: a["events"][0]["input"].pop("1"),
            "wrong sequence": lambda a: a["events"][1].update(seq=99),
            "boolean sequence": lambda a: a["events"][0].update(seq=True),
            "forged alternative legal route": lambda a: a["events"][0]["decision"].update(
                route=["1", "10", "11"]),
            "forged action": lambda a: a["events"][0]["decision"].update(kind="REPAIR"),
            "forged cost": lambda a: a["events"][0]["decision"].update(cost=0),
            "forged expected movement": lambda a: a["events"][0]["decision"].update(
                expected_pair="0000000000000000"),
            "forged expansion count": lambda a: a["events"][0]["decision"].update(expansions=999),
            "forged future packed state": lambda a: a["events"][0]["decision"]["forecast"].__setitem__(
                1, "0000000000000000"),
            "missing future packed state": lambda a: a["events"][0]["decision"]["forecast"].pop(),
            "missing decision": lambda a: a["events"][0].pop("decision"),
            "extra decision field": lambda a: a["events"][0]["decision"].update(extra=True),
            "invalid decision shape": lambda a: a["events"][0].update(decision=[]),
            "forged executed output": lambda a: a["events"][0].update(output="0000000000000000"),
        }
        for label, mutate in mutations.items():
            damaged = deepcopy(archive)
            mutate(damaged)
            with self.subTest(case=label), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged)


if __name__ == "__main__":
    unittest.main()
