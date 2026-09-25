"""Existing CLI/session/live interfaces carry the field policy end to end."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from solvefinite.__main__ import main
from solvefinite.field_agent import FieldAgentManifest
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL, load_live
from solvefinite.session import Scenario, StateLock, AgentBusy, load_session, run_session
from solvefinite.tomigidt import Tomigidt


class FieldAgentCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_cli_exports_and_resumes_field_mission_in_another_process(self):
        scenario_path, state = self.root / "scenario.json", self.root / "state.json"
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["agent", "scenario", "--profile", "field",
                                   "--output", str(scenario_path)]), 0)
        scenario = Scenario.load(scenario_path)
        self.assertEqual(type(scenario.manifest), FieldAgentManifest)
        first = run_session(state, steps=1, capacity=1, scenario_path=scenario_path)
        self.assertEqual(first["state"]["position"], "k:0:4")
        child = subprocess.run([sys.executable, "-m", "solvefinite", "agent", "run",
                                "--state", str(state), "--steps", "10", "--capacity", "9"],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        result = json.loads(child.stdout)
        self.assertEqual((result["cycle"], result["state"]["energy"], result["stop_reason"]),
                         (4, 90, "COMPLETE"))
        retained, actual = load_session(state, capacity=2)
        control = Tomigidt(scenario.manifest, capacity=30)
        self.addCleanup(actual.close)
        self.addCleanup(control.close)
        while control.status != "COMPLETE":
            control.step(scenario.observe(control.position, control.cycle + 1))
        self.assertEqual(retained, scenario)
        self.assertEqual(actual.archive(), control.archive())
        before = state.read_bytes()
        self.assertEqual(run_session(state, steps=10)["executed_cycles"], 0)
        self.assertEqual(state.read_bytes(), before)
        with StateLock(state), self.assertRaises(AgentBusy):
            run_session(state, steps=1)

    def test_field_live_retry_after_restart_uses_declared_initial_position(self):
        config_path, state = self.root / "config.json", self.root / "live.json"
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["agent", "live-config", "--profile", "field",
                                   "--output", str(config_path)]), 0)
        config = LiveConfig.load(config_path)
        self.assertIs(type(config.manifest), FieldAgentManifest)
        with LiveSession(state, capacity=1, config=config) as session:
            ready = session.ready()
            request = {"protocol": PROTOCOL, "type": "observe", "producer": ready["producer"],
                       "epoch": ready["epoch"], "seq": ready["next"]["seq"],
                       "position": ready["next"]["position"],
                       "observations": {path: 0 for path in ready["next"]["paths"]}}
            self.assertEqual(request["position"], "k:0:0")
            first = session.handle(request)
        with LiveSession(state, capacity=12) as session:
            retried = session.handle(request)
            self.assertTrue(retried["duplicate"])
            self.assertFalse(first["duplicate"])
            self.assertEqual({key: value for key, value in retried.items() if key != "duplicate"},
                             {key: value for key, value in first.items() if key != "duplicate"})
        _, restored = load_live(state)
        self.addCleanup(restored.close)
        self.assertEqual(restored.cycle, 1)
        self.assertEqual(restored.energy, 98)

    def test_malformed_field_manifest_is_rejected_before_creating_session(self):
        scenario = Scenario(FieldAgentManifest(), changes=()).to_dict()
        scenario["agent"]["graph"] = {"k:0:0": []}
        path, state = self.root / "bad.json", self.root / "state.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        errors = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(errors):
            self.assertEqual(main(["agent", "run", "--state", str(state),
                                   "--scenario", str(path)]), 2)
        self.assertFalse(state.exists())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
