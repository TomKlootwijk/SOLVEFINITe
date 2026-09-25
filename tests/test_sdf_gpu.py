"""Optional real-GPU conformance for intrinsic signed fields and closed ticks."""

from copy import deepcopy
from dataclasses import replace
import importlib.util
import random
import sys
import unittest
from unittest.mock import patch

from solvefinite.field import FieldManifest, FieldMachine, evaluate_field
from solvefinite.gpu import GpuUnavailable
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.sdf_gpu import GpuFieldExecutor


HAS_WGPU = importlib.util.find_spec("wgpu") is not None


def graph_manifest(count, edges, signs, **changes):
    return FieldManifest(nodes=tuple(f"node-{index}" for index in range(count)),
                         edges=tuple(sorted(edges)), signs=tuple(signs),
                         routes=tuple((index, index, index) for index in range(count)),
                         turns=tuple((11, 53, 137) for _ in range(count)), **changes)


class OptionalFieldGpuTests(unittest.TestCase):
    def test_explicit_gpu_request_never_falls_back_when_dependency_is_missing(self):
        manifest = FieldManifest()
        with patch.dict(sys.modules, {"wgpu": None}):
            with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field fallback")):
                with self.assertRaises(GpuUnavailable):
                    FieldMachine(manifest, backend="gpu")


