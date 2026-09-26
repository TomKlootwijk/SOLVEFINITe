"""OG7 actual instruction textures, device trajectories and owner admission."""

from contextlib import ExitStack
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
from solvefinite.organogram import (GeneratedFieldRecipe, OrganogramBinding, StageContext)
from solvefinite.organogram_gpu import GpuOrganogramGeometry
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from tests.test_hadamard_gpu import no_cpu_routing


REFERENCE = json.loads((Path(__file__).resolve().parents[1] /
    "docs/evidence/organogram-v1/formal-reference.json").read_text(encoding="utf-8"))


def forbid_organogram_producers():
    stack = ExitStack()
    stack.enter_context(no_cpu_routing())
    for name in ("interpret_cpu", "union_signs_cpu", "regenerate", "evaluate_field"):
        stack.enter_context(patch("solvefinite.organogram." + name,
            side_effect=AssertionError("Explicit GPU operation invoked CPU producer " + name)))
    stack.enter_context(patch.object(GeneratedFieldRecipe, "field_manifest",
        side_effect=AssertionError("Eager generated CPU manifest")))
    return stack


def reference_recipe(key="standalone_stage"):
    return GeneratedFieldRecipe(KleinFieldRecipe(), OrganogramBinding.from_dict(REFERENCE["binding"]),
        HadamardBinding(), (StageContext.from_dict(REFERENCE[key]["document"]["context"]),))


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "Optional wgpu is not installed")
class OrganogramGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.probe = GpuFieldAgentExecutor(KleinFieldRecipe(), routing=HadamardBinding())
        except GpuUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.addClassCleanup(cls.probe.close)

    def geometry(self, recipe=None):
        result = GpuOrganogramGeometry(recipe or reference_recipe())
        self.addCleanup(result.close)
        return result

    def executor(self, recipe=None):
        result = GpuFieldAgentExecutor(recipe or KleinFieldRecipe(), routing=HadamardBinding())
        self.addCleanup(result.close)
        return result

    def repaired_source(self):
        source = self.executor()
        r, node, field, metadata = unpack(unpair(int(reference_recipe().stages[0].start_pair, 16))[0])
        source.seed(pair(pack(r, node, field, int(Opcode.STEP) | (metadata & 16))), 100)
        source.repair(5)
        return source

    def test_actual_texture_document_fields_and_no_cpu_producers(self):
        with forbid_organogram_producers():
            result = self.geometry()
        expected = REFERENCE["standalone_stage"]
        self.assertEqual(result.last_derivation, expected["document"])
        self.assertEqual(result.fields, tuple(expected["union"]["field"]))
        self.assertEqual(result.manifest.signs, tuple(expected["union"]["signs"]))
        self.assertEqual(result.stage_digests, (expected["derivation_sha256"],))
        self.assertEqual(result.allocation_info["instruction_texture_bytes"], 4 * 19)
        self.assertEqual(result.allocation_info["grammar_movement_texture_bytes"], 16 * 20)

    def test_original_tick_and_full_mirror_use_device_context(self):
        for key in ("mirrored_standalone_stage", "original_tick_variant_stage"):
            with self.subTest(key=key), forbid_organogram_producers():
                result = self.geometry(reference_recipe(key))
                self.assertEqual(result.last_derivation, REFERENCE[key]["document"])
                self.assertEqual(result.fields, tuple(REFERENCE[key]["union"]["field"]))
                result.close()

    def test_second_stage_reconstructs_prior_gpu_field_before_continuing(self):
        mission = REFERENCE["two_epoch_mission"]
        contexts = tuple(StageContext.from_dict(stage["result"]["document"]["context"])
                         for stage in mission["stages"])
        recipe = GeneratedFieldRecipe(KleinFieldRecipe(), OrganogramBinding.from_dict(mission["binding"]),
                                      HadamardBinding(), contexts)
        with forbid_organogram_producers():
            result = self.geometry(recipe)
        self.assertEqual(result.stage_digests,
                         tuple(stage["result"]["derivation_sha256"] for stage in mission["stages"]))
        self.assertEqual(result.last_derivation, mission["stages"][-1]["result"]["document"])
        self.assertEqual(result.fields, tuple(mission["stages"][-1]["result"]["union"]["field"]))

    def test_union_redistance_is_not_minimum_ball_residual(self):
        grammar = OrganogramBinding(axiom=[{"symbol": "R", "args": [2]},
            {"symbol": "S", "args": []}, {"symbol": "F", "args": [2]},
            {"symbol": "S", "args": []}], rules=[], generations=0)
        # Zero gains resolve ties by the evolving phase: u+ then v+, reaching
        # centre 4. These device placements realize the frozen two-ball witness.
        base = KleinFieldRecipe(width=3, height=3, radius=1, turns=(64, 64, 64))
        initial = pair(pack(0, 0, -1, Opcode.EMIT))
        context = StageContext(1, 1, f"{initial:016X}", "0" * 64)
        recipe = GeneratedFieldRecipe(base, grammar, HadamardBinding(((0, 0),) * 4), (context,))
        with forbid_organogram_producers():
            result = self.geometry(recipe)
        expected = REFERENCE["union_counterexample"]
        self.assertEqual([(ball["center"], ball["radius"]) for ball in result.last_derivation["balls"]],
                         [(0, 2), (4, 2)])
        self.assertEqual(result.fields, tuple(expected["field"]))
        self.assertNotEqual(result.fields, tuple(expected["margin"]))

    def test_invalid_tape_preflight_allocates_no_device(self):
        grammar = OrganogramBinding(axiom=[{"symbol": "]", "args": []},
            {"symbol": "S", "args": []}], rules=[], generations=0)
        recipe = replace(reference_recipe(), organogram=grammar)
        with patch("solvefinite.organogram_gpu.GpuFieldExecutor", side_effect=AssertionError("allocated")):
            with self.assertRaises(ValueError):
                GpuOrganogramGeometry(recipe)

    def test_device_instruction_decoder_rejects_corruption(self):
        from solvefinite.organogram import encode_tape
        for corrupt in (lambda x: x ^ 0x80000000, lambda x: x ^ 0x00030000,
                        lambda x: x ^ 0x80000001):
            def words(tape):
                original = list(encode_tape(tape))
                original[0] = corrupt(original[0])
                return tuple(original)
            with patch("solvefinite.organogram.encode_tape", side_effect=words):
                with self.assertRaises(ValueError) as failure:
                    GpuOrganogramGeometry(reference_recipe())
            self.assertFalse(failure.exception.device_uncertain)

    def test_maximum_stack_and_scaled_F256_execute_actual_bounded_texture_loop(self):
        token = lambda symbol, *args: {"symbol": symbol, "args": list(args)}
        grammar = OrganogramBinding(
            symbols=[{"name": name, "arity": 0} for name in ("A", "B", "C", "D")],
            axiom=[token(name) for name in ("A", "B", "C", "D")],
            rules=[{"symbol": "A", "guards": [], "rhs": [token("[")] * 32},
                   {"symbol": "B", "guards": [], "rhs": [token("SCALE", 4), token("F", 256)]},
                   {"symbol": "C", "guards": [], "rhs": [token("]")] * 32},
                   {"symbol": "D", "guards": [], "rhs": [token("S")]}],
            generations=1,
            limits={"max_symbols": 67, "max_steps": 4096, "max_balls": 1, "max_stack": 32})
        with forbid_organogram_producers():
            result = self.geometry(replace(reference_recipe(), organogram=grammar))
        document = result.last_derivation
        self.assertEqual(len(document["segments"]), 4096)
        self.assertEqual(len(document["trace"][31]["branch_path"]), 32)
        self.assertEqual(document["final_context"],
            {"branch_path": [], "pair": "81011145910111BB", "radius": 1, "scale": 0})
        self.assertEqual([(ball["center"], ball["radius"]) for ball in document["balls"]], [(17, 1)])

    def test_empty_boundary_is_rejected_without_a_fabricated_field(self):
        grammar = OrganogramBinding(axiom=[{"symbol": "R", "args": [127]},
            {"symbol": "S", "args": []}], rules=[], generations=0)
        with self.assertRaises(ValueError) as failure:
            GpuOrganogramGeometry(replace(reference_recipe(), organogram=grammar))
        self.assertIn("boundary", str(failure.exception))
        self.assertFalse(failure.exception.device_uncertain)

    def test_complete_transcript_corruption_is_pure_certificate_rejection(self):
        original = GpuOrganogramGeometry._document
        def corrupt(*args):
            document = original(*args)
            document["trace"][0]["radius"] += 1
            return document
        with patch.object(GpuOrganogramGeometry, "_document", side_effect=corrupt):
            with self.assertRaises(ValueError) as failure:
                GpuOrganogramGeometry(reference_recipe())
        self.assertFalse(failure.exception.device_uncertain)

    def test_uncertain_dispatch_is_tagged_and_closed(self):
        original = GpuOrganogramGeometry._dispatch
        instances = []
        def fail(owner, entry, groups=1):
            instances.append(owner)
            if entry == "interpret":
                raise OSError("uncertain grammar dispatch")
            return original(owner, entry, groups)
        with patch.object(GpuOrganogramGeometry, "_dispatch", fail):
            with self.assertRaises(OSError) as failure:
                GpuOrganogramGeometry(reference_recipe())
        self.assertTrue(failure.exception.device_uncertain)
        self.assertTrue(instances[-1]._closed)
        self.assertTrue(instances[-1]._base._closed)

    def test_actual_owner_admission_preserves_phase_and_never_seeds(self):
        source = self.repaired_source()
        before = source.snapshot()
        recipe = reference_recipe()
        with forbid_organogram_producers():
            candidate = self.executor(recipe)
            with patch.object(candidate, "seed", side_effect=AssertionError("host seed")):
                actual = candidate.admit_generated(source, recipe.organogram.cost,
                    organogram=recipe.organogram, prefix_sha256=recipe.stages[-1].prefix_sha256)
            expected = pair(pack(187, 17, candidate.fields[17], 17))
            self.assertEqual(actual, (expected, 94))
            self.assertEqual(candidate.snapshot(), actual)
            # The next action and reindex also consume the generated certificate.
            destination = candidate.routing_model.neighbors[17][0]
            forecast, costs = candidate.forecast(expected, (candidate._nodes[destination],), (0,))
            self.assertEqual(candidate.advance_to(candidate._nodes[destination], 0),
                             (forecast[0], costs[0], 94 - costs[0]))
            snapshot = candidate.snapshot()
            candidate.reindex(psi_sign=-1, phase_origin=17)
            self.assertEqual(candidate.snapshot(), snapshot)
        self.assertEqual(source.snapshot(), before)

    def test_owner_context_rejections_precede_candidate_writes(self):
        source = self.repaired_source()
        candidate = self.executor(reference_recipe())
        before = source.snapshot()
        binding = candidate.recipe.organogram
        prefix = candidate.recipe.stages[-1].prefix_sha256
        with patch.object(candidate, "_dispatch", side_effect=AssertionError("invalid dispatch")):
            for cost, grammar, digest in ((2, binding, prefix), (1, OrganogramBinding(cost=2), prefix),
                                         (1, binding, "f" * 64), (True, binding, prefix)):
                with self.subTest(cost=cost, digest=digest), self.assertRaises(ValueError):
                    candidate.admit_generated(source, cost, organogram=grammar, prefix_sha256=digest)
            with self.assertRaises(ValueError):
                candidate.seed(pair(pack(187, 17, candidate.fields[17], 17)), 100)
            with self.assertRaises(ValueError):
                candidate.admit_growth(source, 1)
        self.assertEqual(source.snapshot(), before)
        self.assertFalse(candidate._seeded)
        self.assertFalse(candidate.failed)

    def test_owner_readback_corruption_disposes_only_complete_candidate(self):
        source = self.repaired_source()
        candidate = self.executor(reference_recipe())
        before = source.snapshot()
        read = candidate._device.queue.read_buffer
        def corrupt(buffer, *args, **kwargs):
            result = bytes(read(buffer, *args, **kwargs))
            if buffer is candidate._canonical:
                words = list(struct.unpack("<4I", result)); words[2] += 1
                return struct.pack("<4I", *words)
            return result
        with patch.object(candidate._device.queue, "read_buffer", side_effect=corrupt):
            with self.assertRaises(ValueError) as failure:
                candidate.admit_generated(source, 1, organogram=candidate.recipe.organogram,
                                          prefix_sha256=candidate.recipe.stages[-1].prefix_sha256)
        self.assertFalse(failure.exception.device_uncertain)
        self.assertTrue(candidate._closed)
        self.assertFalse(source._closed)
        self.assertEqual(source.snapshot(), before)

    def test_payload_counts_include_instruction_movement_and_scratch_storage(self):
        candidate = self.executor(reference_recipe())
        accounting = candidate.allocation_info
        buffers = sum(b.size for b in candidate._buffers + candidate._geometry._buffers + candidate._bundle.buffers)
        textures = (384 + 12 + 16) * 20 + 4 * 19
        self.assertEqual(accounting["device_buffer_bytes"], buffers)
        self.assertEqual(accounting["device_texture_bytes"], textures)
        self.assertEqual(accounting["device_payload_bytes"], buffers + textures)
        self.assertGreater(accounting["organogram"]["grammar_retained_transcript_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
