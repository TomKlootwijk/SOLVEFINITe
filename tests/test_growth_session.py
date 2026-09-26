"""GD6 durable current-geometry simulation, live admission and continuation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from solvefinite.field_agent import FieldAgentManifest, GROWTH_POLICY
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.f8 import IndexBinding
from solvefinite.growth import GrowthBinding
from solvefinite.live import LiveConfig, LiveProtocolError, LiveSession, PROTOCOL, load_live
from solvefinite.runtime import write_json
from solvefinite.session import Scenario, load_session, run_session
from solvefinite.tomigidt import Tomigidt


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = json.loads((ROOT / "docs/evidence/growth-v1/formal-reference.json").read_text())


def manifest(**kwargs):
    return FieldAgentManifest(policy=GROWTH_POLICY, **kwargs)


def scenario(spec=None):
    return Scenario(manifest() if spec is None else spec, changes=((2, "k:0:3", 70),))


def observe_request(response, observations=None):
    frame = response["next"]
    return {"protocol": PROTOCOL, "type": "observe",
            "producer": response["producer"], "epoch": response["epoch"],
            "seq": frame["seq"], "position": frame["position"],
            "geometry_epoch": frame["geometry_epoch"],
            "observations": dict.fromkeys(frame["paths"], 0) if observations is None else observations}


def advance_reference(session, first=0, stop=14):
    response = session.ready()
    sent = []
    for expected in REFERENCE["default_mission"]["events"][first:stop]:
        request = observe_request(response, expected["input"])
        sent.append(deepcopy(request))
        response = session.handle(request)
        if response["event"]["decision"]["kind"] != expected["kind"]:
            raise AssertionError((response["event"], expected))
        if response["state"]["energy"] != expected["state"]["energy"]:
            raise AssertionError((response["state"], expected["state"]))
    return response, sent


class GrowthSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="growth-session-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / "retained state.json"

    def test_simulator_uses_current_geometry_and_epoch_zero_hazards(self):
        configured = scenario()
        self.assertEqual(configured.observe("k:0:4", 2),
                         REFERENCE["default_mission"]["events"][1]["input"])
        self.assertEqual(configured.observe("k:6:4", 6, geometry_epoch=1),
                         REFERENCE["default_mission"]["events"][5]["input"])
        self.assertEqual(configured.observe("k:0:3", 8, geometry_epoch=1)["k:0:3"], 0)
        for invalid in (-1, 2, True, 1.0, "1", None):
            with self.subTest(epoch=invalid), self.assertRaises(ValueError):
                configured.observe("k:0:0", 1, geometry_epoch=invalid)
        with self.assertRaises(ValueError):
            configured.observe("k:6:4", 6)
        with self.assertRaises(ValueError):
            Scenario().observe("", 1, geometry_epoch=1)

    def test_split_session_growth_and_completion_match_independent_vectors(self):
        configuration = self.directory / "scenario.json"
        write_json(configuration, scenario().to_dict())
        repaired = run_session(self.path, steps=4, capacity=1, scenario_path=configuration)
        self.assertEqual((repaired["status"], repaired["cycle"], repaired["state"]["geometry_epoch"]),
                         ("GROWTH_PENDING", 4, 0))
        self.assertEqual(repaired["stop_reason"], "STEP_BUDGET_EXHAUSTED")
        grown = run_session(self.path, steps=1, capacity=3,
                            index_binding=IndexBinding(epoch=3, psi_sign=-1, phase_origin=17))
        self.assertEqual((grown["cycle"], grown["state"]["geometry_epoch"], grown["state"]["energy"]),
                         (5, 1, 85))
        self.assertEqual(grown["decisions"][0]["kind"], "GROW")
        complete = run_session(self.path, steps=32, capacity=1)
        self.assertEqual((complete["status"], complete["cycle"], complete["state"]["energy"]),
                         ("COMPLETE", 14, 64))
        configured, restored = load_session(self.path, capacity=12)
        try:
            self.assertEqual(configured, scenario())
            self.assertEqual(f"{restored.agent_pair:016X}", "160027E906002717")
            self.assertEqual(restored.manifest.world.width, 4)
            self.assertEqual(restored.current_recipe.width, 8)
            for event, expected in zip(restored.events, REFERENCE["default_mission"]["events"]):
                self.assertEqual(event["geometry_epoch"], expected["input_geometry_epoch"])
                self.assertEqual(event["decision"]["kind"], expected["kind"])
            before = self.path.read_bytes()
            noop = run_session(self.path, steps=32)
            self.assertEqual(noop["executed_cycles"], 0)
            self.assertEqual(self.path.read_bytes(), before)
        finally:
            restored.close()

    def test_two_generations_continue_without_resetting_individual(self):
        spec = manifest(world=KleinFieldRecipe(width=3, height=3, radius=1),
                        target="k:1:1", growth=GrowthBinding(max_epochs=2))
        configuration = self.directory / "two epochs.json"
        write_json(configuration, Scenario(spec, changes=()).to_dict())
        result = run_session(self.path, steps=64, scenario_path=configuration)
        self.assertEqual((result["status"], result["cycle"], result["state"]["geometry_epoch"],
                          result["state"]["energy"]), ("COMPLETE", 25, 2, 33))
        _, restored = load_session(self.path)
        try:
            self.assertEqual(f"{restored.agent_pair:016X}", "86000F0E16000FF2")
            self.assertEqual([e["seq"] for e in restored.events if e["growth"] is not None], [4, 10])
        finally:
            restored.close()

    def test_live_stale_epochs_locality_and_original_retries_after_reopen(self):
        with LiveSession(self.path, config=LiveConfig(manifest(), producer="local", epoch=12)) as live:
            response, sent = advance_reference(live, stop=5)
            self.assertEqual((response["epoch"], response["next"]["geometry_epoch"]), (12, 1))
            self.assertEqual(response["next"]["position"], "k:6:4")
            before = self.path.read_bytes()
            valid = observe_request(response)
            for invalid in (-1, 0, 2, True, 1.0, "1", None):
                damaged = deepcopy(valid); damaged["geometry_epoch"] = invalid
                with self.subTest(epoch=invalid), self.assertRaises(LiveProtocolError) as caught:
                    live.handle(damaged)
                self.assertEqual(caught.exception.code, "GEOMETRY_EPOCH")
            missing = deepcopy(valid); missing.pop("geometry_epoch")
            far = deepcopy(valid); far["observations"]["k:0:3"] = 0
            for damaged in (missing, far):
                with self.assertRaises(LiveProtocolError):
                    live.handle(damaged)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertTrue(live.handle(sent[0])["duplicate"])
            self.assertTrue(live.handle(sent[-1])["duplicate"])
            wrong_duplicate = deepcopy(sent[-1]); wrong_duplicate["geometry_epoch"] = 1
            with self.assertRaises(LiveProtocolError):
                live.handle(wrong_duplicate)
            self.assertEqual(self.path.read_bytes(), before)
        with LiveSession(self.path, capacity=1,
                         index_binding=IndexBinding(epoch=11, psi_sign=-1)) as restored:
            self.assertEqual(restored.ready()["state"]["geometry_epoch"], 1)
            for request in sent:
                self.assertTrue(restored.handle(request)["duplicate"])
            final, later = advance_reference(restored, first=5)
            self.assertEqual((final["state"]["cycle"], final["state"]["energy"]), (14, 64))
            self.assertIsNone(final["next"])
            self.assertTrue(restored.handle(later[0])["duplicate"])
        _, agent = load_live(self.path)
        try:
            self.assertEqual(f"{agent.agent_pair:016X}", "160027E906002717")
        finally:
            agent.close()

    def test_live_admits_new_geometry_hazards_without_replacing_world(self):
        with LiveSession(self.path, config=LiveConfig(manifest())) as live:
            response, _ = advance_reference(live, stop=5)
            request = observe_request(response)
            request["observations"][response["next"]["position"]] = 19
            result = live.handle(request)
            self.assertEqual(result["event"]["geometry_epoch"], 1)
            self.assertEqual(result["event"]["decision"]["kind"], "MOVE")
            self.assertEqual(result["state"]["current_recipe"], response["state"]["current_recipe"])
            bad = observe_request(result); bad["target"] = "k:0:0"
            with self.assertRaises(LiveProtocolError):
                live.handle(bad)

    def test_live_requires_new_complete_frames_before_and_after_growth(self):
        with LiveSession(self.path, config=LiveConfig(manifest())) as live:
            response, _ = advance_reference(live, stop=4)
            waiting = live.handle(observe_request(response, {}))
            self.assertEqual((waiting["event"]["decision"]["kind"], waiting["state"]["geometry_epoch"],
                              waiting["state"]["energy"]), ("WAIT", 0, 86))
            grown = live.handle(observe_request(waiting))
            self.assertEqual((grown["event"]["decision"]["kind"], grown["state"]["geometry_epoch"],
                              grown["state"]["energy"]), ("GROW", 1, 85))
            waiting = live.handle(observe_request(grown, {}))
            self.assertEqual((waiting["event"]["decision"]["kind"], waiting["state"]["position"],
                              waiting["state"]["energy"]), ("WAIT", "k:6:4", 85))
            moved = live.handle(observe_request(waiting))
            self.assertEqual(moved["event"]["decision"]["kind"], "MOVE")
            self.assertEqual(moved["event"]["geometry_epoch"], 1)

    def test_pure_growth_failure_preserves_live_owner_and_can_retry(self):
        with LiveSession(self.path, config=LiveConfig(manifest())) as live:
            response, _ = advance_reference(live, stop=4)
            request = observe_request(response, REFERENCE["default_mission"]["events"][4]["input"])
            before = self.path.read_bytes()
            with patch.object(Tomigidt, "step", side_effect=ValueError("candidate certificate rejected")):
                with self.assertRaisesRegex(ValueError, "certificate"):
                    live.handle(request)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertEqual(live.ready()["state"], response["state"])
            self.assertEqual(live.handle(request)["event"]["decision"]["kind"], "GROW")

    def test_uncertain_or_committed_step_failure_is_fatal_before_save(self):
        original = Tomigidt.step

        class CommittedFailure(RuntimeError):
            committed = True

        for committed in (False, True):
            with self.subTest(committed=committed):
                path = self.directory / f"step-{committed}.json"
                with LiveSession(path, config=LiveConfig(manifest())) as live:
                    response, _ = advance_reference(live, stop=4)
                    request = observe_request(response, REFERENCE["default_mission"]["events"][4]["input"])
                    before = path.read_bytes()

                    def failing_step(agent, observations):
                        if committed:
                            original(agent, observations)
                            raise CommittedFailure("committed growth cleanup failed")
                        agent.close()
                        raise RuntimeError("uncertain device mapping")

                    with patch.object(Tomigidt, "step", failing_step), patch("solvefinite.live.write_json") as save:
                        with self.assertRaises(RuntimeError):
                            live.handle(request)
                        save.assert_not_called()
                    with self.assertRaisesRegex(RuntimeError, "failed"):
                        live.ready()
                    self.assertEqual(path.read_bytes(), before)
                with LiveSession(path) as recovered:
                    self.assertEqual(recovered.ready()["state"]["cycle"], 4)
                    self.assertFalse(recovered.handle(request)["duplicate"])

    def test_atomic_write_failures_reopen_actual_durable_growth_prefix(self):
        for after_replace in (False, True):
            with self.subTest(after_replace=after_replace):
                path = self.directory / f"save-{after_replace}.json"
                with LiveSession(path, config=LiveConfig(manifest())) as live:
                    response, _ = advance_reference(live, stop=4)
                    request = observe_request(response, REFERENCE["default_mission"]["events"][4]["input"])

                    def failed_write(target, value):
                        if after_replace:
                            write_json(target, value)
                        raise OSError("durable save outcome uncertain")

                    with patch("solvefinite.live.write_json", failed_write):
                        with self.assertRaises(OSError):
                            live.handle(request)
                    with self.assertRaisesRegex(RuntimeError, "failed"):
                        live.handle({"protocol": PROTOCOL, "type": "status"})
                with LiveSession(path) as recovered:
                    result = recovered.handle(request)
                    self.assertEqual(result["duplicate"], after_replace)
                    self.assertEqual((result["state"]["cycle"], result["state"]["geometry_epoch"],
                                      result["state"]["energy"]), (5, 1, 85))

    def test_cli_exports_growth_and_resumes_same_history(self):
        configured, live_config = self.directory / "scenario.json", self.directory / "live.json"
        commands = [
            ["scenario", "--profile", "growth", "--output", str(configured)],
            ["live-config", "--profile", "growth", "--output", str(live_config)],
            ["run", "--state", str(self.path), "--scenario", str(configured), "--steps", "4"],
            ["run", "--state", str(self.path), "--steps", "32", "--index-sign", "-1"],
            ["inspect", str(self.path), "--index-phase-origin", "99"],
        ]
        for command in commands:
            completed = subprocess.run([sys.executable, "-m", "solvefinite", "agent", *command],
                                       cwd=ROOT, text=True, capture_output=True, timeout=90)
            self.assertEqual(completed.returncode, 0, completed.stderr)
        final = json.loads(completed.stdout)
        self.assertEqual((final["state"]["geometry_epoch"], final["state"]["energy"]), (1, 64))
        self.assertEqual(json.loads(live_config.read_text())["agent"]["policy"], GROWTH_POLICY)
        self.assertIn("execution_info", final)


@unittest.skipUnless(importlib.util.find_spec("wgpu") is not None, "Optional wgpu is not installed")
class RealGrowthContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from solvefinite.gpu import GpuUnavailable
        try:
            probe = Tomigidt(manifest(), backend="gpu")
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        probe.close()

    def fresh_process(self, path, backend, steps):
        result = subprocess.run([sys.executable, "-m", "solvefinite", "agent", "run",
                                 "--state", str(path), "--backend", backend,
                                 "--steps", str(steps), "--capacity", "1",
                                 "--index-sign", "-1", "--index-phase-origin", "67"],
                                cwd=ROOT, text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fresh_process_cpu_gpu_continuation_before_and_after_growth(self):
        with TemporaryDirectory(prefix="growth-cross-process-") as directory:
            directory = Path(directory)
            configured = directory / "scenario.json"
            write_json(configured, scenario().to_dict())
            archives = []
            for source, target in (("cpu", "gpu"), ("gpu", "cpu")):
                for cut in (4, 5):
                    path = directory / f"{source}-{cut}.json"
                    run_session(path, steps=cut, scenario_path=configured, backend=source)
                    final = self.fresh_process(path, target, 64)
                    self.assertEqual((final["status"], final["cycle"], final["state"]["energy"]),
                                     ("COMPLETE", 14, 64))
                    archives.append(json.loads(path.read_text())["agent"])
            self.assertTrue(all(value == archives[0] for value in archives[1:]))

    def test_fresh_process_cpu_gpu_retains_defer_cursor(self):
        with TemporaryDirectory(prefix="growth-defer-process-") as directory:
            directory = Path(directory)
            configured = directory / "scenario.json"
            write_json(configured, scenario(manifest(max_search_expansions=1)).to_dict())
            archives = []
            for source, target in (("cpu", "gpu"), ("gpu", "cpu")):
                path = directory / f"{source}.json"
                initial = run_session(path, steps=1, scenario_path=configured, backend=source)
                self.assertEqual(initial["status"], "SEARCH_DEFERRED")
                final = self.fresh_process(path, target, 2000)
                self.assertEqual(final["status"], "COMPLETE")
                self.assertEqual(final["state"]["geometry_epoch"], 1)
                archives.append(json.loads(path.read_text())["agent"])
            self.assertEqual(archives[0], archives[1])


if __name__ == "__main__":
    unittest.main()