@unittest.skipUnless(HAS_WGPU, "Optional wgpu dependency is not installed")
class RealSdfGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldExecutor(FieldManifest())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def test_exact_default_gpu_field_and_field_selected_operator_trace(self):
        with GpuFieldExecutor(FieldManifest()) as executor:
            self.assertIn(executor.adapter_info["adapter_type"], ("DiscreteGPU", "IntegratedGPU"))
            self.assertEqual(executor.fields, (-6, -4, -3, 0, 2, 3, 5))
            expected = tuple(pair(pack(phase, node, field, Opcode.STEP))
                             for phase, node, field in ((5, 1, -4), (16, 2, -3),
                                                        (27, 3, 0), (80, 4, 2),
                                                        (217, 3, 0), (14, 4, 2)))
            self.assertEqual(executor.advance(6), expected)

    def test_multiple_boundaries_singleton_and_weighted_cycles_match_cpu_fields(self):
        cases = [replace(FieldManifest(), signs=(-1, 0, 1, 1, 0, -1, -1)),
                 graph_manifest(1, (), (0,)),
                 graph_manifest(6, ((0, 1, 7), (0, 3, 2), (1, 2, 1), (1, 4, 3),
                                    (2, 3, 6), (3, 4, 2), (4, 5, 5)), (1, 1, 0, 1, 1, 0))]
        rng = random.Random(1907)
        for count in (4, 9, 16):
            edges = {(index, index + 1): rng.randrange(1, 8) for index in range(count - 1)}
            for left in range(count):
                for right in range(left + 2, count):
                    if rng.random() < 0.2:
                        edges[left, right] = rng.randrange(1, 8)
            signs = tuple(0 if index in (0, count - 1) else 1 for index in range(count))
            cases.append(graph_manifest(count, tuple((a, b, w) for (a, b), w in edges.items()), signs))
        for manifest in cases:
            with self.subTest(nodes=len(manifest.nodes), signs=manifest.signs):
                cpu = FieldMachine(manifest)
                with GpuFieldExecutor(manifest) as executor:
                    self.assertEqual(executor.fields, cpu.fields)
                    self.assertEqual(executor.advance(11), cpu.advance(11))

    def test_maximum_node_index_and_representable_extreme_field_texture_row(self):
        manifest = graph_manifest(256, tuple((0, index, 127) for index in range(1, 256)),
                                  (0,) + (1,) * 255, initial_node=255)
        routes = list(manifest.routes)
        routes[0], routes[255] = (255, 255, 255), (0, 0, 0)
        manifest = replace(manifest, routes=tuple(routes))
        cpu = FieldMachine(manifest)
        with GpuFieldExecutor(manifest) as executor:
            self.assertEqual(executor.fields, (0,) + (127,) * 255)
            actual = executor.advance(8)
            self.assertEqual(actual, cpu.advance(8))
            self.assertEqual([unpack(unpair(value)[0])[1] for value in actual], [0, 255] * 4)
        negative = graph_manifest(3, ((0, 1, 127), (1, 2, 127)), (-1, 0, 1))
        with GpuFieldExecutor(negative) as executor:
            self.assertEqual(executor.fields, (-127, 0, 127))

    def test_unrepresentable_distances_fail_certification_without_signed_byte_wrap(self):
        for side in (-1, 1):
            manifest = graph_manifest(3, ((0, 1, 127), (1, 2, 1)), (0, side, side))
            with self.subTest(side=side), self.assertRaises(ValueError):
                GpuFieldExecutor(manifest)

    def test_reset_preserves_mirror_scalar_geometry_and_rejects_invalid_states(self):
        manifest = FieldManifest()
        first = pair(pack(31, 4, 2, int(Opcode.STEP) | 16))
        expected_machine = FieldMachine(replace(manifest, initial_node=4, initial_phase=31,
                                                initial_orientation=1))
        with GpuFieldExecutor(manifest) as executor:
            executor.reset(first)
            for invalid in (True, -1, 1 << 64, first ^ 1,
                            pair(pack(31, 255, 2, 17)), pair(pack(31, 4, 3, 17)),
                            pair(pack(31, 4, 2, Opcode.GROW)), pair(pack(31, 4, 2, 9))):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    executor.reset(invalid)
            self.assertEqual(executor.advance(32), expected_machine.advance(32))
        with GpuFieldExecutor(manifest) as forward, GpuFieldExecutor(
                replace(manifest, initial_phase=6, initial_orientation=1)) as mirrored:
            for original, reflected in zip(forward.advance(16), mirrored.advance(16)):
                left, right = unpair(original)
                self.assertEqual(unpair(reflected), (right, left))
                self.assertEqual(unpack(left)[2], unpack(right)[2])

    def test_invalid_advance_and_total_budget_do_not_mutate_device_progress(self):
        manifest = replace(FieldManifest(), max_ticks=5)
        cpu = FieldMachine(manifest)
        first_pair = cpu.agent_pair
        with GpuFieldExecutor(manifest) as executor:
            self.assertEqual(executor.advance(4), cpu.advance(4))
            for count in (0, -1, True, 1.0, "1", 4097, 2):
                with self.subTest(count=count), self.assertRaises(ValueError):
                    executor.advance(count)
            self.assertEqual(executor.advance(1), cpu.advance(1))
            with self.assertRaises(ValueError):
                executor.advance(1)
            executor.reset(first_pair)
            self.assertEqual(executor.advance(5), FieldMachine(manifest).advance(5))
        with self.assertRaises(ValueError):
            executor.advance(1)

    def test_split_gpu_batches_and_both_backend_replays_preserve_exact_archive(self):
        manifest = FieldManifest()
        cpu = FieldMachine(manifest)
        gpu = FieldMachine(manifest, backend="gpu")
        self.addCleanup(gpu.close)
        for steps in (1, 3, 7, 32, 4096):
            self.assertEqual(gpu.advance(steps), cpu.advance(steps))
            self.assertEqual(gpu.archive(), cpu.archive())
        for backend in ("cpu", "gpu"):
            with self.subTest(backend=backend):
                restored = FieldMachine.from_archive(cpu.archive(), backend=backend)
                self.addCleanup(restored.close)
                self.assertEqual(restored.archive(), gpu.archive())
                self.assertEqual(restored.advance(3), FieldMachine.from_archive(cpu.archive()).advance(3))

    def test_gpu_replay_rejects_valid_parity_transition_and_snapshot_tampering(self):
        cpu = FieldMachine()
        cpu.advance(4)
        original = cpu.archive()
        changed_trace = deepcopy(original)
        changed_trace["trace"][0] = f"{pair(pack(6, 1, -4, 1)):016X}"
        changed_snapshot = deepcopy(original)
        changed_snapshot["expected"]["tick"] = 3
        for damaged in (changed_trace, changed_snapshot):
            with self.subTest(archive=damaged), self.assertRaises(ValueError):
                FieldMachine.from_archive(damaged, backend="gpu")

    def test_gpu_field_and_operator_compilation_cannot_use_cpu_oracles_as_fallback(self):
        manifest = FieldManifest()
        expected_field = evaluate_field(manifest)
        expected_trace = FieldMachine(manifest).advance(64)
        with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field fallback")):
            with patch("solvefinite.field.build_operators", side_effect=AssertionError("CPU operator fallback")):
                with GpuFieldExecutor(manifest) as executor:
                    self.assertEqual(executor.fields, expected_field)
                    self.assertEqual(executor.advance(64), expected_trace)
                machine = FieldMachine(manifest, backend="gpu")
                self.addCleanup(machine.close)
                self.assertEqual(machine.advance(64), expected_trace)
                self.assertEqual(machine.execution_info["backend"], "gpu")


if __name__ == "__main__":
    unittest.main()
