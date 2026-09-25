"""Actual-device execution and failure admission for the integrated field agent."""

import importlib.util
import unittest
from threading import RLock
from unittest.mock import Mock, patch

from solvefinite.field import FieldManifest, evaluate_field
from solvefinite.field_agent_gpu import GpuFieldAgentExecutor, MAX_ENERGY, _IndexBundle
from solvefinite.field_world import FieldWorld, KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.motion import EnergyExhausted
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.sdf_gpu import GpuFieldExecutor


HAS_WGPU = importlib.util.find_spec("wgpu") is not None


def initial_pair(fields, node=0, phase=250, orientation=0):
    return pair(pack(phase, node, fields[node], int(Opcode.STEP) | (orientation << 4)))


def walk(recipe, start, directions):
    domain = recipe.domain()
    node = start
    route = []
    for direction in directions:
        node, _ = domain.step(node, direction)
        route.append(domain.nodes[node])
    return tuple(route)


class FieldAgentGpuOwnershipTests(unittest.TestCase):
    def test_close_attempts_all_resources_after_a_destroy_failure(self):
        owner = object.__new__(GpuFieldAgentExecutor)
        owner._closed = False
        owner._lock = RLock()
        first, second, texture, geometry = Mock(), Mock(), Mock(), Mock()
        first.destroy.side_effect = RuntimeError("destroy failure")
        owner._buffers = [first, second]
        owner._texture, owner._geometry = texture, geometry
        owner._bundle = _IndexBundle()
        owner._bundle.texture = texture
        with self.assertRaisesRegex(RuntimeError, "destroy failure"):
            owner.close()
        for resource in (first, second, texture):
            resource.destroy.assert_called_once_with()
        geometry.close.assert_called_once_with()
        owner.close()
        geometry.close.assert_called_once_with()


