"""GD5 actual-device dyadic mapping, admission, failure and resource witnesses."""

from dataclasses import replace
import gc
import importlib.util
import struct
import unittest
from unittest.mock import patch

from solvefinite.f8 import IndexBinding
from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.hadamard import HadamardBinding
from solvefinite.motion import EnergyExhausted
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from tests.test_f8 import independent
from tests.test_hadamard_gpu import no_cpu_routing, predict


def doubled(recipe):
    """Test-side production without the runtime growth helper."""
    u, v = divmod(recipe.center, recipe.height)
    return replace(recipe, width=2 * recipe.width, height=2 * recipe.height,
                   center=4 * u * recipe.height + 2 * v, radius=2 * recipe.radius)


def mapped(recipe, node):
    u, v = divmod(node, recipe.height)
    return 4 * u * recipe.height + 2 * v


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class GrowthGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe(), routing=HadamardBinding())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def executor(self, recipe=None, routing=None, index=None):
        owner = GpuFieldAgentExecutor(recipe or KleinFieldRecipe(), index,
                                      routing=routing or HadamardBinding())
        self.addCleanup(owner.close)
        return owner

    def completed(self, recipe=None, node=17, phase=187, eta=1, energy=100):
        owner = self.executor(recipe)
        fields = independent(owner.recipe)[3]
        owner.seed(pair(pack(phase, node, fields[node], int(Opcode.STEP) | eta << 4)), energy)
        owner.repair(5)
        return owner

    def assert_source(self, source, original):
        self.assertFalse(source.failed)
        self.assertFalse(source._closed)
        self.assertEqual(source.snapshot(), original)
        self.assertTrue(source._terminal)

    def test_actual_mapping_recomputes_field_and_never_host_seeds(self):
        # Here B(E(0))=-4 while 2*B(0)=-6, exposing a simple doubling shortcut.
        recipe = KleinFieldRecipe(width=3, height=5, center=1, radius=3)
        source = self.completed(recipe, node=0, phase=221, eta=1)
        before = source.snapshot()
        new_recipe = doubled(recipe)
        fields = independent(new_recipe)[3]
        self.assertNotEqual(fields[0], 2 * unpack(unpair(before[0])[0])[2])
        with no_cpu_routing():
            candidate = self.executor(new_recipe, index=IndexBinding(31, -1, 217))
            with patch.object(candidate, "seed", side_effect=AssertionError("host-seeded mapping")):
                result = candidate.admit_growth(source, 7)
        self.assertEqual(result, (pair(pack(221, 0, -4, int(Opcode.STEP) | 16)), 88))
        self.assertEqual(candidate.snapshot(), result)
        self.assertEqual(candidate._ticks, 0)
        self.assertFalse(candidate._terminal)
        self.assert_source(source, before)

    def test_all_canonical_sources_and_both_mirrors(self):
        recipe = KleinFieldRecipe()
        fields = independent(recipe)[3]
        new_recipe = doubled(recipe)
        new_fields = independent(new_recipe)[3]
        # Every source identity, with both mirror orientations and wrapped R.
        for node in range(len(fields)):
            results = []
            for eta in (0, 1):
                with self.subTest(node=node, eta=eta):
                    phase = (255 if node % 2 else 0)
                    phase = (-phase if eta else phase) & 255
                    source = self.completed(recipe, node=node, phase=phase, eta=eta)
                    candidate = self.executor(new_recipe)
                    result = candidate.admit_growth(source, 1)
                    destination = mapped(recipe, node)
                    self.assertEqual(result, (pair(pack(phase, destination, new_fields[destination],
                                                       int(Opcode.STEP) | eta << 4)), 94))
                    results.append(result[0])
                    source.close()
                    candidate.close()
                    # unittest cleanup callbacks otherwise retain all 80
                    # executor/device object graphs until this method ends.
                    self.doCleanups()
                    del source, candidate
                    gc.collect()
            self.assertEqual(unpair(results[1]), unpair(results[0])[::-1])

    def test_two_device_generations_continue_actual_hadamard_motion(self):
        recipe = KleinFieldRecipe(width=3, height=3, center=8, radius=1)
        source = self.completed(recipe, node=8, phase=0, eta=1)
        with no_cpu_routing():
            for epoch in (1, 2):
                previous = source.snapshot()
                candidate = self.executor(doubled(source.recipe), index=IndexBinding(epoch, -1, 255))
                actual, energy = candidate.admit_growth(source, 1)
                self.assert_source(source, previous)
                node = unpack(unpair(actual)[0])[1]
                destination = candidate.routing_model.neighbors[node][0]
                path = candidate._nodes[destination]
                expected, costs = predict(candidate.recipe, HadamardBinding(), actual, (destination,), (3,))
                self.assertEqual(candidate.forecast(actual, (path,), (3,)), (expected, costs))
                moved, cost, remaining = candidate.advance_to(path, 3)
                self.assertEqual((moved, cost, remaining), (expected[0], costs[0], energy - costs[0]))
                candidate.repair(5)
                source = candidate
        self.assertEqual(source.recipe.width * source.recipe.height, 144)

    def test_maximum_candidate_and_complete_old_plus_new_accounting(self):
        recipe = KleinFieldRecipe(width=8, height=8, center=63, radius=2)
        source = self.completed(recipe, node=63)
        candidate = self.executor(doubled(recipe))
        old, new = source.allocation_info, candidate.allocation_info
        total = old["device_payload_bytes"] + new["device_payload_bytes"]
        expected_buffers = sum(buffer.size for owner in (source, candidate)
                               for buffer in owner._buffers + owner._geometry._buffers + owner._bundle.buffers)
        self.assertEqual(total, expected_buffers + (12 + 384) * (64 + 256))
        buffers = tuple(candidate._buffers)
        candidate.admit_growth(source, 1)
        self.assertEqual(tuple(candidate._buffers), buffers)
        self.assertEqual(candidate.allocation_info["device_payload_bytes"], new["device_payload_bytes"])

    def test_invalid_candidate_contexts_and_costs_are_pure(self):
        source = self.completed()
        before = source.snapshot()
        valid = doubled(source.recipe)
        cases = (replace(valid, center=2), replace(valid, radius=3),
                 replace(valid, turns=(12, 53, 137)), replace(valid, baseline_id="other"),
                 source.recipe)
        for recipe in cases:
            candidate = self.executor(recipe)
            with patch.object(candidate, "_dispatch", side_effect=AssertionError("invalid dispatch")):
                with self.assertRaises(ValueError):
                    candidate.admit_growth(source, 1)
            self.assertFalse(candidate.failed)
            self.assertFalse(candidate._seeded)
            self.assert_source(source, before)
        candidate = self.executor(valid)
        for cost in (True, 0, 128, 1.0, "1"):
            with self.assertRaises(ValueError):
                candidate.admit_growth(source, cost)
        with self.assertRaises(EnergyExhausted):
            candidate.admit_growth(source, 96)
        self.assert_source(source, before)

    def test_requires_repaired_source_matching_routing_and_once_only(self):
        source = self.executor()
        fields = independent(source.recipe)[3]
        candidate = self.executor(doubled(source.recipe))
        with self.assertRaises(ValueError):
            candidate.admit_growth(source, 1)
        source.seed(pair(pack(0, 0, fields[0], Opcode.STEP)), 100)
        with self.assertRaises(ValueError):
            candidate.admit_growth(source, 1)
        source.repair(5)
        different = self.executor(doubled(source.recipe), routing=HadamardBinding(((0, 0),) * 4))
        with self.assertRaises(ValueError):
            different.admit_growth(source, 1)
        candidate.admit_growth(source, 1)
        snapshot = candidate.snapshot()
        with self.assertRaises(ValueError):
            candidate.admit_growth(source, 1)
        with self.assertRaises(ValueError):
            candidate.seed(*snapshot)
        self.assertEqual(candidate.snapshot(), snapshot)

    def test_complete_output_or_canonical_certificate_rejection_is_pure(self):
        source = self.completed()
        before = source.snapshot()
        for arena in ("output", "canonical"):
            with self.subTest(arena=arena):
                candidate = self.executor(doubled(source.recipe))
                read = candidate._device.queue.read_buffer

                def corrupt(buffer, *args, **kwargs):
                    raw = bytes(read(buffer, *args, **kwargs))
                    if buffer is (candidate._output if arena == "output" else candidate._canonical):
                        words = list(struct.unpack(f"<{len(raw) // 4}I", raw))
                        # Parity-independent separate-energy disagreement.
                        words[3 if arena == "output" else 2] += 1
                        return struct.pack(f"<{len(words)}I", *words)
                    return raw

                with patch.object(candidate._device.queue, "read_buffer", side_effect=corrupt):
                    with self.assertRaises(ValueError) as failure:
                        candidate.admit_growth(source, 1)
                self.assertFalse(failure.exception.device_uncertain)
                self.assertFalse(candidate.failed)
                self.assertTrue(candidate._closed)
                self.assert_source(source, before)

    def test_shader_rejects_corrupted_old_pair_before_canonical_mapping(self):
        source = self.completed()
        before = source.snapshot()
        for fault in ("mirror", "opcode", "field", "height", "energy"):
            with self.subTest(fault=fault):
                candidate = self.executor(doubled(source.recipe))
                write = candidate._device.queue.write_buffer

                def corrupt(buffer, offset, data, *args, **kwargs):
                    if buffer is candidate._jobs:
                        words = list(struct.unpack("<8I", data))
                        if fault == "mirror":
                            words[1] ^= 1
                        elif fault == "opcode":
                            r, g, b, a = unpack(words[0])
                            words[:2] = unpair(pair(pack(r, g, b, (a & 16) | Opcode.STEP)))
                        elif fault == "field":
                            words[6] = (words[6] + 1) & 0xffffffff
                        elif fault == "height":
                            words[3] = 0
                        else:
                            words[2] = 0
                        data = struct.pack("<8I", *words)
                    return write(buffer, offset, data, *args, **kwargs)

                with patch.object(candidate._device.queue, "write_buffer", side_effect=corrupt):
                    with self.assertRaisesRegex(ValueError, "status") as failure:
                        candidate.admit_growth(source, 1)
                self.assertFalse(failure.exception.device_uncertain)
                self.assert_source(source, before)

    def test_device_field_mutation_cannot_be_replaced_by_host_doubling(self):
        source = self.completed()
        before = source.snapshot()
        candidate = self.executor(doubled(source.recipe))
        destination = mapped(source.recipe, unpack(unpair(before[0])[0])[1])
        candidate._device.queue.write_buffer(candidate._geometry._field_buffer, 4 * destination,
                                             struct.pack("<i", candidate.fields[destination] + 1))
        with self.assertRaises(ValueError) as failure:
            candidate.admit_growth(source, 1)
        self.assertFalse(failure.exception.device_uncertain)
        self.assert_source(source, before)

    def test_uncertain_candidate_dispatch_and_each_readback_close_candidate(self):
        source = self.completed()
        before = source.snapshot()
        for fault in ("dispatch", "output", "canonical", "short_output", "short_canonical"):
            with self.subTest(fault=fault):
                candidate = self.executor(doubled(source.recipe))
                read = candidate._device.queue.read_buffer

                def fail_read(buffer, *args, **kwargs):
                    selected = candidate._canonical if "canonical" in fault else candidate._output
                    if buffer is selected:
                        if fault.startswith("short"):
                            return b""
                        raise RuntimeError("uncertain growth read")
                    return read(buffer, *args, **kwargs)

                injection = patch.object(candidate, "_dispatch", side_effect=RuntimeError("uncertain growth dispatch")) \
                    if fault == "dispatch" else patch.object(candidate._device.queue, "read_buffer", side_effect=fail_read)
                with injection:
                    with self.assertRaises((RuntimeError, ValueError, struct.error)) as failure:
                        candidate.admit_growth(source, 1)
                self.assertTrue(failure.exception.device_uncertain)
                self.assertTrue(failure.exception.candidate_failed)
                self.assertTrue(candidate.failed)
                self.assertTrue(candidate._closed)
                self.assert_source(source, before)

    def test_uncertain_old_readback_closes_source_without_candidate_dispatch(self):
        source = self.completed()
        candidate = self.executor(doubled(source.recipe))
        with patch.object(source._device.queue, "read_buffer", side_effect=RuntimeError("old readback")), \
                patch.object(candidate, "_dispatch", side_effect=AssertionError("premature mapping")):
            with self.assertRaisesRegex(RuntimeError, "old readback"):
                candidate.admit_growth(source, 1)
        self.assertTrue(source.failed)
        self.assertTrue(source._closed)
        self.assertFalse(candidate.failed)
        self.assertFalse(candidate._seeded)

    def test_composed_constructor_uncertainty_preserves_exception_type(self):
        source = self.completed()
        before = source.snapshot()
        queue_type = type(source._device.queue)
        for short in (False, True):
            with self.subTest(short=short):
                action = (lambda *args, **kwargs: b"") if short else RuntimeError("construction readback")
                with patch.object(queue_type, "read_buffer", side_effect=action):
                    with self.assertRaises((RuntimeError, struct.error)) as failure:
                        GpuFieldAgentExecutor(doubled(source.recipe), routing=HadamardBinding())
                self.assertTrue(failure.exception.device_uncertain)
                self.assertTrue(failure.exception.candidate_failed)
                self.assert_source(source, before)

    def test_composed_constructor_complete_field_rejection_is_pure(self):
        source = self.completed()
        before = source.snapshot()
        failure = ValueError("pure candidate field certificate")
        with patch("solvefinite.field.certify_field", side_effect=failure):
            with self.assertRaisesRegex(ValueError, "pure candidate field") as received:
                GpuFieldAgentExecutor(doubled(source.recipe), routing=HadamardBinding())
        self.assertIs(received.exception, failure)
        self.assertFalse(failure.device_uncertain)
        self.assertFalse(failure.candidate_failed)
        self.assert_source(source, before)

    def test_constructor_early_write_is_uncertain_but_allocation_is_pure(self):
        source = self.completed()
        before = source.snapshot()
        for operation in ("write", "allocate"):
            with self.subTest(operation=operation):
                target, name = ((type(source._device.queue), "write_buffer") if operation == "write"
                                else (type(source._device), "create_buffer"))
                failure = RuntimeError("early candidate " + operation)
                with patch.object(target, name, side_effect=failure):
                    with self.assertRaises(RuntimeError) as received:
                        GpuFieldAgentExecutor(doubled(source.recipe), routing=HadamardBinding())
                self.assertIs(received.exception, failure)
                self.assertEqual(failure.device_uncertain, operation == "write")
                self.assert_source(source, before)

    def test_constructor_final_state_fence_and_hadamard_certificate(self):
        source = self.completed()
        before = source.snapshot()
        queue_type = type(source._device.queue)
        read = queue_type.read_buffer

        def fail_final(queue, buffer, *args, **kwargs):
            if buffer.size == 16:
                raise RuntimeError("candidate final state fence")
            return read(queue, buffer, *args, **kwargs)

        with patch.object(queue_type, "read_buffer", new=fail_final):
            with self.assertRaisesRegex(RuntimeError, "final state fence") as failure:
                GpuFieldAgentExecutor(doubled(source.recipe), routing=HadamardBinding())
        self.assertTrue(failure.exception.device_uncertain)
        with patch("solvefinite.field_agent_gpu.RoutingModel.certified",
                   side_effect=ValueError("candidate Hadamard certificate")):
            with self.assertRaisesRegex(ValueError, "Hadamard certificate") as failure:
                GpuFieldAgentExecutor(doubled(source.recipe), routing=HadamardBinding())
        self.assertFalse(failure.exception.device_uncertain)
        self.assert_source(source, before)

    def growth_owner(self):
        from solvefinite.field_agent import FieldAgentManifest, GROWTH_POLICY
        from solvefinite.tomigidt import Tomigidt
        agent = Tomigidt(FieldAgentManifest(policy=GROWTH_POLICY, target="k:0:0"),
                        capacity=1, backend="gpu")
        self.addCleanup(agent.close)
        self.assertEqual(agent.step(dict.fromkeys(agent.visible_paths, 0)).kind, "REPAIR")
        self.assertEqual(agent.status, "GROWTH_PENDING")
        return agent

    @staticmethod
    def cache_state(world):
        return world.active_paths, world.evicted_paths, world.hit_count, world.regeneration_count

    def test_owner_pure_complete_candidate_rejection_preserves_history_and_tracks_peak(self):
        agent = self.growth_owner()
        old_world, old_gpu = agent.world, agent._gpu
        before = agent.archive(), self.cache_state(old_world), old_gpu.snapshot()
        self.assertEqual(agent.execution_info["growth"]["peak_preparation_payload"], {})
        admit, candidates = GpuFieldAgentExecutor.admit_growth, []

        def rejected(candidate, source, cost):
            candidates.append(candidate)
            read = candidate._device.queue.read_buffer

            def corrupt(buffer, *args, **kwargs):
                raw = bytes(read(buffer, *args, **kwargs))
                if buffer is candidate._output:
                    values = list(struct.unpack("<8I", raw))
                    values[3] += 1
                    return struct.pack("<8I", *values)
                return raw

            with patch.object(candidate._device.queue, "read_buffer", side_effect=corrupt):
                return admit(candidate, source, cost)

        with patch.object(GpuFieldAgentExecutor, "admit_growth", new=rejected):
            with self.assertRaisesRegex(ValueError, "growth disagrees") as failure:
                agent.step(dict.fromkeys(agent.visible_paths, 0))
        self.assertFalse(failure.exception.device_uncertain)
        self.assertFalse(agent.closed)
        self.assertIs(agent.world, old_world)
        self.assertIs(agent._gpu, old_gpu)
        self.assertEqual((agent.archive(), self.cache_state(old_world), old_gpu.snapshot()), before)
        self.assertTrue(candidates[0]._closed)
        self.assertGreater(agent.execution_info["growth"]["peak_preparation_payload"]["device_payload_bytes"],
                           old_gpu.allocation_info["device_payload_bytes"])
        self.assertEqual(agent.step(dict.fromkeys(agent.visible_paths, 0)).kind, "GROW")
        self.assertEqual((agent.cycle, agent.geometry_epoch, agent.energy), (2, 1, 94))

    def test_owner_uncertain_detached_constructor_and_admission_close_without_event(self):
        for stage in ("constructor", "admission"):
            with self.subTest(stage=stage):
                agent = self.growth_owner()
                old_world, old_gpu = agent.world, agent._gpu
                before = agent.archive(), self.cache_state(old_world)
                admit = GpuFieldAgentExecutor.admit_growth

                def uncertain(candidate, source, cost):
                    with patch.object(candidate._device.queue, "read_buffer",
                                      side_effect=RuntimeError("uncertain detached admission")):
                        return admit(candidate, source, cost)

                queue_type = type(old_gpu._device.queue)
                read = queue_type.read_buffer

                def fail_construction(queue, buffer, *args, **kwargs):
                    if buffer.size == 4 * (4 * len(old_gpu.fields)):
                        raise RuntimeError("uncertain detached constructor")
                    return read(queue, buffer, *args, **kwargs)

                injection = patch.object(queue_type, "read_buffer", new=fail_construction) \
                    if stage == "constructor" else patch.object(GpuFieldAgentExecutor, "admit_growth", new=uncertain)
                with injection:
                    with self.assertRaisesRegex(RuntimeError, "uncertain detached") as failure:
                        agent.step(dict.fromkeys(agent.visible_paths, 0))
                self.assertTrue(failure.exception.device_uncertain)
                self.assertTrue(agent.closed)
                self.assertTrue(old_gpu._closed)
                self.assertIs(agent.world, old_world)
                self.assertEqual((agent.archive(), self.cache_state(old_world)), before)

    def test_owner_uncertain_old_canonical_read_closes_without_event(self):
        agent = self.growth_owner()
        old_world, old_gpu = agent.world, agent._gpu
        before = agent.archive(), self.cache_state(old_world)
        read = old_gpu._device.queue.read_buffer

        def fail_old(buffer, *args, **kwargs):
            if buffer is old_gpu._canonical:
                raise RuntimeError("uncertain old canonical state")
            return read(buffer, *args, **kwargs)

        with patch.object(old_gpu._device.queue, "read_buffer", side_effect=fail_old):
            with self.assertRaisesRegex(RuntimeError, "uncertain old canonical"):
                agent.step(dict.fromkeys(agent.visible_paths, 0))
        self.assertTrue(old_gpu.failed)
        self.assertTrue(agent.closed)
        self.assertIs(agent.world, old_world)
        self.assertEqual((agent.archive(), self.cache_state(old_world)), before)


if __name__ == "__main__":
    unittest.main()
