"""Optional real-device conformance checks against the established CPU profile.

An unavailable optional dependency or adapter skips these tests. Numerical,
shader, and policy errors on an available GPU remain failures.
"""

import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from solvefinite.gpu import GpuExecutor, GpuUnavailable
from solvefinite.motion import EnergyExhausted, move
from solvefinite.rp32 import pack, pair, unpair, unpack
from solvefinite.tomigidt import AgentManifest, Tomigidt
from solvefinite.world import World, WorldConfig


HAS_WGPU = importlib.util.find_spec("wgpu") is not None
PATHS = tuple(dict.fromkeys((
    "11", "", "0", "00", "1", "10", "01", "001", "0001", "0101",
    *("0" * depth for depth in range(1, 33)),
    *("1" * depth for depth in range(1, 33)),
    "01" * 16, "10" * 16, "1" + "0" * 31, "0" * 31 + "1",
)))


def cpu_forecast(config, agent_pair, route, hazards):
    world = World(config, capacity=1)
    states, costs = [], []
    for path, hazard in zip(route, hazards):
        agent_pair, cost = move(agent_pair, path, world, hazard)
        states.append(agent_pair)
        costs.append(cost)
    return tuple(states), tuple(costs)


def local_frame(agent, cycle):
    return {path: 70 if path == "00" and cycle >= 2 else 0
            for path in agent.visible_paths}


class OptionalGpuDependencyTests(unittest.TestCase):
    def test_missing_optional_dependency_is_explicit_failure_without_cpu_fallback(self):
        with patch.dict(sys.modules, {"wgpu": None}):
            with patch.object(World, "derive", side_effect=AssertionError("CPU fallback")):
                with self.assertRaises(GpuUnavailable):
                    GpuExecutor(WorldConfig(), ("", "0"))

    def test_initial_agent_pair_upload_failure_closes_created_executor(self):
        with patch("solvefinite.gpu.GpuExecutor") as factory:
            executor = factory.return_value
            executor.nodes = ()
            executor.commit_pair.side_effect = OSError("initial GPU upload failed")
            with self.assertRaisesRegex(OSError, "initial GPU upload failed"):
                Tomigidt(backend="gpu")
            factory.assert_called_once()
            executor.commit_pair.assert_called_once_with(pair(pack(250, 3, 100, 1)))
            executor.close.assert_called_once_with()


