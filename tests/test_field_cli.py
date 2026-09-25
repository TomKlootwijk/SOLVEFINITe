"""Persistence, ownership and fresh-process use of the intrinsic field profile."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.__main__ import main
from solvefinite.field import FieldMachine, FieldManifest
from solvefinite.field_cli import inspect_field, run_field_session
from solvefinite.klein import KleinDomain
from solvefinite.runtime import write_json
from solvefinite.session import AgentBusy, StateLock


class FieldCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "field.json"

    def test_resuming_and_fresh_process_inspection_preserve_the_trace(self):
        first = run_field_session(self.state, steps=7)
        second = run_field_session(self.state, steps=11)
        self.assertFalse(first["restored"])
        self.assertTrue(second["restored"])
        self.assertEqual(second["state"]["tick"], 18)
        control = FieldMachine()
        self.addCleanup(control.close)
        control.advance(18)
        self.assertEqual(json.loads(self.state.read_text()), control.archive())
        result = subprocess.run(
            [sys.executable, "-m", "solvefinite", "field", "inspect", str(self.state)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
            timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], control.snapshot())

    def test_failed_budget_admission_preserves_existing_file_and_avoids_new_file(self):
        manifest_path = self.state.with_name("manifest.json")
        raw = FieldManifest().to_dict()
        raw["max_ticks"] = 5
        write_json(manifest_path, raw)
        with self.assertRaises(ValueError):
            run_field_session(self.state, steps=6, manifest_path=manifest_path)
        self.assertFalse(self.state.exists())
        run_field_session(self.state, steps=3, manifest_path=manifest_path)
        previous = self.state.read_bytes()
        with self.assertRaises(ValueError):
            run_field_session(self.state, steps=3)
        self.assertEqual(self.state.read_bytes(), previous)

    def test_changed_manifest_and_lock_contention_do_not_advance(self):
        run_field_session(self.state, steps=2)
        previous = self.state.read_bytes()
        changed = FieldManifest().to_dict()
        changed["initial_phase"] = 0
        manifest_path = self.state.with_name("changed.json")
        write_json(manifest_path, changed)
        with self.assertRaises(ValueError):
            run_field_session(self.state, steps=1, manifest_path=manifest_path)
        with StateLock(self.state):
            with self.assertRaises(AgentBusy):
                run_field_session(self.state, steps=1)
        self.assertEqual(self.state.read_bytes(), previous)

    def test_corrupted_archive_cannot_be_inspected_or_advanced(self):
        run_field_session(self.state, steps=3)
        archive = json.loads(self.state.read_text())
        archive["trace"][0] = "0000000000000000"
        write_json(self.state, archive)
        previous = self.state.read_bytes()
        with self.assertRaises(ValueError):
            inspect_field(self.state)
        with self.assertRaises(ValueError):
            run_field_session(self.state, steps=1)
        self.assertEqual(self.state.read_bytes(), previous)

    def test_cli_exports_manifest_and_reports_invalid_step_without_traceback(self):
        path = self.state.with_name("manifest.json")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["field", "manifest", "--output", str(path)]), 0)
        self.assertEqual(FieldManifest.from_dict(json.loads(path.read_text())), FieldManifest())
        errors = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(errors):
            self.assertEqual(main(["field", "run", "--state", str(self.state), "--steps", "0"]), 2)
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertFalse(self.state.exists())

    def test_klein_export_run_and_fresh_process_resume(self):
        path = self.state.with_name("klein.json")
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([
                "field", "klein", "--output", str(path), "--width", "5", "--height", "3",
                "--center", "1", "--radius", "2", "--initial-node", "13",
                "--initial-phase", "17", "--initial-orientation", "1", "--max-ticks", "48"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["profile"], "relational-sdf-v2")
        self.assertFalse(result["topology_audit"]["base"]["orientable"])
        self.assertTrue(result["topology_audit"]["toroidal_cover_faces"])
        manifest = FieldManifest.from_dict(json.loads(path.read_text()))
        self.assertEqual(manifest, KleinDomain(5, 3).field_manifest(
            center=1, radius=2, initial_node=13, initial_phase=17,
            initial_orientation=1, max_ticks=48))
        first = run_field_session(self.state, steps=7, manifest_path=path)
        self.assertEqual(first["profile"], "relational-sdf-v2")
        worker = subprocess.run(
            [sys.executable, "-m", "solvefinite", "field", "run", "--state", str(self.state),
             "--steps", "11"], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.assertEqual(worker.returncode, 0, worker.stderr)
        resumed = json.loads(worker.stdout)
        self.assertTrue(resumed["restored"])
        self.assertEqual(resumed["profile"], "relational-sdf-v2")
        control = FieldMachine(manifest)
        self.addCleanup(control.close)
        control.advance(18)
        self.assertEqual(json.loads(self.state.read_text()), control.archive())
        inspected = inspect_field(self.state)
        self.assertEqual(inspected["profile"], "relational-sdf-v2")
        self.assertEqual(inspected["state"], control.snapshot())

    def test_invalid_klein_export_preserves_output(self):
        path = self.state.with_name("klein.json")
        for option, value in (("--width", "2"), ("--height", "33"), ("--center", "64"),
                              ("--radius", "0"), ("--radius", "999"),
                              ("--initial-orientation", "2"), ("--max-ticks", "65537")):
            with self.subTest(option=option, value=value):
                errors = StringIO()
                with redirect_stdout(StringIO()), redirect_stderr(errors):
                    self.assertEqual(main(["field", "klein", "--output", str(path), option, value]), 2)
                self.assertNotIn("Traceback", errors.getvalue())
                self.assertFalse(path.exists())
        path.write_text("retained content", encoding="utf-8")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(main(["field", "klein", "--output", str(path), "--width", "2"]), 2)
        self.assertEqual(path.read_text(encoding="utf-8"), "retained content")

    def test_klein_descriptor_tampering_cannot_advance_saved_state(self):
        path = self.state.with_name("klein.json")
        write_json(path, KleinDomain().field_manifest().to_dict())
        run_field_session(self.state, steps=9, manifest_path=path)
        previous = self.state.read_bytes()
        changed = json.loads(path.read_text())
        changed["topology"]["width"] = 4
        changed["topology"]["height"] = 16
        write_json(path, changed)
        with self.assertRaises(ValueError):
            run_field_session(self.state, steps=1, manifest_path=path)
        self.assertEqual(self.state.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
