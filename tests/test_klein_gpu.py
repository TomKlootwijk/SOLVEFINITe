"""Optional actual-device conformance for versioned seam-transport fields."""

from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from solvefinite.field import FieldManifest, FieldMachine, evaluate_field
from solvefinite.gpu import GpuUnavailable
from solvefinite.klein import KleinDomain
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.sdf_gpu import GpuFieldExecutor


HAS_WGPU = importlib.util.find_spec("wgpu") is not None
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(HAS_WGPU, "Optional wgpu dependency is not installed")
class RealKleinGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldExecutor(KleinDomain(3, 3).field_manifest(radius=1))
        except GpuUnavailable as exc:
            raise unittest.SkipTest(f"A supported real GPU is unavailable: {exc}") from exc
        cls.addClassCleanup(cls.probe.close)

    def test_exact_fields_and_traces_for_odd_even_and_maximum_quotients(self):
        for width, height in ((3, 3), (4, 5), (5, 4), (16, 16)):
            with self.subTest(width=width, height=height):
                manifest = KleinDomain(width, height).field_manifest(radius=1)
                cpu = FieldMachine(manifest)
                self.addCleanup(cpu.close)
                with GpuFieldExecutor(manifest) as executor:
                    self.assertIn(executor.adapter_info["adapter_type"],
                                  ("DiscreteGPU", "IntegratedGPU"))
                    self.assertEqual(executor.fields, cpu.fields)
                    self.assertEqual(executor.advance(3 * width + 1),
                                     cpu.advance(3 * width + 1))

    def test_both_seam_directions_boundary_classes_and_complete_mirror_transport(self):
        domain = KleinDomain(8, 5)
        for direction, start in (("u+", domain.node(7, 1)),
                                 ("u-", domain.node(0, 1))):
            routes = tuple((domain.step(node, direction)[0],) * 3
                           for node in range(len(domain.nodes)))
            manifest = replace(domain.field_manifest(initial_node=start), routes=routes)
            traces = []
            for orientation, phase in ((0, 250), (1, 6)):
                seed = replace(manifest, initial_orientation=orientation, initial_phase=phase)
                with self.subTest(direction=direction, orientation=orientation):
                    cpu = FieldMachine(seed)
                    self.addCleanup(cpu.close)
                    with GpuFieldExecutor(seed) as executor:
                        trace = executor.advance(24)
                        self.assertEqual(trace, cpu.advance(24))
                        # Evaluate K8 independently, including the selected
                        # departure class and both complete packed mirror words.
                        node, eta, r = start, orientation, phase
                        classes, crossings = set(), 0
                        for value in trace:
                            signed = executor.fields[node]
                            classes.add((signed > 0) - (signed < 0))
                            column = 0 if signed < 0 else 1 if signed == 0 else 2
                            destination, tau = domain.step(node, direction)
                            turn = seed.turns[node][column]
                            r = (r + (-1 if eta else 1) * turn) % 256
                            r = (-r if tau else r) % 256
                            eta ^= tau
                            crossings += tau
                            expected = pair(pack(r, destination, executor.fields[destination],
                                                 int(Opcode.STEP) | (eta << 4)))
                            self.assertEqual(value, expected)
                            left, right = unpair(value)
                            self.assertIn(unpack(left)[3], (1, 17))
                            self.assertIn(unpack(right)[3], (1, 17))
                            node = destination
                        self.assertEqual(classes, {-1, 0, 1})
                        self.assertEqual(crossings, 3)
                        traces.append(trace)
            for original, mirrored in zip(*traces):
                left, right = unpair(original)
                self.assertEqual(unpair(mirrored), (right, left))

    def test_seam_bitset_handles_word_boundaries_and_highest_node_in_both_directions(self):
        count = 256
        edges = tuple(sorted([(0, node, 1) for node in range(1, count)]
                             + [(31, 32, 1), (32, 255, 1)]))
        seam_edges = ((0, 31), (0, 255), (31, 32), (32, 255))
        for tour in ((0, 31, 32, 255), (0, 255, 32, 31)):
            routes = [(node,) * 3 for node in range(count)]
            for source, destination in zip(tour, tour[1:] + tour[:1]):
                routes[source] = (destination,) * 3
            manifest = FieldManifest(
                profile="relational-sdf-v2", nodes=tuple(f"n{node}" for node in range(count)),
                edges=edges, signs=(0,) + (1,) * (count - 1),
                routes=tuple(routes), turns=((11, 53, 137),) * count, seams=seam_edges,
            )
            with self.subTest(tour=tour), GpuFieldExecutor(manifest) as executor:
                expected = FieldMachine(manifest)
                self.addCleanup(expected.close)
                self.assertEqual(executor.fields, (0,) + (1,) * (count - 1))
                trace = executor.advance(8)
                self.assertEqual(trace, expected.advance(8))
                self.assertEqual([unpack(unpair(value)[0])[1] for value in trace],
                                 list(tour[1:] + tour[:1]) * 2)
                self.assertEqual([unpack(unpair(value)[0])[3] for value in trace],
                                 [17, 1] * 4)

    def test_split_batches_and_cross_backend_archives_are_identical(self):
        manifest = KleinDomain(5, 4).field_manifest(initial_orientation=1)
        cpu = FieldMachine(manifest)
        gpu = FieldMachine(manifest, backend="gpu")
        self.addCleanup(cpu.close)
        self.addCleanup(gpu.close)
        for count in (1, 7, 31, 4096, 3):
            self.assertEqual(gpu.advance(count), cpu.advance(count))
            self.assertEqual(gpu.archive(), cpu.archive())
        archive = cpu.archive()
        continuation = cpu.advance(17)
        for backend in ("cpu", "gpu"):
            with self.subTest(backend=backend):
                restored = FieldMachine.from_archive(archive, backend=backend)
                self.addCleanup(restored.close)
                self.assertEqual(restored.archive(), archive)
                self.assertEqual(restored.advance(17), continuation)

    def test_cross_process_replay_in_both_backend_directions(self):
        manifest = KleinDomain(5, 4).field_manifest(initial_orientation=1)
        for source_backend, replay_backend in (("cpu", "gpu"), ("gpu", "cpu")):
            source = FieldMachine(manifest, backend=source_backend)
            self.addCleanup(source.close)
            source.advance(37)
            archive = source.archive()
            source.advance(19)
            code = (
                "import json, sys\n"
                "from solvefinite.field import FieldMachine\n"
                "machine = FieldMachine.from_archive(json.load(sys.stdin), backend=sys.argv[1])\n"
                "try:\n"
                "    machine.advance(19)\n"
                "    print(json.dumps(machine.archive(), sort_keys=True))\n"
                "finally:\n"
                "    machine.close()\n"
            )
            with self.subTest(source=source_backend, replay=replay_backend):
                completed = subprocess.run(
                    [sys.executable, "-c", code, replay_backend], cwd=ROOT,
                    input=json.dumps(archive), text=True, capture_output=True, timeout=90,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout), source.archive())

    def test_replay_rejects_altered_seams_and_valid_parity_transport_tampering(self):
        manifest = replace(KleinDomain(5, 4).field_manifest(), topology=None)
        source = FieldMachine(manifest)
        self.addCleanup(source.close)
        source.advance(13)
        changed_seams = deepcopy(source.archive())
        changed_seams["manifest"]["seams"] = []
        changed_phase = deepcopy(source.archive())
        phase, node, field, metadata = unpack(unpair(int(changed_phase["trace"][4], 16))[0])
        changed_phase["trace"][4] = f"{pair(pack((phase + 1) % 256, node, field, metadata)):016X}"
        for damaged in (changed_seams, changed_phase):
            with self.subTest(damage=damaged), self.assertRaises(ValueError):
                FieldMachine.from_archive(damaged, backend="gpu")

    def test_gpu_derives_seams_without_cpu_field_operator_or_transport_fallbacks(self):
        manifest = KleinDomain(8, 8).field_manifest()
        expected_field = evaluate_field(manifest)
        cpu = FieldMachine(manifest)
        self.addCleanup(cpu.close)
        expected_trace = cpu.advance(73)
        with patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field fallback")), \
                patch("solvefinite.field.build_operators", side_effect=AssertionError("CPU operators")), \
                patch.object(FieldManifest, "seam", side_effect=AssertionError("CPU route transport")):
            with GpuFieldExecutor(manifest) as executor:
                self.assertEqual(executor.fields, expected_field)
                self.assertEqual(executor.advance(73), expected_trace)
            machine = FieldMachine(manifest, backend="gpu")
            self.addCleanup(machine.close)
            self.assertEqual(machine.advance(73), expected_trace)
            self.assertEqual(machine.execution_info["backend"], "gpu")


if __name__ == "__main__":
    unittest.main()