@unittest.skipUnless(HAS_WGPU, "Optional wgpu dependency is not installed")
class RealGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = WorldConfig(max_depth=32)
        try:
            cls.executor = GpuExecutor(cls.config, PATHS)
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.executor.close)

    def test_real_adapter_and_input_aligned_nodes_match_cpu_derivation(self):
        info = self.executor.adapter_info
        self.assertIs(type(info), dict)
        self.assertTrue(info)
        self.assertIn(info["adapter_type"], ("DiscreteGPU", "IntegratedGPU"))
        self.assertIs(type(self.executor.nodes), tuple)
        self.assertEqual(tuple(node.path for node in self.executor.nodes), PATHS)
        reference = World(self.config, 1)
        self.assertEqual(self.executor.nodes, tuple(reference.derive(path) for path in PATHS))
        for node in self.executor.nodes:
            self.assertEqual(node.log_radius, len(node.path))
            unpair(node.pair)

    def test_shader_derivation_handles_orientation_signed_endpoints_and_huge_field_changes(self):
        boundary_turns = ((0, 255), (255, 0), (128, 127), (127, 128))
        configurations = (
            WorldConfig(seed=(0, 255, -128, 0), max_depth=32, phase_turns=boundary_turns),
            WorldConfig(seed=(255, 0, 127, 127), max_depth=32, phase_turns=boundary_turns),
            WorldConfig(seed=(1, 128, -1, 16), max_depth=32, field_changes=(0, 0)),
            WorldConfig(seed=(254, 255, 0, 113), max_depth=32,
                        field_changes=(-(10 ** 100), 10 ** 100)),
            WorldConfig(seed=(128, 127, -128, 18), max_depth=32,
                        field_changes=(-255, 255)),
            WorldConfig(seed=(127, 128, 127, 2), max_depth=32,
                        field_changes=(-256, 256)),
        )
        for config in configurations:
            with self.subTest(seed=config.seed, changes=config.field_changes):
                reference = World(config, 1)
                expected = tuple(reference.derive(path) for path in PATHS)
                with GpuExecutor(config, iter(PATHS)) as executor:
                    self.assertEqual(executor.nodes, expected)
                    self.assertEqual(executor.nodes[PATHS.index("")].pair, pair(pack(*config.seed)))
                    for node in executor.nodes:
                        unpair(node.pair)

    def test_forecast_matches_shared_motion_for_orientation_and_repeated_nodes(self):
        route = ("", "0", "1", "00", "01", "10", "0")
        hazards = (0, 3, 0, 1, 2, 0, 0)
        configs = (self.config,
                   WorldConfig(seed=(255, 0, -128, 18), max_depth=32,
                               field_changes=(-(10 ** 100), 10 ** 100)))
        for config in configs:
            with GpuExecutor(config, PATHS) as executor:
                for seed in ((0, 0, 127, 1), (255, 255, 127, 17), (250, 3, 127, 113)):
                    with self.subTest(world_seed=config.seed, agent_seed=seed):
                        initial = pair(pack(*seed))
                        expected = cpu_forecast(config, initial, route, hazards)
                        actual = executor.forecast(initial, route, hazards)
                        self.assertEqual(actual, expected)
                        self.assertIs(type(actual), tuple)
                        self.assertIs(type(actual[0]), tuple)
                        self.assertIs(type(actual[1]), tuple)
                        for state in actual[0]:
                            unpair(state)

    def test_energy_boundaries_do_not_wrap_or_poison_subsequent_dispatch(self):
        exact = pair(pack(250, 3, 3, 1))
        states, costs = self.executor.forecast(exact, ("0",), (0,))
        self.assertEqual(costs, (3,))
        self.assertEqual(unpack(unpair(states[-1])[0])[2], 0)
        for seed, route, hazards in (
            ((250, 3, -1, 1), ("0",), (0,)),
            ((250, 3, 0, 1), ("0",), (0,)),
            ((250, 3, 4, 1), ("0", "00"), (0, 0)),
            ((250, 3, 127, 1), ("0",), (127,)),
        ):
            with self.subTest(seed=seed, route=route), self.assertRaises(EnergyExhausted):
                self.executor.forecast(pair(pack(*seed)), route, hazards)
        self.assertEqual(self.executor.forecast(exact, ("0",), (0,)), (states, costs))

    def test_empty_and_maximum_length_forecasts_keep_declared_boundaries(self):
        initial = pair(pack(250, 3, 100, 1))
        self.assertEqual(self.executor.forecast(initial, (), ()), ((), ()))
        route, hazards = ("",) * 32, (0,) * 32
        self.assertEqual(self.executor.forecast(initial, route, hazards),
                         cpu_forecast(self.config, initial, route, hazards))
        with self.assertRaises(ValueError):
            self.executor.forecast(initial, ("",) * 33, (0,) * 33)

    def test_closed_executor_cannot_dispatch_or_reenter_context(self):
        executor = GpuExecutor(self.config, ("", "0"))
        executor.close()
        executor.close()
        with self.assertRaises(ValueError):
            executor.forecast(pair(pack(250, 3, 100, 1)), ("0",), (0,))
        with self.assertRaises(ValueError):
            executor.__enter__()

    def test_unavailable_or_software_adapter_is_not_silently_replaced_by_cpu(self):
        for adapter in (None, SimpleNamespace(info={"adapter_type": "CPU"})):
            with self.subTest(adapter=adapter):
                with patch("wgpu.gpu.request_adapter_sync", return_value=adapter):
                    with patch.object(World, "derive", side_effect=AssertionError("CPU fallback")):
                        with self.assertRaises(GpuUnavailable):
                            GpuExecutor(self.config, ("", "0"))

    def test_invalid_forecast_inputs_reject_before_corrupting_gpu_state(self):
        initial = pair(pack(250, 3, 100, 1))
        valid = self.executor.forecast(initial, ("0", "00"), (0, 0))
        invalid = (
            (True, ("0",), (0,)), (-1, ("0",), (0,)), (1 << 64, ("0",), (0,)),
            (initial ^ 1, ("0",), (0,)),
            (initial, ("1010101",), (0,)), (initial, ("2",), (0,)),
            (initial, (None,), (0,)), (initial, ("0",), (True,)),
            (initial, ("0",), (-1,)), (initial, ("0",), (128,)),
            (initial, ("0",), (0.0,)), (initial, ("0",), ("0",)),
            (initial, ("0", "00"), (0,)), (initial, ("0",), (0, 0)),
            (initial, None, (0,)), (initial, ("0",), None),
        )
        for agent_pair, route, hazards in invalid:
            with self.subTest(agent_pair=agent_pair, route=route, hazards=hazards):
                with self.assertRaises(ValueError):
                    self.executor.forecast(agent_pair, route, hazards)
        self.assertEqual(self.executor.forecast(initial, ("0", "00"), (0, 0)), valid)

    def test_invalid_upload_configuration_and_paths_are_rejected(self):
        for config, paths in (
            ({}, ("",)), (None, ("",)), (self.config, ()),
            (self.config, ("0", "0")), (self.config, ("2",)),
            (self.config, (True,)), (self.config, ("0" * 33,)),
            (WorldConfig(max_depth=1), ("00",)), (self.config, None),
        ):
            with self.subTest(config=config, paths=paths), self.assertRaises(ValueError):
                GpuExecutor(config, paths)

    def test_gpu_computation_cannot_fall_back_to_cpu_world_derivation(self):
        paths = ("", "0", "00", "1", "11")
        seed = pair(pack(250, 3, 100, 17))
        expected_nodes = tuple(World(self.config, 1).derive(path) for path in paths)
        expected_motion = cpu_forecast(self.config, seed, ("0", "00", "11"), (2, 1, 0))
        with patch.object(World, "derive", side_effect=AssertionError("CPU derivation fallback")):
            with GpuExecutor(self.config, paths) as executor:
                self.assertEqual(executor.nodes, expected_nodes)
                self.assertEqual(executor.forecast(seed, ("0", "00", "11"), (2, 1, 0)),
                                 expected_motion)

    def test_gpu_agent_decisions_and_archive_equal_cpu_during_hazard_replanning(self):
        manifest = AgentManifest()
        cpu = Tomigidt(manifest, capacity=1)
        gpu = Tomigidt(manifest, capacity=8, backend="gpu")
        self.addCleanup(gpu.close)
        for cycle in range(1, 33):
            frame = local_frame(cpu, cycle)
            self.assertEqual(gpu.step(frame), cpu.step(frame))
            self.assertEqual(gpu.archive(), cpu.archive())
            if cycle == 2:
                restored = Tomigidt.from_archive(gpu.archive(), capacity=1, backend="gpu")
                self.addCleanup(restored.close)
                self.assertEqual(restored.archive(), cpu.archive())
                gpu.close()
                gpu = restored
            if cpu.status == "COMPLETE":
                break
        self.assertEqual((cpu.status, gpu.status), ("COMPLETE", "COMPLETE"))
        self.assertEqual(cpu.position, "11")
        self.assertEqual(unpack(unpair(gpu.agent_pair)[0])[2], 78)
        rebuilt = Tomigidt.from_archive(cpu.archive(), capacity=2, backend="gpu")
        self.addCleanup(rebuilt.close)
        self.assertEqual(rebuilt.archive(), gpu.archive())

    def test_gpu_agent_replays_incremental_search_and_partial_sensor_wait(self):
        manifest = AgentManifest(max_search_expansions=1)
        cpu = Tomigidt(manifest)
        gpu = Tomigidt(manifest, backend="gpu")
        self.addCleanup(gpu.close)
        for cycle in range(1, 65):
            frame = {} if cycle == 3 else {path: 0 for path in cpu.visible_paths}
            self.assertEqual(gpu.step(frame), cpu.step(frame))
            self.assertEqual(gpu.archive(), cpu.archive())
            if cycle == 3:
                self.assertEqual(cpu.status, "WAITING")
                restored = Tomigidt.from_archive(cpu.archive(), backend="gpu")
                self.addCleanup(restored.close)
                self.assertEqual(restored.archive(), gpu.archive())
                gpu.close()
                gpu = restored
            if cpu.status == "COMPLETE":
                break
        self.assertEqual((cpu.status, gpu.status), ("COMPLETE", "COMPLETE"))


if __name__ == "__main__":
    unittest.main()
