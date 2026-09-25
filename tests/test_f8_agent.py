"""Storage-version changes must leave the existing autonomous agent unchanged."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from solvefinite.__main__ import main
from solvefinite.f8 import F8Index, IndexBinding, MAX_EPOCH
from solvefinite.field_agent import FieldAgentManifest
from solvefinite.field_world import FieldWorld, KleinFieldRecipe
from solvefinite.live import LiveConfig, LiveSession, PROTOCOL, load_live
from solvefinite.session import Scenario, load_session, run_session
from solvefinite.tomigidt import AgentManifest, Tomigidt


ROOT = Path(__file__).resolve().parents[1]


def cache(world):
    return (world.capacity, world.active_paths, world.evicted_paths,
            world.hit_count, world.regeneration_count)


def mission(manifest=None):
    return Scenario(FieldAgentManifest() if manifest is None else manifest,
                    changes=((2, "k:0:3", 70),))


class F8AgentTests(unittest.TestCase):
    def agent(self, manifest=None, **kwargs):
        result = Tomigidt(FieldAgentManifest() if manifest is None else manifest, **kwargs)
        self.addCleanup(result.close)
        return result

    def test_derivation_walks_actual_tree_and_fifo_regenerates_across_versions(self):
        world = FieldWorld(KleinFieldRecipe(), 1)
        original = F8Index.lookup
        visited = []

        def observed(index, key):
            row = original(index, key)
            visited.append((index.binding.epoch, key[-1], row))
            return row

        with patch.object(F8Index, "lookup", observed):
            first = world.get("k:0:0")
            self.assertIs(world.get("k:0:0"), first)
            self.assertEqual(len(visited), 1)
            world.get("k:0:1")
            saved = cache(world)
            old = world.index
            world.reindex(psi_sign=-1, phase_origin=253)
            self.assertEqual(cache(world), saved)
            self.assertIsNot(world.index, old)
            rebuilt = world.get("k:0:0")
        self.assertEqual(first, rebuilt)
        self.assertIsNot(first, rebuilt)
        self.assertEqual(world.regeneration_count, 1)
        self.assertEqual([item[0] for item in visited], [0, 0, 1])
        self.assertTrue(any(node != row for _, node, row in visited))
        with patch.object(F8Index, "lookup", return_value=None):
            with self.assertRaises(ValueError):
                world.derive("k:0:2")

    def test_reindex_preserves_every_action_and_retained_deferred_search(self):
        for quantum in (1, 65536):
            with self.subTest(quantum=quantum):
                scenario = mission(replace(FieldAgentManifest(), max_search_expansions=quantum))
                control = self.agent(scenario.manifest, capacity=32)
                changing = self.agent(scenario.manifest, capacity=1,
                                      index_binding=IndexBinding(9, -1, 254))
                defer_count = 0
                while control.status != "COMPLETE":
                    self.assertLess(control.cycle, 64)
                    saved = changing.archive(), cache(changing.world)
                    planning = changing._planning
                    previous = changing.world.index
                    replacement = changing.reindex(psi_sign=(-1 if control.cycle % 2 else 1),
                                                   phase_origin=control.cycle * 29 % 256)
                    self.assertEqual(replacement.binding.epoch, previous.binding.epoch + 1)
                    self.assertIs(changing._planning, planning)
                    self.assertEqual((changing.archive(), cache(changing.world)), saved)
                    frame = scenario.observe(control.position, control.cycle + 1)
                    a, b = control.step(frame), changing.step(frame)
                    defer_count += b.kind == "DEFER"
                    self.assertEqual(a.to_dict(), b.to_dict())
                    self.assertEqual(control.archive(), changing.archive())
                self.assertEqual((f"{changing.agent_pair:016X}", changing.energy),
                                 ("06011145160111BB", 90))
                self.assertEqual(defer_count > 0, quantum == 1)
                replay = Tomigidt.from_archive(changing.archive(), capacity=3,
                                              index_binding=IndexBinding(170, 1, 33))
                self.addCleanup(replay.close)
                self.assertEqual(replay.archive(), changing.archive())
                self.assertNotIn("index", replay.snapshot())
                self.assertNotIn("index_binding", replay.archive())

    def test_candidate_failure_preserves_old_index_cache_history_and_search(self):
        agent = self.agent(replace(FieldAgentManifest(), max_search_expansions=1))
        agent.step({name: 0 for name in agent.visible_paths})
        original, planning = agent.world.index, agent._planning
        saved = agent.archive(), cache(agent.world)
        with patch.object(F8Index, "certified", side_effect=ValueError("certificate rejected")):
            with self.assertRaisesRegex(ValueError, "certificate rejected"):
                agent.reindex(psi_sign=-1)
        self.assertIs(agent.world.index, original)
        self.assertIs(agent._planning, planning)
        self.assertEqual((agent.archive(), cache(agent.world)), saved)
        self.assertFalse(agent._closed)
        agent.world.derive(agent.position)
        agent.step({name: 0 for name in agent.visible_paths})
        self.assertEqual(agent.cycle, 2)

    def test_invalid_rebuild_and_epoch_overflow_precede_field_compilation(self):
        agent = self.agent()
        exhausted = self.agent(index_binding=IndexBinding(MAX_EPOCH))
        for owner, kwargs in ((agent, {"psi_sign": True}), (agent, {"psi_sign": 0}),
                              (agent, {"phase_origin": 256}), (agent, {"phase_origin": 0.0}),
                              (exhausted, {})):
            before, index = owner.archive(), owner.world.index
            with patch("solvefinite.f8.evaluate_field", side_effect=AssertionError("compiled")):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    owner.reindex(**kwargs)
            self.assertIs(owner.world.index, index)
            self.assertEqual(owner.archive(), before)
        with self.assertRaises(ValueError):
            Tomigidt(AgentManifest(), index_binding=IndexBinding())
        binary = self.agent(AgentManifest())
        with self.assertRaises(ValueError):
            binary.reindex()
        agent.close()
        with self.assertRaises(ValueError):
            agent.reindex()

    def test_reindex_and_step_are_serialized_by_the_same_owner(self):
        agent = self.agent()
        entered, release, step_started = Event(), Event(), Event()
        original = F8Index.rebuild

        def gated(index, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Test failed to release replacement preparation")
            return original(index, **kwargs)

        def step():
            step_started.set()
            return agent.step({name: 0 for name in agent.visible_paths})

        with patch.object(F8Index, "rebuild", gated), ThreadPoolExecutor(2) as pool:
            replacement = pool.submit(agent.reindex, psi_sign=-1)
            try:
                self.assertTrue(entered.wait(5))
                action = pool.submit(step)
                self.assertTrue(step_started.wait(5))
                self.assertFalse(action.done())
                self.assertEqual(agent.cycle, 0)
            finally:
                release.set()
            self.assertEqual(replacement.result(timeout=5).binding.epoch, 1)
            self.assertEqual(action.result(timeout=5).kind, "MOVE")
        self.assertEqual(agent.cycle, 1)

    def test_tree_children_do_not_become_physical_movement(self):
        agent = self.agent(replace(FieldAgentManifest(), initial_node="k:0:1"))
        index = agent.world.index
        self.assertEqual((index.rows[0][4], index.rows[index.rows[0][5]][4]), (1, 16))
        with self.assertRaisesRegex(ValueError, "quotient edge"):
            agent.world.forecast(agent.agent_pair, ("k:3:1",), (0,))
        self.assertEqual(agent.cycle, 0)

    def test_live_rebuild_keeps_durable_bytes_and_retry_identity_across_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "live.json"
            with LiveSession(path, config=LiveConfig(FieldAgentManifest()), capacity=1) as session:
                ready = session.ready()
                request = {"protocol": PROTOCOL, "type": "observe", "producer": ready["producer"],
                           "epoch": ready["epoch"], "seq": ready["next"]["seq"],
                           "position": ready["next"]["position"],
                           "observations": {name: 0 for name in ready["next"]["paths"]}}
                acknowledged = session.handle(request)
                saved = path.read_bytes()
                session.reindex(psi_sign=-1, phase_origin=255)
                self.assertEqual(path.read_bytes(), saved)
                self.assertEqual(session.execution_info["index"]["version"]["binding"]["epoch"], 1)
                with self.assertRaises(ValueError):
                    session.reindex(phase_origin=-1)
                self.assertEqual(session.ready()["state"]["cycle"], 1)
            with LiveSession(path, capacity=20, index_binding=IndexBinding(18, 1, 122)) as session:
                retried = session.handle(request)
                self.assertTrue(retried["duplicate"])
                self.assertEqual({k: v for k, v in acknowledged.items() if k != "duplicate"},
                                 {k: v for k, v in retried.items() if k != "duplicate"})
                self.assertEqual(path.read_bytes(), saved)
            _, replay = load_live(path, index_binding=IndexBinding(77, -1, 4))
            self.addCleanup(replay.close)
            self.assertEqual(replay.cycle, 1)

    def test_cli_replays_different_index_version_and_inspection_is_read_only(self):
        with TemporaryDirectory() as folder:
            state, scenario_path = Path(folder) / "state.json", Path(folder) / "scenario.json"
            scenario = mission()
            scenario_path.write_text(json.dumps(scenario.to_dict()), encoding="utf-8")
            run_session(state, scenario_path=scenario_path, steps=1,
                        index_binding=IndexBinding(3, -1, 250))
            command = [sys.executable, "-m", "solvefinite", "agent"]
            child = subprocess.run(command + ["run", "--state", str(state), "--steps", "10",
                                               "--index-epoch", "12", "--index-sign", "1",
                                               "--index-phase-origin", "7"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(child.returncode, 0, child.stderr)
            result = json.loads(child.stdout)
            self.assertEqual(result["state"]["agent_pair"], "06011145160111BB")
            self.assertEqual(result["execution_info"]["index"]["version"]["binding"],
                             IndexBinding(12, 1, 7).to_dict())
            saved = state.read_bytes()
            inspect = subprocess.run(command + ["inspect", str(state),
                                                 "--index-sign", "-1"], cwd=ROOT,
                                     capture_output=True, text=True, timeout=30)
            self.assertEqual(inspect.returncode, 0, inspect.stderr)
            self.assertEqual(state.read_bytes(), saved)
            _, restored = load_session(state, index_binding=IndexBinding(22, -1, 255))
            self.addCleanup(restored.close)
            control = self.agent()
            while control.status != "COMPLETE":
                control.step(scenario.observe(control.position, control.cycle + 1))
            self.assertEqual(restored.archive(), control.archive())
            for name, flags in (("invalid", ["--index-phase-origin", "256"]),
                                ("binary", ["--index-sign", "-1"])):
                path = Path(folder) / f"{name}.json"
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(main(["agent", "run", "--state", str(path), *flags]), 2)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
