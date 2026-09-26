"""DP CPU production and independent certification against frozen formal vectors."""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.field import evaluate_field
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.hadamard import HadamardBinding
from solvefinite.organogram import OrganogramBinding, GeneratedFieldRecipe
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair
from solvefinite.taper import (
    I32_MIN, I32_MAX, PROFILE, WORLD_PROFILE, DERIVATION_PROFILE, TAPE_PROFILE,
    TaperBinding, TaperFieldRecipe, TaperFieldCertificate, StageContext,
    TapeInstruction, TapeBudget, compile_tape, preflight, taper_bounds,
    encode_tape, decode_tape, word_offsets, interpret_cpu, certify_derivation,
    occupancy_cpu, union_signs_cpu, signs_from_occupancy_cpu,
    certify_stage, regenerate, select_target, canonical_bytes,
)

REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs/evidence/directional-v1/formal-reference.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
BASE = KleinFieldRecipe()
ROUTING = HadamardBinding()
BINDING = TaperBinding.from_dict(REFERENCE["binding"])
STAGE = REFERENCE["default_mission"]["stages"][0]
RESULT = STAGE["result"]
CONTEXT = StageContext.from_dict(RESULT["document"]["context"])
FIELDS = tuple(STAGE["prior_field"])


def token(symbol, *args):
    return {"symbol": symbol, "args": list(args)}


def simple_binding(tokens, *, generations=0, **updates):
    source = BINDING.to_dict()
    source.update(axiom=tokens, generations=generations, **updates)
    return TaperBinding.from_dict(source)


def generated(binding=BINDING, contexts=(CONTEXT,), base=BASE):
    return TaperFieldRecipe(base, binding, ROUTING, contexts)


def tape_of(tokens):
    return tuple(TapeInstruction((i % 32,), item["symbol"], tuple(item["args"])) for i, item in enumerate(tokens))


def frame(base, *, node=0, phase=0, orientation=0, tick=5, epoch=1):
    fields = evaluate_field(base.field_manifest())
    return StageContext(epoch, tick, f"{pair(pack(phase, node, fields[node], int(Opcode.EMIT) | orientation << 4)):016X}", "0" * 64)


def stage_certificate(recipe, result, prior_fields=FIELDS, prior_certificate=None):
    return certify_stage(recipe, prior_fields, result["document"], tuple(result["union"]["signs"]),
                         tuple(result["union"]["field"]), prior_certificate=prior_certificate)


def word(code, operand=0):
    raw = code << 24 | operand
    return raw | ((raw.bit_count() & 1) << 31)


