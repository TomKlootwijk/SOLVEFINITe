"""Fresh-process CLI recovery and errors using only temporary artifacts."""

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.runtime import Runtime


ROOT = Path(__file__).resolve().parent.parent


def run_cli(*arguments):
    return subprocess.run(
        [sys.executable, "-m", "solvefinite", *(str(arg) for arg in arguments)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class CLIRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory(prefix="solvefinite-cli-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.output = Path(cls.directory.name) / "demo with spaces"
        cls.demo_result = run_cli("demo", "--output", cls.output)
        if cls.demo_result.returncode != 0:
            raise AssertionError(
                f"Demo exited {cls.demo_result.returncode}: {cls.demo_result.stderr}"
            )
        cls.report = json.loads(cls.demo_result.stdout)
        cls.checkpoint_path = cls.output / "checkpoint.json"
        cls.recovered_path = cls.output / "recovered.json"

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_demo_artifacts_and_independent_expected_vector(self):
        report = self.assert_success(self.demo_result)
        self.assertEqual(read_json(self.output / "report.json"), report)
        self.assertEqual(set(report["checks"]), {
            "evicted_node_reconstructed_exactly",
            "imagined_and_executed_movement_match",
            "fresh_process_replayed_checkpoint_exactly",
            "resumed_and_uninterrupted_journals_match",
            "worker_is_a_separate_process",
        })
        for name, passed in report["checks"].items():
            with self.subTest(check=name):
                self.assertIs(passed, True)

        # Independent demo vector: left route movement costs 43+2+2=47;
        # right route costs 6+4+4=14; 100-14-5 leaves energy 81.
        self.assertEqual(report["chosen_route"], ["1", "10", "100"])
        self.assertEqual([plan["movement_cost"] for plan in report["candidate_plans"]],
                         [47, 14])
        self.assertEqual(report["remaining_energy"], 81)
        self.assertEqual(report["checkpoint"]["agent_pair"], "115E0B7D015E0B83")
        self.assertEqual(report["completed"]["agent_pair"], "16516707065167F9")
        self.assertEqual(report["checkpoint"]["tick"], 6)
        self.assertEqual(report["checkpoint"]["cursor"], 1)
        self.assertIs(report["checkpoint"]["repaired"], False)
        self.assertEqual(report["completed"]["tick"], 9)
        self.assertEqual(report["completed"]["position"], "100")
        self.assertEqual(report["completed"]["cursor"], 3)
        self.assertIs(report["completed"]["repaired"], True)

        self.assertEqual(report["control_cache"]["capacity_pairs"], 2)
        self.assertEqual(report["recovered_cache"]["capacity_pairs"], 1)
        self.assertLessEqual(len(report["control_cache"]["active_paths"]), 2)
        self.assertLessEqual(len(report["recovered_cache"]["active_paths"]), 1)
        for name, expected in (("checkpoint", self.checkpoint_path),
                               ("recovered", self.recovered_path),
                               ("report", self.output / "report.json")):
            self.assertEqual(Path(report["artifacts"][name]), expected)
            self.assertTrue(expected.is_file())

        # Loading performs replay rather than trusting the archived witness.
        checkpoint = Runtime.load(self.checkpoint_path, capacity=2)
        completed = Runtime.load(self.recovered_path, capacity=1)
        self.assertEqual(checkpoint.snapshot(), report["checkpoint"])
        self.assertEqual(completed.snapshot(), report["completed"])
        checkpoint.finish()
        self.assertEqual(checkpoint.archive(), completed.archive())

    def test_replay_without_resume_preserves_interrupted_checkpoint(self):
        replayed_path = self.output / "checkpoint replayed.json"
        replayed = self.assert_success(run_cli(
            "replay", self.checkpoint_path, "--output", replayed_path,
        ))
        archived = read_json(self.checkpoint_path)
        self.assertIs(replayed["replay_verified"], True)
        self.assertEqual(replayed["restored"], archived["expected"])
        self.assertEqual(replayed["final"], archived["expected"])
        self.assertIs(replayed["final"]["repaired"], False)
        self.assertEqual(read_json(replayed_path), archived)
        self.assertEqual(Runtime.load(replayed_path).snapshot(), archived["expected"])

    def test_resume_with_larger_cache_matches_canonical_final_and_journal(self):
        resumed_path = self.output / "resumed capacity eight.json"
        resumed = self.assert_success(run_cli(
            "replay", self.checkpoint_path, "--resume", "--capacity", "8",
            "--output", resumed_path,
        ))
        self.assertIs(resumed["replay_verified"], True)
        self.assertEqual(resumed["restored"], self.report["checkpoint"])
        self.assertEqual(resumed["final"], self.report["completed"])
        self.assertEqual(resumed["cache"]["capacity_pairs"], 8)
        self.assertLessEqual(len(resumed["cache"]["active_paths"]), 8)
        resumed_archive = read_json(resumed_path)
        recovered_archive = read_json(self.recovered_path)
        self.assertEqual(resumed_archive, recovered_archive)
        self.assertEqual(resumed_archive["events"], recovered_archive["events"])
        self.assertEqual(Runtime.load(resumed_path, capacity=8).snapshot(),
                         self.report["completed"])

    def test_bad_archives_and_capacity_report_useful_errors_without_tracebacks(self):
        malformed = self.output / "malformed.json"
        malformed.write_text('{"format":', encoding="utf-8")
        wrong_shape = self.output / "wrong-shape.json"
        wrong_shape.write_text("{}", encoding="utf-8")
        missing = self.output / "missing.json"
        cases = (
            (("replay", missing), "missing.json"),
            (("replay", malformed), "Expecting value"),
            (("replay", wrong_shape), "Archive must contain exactly"),
            (("replay", self.checkpoint_path, "--capacity", "0"), "capacity must be at least 1"),
        )
        for arguments, diagnostic in cases:
            with self.subTest(arguments=arguments):
                result = run_cli(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("solvefinite:", result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
