"""DP9 actual instruction decoding, projected occupancy and owner admission."""

from contextlib import ExitStack
from collections import deque
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from solvefinite.field_agent_gpu import GpuFieldAgentExecutor
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.gpu import GpuUnavailable
from solvefinite.hadamard import HadamardBinding
from solvefinite.organogram import StageContext
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.taper import TaperBinding, TaperFieldRecipe
from solvefinite.taper_gpu import GpuTaperGeometry
from tests.test_hadamard_gpu import no_cpu_routing


REFERENCE = json.loads((Path(__file__).resolve().parents[1] /
    "docs/evidence/directional-v1/formal-reference.json").read_text(encoding="utf-8"))


def forbid_taper_producers():
    stack = ExitStack()
    stack.enter_context(no_cpu_routing())
    for name in ("interpret_cpu", "occupancy_cpu", "signs_from_occupancy_cpu", "union_signs_cpu", "regenerate", "evaluate_field"):
        stack.enter_context(patch("solvefinite.taper." + name,
            side_effect=AssertionError("Explicit GPU operation invoked CPU producer " + name)))
    stack.enter_context(patch.object(TaperFieldRecipe, "field_manifest",
        side_effect=AssertionError("Eager generated CPU manifest")))
    return stack


def reference_recipe(key="default_mission"):
    mission = REFERENCE[key]
    base = dict(mission["initial_recipe"])
    base["turns"] = tuple(base["turns"])
    return TaperFieldRecipe(KleinFieldRecipe(**base),
        TaperBinding.from_dict(mission["binding"]), HadamardBinding(),
        tuple(StageContext.from_dict(stage["result"]["document"]["context"]) for stage in mission["stages"]))


def token(symbol, *args):
    return {"symbol": symbol, "args": list(args)}


def simple_recipe(tape=None, *, node=11, phase=0, eta=0, center=0, turns=(11, 53, 137),
                  gains=None, site_limit=1 << 24):
    base = KleinFieldRecipe(width=8, height=8, center=center, radius=2, turns=turns)
    # Literal source fields from independently frozen fixtures; no CPU compiler.
    fixture = REFERENCE["geometry_vectors"]["fixtures"][1 if center == 6 else 0]
    signed = fixture["prior_field"][node]
    context = StageContext(1, 1, f"{pair(pack(phase, node, signed, int(Opcode.EMIT) | (eta << 4))):016X}", "0" * 64)
    binding = TaperBinding(axiom=tape or [token("TAPER", 3, 1, 1)], rules=[], generations=0,
        limits={"max_symbols": 128, "max_steps": 4096, "max_primitives": 64,
                "max_stack": 32, "max_primitive_sites": site_limit})
    return TaperFieldRecipe(base, binding, HadamardBinding() if gains is None else HadamardBinding(gains), (context,))


