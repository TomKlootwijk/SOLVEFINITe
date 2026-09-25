"""Persistence, sensor provenance, and live OS ownership of simulated sessions."""

from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from solvefinite.runtime import write_json
from solvefinite.session import (
    AgentBusy, SESSION_FORMAT, Scenario, StateLock, load_session, run_session,
)
from solvefinite.tomigidt import AgentManifest, Tomigidt


class ScenarioTests(unittest.TestCase):
    def test_local_complete_frames_follow_changes_and_are_fresh(self):
        scenario = Scenario(hazards=(("", 3), ("1", 9), ("11", 100)),
                            changes=((3, "00", 12), (2, "00", 70), (1, "1", 4)))
        self.assertEqual(scenario.observe("", 1), {"": 3, "0": 0, "1": 4})
        self.assertEqual(scenario.observe("0", 1), {"": 3, "0": 0, "00": 0})
        self.assertEqual(scenario.observe("0", 2), {"": 3, "0": 0, "00": 70})
        self.assertEqual(scenario.observe("0", 3), {"": 3, "0": 0, "00": 12})
        self.assertEqual(scenario.observe("0", 4), {"": 3, "0": 0, "00": 12})
        changed_frame = scenario.observe("", 1)
        changed_frame["0"] = 127
        self.assertEqual(scenario.observe("", 1)["0"], 0)
        self.assertNotIn("11", scenario.observe("", 1))

    def test_round_trip_normalizes_order_and_is_immutable(self):
        scenario = Scenario(hazards=(("1", 10), ("0", 20)),
                            changes=((4, "0", 3), (2, "1", 8)))
        self.assertEqual(scenario, Scenario.from_dict(json.loads(json.dumps(scenario.to_dict()))))
        self.assertEqual(scenario.hazards, (("0", 20), ("1", 10)))
        self.assertEqual(scenario.changes, ((2, "1", 8), (4, "0", 3)))
        with self.assertRaises(FrozenInstanceError):
            scenario.changes = ()

    def test_strict_immutable_constructor_and_ranges(self):
        invalid = [
            {"manifest": {}}, {"hazards": []}, {"hazards": (["0", 1],)},
            {"hazards": (("0",),)}, {"hazards": (("0", 1, 2),)},
            {"hazards": (("0", 1), ("0", 2))}, {"hazards": (([], 1),)},
            {"hazards": (("000", 1),)}, {"changes": []},
            {"changes": ([2, "00", 1],)}, {"changes": ((2, "00"),)},
            {"changes": ((2, "00", 1), (2, "00", 2))},
            {"changes": ((2, "000", 1),)}, {"changes": ((2, [], 1),)},
        ]
        for hazard in (-1, 128, True, False, "1", 1.0, None):
            invalid.extend([{"hazards": (("0", hazard),)},
                            {"changes": ((2, "00", hazard),)}])
        for cycle in (0, -1, 10001, True, False, "2", 2.0, None):
            invalid.append({"changes": ((cycle, "00", 1),)})
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                Scenario(**arguments)

    def test_small_custom_graph_requires_explicit_compatible_changes(self):
        manifest = AgentManifest(target="", graph=(("", ()),), max_cycles=1)
        with self.assertRaises(ValueError):
            Scenario(manifest)
        scenario = Scenario(manifest, changes=())
        self.assertEqual(scenario.observe("", 1), {"": 0})

    def test_observation_arguments_are_validated(self):
        scenario = Scenario()
        for position in (None, True, [], "000", "2"):
            with self.subTest(position=position), self.assertRaises(ValueError):
                scenario.observe(position, 1)
        for cycle in (0, -1, True, 1.0, "1", None, 10001):
            with self.subTest(cycle=cycle), self.assertRaises(ValueError):
                scenario.observe("", cycle)

    def test_json_schema_rejects_missing_extra_and_wrong_shapes(self):
        good = Scenario().to_dict()
        invalid = [None, [], {}, dict(good, extra=1), dict(good, format="future"),
                   dict(good, hazards=[]), dict(good, changes=()),
                   dict(good, changes=[{"cycle": 2, "path": "00"}]),
                   dict(good, changes=[{"cycle": 2, "path": "00", "hazard": 5, "extra": 0}])]
        invalid.extend({key: value for key, value in good.items() if key != omitted}
                       for omitted in good)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Scenario.from_dict(value)

    def test_load_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            text = json.dumps(Scenario().to_dict())
            for malformed in (text.replace('"hazards": {}', '"hazards": {"0": 1, "0": 2}'),
                              text.replace('"hazards": {}', '"hazards": {"0": NaN}')):
                path.write_text(malformed, encoding="utf-8")
                with self.assertRaises(ValueError):
                    Scenario.load(path)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "state.json"

    def scenario_file(self, scenario):
        path = self.directory / "scenario.json"
        write_json(path, scenario.to_dict())
        return path

    def test_fresh_and_interrupted_sessions_retain_identical_journals_across_capacities(self):
        full_path = self.directory / "full.json"
        full = run_session(full_path, capacity=1)
        self.assertEqual(full["status"], "COMPLETE")
        self.assertEqual(full["stop_reason"], "COMPLETE")
        self.assertFalse(full["restored"])
        self.assertEqual(full["executed_cycles"], full["cycle"])
        first = run_session(self.path, steps=1, capacity=7)
        self.assertEqual(first["stop_reason"], "STEP_BUDGET_EXHAUSTED")
        self.assertEqual(first["executed_cycles"], 1)
        middle = run_session(self.path, steps=2, capacity=1)
        self.assertTrue(middle["restored"])
        last = run_session(self.path, capacity=4)
        self.assertEqual(last["status"], "COMPLETE")
        self.assertEqual(last["capacity_pairs"], 4)
        self.assertEqual(last["state_path"], str(self.path.resolve()))
        self.assertEqual(full["state"], last["state"])
        self.assertEqual(full["decisions"], first["decisions"] + middle["decisions"] + last["decisions"])
        self.assertEqual(json.loads(full_path.read_text()), json.loads(self.path.read_text()))

    def test_complete_resume_does_not_write_or_take_another_step(self):
        run_session(self.path)
        before = self.path.read_bytes()
        with patch("solvefinite.session.write_json", side_effect=AssertionError("unexpected write")):
            result = run_session(self.path, capacity=8)
        self.assertTrue(result["restored"])
        self.assertEqual(result["executed_cycles"], 0)
        self.assertEqual(result["decisions"], [])
        self.assertEqual(result["stop_reason"], "COMPLETE")
        self.assertEqual(self.path.read_bytes(), before)

    def test_each_accepted_step_and_initial_state_are_saved(self):
        original = write_json
        archived_cycles = []

        def capture(path, value):
            archived_cycles.append(value["agent"]["expected"]["cycle"])
            original(path, value)

        with patch("solvefinite.session.write_json", side_effect=capture):
            result = run_session(self.path, steps=3)
        self.assertEqual(archived_cycles, [0, 1, 2, 3])
        _, agent = load_session(self.path)
        self.assertEqual(agent.cycle, result["cycle"])

    def test_changed_supplied_scenario_is_rejected_without_changing_state(self):
        run_session(self.path, steps=1)
        before = self.path.read_bytes()
        supplied = self.scenario_file(Scenario(hazards=(("1", 1),)))
        with self.assertRaisesRegex(ValueError, "differs"):
            run_session(self.path, scenario_path=supplied)
        self.assertEqual(self.path.read_bytes(), before)
        same = self.scenario_file(Scenario())
        self.assertTrue(run_session(self.path, steps=1, scenario_path=same)["restored"])

    def test_malformed_scenario_does_not_create_or_modify_a_session(self):
        supplied = self.directory / "bad.json"
        supplied.write_text('{"bad":true}', encoding="utf-8")
        with self.assertRaises(ValueError):
            run_session(self.path, scenario_path=supplied)
        self.assertFalse(self.path.exists())
        run_session(self.path, steps=1)
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            run_session(self.path, scenario_path=supplied)
        self.assertEqual(self.path.read_bytes(), before)

    def test_session_schema_and_duplicate_keys_are_rejected_unchanged(self):
        run_session(self.path, steps=1)
        good = json.loads(self.path.read_text())
        invalid = [None, [], {}, dict(good, extra=1), dict(good, format="future")]
        invalid.extend({key: value for key, value in good.items() if key != omitted}
                       for omitted in good)
        texts = [json.dumps(value) for value in invalid]
        texts.append(json.dumps(good).replace('"format": "tomigidt-session-v1"',
                                              '"format": "tomigidt-session-v1", "format": "tomigidt-session-v1"'))
        for text in texts:
            self.path.write_text(text, encoding="utf-8")
            before = self.path.read_bytes()
            with self.subTest(text=text[:100]), self.assertRaises(ValueError):
                run_session(self.path)
            self.assertEqual(self.path.read_bytes(), before)

    def test_scenario_and_agent_manifest_must_agree(self):
        run_session(self.path, steps=1)
        saved = json.loads(self.path.read_text())
        saved["scenario"]["agent"]["identity"] = "Another identity"
        write_json(self.path, saved)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "manifests disagree"):
            run_session(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_valid_agent_journal_with_wrong_scenario_history_is_rejected(self):
        scenario = Scenario()
        agent = Tomigidt(scenario.manifest)
        frame = scenario.observe("", 1)
        frame[""] = 7  # Valid local packet, but not an observation this scenario supplied.
        agent.step(frame)
        write_json(self.path, {"format": SESSION_FORMAT, "scenario": scenario.to_dict(),
                               "agent": agent.archive()})
        Tomigidt.from_archive(agent.archive())  # Agent replay alone really accepts it.
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "scenario timeline"):
            run_session(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_partial_sensor_frames_are_not_valid_scenario_history(self):
        scenario = Scenario()
        agent = Tomigidt(scenario.manifest)
        agent.step({"": 0})
        write_json(self.path, {"format": SESSION_FORMAT, "scenario": scenario.to_dict(),
                               "agent": agent.archive()})
        with self.assertRaisesRegex(ValueError, "scenario timeline"):
            load_session(self.path)

    def test_read_only_inspection_uses_archive_replay_and_does_not_take_lock(self):
        run_session(self.path, steps=2)
        before = self.path.read_bytes()
        with StateLock(self.path):
            scenario, agent = load_session(self.path, capacity=9)
        self.assertEqual(scenario, Scenario())
        self.assertEqual(agent.cycle, 2)
        self.assertEqual(agent.world.capacity, 9)
        self.assertEqual(self.path.read_bytes(), before)

    def test_cycle_budget_is_a_stop_reason_separate_from_active_status(self):
        scenario = Scenario(replace(AgentManifest(), max_cycles=1), changes=())
        result = run_session(self.path, scenario_path=self.scenario_file(scenario))
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["stop_reason"], "CYCLE_BUDGET_EXHAUSTED")
        self.assertEqual(result["executed_cycles"], 1)
        before = self.path.read_bytes()
        repeated = run_session(self.path)
        self.assertEqual(repeated["executed_cycles"], 0)
        self.assertEqual(repeated["stop_reason"], "CYCLE_BUDGET_EXHAUSTED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_nonactive_agent_stops_without_consuming_all_requested_cycles(self):
        manifest = AgentManifest(target="1", graph=(("", ()), ("1", ())))
        scenario = Scenario(manifest, changes=())
        result = run_session(self.path, scenario_path=self.scenario_file(scenario))
        self.assertEqual((result["status"], result["executed_cycles"]), ("UNREACHABLE", 1))
        self.assertEqual(run_session(self.path)["executed_cycles"], 1)

    def test_resumed_insufficient_energy_agent_samples_a_later_hazard_drop(self):
        scenario = Scenario(hazards=(("0", 127), ("1", 127)),
                            changes=((2, "0", 0), (2, "1", 0)))
        blocked = run_session(self.path, scenario_path=self.scenario_file(scenario))
        self.assertEqual(blocked["status"], "INSUFFICIENT_ENERGY")
        self.assertEqual(blocked["executed_cycles"], 1)
        self.assertEqual(blocked["state"]["position"], "")
        resumed = run_session(self.path)
        self.assertTrue(resumed["restored"])
        self.assertEqual(resumed["decisions"][0]["kind"], "MOVE")
        self.assertEqual(resumed["status"], "COMPLETE")
        self.assertEqual(resumed["stop_reason"], "COMPLETE")

    def test_search_deferred_retries_once_per_run_then_stops_at_cycle_budget(self):
        scenario = Scenario(replace(AgentManifest(), max_search_expansions=1, max_cycles=3),
                            changes=())
        supplied = self.scenario_file(scenario)
        for cycle in (1, 2, 3):
            result = run_session(self.path, scenario_path=supplied)
            self.assertEqual(result["status"], "SEARCH_DEFERRED")
            self.assertEqual(result["executed_cycles"], 1)
            self.assertEqual(result["cycle"], cycle)
            self.assertEqual(result["stop_reason"], "CYCLE_BUDGET_EXHAUSTED" if cycle == 3
                             else "SEARCH_DEFERRED")
        before = self.path.read_bytes()
        exhausted = run_session(self.path)
        self.assertEqual(exhausted["executed_cycles"], 0)
        self.assertEqual(exhausted["stop_reason"], "CYCLE_BUDGET_EXHAUSTED")
        self.assertEqual(self.path.read_bytes(), before)

    def test_write_failure_leaves_last_durable_cycle_resumable(self):
        full_path = self.directory / "full.json"
        run_session(full_path)
        original = write_json

        def fail_third_cycle(path, value):
            if value["agent"]["expected"]["cycle"] == 3:
                raise OSError("simulated storage failure")
            original(path, value)

        with patch("solvefinite.session.write_json", side_effect=fail_third_cycle):
            with self.assertRaisesRegex(OSError, "storage failure"):
                run_session(self.path)
        _, retained = load_session(self.path)
        self.assertEqual(retained.cycle, 2)
        resumed = run_session(self.path)
        self.assertEqual(resumed["status"], "COMPLETE")
        self.assertEqual(json.loads(self.path.read_text()), json.loads(full_path.read_text()))

    def test_invalid_runner_arguments_do_not_create_state(self):
        for arguments in ({"steps": 0}, {"steps": True}, {"steps": 1.0},
                          {"capacity": 0}, {"capacity": False}, {"capacity": 1.0}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                run_session(self.path, **arguments)
            self.assertFalse(self.path.exists())


class StateLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "state.json"

    def start_holder(self):
        script = (
            "from solvefinite.session import StateLock\n"
            "import sys\n"
            "with StateLock(sys.argv[1]):\n"
            "    print('locked', flush=True)\n"
            "    sys.stdin.readline()\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(self.path)],
            cwd=Path(__file__).resolve().parents[1], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

        def cleanup():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

        self.addCleanup(cleanup)
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        self.assertEqual(ready.get(timeout=5), "locked\n")
        self.assertIsNone(process.poll())
        return process

    def test_live_other_process_contends_and_graceful_exit_releases(self):
        process = self.start_holder()
        with self.assertRaises(AgentBusy):
            run_session(self.path, steps=1)
        self.assertFalse(self.path.exists())
        process.stdin.write("release\n")
        process.stdin.flush()
        self.assertEqual(process.wait(timeout=5), 0)
        result = run_session(self.path, steps=1)
        self.assertEqual(result["executed_cycles"], 1)
        self.assertTrue(Path(str(self.path) + ".lock").exists())

    def test_abrupt_process_termination_releases_without_deleting_lock_file(self):
        process = self.start_holder()
        with self.assertRaises(AgentBusy):
            with StateLock(self.path):
                pass
        process.terminate()
        process.wait(timeout=5)
        lock_path = Path(str(self.path) + ".lock")
        self.assertTrue(lock_path.exists())
        with StateLock(self.path):
            self.assertTrue(lock_path.exists())

    def test_canonical_alias_conflicts_but_distinct_state_paths_are_independent(self):
        alias = self.directory / "unused" / ".." / self.path.name
        with StateLock(self.path):
            with self.assertRaises(AgentBusy):
                with StateLock(alias):
                    pass
            with StateLock(self.directory / "different.json"):
                pass

    def test_existing_lock_content_is_never_truncated_or_used_as_ownership(self):
        lock_path = Path(str(self.path) + ".lock")
        lock_path.write_bytes(b"arbitrary stale contents")
        with StateLock(self.path):
            pass
        self.assertEqual(lock_path.read_bytes(), b"arbitrary stale contents")

    def test_exception_exit_releases_lock_and_reentry_is_rejected(self):
        context = StateLock(self.path)
        with self.assertRaisesRegex(RuntimeError, "example"):
            with context:
                with self.assertRaises(AgentBusy):
                    context.__enter__()
                raise RuntimeError("example")
        with context:
            pass


if __name__ == "__main__":
    unittest.main()