class TaperSchemaTests(unittest.TestCase):
    def test_frozen_binding_context_recipe_and_detached_json(self):
        self.assertEqual(TaperBinding().to_dict(), REFERENCE["binding"])
        value = BINDING.to_dict()
        value["rules"][0]["rhs"][0]["symbol"] = "S"
        self.assertEqual(BINDING.to_dict(), REFERENCE["binding"])
        limits = BINDING.limits
        limits["max_steps"] = 1
        self.assertEqual(BINDING.limits["max_steps"], 128)
        recipe = generated()
        self.assertEqual(TaperFieldRecipe.from_dict(recipe.to_dict()), recipe)
        self.assertEqual(StageContext.from_dict(CONTEXT.to_dict()), CONTEXT)
        for obj, name, value in ((BINDING, "_canonical", b"{}"), (CONTEXT, "tick", 99), (recipe, "base", None)):
            with self.subTest(type=type(obj)), self.assertRaises(FrozenInstanceError):
                setattr(obj, name, value)
            self.assertFalse(hasattr(obj, "__dict__"))
        self.assertEqual((recipe.width, recipe.height, recipe.center, recipe.radius, recipe.turns,
                          recipe.baseline_id, recipe.domain(), recipe.graph(), recipe.index("k:3:2")),
                         (4, 5, 0, 2, BASE.turns, BASE.baseline_id, BASE.domain(), BASE.graph(), 17))

    def test_top_level_keys_and_strict_numbers(self):
        source = BINDING.to_dict()
        invalid = [None, [], {}, {**source, "unknown": 0}]
        invalid += [{key: item for key, item in source.items() if key != omitted} for omitted in source]
        for name, values in (("max_epochs", (-1, 5, True, 1.0, "1", None)),
                             ("cost", (0, 128, False, 1.0, None)),
                             ("generations", (-1, 9, True, 2.0)),
                             ("format", (None, True, "other"))):
            invalid.extend({**source, name: value} for value in values)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaperBinding.from_dict(value)
        for epochs in range(5):
            self.assertEqual(TaperBinding(epochs, 127).max_epochs, epochs)

    def test_symbols_tokens_rule_guard_and_expression_schema(self):
        source = BINDING.to_dict()
        mutations = []
        def add(path, value):
            item = deepcopy(source)
            target = item
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            mutations.append(item)
        for symbols in ([], source["symbols"] * 6, [{"name": "F", "arity": 1}],
                        [{"name": "lower", "arity": 0}], [{"name": "A" * 17, "arity": 0}],
                        [{"name": "A", "arity": True}], [{"name": "A", "arity": 5}],
                        [{"name": "A", "arity": 0}] * 2):
            add(["symbols"], symbols)
        for value in ([], [token("Z")], [token("A")], [token("A", True)],
                      [token("A", I32_MAX + 1)], [token("A", {"context": "energy", "mul": 1, "add": 0})],
                      [token("A", {"context": "tick", "mul": 32768, "add": 0})],
                      [token("A", {"context": "tick", "mul": 1, "add": False})]):
            add(["axiom"], value)
        add(["rules", 0, "symbol"], "F")
        add(["rules", 0, "rhs"], [token("F", {"arg": 1, "mul": 1, "add": 0})])
        for guard in ({"arg": True, "op": "eq", "value": 0}, {"arg": 0, "op": "other", "value": 0},
                      {"arg": 0, "op": "eq", "value": True}, {"arg": 0, "op": "xor_eq", "mask": -1, "value": 0},
                      {"arg": 0, "op": "xor_eq", "mask": 1, "value": 1 << 32},
                      {"arg": 0, "op": "eq", "value": 0, "mask": 1}):
            add(["rules", 0, "guards"], [guard])
        for name, minimum, maximum in (("max_symbols", 1, 1024), ("max_steps", 1, 4096),
                                       ("max_primitives", 1, 64), ("max_stack", 0, 32),
                                       ("max_primitive_sites", 1, 1 << 24)):
            for value in (minimum - 1, maximum + 1, True, 1.0):
                add(["limits", name], value)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                TaperBinding.from_dict(value)

    def test_original_context_full_pair_digest_and_stage_order(self):
        source = CONTEXT.to_dict()
        invalid = []
        for name, values in (("epoch", (0, 5, True, 1.0)), ("tick", (0, -1, I32_MAX + 1, False, 5.0)),
                             ("prefix_sha256", ("0" * 63, "A" * 64, "g" * 64, None)),
                             ("start_pair", (CONTEXT.start_pair.lower(), "0000000000000000", None,
                                              f"{int(CONTEXT.start_pair, 16) ^ 1:016X}",
                                              f"{pair(pack(0, 0, -2, int(Opcode.STEP))):016X}"))):
            invalid.extend({**source, name: value} for value in values)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                StageContext.from_dict(value)
        self.assertEqual(replace(CONTEXT, tick=I32_MAX).tick, I32_MAX)
        for stages in ([], (), (replace(CONTEXT, epoch=2),), (CONTEXT, CONTEXT),
                       (CONTEXT, replace(CONTEXT, epoch=2, tick=4))):
            with self.subTest(stages=stages), self.assertRaises(ValueError):
                generated(TaperBinding(2), stages)
        with self.assertRaises(ValueError):
            generated(TaperBinding(0))
        with self.assertRaises(ValueError):
            TaperFieldRecipe.from_dict({**generated().to_dict(), "fields": list(FIELDS)})

    def test_profiles_do_not_alias_old_grammar_recipe_or_codec(self):
        self.assertEqual(PROFILE, "klein-taper-organogram-v1")
        for source in (OrganogramBinding().to_dict(), {**BINDING.to_dict(), "organogram": {}}):
            with self.assertRaises(ValueError):
                TaperBinding.from_dict(source)
        old = GeneratedFieldRecipe(BASE, OrganogramBinding(), ROUTING, (CONTEXT,))
        for value in (old.to_dict(), {**generated().to_dict(), "format": old.version}):
            with self.assertRaises(ValueError):
                TaperFieldRecipe.from_dict(value)
        with self.assertRaises(ValueError):
            generated(OrganogramBinding())
        with self.assertRaises(ValueError):
            compile_tape(OrganogramBinding(), CONTEXT)
        with self.assertRaises(ValueError):
            preflight(compile_tape(BINDING, CONTEXT), BINDING, old)
        for profile in ("OG-TAPE32-v1", True, None):
            with self.assertRaises(ValueError):
                decode_tape((word(6),), profile=profile)
            with self.assertRaises(ValueError):
                encode_tape(tape_of([token("S")]), profile=profile)
        self.assertEqual(generated().binding, BINDING)

    def test_instruction_address_arity_and_exact_containers(self):
        for address in ([], (), (True,), (-1,), (32,), (0, 1), (0, 2, 0, 0),
                        (0, 1, -1, 1), (0, 1, 64, 0), (0, 1, 0, 32)):
            with self.subTest(address=address), self.assertRaises(ValueError):
                TapeInstruction(address, "S", ())
        for symbol, args in (("TAPER", (1, 1)), ("TAPER", (1, 1, 1, 1)),
                             ("TAPER", [1, 1, 1]), ("TAPER", (True, 1, 1)),
                             ("S", (0,)), ("A", (1,)), (False, ())):
            with self.subTest(symbol=symbol, args=args), self.assertRaises(ValueError):
                TapeInstruction((0,), symbol, args)
        value = TapeInstruction((0, 1, -1, 0), "TAPER", (1, 1, 2))
        detached = value.to_dict()
        detached["args"][0] = 7
        self.assertEqual(value.args, (1, 1, 2))
        with self.assertRaises(FrozenInstanceError):
            value.args = (3, 1, 2)