@unittest.skipUnless(HAS_WGPU, "Optional wgpu dependency is not installed")
class RealFieldAgentGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def test_device_samples_regenerate_without_retaining_a_packed_world_arena(self):
        for recipe in (KleinFieldRecipe(), KleinFieldRecipe(width=16, height=16)):
            fields = evaluate_field(recipe.field_manifest())
            with self.subTest(size=(recipe.width, recipe.height)), GpuFieldAgentExecutor(recipe) as executor:
                self.assertEqual(executor.recipe, recipe)
                self.assertEqual(executor.fields, fields)
                self.assertIn(executor.adapter_info["adapter_type"], ("DiscreteGPU", "IntegratedGPU"))
                for index in sorted({0, 1, 15, 31, 32, len(fields) - 1} & set(range(len(fields)))):
                    expected = pair(pack(0, index, fields[index], Opcode.DATA))
                    self.assertEqual(executor.derive_node(index), expected)
                    self.assertEqual(executor.derive_node(index), expected)
                sizes = executor.allocation_info
                self.assertEqual(sizes["device_texture_bytes"], 60 * len(fields))
                self.assertEqual(sizes["device_payload_bytes"],
                                 sizes["device_buffer_bytes"] + sizes["device_texture_bytes"])
                self.assertEqual(sizes["retained_world_node_pair_count"], 0)
                self.assertEqual(sizes["host_field_code_payload_bytes"], 4 * len(fields))
                self.assertGreater(sizes["device_buffer_bytes"],
                                   sum(buffer.size for buffer in executor._geometry._buffers))
                # Exercise the highest texture row and both seam directions,
                # including node 255 and its reverse traversal at the limit.
                seed = initial_pair(fields, node=len(fields) - 1, orientation=1)
                route = walk(recipe, len(fields) - 1, ("u+", "u-"))
                expected, costs = FieldWorld(recipe, 1).forecast(seed, route, (0, 0))
                executor.seed(seed, 100)
                self.assertEqual(executor.forecast(seed, route, (0, 0)), (expected, costs))
                remaining = 100
                for destination, predicted, cost in zip(route, expected, costs):
                    remaining -= cost
                    self.assertEqual(executor.advance_to(destination, 0), (predicted, cost, remaining))

    def test_arbitrary_neighbor_forecast_and_actual_moves_match_k8_in_both_orientations(self):
        recipe = KleinFieldRecipe(radius=1, turns=(0, 128, 255))
        domain = recipe.domain()
        route = walk(recipe, 0, ("u-", "u+", "v+", "u+", "v-", "u-"))
        hazards = (0, 1, 127, 7, 0, 3)
        for orientation in (0, 1):
            with self.subTest(orientation=orientation), GpuFieldAgentExecutor(recipe) as executor:
                seed = initial_pair(executor.fields, phase=37, orientation=orientation)
                executor.seed(seed, MAX_ENERGY)
                forecast, costs = executor.forecast(seed, route, hazards)
                self.assertEqual(executor.snapshot(), (seed, MAX_ENERGY))
                node, phase, eta = 0, 37, orientation
                fields_seen = set()
                expected_energy = MAX_ENERGY
                for destination, hazard, predicted, cost in zip(route, hazards, forecast, costs):
                    signed = executor.fields[node]
                    fields_seen.add((signed > 0) - (signed < 0))
                    column = 0 if signed < 0 else 1 if signed == 0 else 2
                    target = recipe.index(destination)
                    tau = int(tuple(sorted((node, target))) in domain.seams)
                    phase = (phase + (-1 if eta else 1) * recipe.turns[column]) % 256
                    phase = (-phase if tau else phase) % 256
                    eta ^= tau
                    expected = pair(pack(phase, target, executor.fields[target], 1 | (eta << 4)))
                    self.assertEqual(predicted, expected)
                    self.assertEqual(cost, 1 + abs(executor.fields[target]) + hazard)
                    actual, actual_cost, energy = executor.advance_to(destination, hazard)
                    self.assertEqual((actual, actual_cost), (predicted, cost))
                    expected_energy -= cost
                    self.assertEqual(energy, expected_energy)
                    self.assertEqual(executor.snapshot(), (actual, energy))
                    self.assertIn(unpack(unpair(actual)[0])[3], (1, 17))
                    node = target
                self.assertEqual(fields_seen, {-1, 0, 1})
                self.assertEqual(executor.snapshot()[1], MAX_ENERGY - sum(costs))

    def test_forecast_matches_cpu_and_handles_all_255_hops_without_advancing_owner(self):
        recipe = KleinFieldRecipe(width=5, height=4)
        world = FieldWorld(recipe, capacity=1)
        route = walk(recipe, 0, ("u+",) * 255)
        hazards = tuple(index % 128 for index in range(255))
        with GpuFieldAgentExecutor(recipe) as executor:
            seed = initial_pair(executor.fields, orientation=1)
            expected = world.forecast(seed, route, hazards)
            # Independent forecast need not fit the canonical live energy.
            executor.seed(seed, 0)
            self.assertEqual(executor.forecast(seed, route, hazards), expected)
            self.assertEqual(executor.snapshot(), (seed, 0))
            self.assertEqual(executor.forecast(seed, (), ()), ((), ()))
            self.assertEqual(executor.snapshot(), (seed, 0))

    def test_repair_keeps_negative_sdf_and_mirror_while_debiting_separate_energy(self):
        recipe = KleinFieldRecipe()
        with GpuFieldAgentExecutor(recipe) as executor:
            seed = initial_pair(executor.fields, phase=19, orientation=1)
            self.assertLess(executor.fields[0], 0)
            executor.seed(seed, MAX_ENERGY)
            value, energy = executor.repair(7)
            self.assertEqual(unpack(unpair(value)[0]), (19, 0, executor.fields[0], 22))
            self.assertEqual(energy, MAX_ENERGY - 7)
            self.assertEqual(executor.snapshot(), (value, energy))
            for action in (lambda: executor.repair(1),
                           lambda: executor.advance_to(recipe.domain().nodes[1], 0)):
                with self.assertRaises(ValueError):
                    action()
                self.assertFalse(executor.failed)
            self.assertEqual(executor.snapshot(), (value, energy))

    def test_insufficient_energy_and_invalid_inputs_do_not_write_or_poison(self):
        recipe = KleinFieldRecipe()
        route = walk(recipe, 0, ("u+",))
        with GpuFieldAgentExecutor(recipe) as executor:
            seed = initial_pair(executor.fields)
            for energy in (-1, MAX_ENERGY + 1, True, 1.0):
                with self.subTest(energy=energy), self.assertRaises(ValueError):
                    executor.seed(seed, energy)
                self.assertFalse(executor.failed)
            executor.seed(seed, 0)
            for action in (lambda: executor.advance_to(route[0], 0), lambda: executor.repair(1)):
                with self.assertRaises(EnergyExhausted):
                    action()
                self.assertFalse(executor.failed)
            bad_pair = pair(pack(250, 0, executor.fields[0] + 1, Opcode.STEP))
            invalid = (
                lambda: executor.seed(seed, 10),
                lambda: executor.derive_node(True),
                lambda: executor.derive_node(len(executor.fields)),
                lambda: executor.forecast(bad_pair, (), ()),
                lambda: executor.forecast(seed, ("k:00:0",), (0,)),
                lambda: executor.forecast(seed, ("k:1:1",), (0,)),
                lambda: executor.forecast(seed, ("k:0:0",), (0,)),
                lambda: executor.forecast(seed, route, (True,)),
                lambda: executor.forecast(seed, route, (128,)),
                lambda: executor.forecast(seed, route, ()),
                lambda: executor.forecast(seed, list(route), (0,)),
                lambda: executor.forecast(seed, route, [0]),
                lambda: executor.forecast(seed, route * 256, (0,) * 256),
                lambda: executor.advance_to("k:00:0", 0),
                lambda: executor.advance_to("k:1:1", 0),
                lambda: executor.advance_to(route[0], True),
                lambda: executor.repair(0),
                lambda: executor.repair(128),
            )
            for action in invalid:
                with self.subTest(action=action), self.assertRaises(ValueError):
                    action()
                self.assertFalse(executor.failed)
            self.assertEqual(executor.snapshot(), (seed, 0))

    def test_real_device_execution_cannot_call_cpu_field_sample_or_transition_oracles(self):
        recipe = KleinFieldRecipe()
        world = FieldWorld(recipe, capacity=1)
        fields = evaluate_field(recipe.field_manifest())
        seed = initial_pair(fields)
        route = walk(recipe, 0, ("v-", "u-", "v+"))
        hazards = (0, 0, 0)
        expected, costs = world.forecast(seed, route, hazards)
        with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field")), \
                patch("solvefinite.field.build_operators", side_effect=AssertionError("CPU operator")), \
                patch.object(FieldManifest, "seam", side_effect=AssertionError("CPU seam")), \
                patch.object(FieldWorld, "derive", side_effect=AssertionError("CPU sample")), \
                patch.object(FieldWorld, "forecast", side_effect=AssertionError("CPU forecast")):
            with GpuFieldAgentExecutor(recipe) as executor:
                executor.seed(seed, 100)
                self.assertEqual(executor.fields, fields)
                self.assertEqual(executor.derive_node(0), pair(pack(0, 0, fields[0], 0)))
                self.assertEqual(executor.forecast(seed, route, hazards), (expected, costs))
                energy = 100
                for destination, hazard, predicted, cost in zip(route, hazards, expected, costs):
                    energy -= cost
                    self.assertEqual(executor.advance_to(destination, hazard), (predicted, cost, energy))
                emitted, remaining = executor.repair(5)
                self.assertEqual(remaining, energy - 5)
                self.assertEqual(unpack(unpair(emitted)[0])[:3], unpack(unpair(expected[-1])[0])[:3])

    def test_gpu_fifo_regeneration_and_forecast_never_call_cpu_field_evaluation(self):
        recipe = KleinFieldRecipe()
        with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field")), \
                patch("solvefinite.field_world.evaluate_field", side_effect=AssertionError("CPU world field")):
            with GpuFieldAgentExecutor(recipe) as executor:
                world = FieldWorld(recipe, capacity=1, executor=executor)
                seed = initial_pair(executor.fields)
                executor.seed(seed, 100)
                with patch.object(executor, "derive_node", wraps=executor.derive_node) as derived:
                    first = world.get("k:0:0")
                    world.get("k:0:1")
                    regenerated = world.get("k:0:0")
                    self.assertEqual(first, regenerated)
                    self.assertEqual(derived.call_count, 3)
                    self.assertEqual(world.regeneration_count, 1)
                    self.assertEqual(world.active_paths, ("k:0:0",))
                    world.get("k:0:0")
                    self.assertEqual(derived.call_count, 3)
                    route = walk(recipe, 0, ("u-", "v+"))
                    world.forecast(seed, route, (0, 0))
                    self.assertEqual(world.active_paths, ("k:0:0",))
                    self.assertEqual(derived.call_count, 3)
                    self.assertEqual(executor.snapshot(), (seed, 100))

    def test_reference_mission_decisions_archives_and_replay_match_cpu_without_fallback(self):
        from solvefinite.field_agent import FieldAgentManifest
        from solvefinite.session import Scenario
        from solvefinite.tomigidt import Tomigidt

        manifest = FieldAgentManifest()
        scenario = Scenario(manifest, changes=((2, "k:0:3", 70),))
        cpu = Tomigidt(manifest, capacity=1)
        self.addCleanup(cpu.close)
        expected = []
        for _ in range(4):
            frame = scenario.observe(cpu.position, cpu.cycle + 1)
            cpu.step(frame)
            expected.append((frame, cpu.archive()))
        self.assertEqual(cpu.status, "COMPLETE")
        self.assertEqual(cpu.energy, 90)
        with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field")), \
                patch("solvefinite.field_world.evaluate_field", side_effect=AssertionError("CPU world field")), \
                patch("solvefinite.field.build_operators", side_effect=AssertionError("CPU operators")), \
                patch.object(FieldManifest, "seam", side_effect=AssertionError("CPU transition seam")):
            gpu = Tomigidt(manifest, capacity=2, backend="gpu")
            self.addCleanup(gpu.close)
            for frame, archive in expected:
                gpu.step(frame)
                self.assertEqual(gpu.archive(), archive)
                self.assertEqual(gpu._gpu.snapshot(), (gpu.agent_pair, gpu.energy))
            restored = Tomigidt.from_archive(cpu.archive(), capacity=1, backend="gpu")
            self.addCleanup(restored.close)
            self.assertEqual(restored.archive(), cpu.archive())
            self.assertEqual(restored._gpu.snapshot(), (cpu.agent_pair, cpu.energy))

    def test_uncertain_device_failure_poisoning_and_idempotent_close(self):
        recipe = KleinFieldRecipe()
        executor = GpuFieldAgentExecutor(recipe)
        self.addCleanup(executor.close)
        executor.seed(initial_pair(executor.fields), 100)
        with patch.object(executor._device.queue, "write_buffer", side_effect=RuntimeError("device failure")):
            with self.assertRaisesRegex(RuntimeError, "device failure"):
                executor.derive_node(0)
        self.assertTrue(executor.failed)
        with self.assertRaisesRegex(ValueError, "failed"):
            executor.snapshot()
        with self.assertRaisesRegex(ValueError, "failed"):
            executor.derive_node(0)
        executor.close()
        executor.close()
        with self.assertRaisesRegex(ValueError, "closed"):
            executor.derive_node(0)

    def test_readback_failure_after_actual_dispatch_prevents_further_actions(self):
        recipe = KleinFieldRecipe()
        with GpuFieldAgentExecutor(recipe) as executor:
            seed = initial_pair(executor.fields)
            executor.seed(seed, 100)
            with patch.object(executor._device.queue, "read_buffer", side_effect=RuntimeError("readback failed")):
                with self.assertRaisesRegex(RuntimeError, "readback failed"):
                    executor.advance_to("k:0:1", 0)
            self.assertTrue(executor.failed)
            self.assertEqual((executor._pair, executor._energy), (seed, 100))
            with self.assertRaisesRegex(ValueError, "failed"):
                executor.advance_to("k:0:1", 0)

    def test_owner_closes_on_actual_prediction_mismatch_without_admitting_an_event(self):
        from solvefinite.field_agent import FieldAgentManifest
        from solvefinite.tomigidt import Tomigidt

        agent = Tomigidt(FieldAgentManifest(), backend="gpu")
        self.addCleanup(agent.close)
        previous = agent.archive()
        original_advance = agent._gpu.advance_to

        def changed_result(destination, hazard):
            value, cost, energy = original_advance(destination, hazard)
            phase, node, signed, metadata = unpack(unpair(value)[0])
            return pair(pack((phase + 1) % 256, node, signed, metadata)), cost, energy

        with patch.object(agent._gpu, "advance_to", side_effect=changed_result):
            with self.assertRaisesRegex(ValueError, "admitted prediction"):
                agent.step({name: 0 for name in agent.visible_paths})
        self.assertTrue(agent._closed)
        self.assertTrue(agent._gpu._closed)
        self.assertEqual(agent.archive(), previous)
        frame = {name: 0 for name in agent.visible_paths}
        control = Tomigidt.from_archive(previous)
        recovered = Tomigidt.from_archive(previous, backend="gpu")
        self.addCleanup(control.close)
        self.addCleanup(recovered.close)
        control.step(frame)
        recovered.step(frame)
        self.assertEqual(recovered.archive(), control.archive())
        self.assertEqual(recovered._gpu.snapshot(), (control.agent_pair, control.energy))

    def test_owner_recovers_prior_archive_after_uncertain_actual_seam_move(self):
        from solvefinite.field_agent import FieldAgentManifest
        from solvefinite.session import Scenario
        from solvefinite.tomigidt import Tomigidt

        manifest = FieldAgentManifest()
        scenario = Scenario(manifest, changes=((2, "k:0:3", 70),))
        agent = Tomigidt(manifest, backend="gpu")
        self.addCleanup(agent.close)
        agent.step(scenario.observe(agent.position, 1))
        previous = agent.archive()
        frame = scenario.observe(agent.position, 2)
        original_advance = agent._gpu.advance_to

        def failed_readback(destination, hazard):
            with patch.object(agent._gpu._device.queue, "read_buffer", side_effect=RuntimeError("action readback")):
                return original_advance(destination, hazard)

        with patch.object(agent._gpu, "advance_to", side_effect=failed_readback):
            with self.assertRaisesRegex(RuntimeError, "action readback"):
                agent.step(frame)
        self.assertTrue(agent._gpu.failed)
        self.assertTrue(agent._closed)
        self.assertTrue(agent._gpu._closed)
        self.assertEqual(agent.archive(), previous)
        control = Tomigidt.from_archive(previous)
        recovered = Tomigidt.from_archive(previous, backend="gpu")
        self.addCleanup(control.close)
        self.addCleanup(recovered.close)
        control.step(frame)
        recovered.step(frame)
        self.assertEqual(recovered.archive(), control.archive())
        self.assertEqual(recovered._gpu.snapshot(), (control.agent_pair, control.energy))
        self.assertEqual(unpack(unpair(recovered.agent_pair)[0])[3], 17)

    def test_partial_construction_releases_own_buffers_and_composed_geometry(self):
        captured = []
        original_close = GpuFieldExecutor.close

        def interrupted(owner):
            buffer = owner._buffer(16)
            destroyed = Mock(wraps=buffer.destroy)
            buffer.destroy = destroyed
            captured.append((owner, destroyed))
            raise RuntimeError("interrupted initialization")

        with patch.object(GpuFieldAgentExecutor, "_initialize", interrupted), \
                patch.object(GpuFieldExecutor, "close", autospec=True, side_effect=original_close) as closed:
            with self.assertRaisesRegex(RuntimeError, "interrupted initialization"):
                GpuFieldAgentExecutor(KleinFieldRecipe())
        self.assertEqual(closed.call_count, 1)
        owner, destroyed = captured[0]
        self.assertTrue(owner._closed)
        self.assertTrue(owner._geometry._closed)
        destroyed.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
