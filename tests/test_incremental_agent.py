"""Incremental search survives cycles/processes without rewriting v1 history."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from solvefinite.rp32 import unpack, unpair
from solvefinite.session import Scenario, load_session, run_session
from solvefinite.tomigidt import AgentManifest, Tomigidt


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
LEGACY_POLICY = "tomigidt-observe-plan-act-v1"
INCREMENTAL_POLICY = "tomigidt-observe-plan-act-v2"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def zero_frame(agent):
    return {path: 0 for path in agent.visible_paths}


def cache_state(agent):
    world = agent.world
    return (world.active_paths, world.evicted_paths, world.hit_count,
            world.regeneration_count)


def run_cli(*arguments):
    result = subprocess.run(
        [sys.executable, "-m", "solvefinite", *(str(argument) for argument in arguments)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    if result.returncode:
        raise AssertionError(f"CLI failed with {result.returncode}: {result.stderr}")
    if result.stderr:
        raise AssertionError(f"Unexpected CLI diagnostic: {result.stderr}")
    return json.loads(result.stdout)


class LegacyPolicyCompatibilityTests(unittest.TestCase):
    def test_frozen_v1_sessions_replay_to_the_identical_archive(self):
        for name in ("tomigidt_v1_default_session.json", "tomigidt_v1_deferred_session.json"):
            path = FIXTURES / name
            original = read_json(path)
            self.assertEqual(original["agent"]["manifest"]["policy"], LEGACY_POLICY)
            self.assertNotIn("planning", original["agent"]["expected"])
            for capacity in (1, 8):
                with self.subTest(fixture=name, capacity=capacity):
                    scenario, agent = load_session(path, capacity)
                    self.assertEqual(scenario.to_dict(), original["scenario"])
                    self.assertEqual(agent.archive(), original["agent"])
                    self.assertEqual(agent.manifest.policy, LEGACY_POLICY)

    def test_v1_search_retries_keep_resetting_instead_of_gaining_v2_cursor(self):
        original = read_json(FIXTURES / "tomigidt_v1_deferred_session.json")
        agent = Tomigidt.from_archive(original["agent"])
        old_decision = original["agent"]["events"][-1]["decision"]
        original_pair = agent.agent_pair
        for cycle in range(3, 6):
            decision = agent.step(zero_frame(agent))
            self.assertEqual(decision.to_dict(), old_decision)
            self.assertEqual(decision.expansions, 1)
            self.assertEqual((agent.cycle, agent.status, agent.position, agent.agent_pair),
                             (cycle, "SEARCH_DEFERRED", "", original_pair))
            self.assertNotIn("planning", agent.snapshot())
            agent = Tomigidt.from_archive(agent.archive(), capacity=1)

    def test_v1_runner_stops_each_invocation_after_one_deferred_retry(self):
        fixture = FIXTURES / "tomigidt_v1_deferred_session.json"
        with TemporaryDirectory(prefix="tomigidt-v1-") as directory:
            path = Path(directory) / "legacy session.json"
            shutil.copyfile(fixture, path)
            for cycle in (3, 4):
                summary = run_session(path, steps=64, capacity=1)
                self.assertEqual(summary["executed_cycles"], 1)
                self.assertEqual(summary["cycle"], cycle)
                self.assertEqual(summary["stop_reason"], "SEARCH_DEFERRED")
                self.assertEqual(summary["decisions"][0]["expansions"], 1)
                self.assertNotIn("planning", summary["state"])

    def test_v1_wait_fixture_keeps_fresh_frame_semantics(self):
        original = read_json(FIXTURES / "tomigidt_v1_waiting_agent.json")
        agent = Tomigidt.from_archive(original)
        self.assertEqual(agent.archive(), original)
        self.assertEqual(agent.step({"1": 0}).kind, "WAIT")
        self.assertEqual(agent.position, "")
        self.assertEqual(agent.step(zero_frame(agent)).kind, "MOVE")
        self.assertEqual(agent.position, "0")
        self.assertNotIn("planning", agent.snapshot())


class IncrementalPolicyBehaviorTests(unittest.TestCase):
    def test_default_manifest_binds_new_policy_and_round_trips_old_policy(self):
        self.assertEqual(AgentManifest().policy, INCREMENTAL_POLICY)
        for policy in (LEGACY_POLICY, INCREMENTAL_POLICY):
            with self.subTest(policy=policy):
                manifest = AgentManifest(policy=policy)
                self.assertEqual(manifest.to_dict()["policy"], policy)
                self.assertEqual(AgentManifest.from_dict(manifest.to_dict()), manifest)
        for invalid in (None, True, "tomigidt-observe-plan-act-v999"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                AgentManifest(policy=invalid)

    def test_quantum_one_search_accumulates_until_it_can_move_and_complete(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        previous_expansions = 0
        moves = []
        saw_defer = False
        for _ in range(128):
            before = (agent.position, agent.agent_pair)
            decision = agent.step(zero_frame(agent))
            planning = agent.snapshot()["planning"]
            if decision.kind == "DEFER":
                saw_defer = True
                self.assertEqual((agent.position, agent.agent_pair), before)
                self.assertEqual(decision.expansions, previous_expansions + 1)
                self.assertEqual(planning["expansions"], decision.expansions)
                self.assertEqual(planning["position"], agent.position)
                self.assertEqual(planning["target"], agent.manifest.target)
                self.assertEqual(planning["agent_pair"], f"{agent.agent_pair:016X}")
                self.assertIs(type(planning["pending_states"]), int)
                self.assertGreater(planning["pending_states"], 0)
                previous_expansions = decision.expansions
            elif decision.kind == "MOVE":
                self.assertIsNone(planning)
                self.assertIn(decision.expansions,
                              (previous_expansions, previous_expansions + 1))
                self.assertEqual(agent.agent_pair, decision.forecast[0])
                moves.append(agent.position)
                previous_expansions = 0
            else:
                self.assertEqual(decision.kind, "REPAIR")
                self.assertIsNone(planning)
                break
        self.assertTrue(saw_defer)
        self.assertEqual((agent.status, moves), ("COMPLETE", ["0", "00", "11"]))
        self.assertEqual(unpack(unpair(agent.agent_pair)[0])[2], 86)

    def test_changed_known_hazard_discards_cursor_and_selects_new_route(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        first = agent.step(zero_frame(agent))
        self.assertEqual(first.kind, "DEFER")
        second = agent.step(zero_frame(agent))
        self.assertEqual(second.kind, "DEFER")
        self.assertEqual(second.expansions, 2)
        old_planning = agent.snapshot()["planning"]
        before = (agent.position, agent.agent_pair)
        frame = zero_frame(agent)
        frame["0"] = 70
        revised = agent.step(frame)
        self.assertEqual((revised.kind, revised.expansions), ("DEFER", 1))
        self.assertEqual((agent.position, agent.agent_pair), before)
        self.assertNotEqual(agent.snapshot()["planning"]["weights"], old_planning["weights"])
        self.assertEqual(agent.snapshot()["planning"]["weights"]["0"], 73)
        for _ in range(64):
            decision = agent.step(frame)
            if decision.kind == "MOVE":
                break
            self.assertEqual(decision.kind, "DEFER")
        self.assertEqual((decision.kind, agent.position), ("MOVE", "1"))
        self.assertEqual(decision.route, ("1", "10", "11"))
        self.assertEqual(decision.cost, 11)

    def test_wait_preserves_search_without_expanding_and_resume_continues(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        first = agent.step(zero_frame(agent))
        before_planning = deepcopy(agent.snapshot()["planning"])
        before_pair = agent.agent_pair
        waited = agent.step({})
        self.assertEqual(waited.kind, "WAIT")
        self.assertEqual(agent.agent_pair, before_pair)
        self.assertEqual(agent.snapshot()["planning"], before_planning)
        restored = Tomigidt.from_archive(agent.archive(), capacity=8)
        self.assertEqual(restored.archive(), agent.archive())
        resumed = restored.step(zero_frame(restored))
        self.assertEqual(resumed.kind, "DEFER")
        self.assertEqual(resumed.expansions, first.expansions + 1)

    def test_changed_partial_frame_clears_stale_cursor_without_searching(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        agent.step(zero_frame(agent))
        agent.step(zero_frame(agent))
        self.assertTrue(agent.pending_search)
        original_pair = agent.agent_pair
        waited = agent.step({"0": 70})
        self.assertEqual(waited.kind, "WAIT")
        self.assertEqual((agent.position, agent.agent_pair), ("", original_pair))
        self.assertIsNone(agent.snapshot()["planning"])
        self.assertFalse(agent.pending_search)
        frame = zero_frame(agent)
        frame["0"] = 70
        restarted = agent.step(frame)
        self.assertEqual((restarted.kind, restarted.expansions), ("DEFER", 1))

    def test_measurement_change_on_would_finish_cycle_prevents_stale_action(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        for _ in range(64):
            would_be = Tomigidt.from_archive(agent.archive())
            original_decision = would_be.step(zero_frame(would_be))
            if original_decision.kind == "MOVE":
                break
            self.assertEqual(original_decision.kind, "DEFER")
            agent = would_be
        self.assertEqual((original_decision.kind, would_be.position), ("MOVE", "0"))
        self.assertTrue(agent.pending_search)
        original_pair = agent.agent_pair
        changed = zero_frame(agent)
        changed["0"] = 70
        revised = agent.step(changed)
        self.assertEqual((revised.kind, revised.expansions), ("DEFER", 1))
        self.assertEqual((agent.position, agent.agent_pair), ("", original_pair))
        for _ in range(64):
            decision = agent.step(changed)
            if decision.kind == "MOVE":
                break
        self.assertEqual((decision.kind, agent.position), ("MOVE", "1"))

    def test_hop_limit_defer_has_no_cursor_and_runner_does_not_spin(self):
        nodes = ("", *(format(number, "06b") for number in range(1, 34)))
        graph = tuple((node, (nodes[index + 1],) if index + 1 < len(nodes) else ())
                      for index, node in enumerate(nodes))
        manifest = AgentManifest(graph=graph, target=nodes[-1], max_search_expansions=1)
        agent = Tomigidt(manifest)
        original_pair = agent.agent_pair
        decision = agent.step(zero_frame(agent))
        self.assertEqual((decision.kind, decision.expansions), ("DEFER", 0))
        self.assertEqual((agent.position, agent.agent_pair), ("", original_pair))
        self.assertIsNone(agent.snapshot()["planning"])
        self.assertFalse(agent.pending_search)
        with TemporaryDirectory(prefix="tomigidt-hop-limit-") as directory:
            scenario_path = Path(directory) / "scenario.json"
            state_path = Path(directory) / "session.json"
            scenario_path.write_text(json.dumps(Scenario(manifest, changes=()).to_dict()), encoding="utf-8")
            summary = run_session(state_path, steps=64, scenario_path=scenario_path)
            self.assertEqual(summary["executed_cycles"], 1)
            self.assertEqual(summary["stop_reason"], "SEARCH_DEFERRED")
            self.assertIsNone(summary["state"]["planning"])

    def test_runner_step_budget_preserves_pending_search_for_next_invocation(self):
        with TemporaryDirectory(prefix="tomigidt-step-budget-") as directory:
            scenario_path = Path(directory) / "scenario.json"
            state_path = Path(directory) / "session.json"
            scenario = Scenario(manifest=AgentManifest(max_search_expansions=1), changes=())
            scenario_path.write_text(json.dumps(scenario.to_dict()), encoding="utf-8")
            first = run_session(state_path, steps=1, scenario_path=scenario_path)
            self.assertEqual(first["stop_reason"], "STEP_BUDGET_EXHAUSTED")
            self.assertEqual(first["status"], "SEARCH_DEFERRED")
            self.assertEqual(first["state"]["planning"]["expansions"], 1)
            second = run_session(state_path, steps=1)
            self.assertEqual(second["stop_reason"], "STEP_BUDGET_EXHAUSTED")
            self.assertEqual(second["state"]["planning"]["expansions"], 2)

    def test_failed_cycle_write_preserves_durable_cursor_and_exact_continuation(self):
        with TemporaryDirectory(prefix="tomigidt-write-failure-") as directory:
            output = Path(directory)
            scenario_path = output / "scenario.json"
            state_path = output / "interrupted session.json"
            control_path = output / "control session.json"
            scenario = Scenario(manifest=AgentManifest(max_search_expansions=1), changes=())
            scenario_path.write_text(json.dumps(scenario.to_dict()), encoding="utf-8")
            initial = run_session(state_path, steps=2, scenario_path=scenario_path)
            self.assertEqual(initial["cycle"], 2)
            self.assertEqual(initial["state"]["planning"]["expansions"], 2)
            durable_bytes = state_path.read_bytes()
            durable_archive = read_json(state_path)
            with patch("solvefinite.session.write_json", side_effect=OSError("simulated archive write failure")) as writer:
                with self.assertRaisesRegex(OSError, "simulated archive write failure"):
                    run_session(state_path, steps=128)
                writer.assert_called_once()
                attempted = writer.call_args.args[1]
                self.assertEqual(attempted["agent"]["expected"]["cycle"], 3)
                self.assertEqual(attempted["agent"]["expected"]["planning"]["expansions"], 3)
            self.assertEqual(state_path.read_bytes(), durable_bytes)
            _, restored = load_session(state_path, capacity=1)
            self.assertEqual(restored.archive(), durable_archive["agent"])
            self.assertEqual(restored.cycle, 2)
            self.assertTrue(restored.pending_search)
            resumed = run_session(state_path, steps=128, capacity=1)
            control = run_session(control_path, steps=128, capacity=8, scenario_path=scenario_path)
            self.assertEqual((resumed["status"], control["status"]), ("COMPLETE", "COMPLETE"))
            self.assertEqual(resumed["state"], control["state"])
            self.assertEqual(read_json(state_path), read_json(control_path))

    def test_cycle_limit_retains_unfinished_cursor_and_rerun_is_read_only(self):
        with TemporaryDirectory(prefix="tomigidt-cycle-limit-") as directory:
            scenario_path = Path(directory) / "scenario.json"
            state_path = Path(directory) / "session.json"
            manifest = AgentManifest(max_search_expansions=1, max_cycles=3)
            scenario_path.write_text(json.dumps(Scenario(manifest, changes=()).to_dict()), encoding="utf-8")
            exhausted = run_session(state_path, steps=64, scenario_path=scenario_path)
            self.assertEqual(exhausted["executed_cycles"], 3)
            self.assertEqual(exhausted["cycle"], 3)
            self.assertEqual(exhausted["status"], "SEARCH_DEFERRED")
            self.assertEqual(exhausted["stop_reason"], "CYCLE_BUDGET_EXHAUSTED")
            self.assertEqual(exhausted["state"]["planning"]["expansions"], 3)
            _, restored = load_session(state_path, capacity=8)
            self.assertTrue(restored.pending_search)
            before = state_path.read_bytes()
            rerun = run_session(state_path, steps=64, capacity=1)
            self.assertEqual(rerun["executed_cycles"], 0)
            self.assertEqual(rerun["decisions"], [])
            self.assertEqual(rerun["stop_reason"], "CYCLE_BUDGET_EXHAUSTED")
            self.assertEqual(rerun["state"], exhausted["state"])
            self.assertEqual(state_path.read_bytes(), before)

    def test_invalid_frames_cannot_change_retained_frontier_or_live_state(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        agent.step(zero_frame(agent))
        before = (agent.archive(), cache_state(agent))
        for invalid in ({"00": 0}, {"0": True}, {"0": -1}, {"1": 128}, [], None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                agent.step(invalid)
            self.assertEqual((agent.archive(), cache_state(agent)), before)

    def test_reconstruction_after_every_cycle_preserves_progress_and_decisions(self):
        manifest = AgentManifest(max_search_expansions=1)
        uninterrupted = Tomigidt(manifest, capacity=8)
        restored = Tomigidt(manifest, capacity=1)
        for cycle in range(128):
            decision = uninterrupted.step(zero_frame(uninterrupted))
            self.assertEqual(restored.step(zero_frame(restored)), decision)
            self.assertEqual(restored.archive(), uninterrupted.archive())
            restored = Tomigidt.from_archive(restored.archive(), capacity=1 + cycle % 3)
            self.assertEqual(restored.archive(), uninterrupted.archive())
            if uninterrupted.status == "COMPLETE":
                break
        self.assertEqual((uninterrupted.status, restored.status), ("COMPLETE", "COMPLETE"))

    def test_planning_summary_and_recorded_progress_are_verified_by_replay(self):
        agent = Tomigidt(AgentManifest(max_search_expansions=1))
        agent.step(zero_frame(agent))
        agent.step(zero_frame(agent))
        original = agent.archive()
        changes = {
            "discard cursor": lambda a: a["expected"].update(planning=None),
            "wrong cumulative count": lambda a: a["expected"]["planning"].update(expansions=999),
            "wrong pending count": lambda a: a["expected"]["planning"].update(pending_states=0),
            "wrong search position": lambda a: a["expected"]["planning"].update(position="0"),
            "wrong goal": lambda a: a["expected"]["planning"].update(target="1"),
            "wrong starting pair": lambda a: a["expected"]["planning"].update(agent_pair="0000000000000000"),
            "wrong retained cost": lambda a: a["expected"]["planning"]["weights"].update({"0": 70}),
            "wrong historical progress": lambda a: a["events"][1]["decision"].update(expansions=1),
            "invented move": lambda a: a["events"][0]["decision"].update(kind="MOVE"),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            with self.subTest(case=label), self.assertRaises(ValueError):
                Tomigidt.from_archive(damaged)

    def test_fresh_process_quantum_one_restarts_equal_uninterrupted_session(self):
        with TemporaryDirectory(prefix="incremental-tomigidt-") as directory:
            output = Path(directory)
            scenario_path = output / "static scenario.json"
            interrupted_path = output / "interrupted session.json"
            control_path = output / "control session.json"
            scenario = Scenario(manifest=AgentManifest(max_search_expansions=1), changes=())
            scenario_path.write_text(json.dumps(scenario.to_dict()), encoding="utf-8")
            control = run_cli("agent", "run", "--state", control_path, "--steps", 128,
                              "--capacity", 8, "--scenario", scenario_path)
            self.assertEqual(control["status"], "COMPLETE")
            self.assertTrue(any(item["kind"] == "DEFER" for item in control["decisions"]))
            decisions = []
            for cycle in range(128):
                resumed = run_cli("agent", "run", "--state", interrupted_path, "--steps", 1,
                                  "--capacity", 1 if cycle % 2 else 8,
                                  "--scenario", scenario_path)
                self.assertEqual(resumed["executed_cycles"], 1)
                self.assertIs(resumed["restored"], cycle > 0)
                decisions.extend(resumed["decisions"])
                if resumed["status"] == "COMPLETE":
                    break
            self.assertEqual(resumed["status"], "COMPLETE")
            self.assertEqual(resumed["state"], control["state"])
            self.assertEqual(decisions, control["decisions"])
            self.assertEqual(read_json(interrupted_path), read_json(control_path))


if __name__ == "__main__":
    unittest.main()