class TaperGrammarAndBudgetTests(unittest.TestCase):
    def test_frozen_tapes_addresses_work_and_words_for_every_mission_stage(self):
        for name in ("default_mission", "mirrored_default_mission", "two_epoch_mission"):
            mission = REFERENCE[name]
            binding = TaperBinding.from_dict(mission["binding"])
            for stage in mission["stages"]:
                expected = stage["result"]
                context = StageContext.from_dict(expected["document"]["context"])
                tape = compile_tape(binding, context)
                with self.subTest(mission=name, epoch=context.epoch):
                    self.assertEqual([x.to_dict() for x in tape], expected["document"]["tape"])
                    self.assertEqual(preflight(tape, binding, BASE).to_dict(), expected["preflight"])
                    self.assertEqual([f"{x:08X}" for x in encode_tape(tape)], expected["encoded_tape_words"])
                    self.assertEqual(list(word_offsets(tape)), expected["word_offsets"])
                    self.assertEqual(decode_tape(encode_tape(tape)), tuple((x.symbol, x.args) for x in tape))

    def test_parallel_first_rule_parameter_pass_erasure_and_overflow(self):
        binding = simple_binding([token("S")], generations=3)
        self.assertEqual(compile_tape(binding, CONTEXT)[0].address, (0, 1, -1, 0, 2, -1, 0, 3, -1, 0))
        for binding in (TaperBinding(generations=1), simple_binding([token("D")], generations=2),
                        simple_binding([token("A", 1)], generations=1, rules=[])):
            with self.assertRaises(ValueError):
                compile_tape(binding, CONTEXT)
        source = BINDING.to_dict()
        source.update(axiom=[token("A", 3)], generations=1,
                      rules=[{"symbol": "A", "guards": [], "rhs": [token("TAPER", {"arg": 0, "mul": 2, "add": -1}, 1, 2)]},
                             {"symbol": "A", "guards": [], "rhs": [token("S")]}])
        self.assertEqual(compile_tape(TaperBinding.from_dict(source), CONTEXT)[0].args, (5, 1, 2))
        source["rules"][0]["rhs"][0]["args"][0] = {"arg": 0, "mul": 32767, "add": I32_MAX}
        with self.assertRaises(ValueError):
            compile_tape(TaperBinding.from_dict(source), CONTEXT)
        source = BINDING.to_dict()
        source.update(axiom=[token("A", 0)], generations=8,
                      rules=[{"symbol": "A", "guards": [], "rhs": [token("A", 0)] * 32}])
        with self.assertRaises(ValueError):
            compile_tape(TaperBinding.from_dict(source), CONTEXT)

    def test_context_affine_inputs_and_unsigned_xor(self):
        context = frame(BASE, phase=187, orientation=1, epoch=2)
        for name, value in (("tick", 5), ("epoch", 2), ("phase", 69), ("field", -2)):
            binding = simple_binding([token("TAPER", {"context": name, "mul": 1, "add": 3}, 1, 65535)], max_epochs=2)
            self.assertEqual(compile_tape(binding, context)[0].args[0], value + 3)
        binding = simple_binding([token("A", -1)], generations=1,
            rules=[{"symbol": "A", "guards": [{"arg": 0, "op": "xor_eq", "mask": 0xFFFFFFFF, "value": 0}],
                    "rhs": [token("TAPER", 1, 1, 2)]}])
        self.assertEqual(compile_tape(binding, CONTEXT)[0].symbol, "TAPER")
        binding = simple_binding([token("TAPER", {"context": "tick", "mul": 32767, "add": 0}, 1, 65535)])
        with self.assertRaises(ValueError):
            compile_tape(binding, replace(CONTEXT, tick=I32_MAX))

    def test_strict_terminal_and_work_rejections_before_geometry(self):
        cases = [[token("TAPER", *args)] for args in ((True, 1, 1), (1, 1.0, 1), (0, 1, 1),
                (65536, 1, 1), (1, 0, 1), (1, 1, 0), (1, 2, 2), (65535, 65535, 1), (32768, 65535, 1))]
        cases += [[token("R", 127), token("SCALE", 1), token("S")],
                  [token("]"), token("S")], [token("["), token("S")], [token("F", 1)],
                  [token("F", 257), token("S")], [token("+", 17), token("S")],
                  [token("SCALE", 5), token("S")], [token("TAPER", 65535, 1, 1)]]
        with patch("solvefinite.taper.occupancy_cpu", side_effect=AssertionError("geometry before rejection")):
            for tokens in cases:
                with self.subTest(tokens=tokens), self.assertRaises(ValueError):
                    binding = simple_binding(tokens)
                    preflight(compile_tape(binding, CONTEXT), binding, BASE)
        for bad in (None, {}, BASE.to_dict()):
            with self.assertRaises(ValueError):
                preflight(compile_tape(BINDING, CONTEXT), BINDING, bad)

    def test_exact_summed_site_budget_and_nested_restoration(self):
        tokens = [token("TAPER", 3, 1, 2), token("S")]
        limits = {**BINDING.limits, "max_primitive_sites": 32}
        binding = simple_binding(tokens, limits=limits)
        self.assertEqual(preflight(compile_tape(binding, CONTEXT), binding, BASE).primitive_sites, 32)
        smaller = simple_binding(tokens, limits={**limits, "max_primitive_sites": 31})
        with self.assertRaises(ValueError):
            preflight(compile_tape(smaller, CONTEXT), smaller, BASE)
        tokens = [token("["), token("SCALE", 1), token("R", 2), token("TAPER", 1, 1, 2),
                  token("]"), token("S"), token("F", 1)]
        binding = simple_binding(tokens)
        work = preflight(compile_tape(binding, CONTEXT), binding, BASE)
        self.assertEqual((work.primitive_sites, work.effective_steps, work.stack_high_water), (29, 1, 1))
        self.assertEqual(taper_bounds(4, 5, 1, 1, 2, 0), REFERENCE["encoding_vectors"]["thin_bounds"])
        self.assertEqual(taper_bounds(4, 5, 65535, 1, 65535, 0), REFERENCE["encoding_vectors"]["maximum_raw_height_thin_bounds"])

    def test_maximum_work_limits_and_all_stages_reject_before_base_producer(self):
        limits = {"max_symbols": 1024, "max_steps": 4096, "max_primitives": 64,
                  "max_stack": 32, "max_primitive_sites": 1 << 24}
        binding = TaperBinding(limits=limits)
        tape = tape_of([token("TAPER", 1, 1, 65535)] * 64 + [token("SCALE", 0)] * 960)
        expected = REFERENCE["encoding_vectors"]["maximum_texture"]
        self.assertEqual(preflight(tape, binding, BASE).to_dict(), expected["preflight"])
        words = [f"{x:08X}" for x in encode_tape(tape)]
        self.assertEqual(sha256(canonical_bytes(words)).hexdigest(), expected["words_sha256"])
        self.assertEqual((word_offsets(tape)[64], word_offsets(tape)[-1]), (192, 1151))
        self.assertEqual(len(decode_tape(encode_tape(tape))), 1024)
        for changed, key, value in ((tape, "max_primitives", 63), (tape, "max_symbols", 1023)):
            with self.assertRaises(ValueError):
                preflight(changed, TaperBinding(limits={**limits, key: value}), BASE)
        deep = tape_of([token("[")] * 32 + [token("SCALE", 4), token("F", 256)] + [token("]")] * 32 + [token("S")])
        self.assertEqual(preflight(deep, binding, BASE).effective_steps, 4096)
        with self.assertRaises(ValueError):
            preflight(deep, TaperBinding(limits={**limits, "max_stack": 31}), BASE)
        bad_binding = simple_binding([token("TAPER", {"context": "tick", "mul": 1, "add": 0}, 1, 65535)], max_epochs=2)
        # Stage one is structurally valid; stage two's raw h is out of range.
        recipe = generated(bad_binding, (CONTEXT, replace(CONTEXT, epoch=2, tick=65536)))
        with patch("solvefinite.taper.evaluate_field", side_effect=AssertionError("base allocated")):
            with self.assertRaises(ValueError):
                regenerate(recipe)

    def test_literal_codec_and_every_malformed_word_category(self):
        vectors = REFERENCE["encoding_vectors"]
        tape = tape_of(vectors["literal_logical_instructions"])
        words = tuple(int(x, 16) for x in vectors["literal_words"])
        self.assertEqual(encode_tape(tape), words)
        self.assertEqual(list(word_offsets(tape)), vectors["word_offsets"])
        self.assertEqual(decode_tape(words), tuple((x.symbol, x.args) for x in tape))
        good = encode_tape(tape_of([token("TAPER", 3, 1, 2)]))
        invalid = [(), list(good), None, (True,), (1.0,), ("88000003",), (-1,), (1 << 32,),
                   good[:1], good[:2], (good[0], good[2], good[1]), good[1:], (good[2],),
                   (word(6, 1),), (word(8, 0), good[1], good[2]), (word(11),),
                   (word(0, 0),), (word(0, 257),), (word(7, 5),),
                   (good[0] ^ 1, *good[1:]), (word(8, 3) ^ 0x80010000, *good[1:]),
                   (word(6),) * 1153, (word(6),) * 1025,
                   (word(8, 1), word(9, 2), word(10, 2))]
        for value in invalid:
            with self.subTest(words=str(value)[:100]), self.assertRaises(ValueError):
                decode_tape(value)


