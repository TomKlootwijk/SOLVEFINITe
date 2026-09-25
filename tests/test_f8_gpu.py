"""Actual-device PX construction, indirection, rebuild and failure witnesses."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import importlib.util
import struct
from threading import Event
import unittest
from unittest.mock import Mock, patch

from solvefinite.f8 import F8Index, IndexBinding, MAX_EPOCH
from solvefinite.field_agent import FieldAgentManifest
from solvefinite.field_agent_gpu import CommittedIndexCleanupError, GpuFieldAgentExecutor
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.tomigidt import Tomigidt
from tests.test_f8 import independent


def seed(executor, node=0, orientation=0):
    return pair(pack(249, node, executor.fields[node], int(Opcode.STEP) | orientation << 4))


def forbid_cpu_compilers():
    stack = ExitStack()
    for target in ("solvefinite.f8.F8Index.build", "solvefinite.f8._compile_records",
                   "solvefinite.f8._compile_rows", "solvefinite.f8.evaluate_field",
                   "solvefinite.psi.field_axes", "solvefinite.field.evaluate_field",
                   "solvefinite.field_world.evaluate_field", "solvefinite.field.build_operators"):
        stack.enter_context(patch(target, side_effect=AssertionError(f"CPU fallback: {target}")))
    return stack


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class F8GpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def executor(self, recipe=None, binding=None):
        executor = GpuFieldAgentExecutor(recipe or KleinFieldRecipe(), binding)
        self.addCleanup(executor.close)
        return executor

    def test_complete_default_and_256_node_keys_tree_and_device_lookups(self):
        for recipe in (KleinFieldRecipe(), KleinFieldRecipe(width=16, height=16, center=255)):
            with self.subTest(recipe=recipe):
                executor = self.executor(recipe)
                oracle = independent(recipe)
                self.assertEqual(executor.fields, oracle[3])
                self.assertEqual(executor.index.records, oracle[4])
                self.assertEqual(executor.index.rows, oracle[5])
                positions = {row[4]: index for index, row in enumerate(oracle[5])}
                for node in range(recipe.width * recipe.height):
                    self.assertEqual(executor.lookup_node(node), positions[node])
                self.assertNotEqual(tuple(positions[node] for node in range(len(positions))),
                                    tuple(range(len(positions))))
                if recipe.width == 4:
                    self.assertEqual(executor.index.records[16], (1, 3, 1, 22, 16, 8, 0, 4))
                    self.assertEqual(tuple(row[4] for row in executor.index.rows),
                                     (1, 16, 17, 18, 19, 15, 3, 4, 14, 13, 0, 11, 2, 12, 9, 6, 5, 10, 8, 7))

    def test_gpu_construction_rebuild_and_actual_moves_without_cpu_compilers(self):
        recipe = KleinFieldRecipe(width=16, height=16, center=255, turns=(0, 128, 255))
        with forbid_cpu_compilers():
            executor = self.executor(recipe)
            value = seed(executor, 255, 1)
            executor.seed(value, 100)
            domain = recipe.domain()
            node = 255
            route = []
            for direction in ("u+", "u-", "v+", "u-", "v-", "u+"):
                node, _ = domain.step(node, direction)
                route.append(domain.nodes[node])
            route, hazards = tuple(route), (0, 2, 1, 7, 0, 3)
            expected = executor.forecast(value, route, hazards)
            prior_index = executor.index
            for epoch, (sign, origin) in enumerate(((-1, 255), (1, 127), (-1, 0)), 1):
                actual = executor.reindex(psi_sign=sign, phase_origin=origin)
                oracle = independent(recipe, IndexBinding(epoch, sign, origin))
                self.assertEqual((actual.records, actual.rows), oracle[4:])
                self.assertIs(actual, executor.index)
                self.assertIsNot(actual, prior_index)
                prior_index = actual
                self.assertEqual(executor.snapshot(), (value, 100))
                self.assertEqual(executor.forecast(value, route, hazards), expected)
                for node in (0, 16, 127, 255):
                    self.assertEqual(executor.lookup_node(node), actual.resolve(node))
                    self.assertEqual(unpack(unpair(executor.derive_node(node))[0])[1], node)
            energy = 100
            for path, hazard, predicted, cost in zip(route, hazards, *expected):
                energy -= cost
                self.assertEqual(executor.advance_to(path, hazard), (predicted, cost, energy))
            self.assertEqual(executor.snapshot(), (expected[0][-1], energy))

    def test_metrics_include_complete_live_and_peak_candidate_bundles(self):
        executor = self.executor()
        before = executor.allocation_info
        count = len(executor.fields)
        self.assertEqual(before["host_index_payload_bytes"], 64 * count + 16)
        self.assertEqual(before["peak_rebuild_host_index_payload_bytes"], 64 * count + 16)
        self.assertEqual(before["peak_rebuild_device_payload_bytes"], before["device_payload_bytes"])
        old_bundle_bytes = sum(buffer.size for buffer in executor._bundle.buffers) + 48 * count
        executor.reindex(psi_sign=-1)
        after = executor.allocation_info
        self.assertEqual(after["device_payload_bytes"], before["device_payload_bytes"])
        self.assertEqual(after["peak_rebuild_device_payload_bytes"], before["device_payload_bytes"] + old_bundle_bytes)
        self.assertEqual(after["peak_rebuild_host_index_payload_bytes"], 2 * (64 * count + 16))
        self.assertEqual(after["retained_world_node_pair_count"], 0)
        self.assertEqual(after["index_version"], {"recipe": executor.recipe.to_dict(),
                                                  "binding": executor.index.binding.to_dict()})

    def test_forged_keys_and_tree_rows_gate_every_device_consumer(self):
        for consumer in ("lookup", "derive", "forecast", "actual"):
            for corruption in ("key", "identity", "clone", "link"):
                with self.subTest(consumer=consumer, corruption=corruption):
                    executor = self.executor()
                    value = seed(executor)
                    executor.seed(value, 100)
                    if corruption == "key":
                        words = list(executor.index.records[0])
                        words[3] ^= 1
                        target, offset = executor._bundle.records, 0
                    else:
                        words = list(executor.index.rows[0])
                        if corruption == "identity":
                            words[4] = 0
                        elif corruption == "clone":
                            words = list(executor.index.rows[executor.index.resolve(0)])
                        else:
                            words[6] = 0  # Root's right edge cycles, hiding G=0.
                        target, offset = executor._bundle.tree, 0
                    executor._device.queue.write_buffer(target, offset, struct.pack("<8I", *words))
                    with self.assertRaises(ValueError):
                        if consumer == "lookup":
                            executor.lookup_node(0)
                        elif consumer == "derive":
                            executor.derive_node(0)
                        elif consumer == "forecast":
                            executor.forecast(value, ("k:0:1",), (0,))
                        else:
                            executor.advance_to("k:0:1", 0)
                    self.assertTrue(executor.failed)
                    self.assertEqual((executor._pair, executor._energy, executor._ticks), (value, 100, 0))
                    canonical = struct.unpack("<4I", executor._device.queue.read_buffer(executor._canonical))
                    self.assertEqual(canonical, (*unpair(value), 100, 0))
                    with self.assertRaises(ValueError):
                        executor.advance_to("k:0:1", 0)
                    executor.close()

    def test_invalid_binding_and_epoch_overflow_precede_device_allocation(self):
        for binding in (None, IndexBinding(epoch=MAX_EPOCH)):
            executor = self.executor(binding=binding)
            previous = executor.index
            with patch.object(executor._device, "create_buffer", side_effect=AssertionError("allocation")), \
                    patch.object(executor._device.queue, "write_buffer", side_effect=AssertionError("write")):
                calls = ({"psi_sign": True}, {"psi_sign": 0}, {"phase_origin": -1}, {"phase_origin": 256})
                if binding is not None:
                    calls += ({},)
                for kwargs in calls:
                    with self.assertRaises(ValueError):
                        executor.reindex(**kwargs)
            self.assertIs(executor.index, previous)
            self.assertFalse(executor.failed)
            self.assertEqual(executor.lookup_node(0), previous.resolve(0))

    def test_pure_certificate_rejection_preserves_old_bundle_and_canonical_state(self):
        executor = self.executor()
        value = seed(executor)
        executor.seed(value, 100)
        old = executor._bundle
        with patch.object(F8Index, "certified", side_effect=ValueError("candidate certificate")):
            with self.assertRaisesRegex(ValueError, "candidate certificate"):
                executor.reindex(psi_sign=-1)
        self.assertIs(executor._bundle, old)
        self.assertFalse(executor.failed)
        self.assertFalse(old.closed)
        self.assertEqual(executor.snapshot(), (value, 100))
        self.assertEqual(executor.lookup_node(0), old.index.resolve(0))

    def test_partial_candidate_allocation_is_destroyed_without_poisoning_old_version(self):
        executor = self.executor()
        old = executor._bundle
        allocated = []
        create = executor._device.create_buffer

        def fail_second(**kwargs):
            if allocated:
                raise RuntimeError("candidate allocation")
            buffer = create(**kwargs)
            buffer.destroy = Mock(wraps=buffer.destroy)
            allocated.append(buffer)
            return buffer

        with patch.object(executor._device, "create_buffer", side_effect=fail_second), \
                patch.object(executor._device.queue, "write_buffer", side_effect=AssertionError("premature write")):
            with self.assertRaisesRegex(RuntimeError, "candidate allocation"):
                executor.reindex()
        allocated[0].destroy.assert_called_once_with()
        self.assertIs(executor._bundle, old)
        self.assertFalse(executor.failed)
        self.assertEqual(executor.lookup_node(0), old.index.resolve(0))

    def test_uncertain_candidate_readback_closes_owner_without_admitting_version(self):
        executor = self.executor()
        value = seed(executor)
        executor.seed(value, 100)
        previous = executor.index
        with patch.object(executor._device.queue, "read_buffer", side_effect=RuntimeError("candidate readback")):
            with self.assertRaisesRegex(RuntimeError, "candidate readback"):
                executor.reindex(phase_origin=42)
        self.assertIs(executor.index, previous)
        self.assertTrue(executor.failed)
        self.assertTrue(executor._closed)
        self.assertTrue(executor._geometry._closed)
        self.assertEqual((executor._pair, executor._energy, executor._ticks), (value, 100, 0))

    def test_invalid_device_candidate_is_rejected_by_unmodified_certificate(self):
        executor = self.executor()
        previous = executor.index
        read_buffer = executor._device.queue.read_buffer
        reads = []

        def corrupt_record(buffer, *args, **kwargs):
            result = read_buffer(buffer, *args, **kwargs)
            if not reads:
                result = bytearray(result)
                struct.pack_into("<I", result, 5 * 4, 7)  # Impossible eigenvalue for node zero.
            reads.append(buffer)
            return result

        with patch.object(executor._device.queue, "read_buffer", side_effect=corrupt_record):
            with self.assertRaises(ValueError):
                executor.reindex(phase_origin=1)
        self.assertIs(executor.index, previous)
        self.assertFalse(executor.failed)
        self.assertFalse(executor._closed)
        self.assertEqual(executor.lookup_node(0), previous.resolve(0))

    def test_cleanup_after_swap_reports_committed_version_and_closes_every_owner(self):
        executor = self.executor()
        old = executor._bundle
        destroy = old.texture.destroy
        old.texture.destroy = Mock(side_effect=RuntimeError("old texture cleanup"))
        try:
            with self.assertRaisesRegex(CommittedIndexCleanupError, "committed") as caught:
                executor.reindex(psi_sign=-1, phase_origin=255)
            self.assertTrue(caught.exception.committed)
            self.assertEqual(executor.index.binding, IndexBinding(1, -1, 255))
            self.assertIsNot(executor._bundle, old)
            self.assertTrue(executor.failed)
            self.assertTrue(executor._closed)
            self.assertTrue(executor._bundle.closed)
            self.assertTrue(executor._geometry._closed)
            old.texture.destroy.assert_called_once_with()
        finally:
            destroy()

    def test_close_attempts_every_bundle_resource_after_first_buffer_failure(self):
        executor = self.executor()
        bundle = executor._bundle
        original = bundle.buffers[0].destroy
        bundle.buffers[0].destroy = Mock(side_effect=RuntimeError("first bundle buffer"))
        others = [*bundle.buffers[1:], bundle.texture]
        for resource in others:
            resource.destroy = Mock(wraps=resource.destroy)
        try:
            with self.assertRaisesRegex(RuntimeError, "first bundle buffer"):
                executor.close()
            for resource in others:
                resource.destroy.assert_called_once_with()
            self.assertTrue(executor._geometry._closed)
            executor.close()
            bundle.buffers[0].destroy.assert_called_once_with()
        finally:
            original()

    def test_owner_reindex_faults_preserve_archive_and_recover_deferred_search(self):
        for fault in ("certificate", "readback", "cleanup"):
            with self.subTest(fault=fault):
                agent = Tomigidt(FieldAgentManifest(max_search_expansions=1), backend="gpu", capacity=1)
                self.addCleanup(agent.close)
                frame = {name: 0 for name in agent.visible_paths}
                self.assertEqual(agent.step(frame).kind, "DEFER")
                archive, snapshot = agent.archive(), agent.snapshot()
                old = agent._gpu._bundle
                cleanup = None
                if fault == "certificate":
                    injection = patch.object(F8Index, "certified", side_effect=ValueError("rejected certificate"))
                    error = ValueError
                elif fault == "readback":
                    injection = patch.object(agent._gpu._device.queue, "read_buffer",
                                             side_effect=RuntimeError("uncertain readback"))
                    error = RuntimeError
                else:
                    cleanup = old.texture.destroy
                    injection = patch.object(old.texture, "destroy", side_effect=RuntimeError("retire failed"))
                    error = CommittedIndexCleanupError
                try:
                    with injection, self.assertRaises(error):
                        agent.reindex(psi_sign=-1, phase_origin=29)
                finally:
                    if cleanup is not None:
                        cleanup()
                self.assertEqual(agent.archive(), archive)
                self.assertEqual(agent.snapshot(), snapshot)
                self.assertEqual(agent.world.index.binding.epoch, int(fault == "cleanup"))
                self.assertEqual(agent._closed, fault != "certificate")
                self.assertEqual(agent._gpu.failed, fault != "certificate")
                control = Tomigidt.from_archive(archive, index_binding=IndexBinding(5, 1, 10))
                self.addCleanup(control.close)
                with forbid_cpu_compilers():
                    recovered = Tomigidt.from_archive(archive, backend="gpu", index_binding=IndexBinding(8, -1, 90))
                    self.addCleanup(recovered.close)
                    recovered.step(frame)
                control.step(frame)
                self.assertEqual(recovered.archive(), control.archive())
                self.assertEqual(recovered._gpu.snapshot(), (control.agent_pair, control.energy))

    def test_public_device_operations_wait_for_whole_candidate_admission(self):
        executor = self.executor()
        entered, release, operation_started, operation_finished = Event(), Event(), Event(), Event()
        certify = F8Index.certified

        def held_certificate(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("test release was not signaled")
            return certify(*args)

        def lookup():
            operation_started.set()
            result = executor.lookup_node(0)
            operation_finished.set()
            return result

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(F8Index, "certified", side_effect=held_certificate):
            rebuild = pool.submit(executor.reindex, psi_sign=-1)
            try:
                self.assertTrue(entered.wait(5))
                operation = pool.submit(lookup)
                self.assertTrue(operation_started.wait(5))
                self.assertFalse(operation_finished.wait(0.05))
            finally:
                release.set()
            index = rebuild.result(5)
            self.assertEqual(operation.result(5), index.resolve(0))

    def test_live_defer_rebuild_preserves_fifo_frontier_and_cross_backend_replay(self):
        manifest = FieldAgentManifest(max_search_expansions=1)
        cpu = Tomigidt(manifest, capacity=32)
        self.addCleanup(cpu.close)
        with forbid_cpu_compilers():
            gpu = Tomigidt(manifest, capacity=1, backend="gpu")
            self.addCleanup(gpu.close)
            frame = {name: 0 for name in gpu.visible_paths}
            # CPU oracle is run outside the forbidden compiler region below.
            self.assertEqual(gpu.step(frame).kind, "DEFER")
        cpu.step(frame)
        self.assertEqual(gpu.archive(), cpu.archive())
        for epoch, (sign, origin) in enumerate(((-1, 0), (1, 255), (-1, 127)), 1):
            previous = gpu.archive()
            state = gpu.snapshot()
            residency = (gpu.world.active_paths, gpu.world.evicted_paths,
                         gpu.world.regeneration_count, gpu.world.capacity)
            with forbid_cpu_compilers():
                index = gpu.reindex(psi_sign=sign, phase_origin=origin)
            self.assertEqual(index.binding.epoch, epoch)
            self.assertEqual(gpu.archive(), previous)
            self.assertEqual(gpu.snapshot(), state)
            self.assertEqual((gpu.world.active_paths, gpu.world.evicted_paths,
                              gpu.world.regeneration_count, gpu.world.capacity), residency)
            self.assertEqual(gpu._gpu.snapshot(), (gpu.agent_pair, gpu.energy))
        restored_cpu = Tomigidt.from_archive(gpu.archive(), capacity=2, index_binding=IndexBinding(9, 1, 45))
        self.addCleanup(restored_cpu.close)
        with forbid_cpu_compilers():
            restored_gpu = Tomigidt.from_archive(gpu.archive(), capacity=2, backend="gpu",
                                                 index_binding=IndexBinding(27, -1, 254))
            self.addCleanup(restored_gpu.close)
        for _ in range(128):
            frame = {name: 0 for name in gpu.visible_paths}
            expected = cpu.step(frame)
            self.assertEqual(restored_cpu.step(frame), expected)
            with forbid_cpu_compilers():
                self.assertEqual(gpu.step(frame), expected)
                self.assertEqual(restored_gpu.step(frame), expected)
            for candidate in (gpu, restored_cpu, restored_gpu):
                self.assertEqual(candidate.archive(), cpu.archive())
            if expected.kind == "MOVE":
                break
        else:
            self.fail("Retained search did not reach its first admitted move")


if __name__ == "__main__":
    unittest.main()
