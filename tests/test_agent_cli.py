"""Fresh-process operation of the persistent TOMIGIDt command line interface."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.rp32 import unpack, unpair


ROOT = Path(__file__).resolve().parent.parent


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "solvefinite", *(str(argument) for argument in arguments)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class AgentCLIIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="tomigidt-cli-")
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "session with spaces"
        self.output.mkdir()
        self.state = self.output / "agent state.json"

    def success(self, *arguments):
        result = run_cli(*arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def failure(self, *arguments, diagnostic=None):
        result = run_cli(*arguments)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(result.stderr)
        if diagnostic is not None:
            self.assertIn(diagnostic, result.stderr)
        return result

    def test_one_cycle_per_process_recovers_exactly_and_matches_uninterrupted_run(self):
        positions = ("0", "", "1", "10", "11", "11")
        new_decisions = []
        for cycle, position in enumerate(positions, 1):
            capacity = 1 if cycle % 2 else 8
            summary = self.success("agent", "run", "--state", self.state,
                                   "--steps", 1, "--capacity", capacity)
            self.assertEqual(summary["identity"], "TOMIGIDt")
            self.assertEqual(summary["cycle"], cycle)
            self.assertEqual(summary["executed_cycles"], 1)
            self.assertIs(summary["restored"], cycle > 1)
            self.assertEqual(summary["state"]["position"], position)
            self.assertEqual(Path(summary["state_path"]), self.state.resolve())
            self.assertEqual(summary["capacity_pairs"], capacity)
            self.assertEqual(len(summary["decisions"]), 1)
            self.assertEqual(summary["decisions"][0]["kind"], "REPAIR" if cycle == 6 else "MOVE")
            self.assertEqual(summary["status"], "COMPLETE" if cycle == 6 else "ACTIVE")
            self.assertEqual(summary["stop_reason"],
                             "COMPLETE" if cycle == 6 else "STEP_BUDGET_EXHAUSTED")
            archive = read_json(self.state)
            self.assertEqual(archive["format"], "tomigidt-session-v1")
            self.assertEqual(archive["agent"]["expected"], summary["state"])
            self.assertEqual(len(archive["agent"]["events"]), cycle)
            self.assertEqual(archive["agent"]["events"][-1]["decision"], summary["decisions"][0])
            new_decisions.extend(summary["decisions"])
        # Independent default vector: entry costs 3+3+4+3+4, repair 5.
        self.assertEqual(summary["state"]["agent_pair"], "164E23BB064E2345")
        self.assertEqual(unpack(unpair(int(summary["state"]["agent_pair"], 16))[0])[2], 78)
        control = self.output / "uninterrupted state.json"
        full = self.success("agent", "run", "--state", control, "--capacity", 1)
        self.assertIs(full["restored"], False)
        self.assertEqual(full["executed_cycles"], 6)
        self.assertEqual(full["decisions"], new_decisions)
        self.assertEqual(full["state"], summary["state"])
        self.assertEqual(read_json(control), read_json(self.state))

    def test_inspect_verifies_existing_session_without_rewriting(self):
        initial = self.success("agent", "run", "--state", self.state, "--steps", 2)
        before = self.state.read_bytes()
        inspected = self.success("agent", "inspect", self.state, "--capacity", 8)
        self.assertIs(inspected["verified"], True)
        self.assertEqual(inspected["event_count"], 2)
        self.assertEqual(inspected["state"], initial["state"])
        self.assertEqual(Path(inspected["state_path"]), self.state.resolve())
        self.assertEqual(self.state.read_bytes(), before)

    def test_completed_rerun_performs_zero_cycles_and_preserves_file(self):
        first = self.success("agent", "run", "--state", self.state)
        before = self.state.read_bytes()
        repeated = self.success("agent", "run", "--state", self.state, "--capacity", 8)
        self.assertEqual(repeated["executed_cycles"], 0)
        self.assertEqual(repeated["decisions"], [])
        self.assertIs(repeated["restored"], True)
        self.assertEqual(repeated["state"], first["state"])
        self.assertEqual(repeated["stop_reason"], "COMPLETE")
        self.assertEqual(self.state.read_bytes(), before)

    def test_generated_scenario_is_readable_and_custom_goal_drives_own_repair(self):
        scenario_path = self.output / "custom scenario.json"
        generated = self.success("agent", "scenario", "--output", scenario_path)
        self.assertEqual(Path(generated["scenario"]), scenario_path.resolve())
        self.assertEqual(generated["identity"], "TOMIGIDt")
        scenario = read_json(scenario_path)
        self.assertEqual(scenario["format"], "tomigidt-simulation-v1")
        self.assertEqual(set(scenario), {"format", "agent", "hazards", "changes"})
        self.assertEqual(scenario["changes"], [{"cycle": 2, "path": "00", "hazard": 70}])
        self.assertEqual(scenario["agent"]["target"], "11")
        scenario["agent"]["target"] = ""
        scenario["agent"]["identity"] = "TOMIGIDt-root-repair"
        write_json(scenario_path, scenario)
        summary = self.success("agent", "run", "--state", self.state, "--scenario", scenario_path)
        self.assertEqual((summary["identity"], summary["status"], summary["cycle"]),
                         ("TOMIGIDt-root-repair", "COMPLETE", 1))
        self.assertEqual([decision["kind"] for decision in summary["decisions"]], ["REPAIR"])
        self.assertEqual(summary["state"]["position"], "")
        self.assertEqual(unpack(unpair(int(summary["state"]["agent_pair"], 16))[0])[2], 95)
        self.assertEqual(read_json(self.state)["scenario"], scenario)

    def test_same_explicit_scenario_resumes_and_different_scenario_does_not_rewrite(self):
        scenario_path = self.output / "scenario.json"
        self.success("agent", "scenario", "--output", scenario_path)
        self.success("agent", "run", "--state", self.state, "--steps", 1,
                     "--scenario", scenario_path)
        resumed = self.success("agent", "run", "--state", self.state, "--steps", 1,
                               "--scenario", scenario_path)
        self.assertIs(resumed["restored"], True)
        self.assertEqual((resumed["cycle"], resumed["state"]["position"]), (2, ""))
        before = self.state.read_bytes()
        changed = read_json(scenario_path)
        changed["changes"][0]["hazard"] = 69
        write_json(scenario_path, changed)
        self.failure("agent", "run", "--state", self.state, "--scenario", scenario_path,
                     diagnostic="supplied scenario differs")
        self.assertEqual(self.state.read_bytes(), before)

    def test_sensor_inputs_supply_no_candidates_or_actions(self):
        self.success("agent", "run", "--state", self.state)
        session = read_json(self.state)
        graph = session["scenario"]["agent"]["graph"]
        position = ""
        for event in session["agent"]["events"]:
            self.assertEqual(set(event), {"seq", "input", "decision", "output"})
            self.assertEqual(set(event["input"]), {position, *graph[position]})
            self.assertTrue(all(type(word) is str and len(word) == 8
                                for word in event["input"].values()))
            if event["decision"]["kind"] == "MOVE":
                destination = event["decision"]["route"][0]
                self.assertIn(destination, graph[position])
                position = destination
        pending = [session]
        while pending:
            current = pending.pop()
            if isinstance(current, dict):
                self.assertNotIn("candidates", current)
                self.assertNotIn("candidate_routes", current)
                pending.extend(current.values())
            elif isinstance(current, list):
                pending.extend(current)

    def test_invalid_arguments_and_missing_or_malformed_state_are_useful_errors(self):
        malformed = self.output / "malformed.json"
        malformed.write_text('{"format":', encoding="utf-8")
        wrong_shape = self.output / "wrong shape.json"
        wrong_shape.write_text("{}", encoding="utf-8")
        cases = [
            (("agent", "run", "--state", self.state, "--steps", 0), "steps"),
            (("agent", "run", "--state", self.state, "--capacity", 0), "capacity"),
            (("agent", "run", "--state", self.state, "--steps", "x"), "invalid int value"),
            (("agent", "inspect", self.output / "missing.json"), "missing.json"),
            (("agent", "inspect", malformed), "Expecting value"),
            (("agent", "inspect", wrong_shape), "Session must contain exactly"),
            (("agent", "run", "--state", self.state, "--scenario", malformed), "Expecting value"),
            (("agent", "scenario"), "--output"),
            (("agent", "unknown-command"), "invalid choice"),
        ]
        for arguments, diagnostic in cases:
            with self.subTest(arguments=arguments):
                self.failure(*arguments, diagnostic=diagnostic)
        self.assertFalse(self.state.exists())

    def test_tampered_state_or_sensor_timeline_is_rejected_without_rewrite(self):
        self.success("agent", "run", "--state", self.state, "--steps", 2)
        original = read_json(self.state)
        changes = {
            "decision": lambda a: a["agent"]["events"][0]["decision"].update(kind="REPAIR"),
            "snapshot": lambda a: a["agent"]["expected"].update(position="11"),
            "sensor timeline": lambda a: a["scenario"]["hazards"].update({"0": 70}),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            write_json(self.state, damaged)
            before = self.state.read_bytes()
            with self.subTest(case=label):
                self.failure("agent", "inspect", self.state)
                self.failure("agent", "run", "--state", self.state)
                self.assertEqual(self.state.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