class TaperGeometryTests(unittest.TestCase):
    def test_literal_footprints_inner_boundaries_and_exact_fields(self):
        for case in REFERENCE["geometry_vectors"]["fixtures"]:
            source = case["prior_recipe"]
            base = KleinFieldRecipe(width=source["width"], height=source["height"], center=source["center"], radius=source["radius"])
            with self.subTest(fixture=case["name"]):
                occupied = occupancy_cpu(base, [case["primitive"]])
                signs = union_signs_cpu(base, [case["primitive"]])
                fields = evaluate_field(replace(base.field_manifest(), signs=signs))
                self.assertEqual([i for i, flag in enumerate(occupied) if flag], case["occupancy"])
                self.assertEqual(list(signs), case["signs"])
                self.assertEqual(list(fields), case["field"])
                self.assertEqual([i for i, x in enumerate(signs) if x == 0], case["boundary"])
                self.assertEqual([i for i, x in enumerate(signs) if x < 0], case["interior"])
                for u, v, _ in base.domain().edges:
                    self.assertLessEqual(abs(fields[u] - fields[v]), 1)
                    self.assertNotEqual(signs[u] * signs[v], -1)
                mirrored = deepcopy(case["primitive"])
                mirrored["pair"] = mirrored["pair"][8:] + mirrored["pair"][:8]
                self.assertEqual(occupancy_cpu(base, [mirrored]), occupied)

    def test_overlap_removes_hidden_boundary_and_is_not_minimum_of_fields(self):
        expected = REFERENCE["geometry_vectors"]["overlap"]
        base = KleinFieldRecipe(8, 8)
        signs = union_signs_cpu(base, expected["primitives"])
        fields = evaluate_field(replace(base.field_manifest(), signs=signs))
        self.assertEqual(list(fields), expected["field"])
        self.assertEqual([i for i, (a, b) in enumerate(zip(fields, expected["minimum_separate_fields"])) if a != b],
                         expected["differing_nodes"])
        self.assertNotEqual(list(fields), expected["minimum_separate_fields"])
        self.assertEqual(fields[35], -1)
        duplicate = expected["primitives"] + expected["primitives"]
        self.assertEqual(union_signs_cpu(base, duplicate), signs)

    def test_thin_legal_and_old_positive_radius_ball_union_witness(self):
        cases = {x["name"]: x for x in REFERENCE["geometry_vectors"]["fixtures"]}
        thin = cases["thin_zero_width"]
        self.assertEqual(thin["interior"], [])
        self.assertEqual(thin["occupancy"], thin["boundary"])
        witness = REFERENCE["geometry_vectors"]["old_ball_union_separation_witness"]
        fields = cases["unwrapped"]["field"]
        self.assertEqual(fields[witness["boundary_node"]], 0)
        self.assertTrue(all(fields[x] >= 0 for x in witness["adjacent_nodes"]))
        self.assertEqual(cases["unwrapped"]["interior"], [19, 26, 27, 28])

    def test_single_ball_profile_uses_inner_boundary_even_at_cut_locus(self):
        base = KleinFieldRecipe(3, 3, radius=1)
        binding = simple_binding([token("R", 2), token("S")])
        context = frame(base)
        # Closed radius-two ball fills this quotient. Old OG still has zero
        # distance margins at its cut locus, whereas DP correctly rejects it.
        with self.assertRaises(ValueError):
            regenerate(generated(binding, (context,), base))

    def test_empty_full_and_malformed_direct_geometry_rejected(self):
        for mask in ((False,) * 20, (True,) * 20, (0,) * 20, [False] * 20, ()):
            with self.assertRaises(ValueError):
                signs_from_occupancy_cpu(BASE, mask)
        primitive = deepcopy(REFERENCE["geometry_vectors"]["fixtures"][0]["primitive"])
        for path, value in (("height", True), ("height", 0), ("height", 65535 << 5),
                            ("numerator", 1.0), ("denominator", 0), ("shaft", 4),
                            ("kind", "cone"), ("apex", 64), ("pair", primitive["pair"].lower()),
                            ("branch_path", ()), ("address", [True])):
            bad = deepcopy(primitive)
            bad[path] = value
            with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                occupancy_cpu(KleinFieldRecipe(8, 8), [bad])
        for items in ([], [primitive] * 65, [{**primitive, "extra": 0}]):
            with self.assertRaises(ValueError):
                occupancy_cpu(KleinFieldRecipe(8, 8), items)