def instruction(code, operand):
    value = operand | (code << 24)
    return value | ((value.bit_count() & 1) << 31)


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class TaperGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe(), routing=HadamardBinding())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.addClassCleanup(cls.probe.close)

    def geometry(self, recipe=None):
        result = GpuTaperGeometry(recipe or reference_recipe())
        self.addCleanup(result.close)
        return result

    def executor(self, recipe=None):
        result = GpuFieldAgentExecutor(recipe or KleinFieldRecipe(), routing=HadamardBinding())
        self.addCleanup(result.close)
        return result

    def test_actual_texture_document_fields_and_no_cpu_producers(self):
        with forbid_taper_producers():
            result = self.geometry()
        expected = REFERENCE["default_mission"]["stages"][0]["result"]
        self.assertEqual(result.last_derivation, expected["document"])
        self.assertEqual(result.fields, tuple(expected["union"]["field"]))
        self.assertEqual(result.manifest.signs, tuple(expected["union"]["signs"]))
        self.assertEqual(result.stage_digests, (expected["derivation_sha256"],))
        self.assertEqual(result.allocation_info["instruction_texture_bytes"], 4 * len(expected["encoded_tape_words"]))
        self.assertEqual(result.allocation_info["occupancy_buffer_bytes"], 80)
        self.assertEqual(result.allocation_info["maximum_primitive_sites"], expected["preflight"]["primitive_sites"])

    def test_two_epochs_reconstruct_original_prior_gpu_fields(self):
        mission = REFERENCE["two_epoch_mission"]
        with forbid_taper_producers():
            result = self.geometry(reference_recipe("two_epoch_mission"))
        self.assertEqual(result.last_derivation, mission["stages"][-1]["result"]["document"])
        self.assertEqual(result.fields, tuple(mission["stages"][-1]["result"]["union"]["field"]))
        self.assertEqual(result.stage_digests, tuple(s["result"]["derivation_sha256"] for s in mission["stages"]))

    def test_original_tick_phase_slope_and_full_mirror_are_device_inputs(self):
        vectors = REFERENCE["mutation_vectors"]
        fields = {}
        for key in ("context_parameter_baseline", "later_original_tick", "different_intrinsic_phase", "narrower_slope", "full_mirror"):
            expected = vectors[key]
            binding = vectors["narrower_slope_binding" if key == "narrower_slope" else "binding"]
            recipe = TaperFieldRecipe(KleinFieldRecipe(width=8, height=8), TaperBinding.from_dict(binding), HadamardBinding(),
                                     (StageContext.from_dict(expected["document"]["context"]),))
            with self.subTest(key=key), forbid_taper_producers():
                result = self.geometry(recipe)
                self.assertEqual(result.last_derivation, expected["document"])
                self.assertEqual(result.fields, tuple(expected["union"]["field"]))
                fields[key] = result.fields
                result.close()
        for key in ("later_original_tick", "different_intrinsic_phase", "narrower_slope"):
            self.assertNotEqual(fields[key], fields["context_parameter_baseline"])
        self.assertEqual(fields["full_mirror"], fields["context_parameter_baseline"])

    def test_six_geometric_fixtures_cover_negative_projection_seam_and_thin_sections(self):
        for fixture in REFERENCE["geometry_vectors"]["fixtures"]:
            primitive = fixture["primitive"]
            phase, center, gains = 0, 0, None
            if fixture["name"] == "reversing_seam":
                phase, center = 73, 6
            elif fixture["name"] in ("opposite_shaft", "transverse_shaft"):
                phase, gains = primitive["shaft"] * 64, ((0, 0),) * 4
            recipe = simple_recipe([token("TAPER", primitive["height"], primitive["numerator"], primitive["denominator"])],
                node=primitive["apex"], phase=phase, center=center, gains=gains)
            with self.subTest(name=fixture["name"]), forbid_taper_producers():
                result = self.geometry(recipe)
                self.assertEqual(result.fields, tuple(fixture["field"]))
                self.assertEqual(result.manifest.signs, tuple(fixture["signs"]))
                self.assertEqual(result.last_derivation["primitives"][0]["shaft"], primitive["shaft"])
                result.close()

    def test_all_four_shaft_banks_and_both_orientations_match_independent_transported_walk(self):
        vectors = ((1, 0), (0, 1), (-1, 0), (0, -1))
        def step(node, vector):
            u, v = divmod(node, 8)
            x, y = u + vector[0], v + vector[1]
            crossed = x < 0 or x >= 8
            if crossed:
                x, y = x % 8, -y
            return x * 8 + y % 8, crossed
        adjacent = tuple(tuple(step(node, direction)[0] for direction in vectors) for node in range(64))
        for bank in range(4):
            for eta in (0, 1):
                # Independent endpoint construction: walk axial then transverse
                # unit edges, reflecting BOTH frame vectors at a reversing seam.
                occupied = set()
                for s in range(4):
                    for t in range(-s, s + 1):
                        node = 11
                        e = vectors[bank]
                        f = tuple(value * (-1 if eta else 1) for value in (-e[1], e[0]))
                        for transverse, count in ((False, s), (True, abs(t))):
                            for _ in range(count):
                                direction = f if transverse else e
                                if transverse and t < 0:
                                    direction = (-direction[0], -direction[1])
                                node, crossed = step(node, direction)
                                if crossed:
                                    e, f = (e[0], -e[1]), (f[0], -f[1])
                        occupied.add(node)
                boundary = {node for node in occupied if any(other not in occupied for other in adjacent[node])}
                distance = {node: 0 for node in boundary}
                pending = deque(sorted(boundary))
                while pending:
                    node = pending.popleft()
                    for other in adjacent[node]:
                        if other not in distance:
                            distance[other] = distance[node] + 1
                            pending.append(other)
                signs = tuple(0 if node in boundary else -1 if node in occupied else 1 for node in range(64))
                expected_fields = tuple(signs[node] * distance[node] for node in range(64))
                phase = ((-1 if eta else 1) * bank * 64) % 256
                recipe = simple_recipe(phase=phase, eta=eta, gains=((0, 0),) * 4)
                with self.subTest(shaft=bank, orientation=eta), forbid_taper_producers():
                    result = self.geometry(recipe)
                    primitive = result.last_derivation["primitives"][0]
                    actual_occupancy = struct.unpack("<64I", result._device.queue.read_buffer(result._occupancy))
                    self.assertEqual(primitive["shaft"], bank)
                    self.assertEqual((int(primitive["pair"], 16) >> 28) & 1, eta)
                    self.assertEqual(actual_occupancy, tuple(int(node in occupied) for node in range(64)))
                    self.assertEqual(result.manifest.signs, signs)
                    self.assertEqual(result.fields, expected_fields)
                    result.close()

    def test_occupancy_union_removes_internal_boundaries_before_redistance(self):
        recipe = simple_recipe([token("TAPER", 3, 1, 1), token("F", 1), token("TAPER", 3, 1, 1)],
                               turns=(0, 0, 0), gains=((0, 0),) * 4)
        with forbid_taper_producers():
            result = self.geometry(recipe)
        expected = REFERENCE["geometry_vectors"]["overlap"]
        self.assertEqual(result.fields, tuple(expected["field"]))
        self.assertNotEqual(result.fields, tuple(expected["minimum_separate_fields"]))
        self.assertLess(result.fields[35], 0)

    def test_large_raw_height_and_zero_width_are_not_artificially_capped(self):
        with forbid_taper_producers():
            result = self.geometry(simple_recipe([token("TAPER", 65534, 1, 65535)]))
        primitive = result.last_derivation["primitives"][0]
        self.assertEqual(primitive["height"], 65534)
        self.assertEqual(result.allocation_info["maximum_primitive_sites"], 65535)
        self.assertIn(0, result.fields)
        self.assertIn(1, result.manifest.signs)

    def test_maximum1152_texel_tape_preserves1024_logical_addresses_and64_primitives(self):
        binding = TaperBinding(symbols=[{"name": "A", "arity": 0}],
            axiom=[token("A")] * 32,
            rules=[{"symbol": "A", "guards": [],
                    "rhs": [token("TAPER", 3, 1, 1)] * 2 + [token("R", 1)] * 30}],
            generations=1, limits={"max_symbols": 1024, "max_steps": 1,
                "max_primitives": 64, "max_stack": 0, "max_primitive_sites": 64 * 28})
        with forbid_taper_producers():
            result = self.geometry(replace(simple_recipe(), taper=binding))
        self.assertEqual(len(result.last_derivation["trace"]), 1024)
        self.assertEqual(len(result.last_derivation["primitives"]), 64)
        self.assertEqual(result.allocation_info["maximum_instruction_texels"], 1152)
        self.assertEqual(result.fields, tuple(REFERENCE["geometry_vectors"]["fixtures"][0]["field"]))

    def test_maximum_stack_restores_context_after4096_effective_movement_steps(self):
        binding = TaperBinding(symbols=[{"name": name, "arity": 0} for name in ("A", "B", "C", "D")],
            axiom=[token(name) for name in ("A", "B", "C", "D")],
            rules=[{"symbol": "A", "guards": [], "rhs": [token("[")] * 32},
                   {"symbol": "B", "guards": [], "rhs": [token("SCALE", 4), token("F", 256)]},
                   {"symbol": "C", "guards": [], "rhs": [token("]")] * 32},
                   {"symbol": "D", "guards": [], "rhs": [token("TAPER", 1, 1, 2)]}],
            generations=1, limits={"max_symbols": 67, "max_steps": 4096,
                "max_primitives": 1, "max_stack": 32, "max_primitive_sites": 2})
        recipe = replace(simple_recipe(), taper=binding)
        with forbid_taper_producers():
            result = self.geometry(recipe)
        document = result.last_derivation
        self.assertEqual(len(document["segments"]), 4096)
        self.assertEqual(len(document["trace"][31]["branch_path"]), 32)
        self.assertEqual(document["final_context"]["scale"], 0)
        self.assertEqual(document["final_context"]["radius"], 1)
        self.assertEqual(document["primitives"][0]["apex"], 11)
        self.assertEqual(document["primitives"][0]["height"], 1)

    def test_large_two_dimensional_dispatch_rejects_full_projected_union(self):
        # K=8,912,777 exceeds a one-dimensional65535*64 dispatch; arithmetic
        # admission succeeds, then actual projected occupancy is the full graph.
        recipe = simple_recipe([token("SCALE", 3), token("TAPER", 65535, 1, 65535)])
        with forbid_taper_producers(), self.assertRaises(ValueError) as failure:
            GpuTaperGeometry(recipe)
        self.assertIn("boundary", str(failure.exception))
        self.assertFalse(failure.exception.device_uncertain)

    def test_sphere_only_uses_new_closed_occupancy_boundary(self):
        with forbid_taper_producers():
            result = self.geometry(simple_recipe([token("S")]))
        self.assertEqual(result.last_derivation["primitives"][0]["kind"], "ball")
        self.assertEqual(result.manifest.signs.count(-1), 1)
        self.assertEqual(result.manifest.signs.count(0), 4)
        self.assertEqual(result.allocation_info["maximum_primitive_sites"], 64)

    def test_preflight_rejection_allocates_no_device(self):
        cases = ([token("]"), token("S")], [token("F", 1)],
                 [token("TAPER", 32769, 65535, 1)], [token("TAPER", 3, 2, 2)])
        for tape in cases:
            with self.subTest(tape=tape):
                recipe = simple_recipe(tape)
                with patch("solvefinite.taper_gpu.GpuFieldExecutor", side_effect=AssertionError("allocated")):
                    with self.assertRaises(ValueError):
                        GpuTaperGeometry(recipe)

    def test_device_strict_continuation_decoder_rejects_malformed_textures(self):
        good = [instruction(8, 3), instruction(9, 1), instruction(10, 1)]
        cases = [good[:2], [good[0], good[2], good[1]], [instruction(9, 3), *good[1:]],
                 [good[0], instruction(9, 0), good[2]], [instruction(11, 3), *good[1:]],
                 [good[0] ^ 0x80000000, *good[1:]], [good[0] ^ 0x00030000, *good[1:]],
                 [*good, instruction(6, 0)], [instruction(6, 1), *good[1:]]]
        for words in cases:
            with self.subTest(words=words), patch("solvefinite.taper.encode_tape", return_value=tuple(words)):
                with self.assertRaises(ValueError) as failure:
                    GpuTaperGeometry(simple_recipe())
                self.assertFalse(failure.exception.device_uncertain)

    def test_device_checks_overflow_reduced_slope_and_site_budget_before_geometry(self):
        for h, p, q in ((32769, 65535, 1), (32768, 65535, 1), (65535, 65534, 65535),
                        (3, 2, 2), (65535, 1, 1)):
            words = tuple(instruction(code, arg) for code, arg in zip((8, 9, 10), (h, p, q)))
            with self.subTest(args=(h, p, q)), patch("solvefinite.taper.encode_tape", return_value=words):
                with self.assertRaises(ValueError) as failure:
                    GpuTaperGeometry(simple_recipe())
                self.assertFalse(failure.exception.device_uncertain)

    def test_empty_and_full_occupancy_are_rejected_without_fabricated_distance(self):
        original = GpuTaperGeometry._dispatch
        def omit_occupancy(owner, entry, groups=1):
            if entry != "generate_occupancy":
                return original(owner, entry, groups)
        with patch.object(GpuTaperGeometry, "_dispatch", omit_occupancy):
            with self.assertRaises(ValueError) as failure:
                GpuTaperGeometry(simple_recipe())
            self.assertFalse(failure.exception.device_uncertain)
        with self.assertRaises(ValueError) as failure:
            GpuTaperGeometry(simple_recipe([token("R", 127), token("S")]))
        self.assertFalse(failure.exception.device_uncertain)

    def test_completed_descriptor_corruption_is_pure_certificate_rejection(self):
        original = GpuTaperGeometry._document
        def corrupt(*args):
            document = original(*args)
            document["primitives"][0]["shaft"] ^= 1
            return document
        with patch.object(GpuTaperGeometry, "_document", side_effect=corrupt):
            with self.assertRaises(ValueError) as failure:
                GpuTaperGeometry(simple_recipe())
        self.assertFalse(failure.exception.device_uncertain)

    def test_uncertain_dispatch_closes_candidate_and_preserves_failure_tag(self):
        original = GpuTaperGeometry._dispatch
        instances = []
        def fail(owner, entry, groups=1):
            instances.append(owner)
            if entry == "generate_occupancy":
                raise OSError("uncertain taper dispatch")
            return original(owner, entry, groups)
        with patch.object(GpuTaperGeometry, "_dispatch", fail):
            with self.assertRaises(OSError) as failure:
                GpuTaperGeometry(simple_recipe())
        self.assertTrue(failure.exception.device_uncertain)
        self.assertTrue(instances[-1]._closed)
        self.assertTrue(instances[-1]._base._closed)

    def test_allocation_failure_closes_every_partial_candidate_resource(self):
        original = GpuTaperGeometry._buffer
        instances = []
        def fail(owner, size, data=None):
            instances.append(owner)
            if len(owner._extra_buffers) == 4:
                raise MemoryError("candidate scratch allocation")
            return original(owner, size, data)
        with patch.object(GpuTaperGeometry, "_buffer", fail):
            with self.assertRaises(MemoryError) as failure:
                GpuTaperGeometry(simple_recipe())
        self.assertFalse(failure.exception.device_uncertain)
        self.assertTrue(instances[-1]._closed)
        self.assertTrue(instances[-1]._base._closed)

    def test_actual_owner_admission_and_following_move_use_device_state(self):
        recipe = reference_recipe()
        source = self.executor()
        r, node, signed, metadata = unpack(unpair(int(recipe.stages[0].start_pair, 16))[0])
        source.seed(pair(pack(r, node, signed, int(Opcode.STEP) | (metadata & 16))), 100)
        source.repair(5)
        before = source.snapshot()
        with forbid_taper_producers():
            candidate = self.executor(recipe)
            with patch.object(candidate, "seed", side_effect=AssertionError("host seed")):
                actual = candidate.admit_generated(source, recipe.taper.cost,
                    taper=recipe.taper, prefix_sha256=recipe.stages[-1].prefix_sha256)
            expected = pair(pack(r, node, candidate.fields[node], int(Opcode.STEP) | (metadata & 16)))
            self.assertEqual(actual, (expected, 94))
            destination = candidate.routing_model.neighbors[node][0]
            paths = (candidate._nodes[destination],)
            forecast, costs = candidate.forecast(expected, paths, (0,))
            self.assertEqual(candidate.advance_to(paths[0], 0), (forecast[0], costs[0], 94 - costs[0]))
            before_reindex = candidate.snapshot()
            candidate.reindex(psi_sign=-1, phase_origin=17)
            self.assertEqual(candidate.snapshot(), before_reindex)
        self.assertEqual(source.snapshot(), before)

    def test_allocation_accounts_for_instruction_texels_occupancy_and_descriptors(self):
        candidate = self.executor(reference_recipe())
        accounting = candidate.allocation_info
        buffers = sum(b.size for b in candidate._buffers + candidate._geometry._buffers + candidate._bundle.buffers)
        texels = len(REFERENCE["default_mission"]["stages"][0]["result"]["encoded_tape_words"])
        textures = (384 + 12 + 16) * 20 + 4 * texels
        self.assertEqual(accounting["device_buffer_bytes"], buffers)
        self.assertEqual(accounting["device_texture_bytes"], textures)
        self.assertEqual(accounting["device_payload_bytes"], buffers + textures)
        self.assertEqual(accounting["taper"]["occupancy_buffer_bytes"], 80)
        self.assertGreater(accounting["taper"]["primitive_record_buffer_bytes"], 0)

    def test_host_stage_accounting_includes_measured_status_and_zero_step_padding_readbacks(self):
        original = GpuTaperGeometry._stage
        byte_counts = []
        def measured(owner, *args):
            read = owner._device.queue.read_buffer
            def capture(*read_args, **kwargs):
                result = read(*read_args, **kwargs)
                byte_counts.append(len(result))
                return result
            with patch.object(owner._device.queue, "read_buffer", side_effect=capture):
                return original(owner, *args)
        with patch.object(GpuTaperGeometry, "_stage", measured), forbid_taper_producers():
            result = self.geometry(simple_recipe())
        # Includes the actual64-byte status and32-byte zero-step segment read.
        self.assertIn(64, byte_counts)
        self.assertEqual(byte_counts.count(32), 2)  # one trace plus padded segment
        info = result.allocation_info
        required_payload = (sum(byte_counts) + 4 * len(result.fields)
                            + info["peak_grammar_host_tape_metadata_bytes"]
                            + info["peak_grammar_host_tape_word_bytes"]
                            + 2 * info["grammar_retained_transcript_bytes"])
        self.assertGreaterEqual(info["peak_grammar_host_stage_payload_bytes"], required_payload)


if __name__ == "__main__":
    unittest.main()