class TaperCertificationTests(unittest.TestCase):
    def test_all_frozen_stages_are_exact_and_preserve_original_contexts(self):
        for name in ("default_mission", "mirrored_default_mission", "two_epoch_mission"):
            mission = REFERENCE[name]
            binding = TaperBinding.from_dict(mission["binding"])
            contexts, prior, certificate = (), BASE, None
            for stage in mission["stages"]:
                result = stage["result"]
                context = StageContext.from_dict(result["document"]["context"])
                contexts += (context,)
                recipe = generated(binding, contexts)
                prior_fields = tuple(stage["prior_field"])
                with self.subTest(mission=name, epoch=context.epoch):
                    self.assertEqual(interpret_cpu(prior, prior_fields, binding, context, ROUTING), result["document"])
                    certificate = stage_certificate(recipe, result, prior_fields, certificate)
                    self.assertEqual(certificate.derivation_sha256, result["derivation_sha256"])
                    self.assertEqual(certificate.last_derivation, result["document"])
                    self.assertEqual(certificate.fields, tuple(result["union"]["field"]))
                    self.assertEqual(select_target(recipe, certificate.fields, unpack(unpair(int(context.start_pair, 16))[0])[1],
                        stage["selection"]["intrinsic_phase"], certificate=certificate), stage["selection"]["target"])
                prior = recipe
            fresh = regenerate(recipe)
            self.assertEqual(fresh, certificate)
            self.assertEqual(TaperFieldRecipe.from_dict(recipe.to_dict()), recipe)

    def test_context_parameter_phase_and_full_mirror_mutations_match_vectors(self):
        vectors = REFERENCE["mutation_vectors"]
        base = KleinFieldRecipe(8, 8)
        fields = evaluate_field(base.field_manifest())
        fields_seen = {}
        for name in ("context_parameter_baseline", "later_original_tick", "different_intrinsic_phase", "narrower_slope", "full_mirror"):
            result = vectors[name]
            context = StageContext.from_dict(result["document"]["context"])
            binding = TaperBinding.from_dict(vectors["narrower_slope_binding" if name == "narrower_slope" else "binding"])
            recipe = generated(binding, (context,), base)
            with self.subTest(mutation=name):
                certificate = regenerate(recipe)
                self.assertEqual(certificate.last_derivation, result["document"])
                self.assertEqual(list(certificate.fields), result["union"]["field"])
                self.assertEqual(certify_derivation(base, fields, binding, context, ROUTING, result["document"]), result["derivation_sha256"])
                fields_seen[name] = certificate.fields
        self.assertEqual(fields_seen["full_mirror"], fields_seen["context_parameter_baseline"])
        for name in ("later_original_tick", "different_intrinsic_phase", "narrower_slope"):
            self.assertNotEqual(fields_seen[name], fields_seen["context_parameter_baseline"])

    def test_nested_pop_restores_full_context_while_transcript_keeps_seam_steps(self):
        document = regenerate(generated()).last_derivation
        trace = document["trace"]
        self.assertEqual((trace[10]["pair"], trace[10]["radius"], trace[10]["scale"]), ("91FE00B181FE004F", 2, 1))
        self.assertEqual((trace[11]["pair"], trace[11]["radius"], trace[11]["scale"]), ("81020C5791020CA9", 1, 0))
        self.assertEqual(trace[12]["pair"], "81011145910111BB")
        self.assertEqual(document["final_context"]["pair"], "81011145910111BB")
        self.assertEqual(len(document["primitives"]), 3)
        self.assertEqual(len(document["segments"]), 7)

    def test_certifier_cannot_fall_back_to_any_cpu_geometry_or_trajectory_producer(self):
        forbidden = ("interpret_cpu", "occupancy_cpu", "union_signs_cpu", "signs_from_occupancy_cpu",
                     "regenerate", "evaluate_field", "_distances", "_packed")
        with ExitStack() as stack:
            for name in forbidden:
                stack.enter_context(patch("solvefinite.taper." + name, side_effect=AssertionError("CPU producer used: " + name)))
            stack.enter_context(patch.object(TaperFieldRecipe, "field_manifest", side_effect=AssertionError("CPU reconstruction")))
            stack.enter_context(patch("solvefinite.psi.field_axes", side_effect=AssertionError("CPU axis compiler")))
            certificate = stage_certificate(generated(), RESULT)
            self.assertEqual(certificate.fields, tuple(RESULT["union"]["field"]))
        # Target ranking is declared host policy and may use quotient BFS.
        self.assertEqual(select_target(generated(), certificate.fields, 17, 69, certificate=certificate), 5)

    def test_document_mutations_missing_extras_wrong_types_and_identity_rejected(self):
        document = RESULT["document"]
        invalid = [None, [], {}, {**document, "balls": []}, {**document, "format": "klein-organogram-derivation-v1"}]
        invalid += [{k: v for k, v in document.items() if k != omitted} for omitted in document]
        def mutate(path, value):
            item = deepcopy(document)
            cursor = item
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            invalid.append(item)
        for category in ("tape", "trace", "segments", "primitives"):
            mutate([category], document[category][:-1])
            mutate([category], document[category] + [document[category][-1]])
            mutate([category], tuple(document[category]))
            mutate([category, 0, "extra"], 0)
        for path, value in ((["context", "tick"], True), (["context", "prefix_sha256"], "1" * 64),
                            (["tape", 0, "args"], [0]), (["trace", 0, "radius"], True),
                            (["trace", 0, "scale"], 0.0), (["segments", 0, "step"], False),
                            (["primitives", 0, "kind"], "ball"), (["primitives", 0, "shaft"], 0),
                            (["primitives", 0, "height"], 4), (["primitives", 0, "numerator"], 2),
                            (["primitives", 0, "pair"], document["primitives"][1]["pair"]),
                            (["primitives", 1, "branch_path"], []), (["primitives", 2, "radius"], 2),
                            (["final_context", "radius"], 2), (["final_context", "pair"], CONTEXT.start_pair)):
            mutate(path, value)
        bad = deepcopy(document)
        bad["trace"][0]["pair"] = bad["trace"][0]["pair"][8:] + bad["trace"][0]["pair"][:8]
        invalid.append(bad)
        cycle = deepcopy(document)
        cycle["trace"] = [cycle]
        invalid.append(cycle)
        mutate(["trace"], [None] * 4097)
        for index, item in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                certify_derivation(BASE, FIELDS, BINDING, CONTEXT, ROUTING, item)

    def test_occupancy_and_exact_distance_are_independently_certified(self):
        recipe = generated()
        signs = tuple(RESULT["union"]["signs"])
        fields = tuple(RESULT["union"]["field"])
        for node in range(len(signs)):
            changed = list(signs)
            changed[node] = 1 if signs[node] != 1 else 0
            with self.subTest(sign_node=node), self.assertRaises(ValueError):
                certify_stage(recipe, FIELDS, RESULT["document"], tuple(changed), fields)
        for node in range(len(fields)):
            changed = list(fields)
            changed[node] += 1 if fields[node] >= 0 else -1
            with self.subTest(field_node=node), self.assertRaises(ValueError):
                certify_stage(recipe, FIELDS, RESULT["document"], signs, tuple(changed))
        for bad_signs, bad_fields in ((list(signs), fields), (signs, list(fields)), (signs[:-1], fields),
                                     ((False,) + signs[1:], fields), (signs, (0.0,) + fields[1:])):
            with self.assertRaises(ValueError):
                certify_stage(recipe, FIELDS, RESULT["document"], bad_signs, bad_fields)

    def test_sealed_certificate_detached_json_and_contiguous_recipe_provenance(self):
        certificate = stage_certificate(generated(), RESULT)
        with self.assertRaises(ValueError):
            TaperFieldCertificate()
        for name in ("fields", "recipe", "_last_document", "stage_digests"):
            with self.assertRaises(FrozenInstanceError):
                setattr(certificate, name, None)
        detached = certificate.last_derivation
        detached["primitives"][0]["height"] = 999
        self.assertEqual(certificate.last_derivation, RESULT["document"])
        mission = REFERENCE["two_epoch_mission"]
        binding = TaperBinding.from_dict(mission["binding"])
        contexts = tuple(StageContext.from_dict(x["result"]["document"]["context"]) for x in mission["stages"])
        first = stage_certificate(generated(binding, contexts[:1]), mission["stages"][0]["result"])
        second_recipe = generated(binding, contexts)
        second = mission["stages"][1]
        for prior in (None, certificate, object()):
            with self.assertRaises(ValueError):
                stage_certificate(second_recipe, second["result"], tuple(second["prior_field"]), prior)
        with self.assertRaises(ValueError):
            stage_certificate(generated(), RESULT, prior_certificate=first)
        good = stage_certificate(second_recipe, second["result"], tuple(second["prior_field"]), first)
        self.assertEqual(len(good.stage_digests), 2)
        with self.assertRaises(ValueError):
            select_target(second_recipe, good.fields, 0, 0, certificate=certificate)
        with self.assertRaises(ValueError):
            select_target(second_recipe, tuple(False for _ in good.fields), 0, 0, certificate=good)

    def test_independent_membership_certificate_across_domains_axes_mirrors_and_seams(self):
        checked = 0
        for width, height in ((3, 3), (4, 5), (8, 8), (3, 85), (85, 3), (16, 16)):
            base = KleinFieldRecipe(width, height)
            fields = evaluate_field(base.field_manifest())
            nodes = (0, width * height - 1, width * height // 2, height + 1)
            for i, node in enumerate(nodes):
                for phase in (0, 64, 128, 192):
                    mirror_results = []
                    for orientation in (0, 1):
                        r = -phase % 256 if orientation else phase
                        context = frame(base, node=node, phase=r, orientation=orientation)
                        binding = simple_binding([token("TAPER", 1 + i % 3, 1, 2)])
                        recipe = generated(binding, (context,), base)
                        with self.subTest(domain=(width, height), node=node, phase=phase, eta=orientation):
                            document = interpret_cpu(base, fields, binding, context, ROUTING)
                            occupied = occupancy_cpu(recipe, document["primitives"])
                            if all(occupied):
                                with self.assertRaises(ValueError):
                                    regenerate(recipe)
                                with self.assertRaises(ValueError):
                                    certify_stage(recipe, fields, document, (0,) * len(fields), (0,) * len(fields))
                            else:
                                signs = union_signs_cpu(recipe, document["primitives"])
                                new_fields = evaluate_field(recipe.field_manifest_from_signs(signs))
                                with patch("solvefinite.taper.occupancy_cpu", side_effect=AssertionError("shared producer")):
                                    certificate = certify_stage(recipe, fields, document, signs, new_fields)
                                mirror_results.append((occupied, certificate.fields))
                                checked += 1
                    if len(mirror_results) == 2:
                        self.assertEqual(*mirror_results)
        self.assertEqual(checked, 192)

    def test_context_prior_field_routing_and_old_recipe_mismatch_rejected(self):
        wrong_pair = f"{pair(pack(69, 17, 0, int(Opcode.EMIT) | 16)):016X}"
        wrong_context = replace(CONTEXT, start_pair=wrong_pair)
        self.assertNotEqual(wrong_context.start_pair, CONTEXT.start_pair)
        for bad_fields in (FIELDS[:-1], list(FIELDS), (True,) + FIELDS[1:], (1.0,) + FIELDS[1:],
                           (128,) + FIELDS[1:]):
            with self.subTest(fields=bad_fields), self.assertRaises(ValueError):
                interpret_cpu(BASE, bad_fields, BINDING, CONTEXT, ROUTING)
        invalid_b = replace(CONTEXT, start_pair=f"{pair(pack(187, 17, 0, int(Opcode.EMIT) | 16)):016X}")
        with self.assertRaises(ValueError):
            interpret_cpu(BASE, FIELDS, BINDING, invalid_b, ROUTING)
        with self.assertRaises(ValueError):
            certify_derivation(BASE, FIELDS, BINDING, wrong_context, ROUTING, RESULT["document"])
        with self.assertRaises(ValueError):
            interpret_cpu(BASE, FIELDS, BINDING, replace(CONTEXT, epoch=2), ROUTING)
        with self.assertRaises(ValueError):
            interpret_cpu(GeneratedFieldRecipe(BASE, OrganogramBinding(), ROUTING, (CONTEXT,)),
                          FIELDS, BINDING, CONTEXT, ROUTING)
        prior = regenerate(generated(TaperBinding(max_epochs=2)))
        next_context = replace(CONTEXT, epoch=2, tick=12)
        with self.assertRaises(ValueError):
            interpret_cpu(prior.recipe, prior.fields, TaperBinding(max_epochs=2, cost=2), next_context, ROUTING)


if __name__ == "__main__":
    unittest.main()
