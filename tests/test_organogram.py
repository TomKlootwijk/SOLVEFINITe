"""OG arithmetic and admission against the committed preimplementation oracle."""

from collections import deque
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.field import evaluate_field
from solvefinite.field_world import KleinFieldRecipe, resolve_field_certificate
from solvefinite.hadamard import HadamardBinding
from solvefinite.organogram import (
    I32_MAX, I32_MIN, OrganogramBinding, StageContext, TapeInstruction,
    GeneratedFieldRecipe, GeneratedFieldCertificate, canonical_bytes,
    compile_tape, preflight, encode_tape, decode_instruction, interpret_cpu,
    certify_derivation, certify_stage, closed_distance, union_signs_cpu,
    regenerate, select_target,
)
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair


REFERENCE_DIR = Path(__file__).resolve().parents[1] / "docs/evidence/organogram-v1"
REFERENCE = json.loads((REFERENCE_DIR / "formal-reference.json").read_text(encoding="utf-8"))
SPEC = importlib.util.spec_from_file_location("independent_organogram_reference", REFERENCE_DIR / "reference-builder.py")
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)
BASE = KleinFieldRecipe()
ROUTING = HadamardBinding()
BINDING = OrganogramBinding.from_dict(REFERENCE["binding"])
CONTEXT = StageContext.from_dict(REFERENCE["standalone_stage"]["document"]["context"])
FIELDS = evaluate_field(BASE.field_manifest())


def simple_binding(tokens, *, generations=0, **updates):
    source = BINDING.to_dict()
    source.update(axiom=tokens, generations=generations, **updates)
    return OrganogramBinding.from_dict(source)


def token(symbol, *args):
    return {"symbol": symbol, "args": list(args)}


def generated(binding=BINDING, contexts=(CONTEXT,)):
    return GeneratedFieldRecipe(BASE, binding, ROUTING, contexts)


def oracle_stages(mission):
    reference = REFERENCE[mission]
    binding = OrganogramBinding.from_dict(reference["binding"])
    contexts = tuple(StageContext.from_dict(item["result"]["document"]["context"]) for item in reference["stages"])
    return generated(binding, contexts), reference["stages"]


class OrganogramSchemaTests(unittest.TestCase):
    def test_frozen_binding_context_recipe_and_detached_json(self):
        self.assertEqual(OrganogramBinding().to_dict(), REFERENCE["binding"])
        value = BINDING.to_dict()
        value["rules"][0]["rhs"][0]["symbol"] = "S"
        self.assertEqual(BINDING.to_dict(), REFERENCE["binding"])
        limits = BINDING.limits
        limits["max_steps"] = 1
        self.assertEqual(BINDING.limits["max_steps"], 128)
        recipe = generated()
        self.assertEqual(GeneratedFieldRecipe.from_dict(recipe.to_dict()), recipe)
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
                OrganogramBinding.from_dict(value)
        for epochs in range(5):
            self.assertEqual(OrganogramBinding(epochs, 127).max_epochs, epochs)

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
                                       ("max_balls", 1, 64), ("max_stack", 0, 32)):
            for value in (minimum - 1, maximum + 1, True, 1.0):
                add(["limits", name], value)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ValueError):
                OrganogramBinding.from_dict(value)

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
                generated(OrganogramBinding(2), stages)
        with self.assertRaises(ValueError):
            generated(OrganogramBinding(0))
        with self.assertRaises(ValueError):
            GeneratedFieldRecipe.from_dict({**generated().to_dict(), "fields": list(FIELDS)})


class OrganogramGrammarTests(unittest.TestCase):
    def test_parallel_addresses_first_matching_rule_erasure_and_tape_words(self):
        tape = compile_tape(BINDING, CONTEXT)
        expected = REFERENCE["standalone_stage"]
        self.assertEqual([entry.to_dict() for entry in tape], expected["document"]["tape"])
        self.assertEqual(preflight(tape, BINDING).to_dict(), expected["preflight"])
        self.assertEqual([f"{value:08X}" for value in encode_tape(tape)], expected["encoded_tape_words"])
        self.assertEqual(len(tape), 19)
        self.assertTrue(all(item.address[0] == 0 for item in tape))  # D erased.
        self.assertEqual(tape[3].address, (0, 1, 0, 3, 2, 2, 0))
        self.assertEqual(tape[15].address, (0, 1, 0, 14, 2, 3, 0))
        with self.assertRaises(ValueError):
            compile_tape(OrganogramBinding(generations=1), CONTEXT)  # B has not rewritten yet.

    def test_pass_unmatched_final_and_empty_rhs(self):
        binding = simple_binding([token("S")], generations=3)
        tape = compile_tape(binding, CONTEXT)
        self.assertEqual(tape[0].address, (0, 1, -1, 0, 2, -1, 0, 3, -1, 0))
        for tokens, rules in (([token("A", 0)], []), ([token("D")], [{"symbol": "D", "guards": [], "rhs": []}])):
            with self.assertRaises(ValueError):
                compile_tape(simple_binding(tokens, generations=2, rules=rules), CONTEXT)
        source = BINDING.to_dict()
        source.update(axiom=[token("A", 0), token("S")], generations=2,
                      rules=[{"symbol": "A", "guards": [], "rhs": [token("B", 1)]},
                             {"symbol": "B", "guards": [], "rhs": []}])
        self.assertEqual([item.symbol for item in compile_tape(OrganogramBinding.from_dict(source), CONTEXT)], ["S"])

    def test_all_context_inputs_affine_guards_and_overflow(self):
        context = StageContext(2, 5, f"{pair(pack(187, 0, -2, 22)):016X}", "0" * 64)
        for case in REFERENCE["expression_vectors"]["context_cases"]:
            binding = simple_binding([token("F", case["expression"]), token("S")], max_epochs=2)
            self.assertEqual(compile_tape(binding, context)[0].args, (case["expected"],))
        for case in REFERENCE["expression_vectors"]["guard_cases"]:
            source = BINDING.to_dict()
            source.update(axiom=[token("A", *case["args"])], generations=1,
                          rules=[{"symbol": "A", "guards": [case["guard"]], "rhs": [token("S")]},
                                 {"symbol": "A", "guards": [], "rhs": [token("R", 2), token("S")]}])
            self.assertEqual([item.symbol for item in compile_tape(OrganogramBinding.from_dict(source), CONTEXT)], ["S"])
        for case in REFERENCE["expression_vectors"]["overflow_rejections"]:
            source = BINDING.to_dict()
            source.update(axiom=[token("A", *case["args"])], generations=1,
                          rules=[{"symbol": "A", "guards": [], "rhs": [token("F", case["expression"]), token("S")]}])
            with self.subTest(case=case), self.assertRaises(ValueError):
                compile_tape(OrganogramBinding.from_dict(source), CONTEXT)
        with self.assertRaises(ValueError):
            compile_tape(simple_binding([token("F", {"context": "tick", "mul": 32767, "add": 0}), token("S")]),
                         replace(CONTEXT, tick=I32_MAX))

    def test_intermediate_symbol_budget_and_terminal_work_limits(self):
        cases = [([token("]"), token("S")], {}), ([token("["), token("S")], {}),
                 ([token("F", 0), token("S")], {}), ([token("F", 257), token("S")], {}),
                 ([token("+", 17), token("S")], {}), ([token("-", 0), token("S")], {}),
                 ([token("R", 128), token("S")], {}), ([token("SCALE", 5), token("S")], {}),
                 ([token("R", 64), token("SCALE", 1), token("S")], {}),
                 ([token("F", 1)], {}), ([token("F", 2), token("S")], {"max_steps": 1}),
                 ([token("S"), token("S")], {"max_balls": 1}),
                 ([token("["), token("S"), token("]")], {"max_stack": 0})]
        for tokens, changes in cases:
            limits = {**BINDING.limits, **changes}
            with self.subTest(tokens=tokens, changes=changes), self.assertRaises(ValueError):
                compile_tape(simple_binding(tokens, limits=limits), CONTEXT)
        # The final erasure cannot conceal an oversized intermediate word.
        source = BINDING.to_dict()
        source.update(axiom=[token("A", 0)], generations=2,
                      rules=[{"symbol": "A", "guards": [], "rhs": [token("D"), token("D"), token("S")]},
                             {"symbol": "D", "guards": [], "rhs": []}],
                      limits={**BINDING.limits, "max_symbols": 2})
        with self.assertRaises(ValueError):
            compile_tape(OrganogramBinding.from_dict(source), CONTEXT)
        # Radius/scale restoration makes the subsequent S valid.
        binding = simple_binding([token("["), token("R", 127), token("SCALE", 4), token("]"), token("S")])
        self.assertEqual(preflight(compile_tape(binding, CONTEXT), binding).balls, 1)
        maximum = simple_binding([token("SCALE", 4), token("F", 256), token("SCALE", 0), token("S")],
                                 limits={**BINDING.limits, "max_steps": 4096})
        self.assertEqual(preflight(compile_tape(maximum, CONTEXT), maximum).effective_steps, 4096)

    def test_signed_affine_extrema_survive_parallel_parameters(self):
        for case in REFERENCE["expression_vectors"]["parameter_cases"]:
            source = BINDING.to_dict()
            source["symbols"][0]["arity"] = len(case["args"])
            source.update(axiom=[token("A", *case["args"])], generations=2,
                          rules=[{"symbol": "A", "guards": [], "rhs": [token("B", case["expression"])]},
                                 {"symbol": "B", "guards": [{"arg": 0, "op": "eq", "value": case["expected"]}],
                                  "rhs": [token("S")]}, {"symbol": "B", "guards": [], "rhs": []}])
            with self.subTest(case=case):
                self.assertEqual([item.symbol for item in compile_tape(OrganogramBinding.from_dict(source), CONTEXT)], ["S"])

    def test_signed_comparison_guards_conjunction_and_false_fallback(self):
        for operator, value, rhs, matches in (("eq", -1, -1, True), ("ne", -1, 1, True),
                                               ("lt", I32_MIN, 0, True), ("le", -1, -1, True),
                                               ("gt", I32_MAX, 0, True), ("ge", 0, 0, True),
                                               ("eq", -1, 1, False), ("ne", -1, -1, False),
                                               ("lt", 1, 0, False), ("le", 0, -1, False),
                                               ("gt", -1, 0, False), ("ge", -1, 0, False)):
            source = BINDING.to_dict()
            source.update(axiom=[token("A", value)], generations=1,
                          rules=[{"symbol": "A", "guards": [{"arg": 0, "op": operator, "value": rhs},
                                                             {"arg": 0, "op": "eq", "value": value}],
                                  "rhs": [token("S")]},
                                 {"symbol": "A", "guards": [], "rhs": [token("R", 2), token("S")]}])
            with self.subTest(operator=operator, value=value, rhs=rhs):
                self.assertEqual([item.symbol for item in compile_tape(OrganogramBinding.from_dict(source), CONTEXT)],
                                 ["S"] if matches else ["R", "S"])

    def test_instruction_profile_and_strict_corruption_rejection(self):
        vectors = REFERENCE["instruction_profile"]["encoding_vectors"]
        tape = tuple(TapeInstruction((index,), item["symbol"], tuple(item["args"]))
                     for index, item in enumerate(vectors["tokens"]))
        words = encode_tape(tape)
        self.assertEqual([f"{word:08X}" for word in words], vectors["words"])
        self.assertEqual(tuple(decode_instruction(word) for word in words), tuple((i.symbol, i.args) for i in tape))
        for word in words:
            for bit in range(32):
                with self.subTest(word=word, bit=bit), self.assertRaises(ValueError):
                    decode_instruction(word ^ (1 << bit))
        for raw in (1 << 16, 1 << 27, (6 << 24) | 1, (5 << 24) | 128, 257):
            even = raw | ((raw.bit_count() & 1) << 31)
            with self.assertRaises(ValueError):
                decode_instruction(even)
        for args in (((0, 2, -1, 0), "S", ()), ((0, 1, -1, 1), "S", ()), ((True,), "S", ()),
                     ((0,), "F", (True,)), ((0,), "A", ())):
            with self.assertRaises(ValueError):
                TapeInstruction(*args)


class OrganogramFieldTests(unittest.TestCase):
    def test_pinned_preimplementation_hashes(self):
        self.assertEqual(hashlib.sha256((REFERENCE_DIR / "formal-reference.json").read_bytes()).hexdigest(),
                         "21df28af479fbae2c70a7390a71b0baf9322fcbf38de3ce9db8ff5e5f3b4a6fe")
        self.assertEqual(hashlib.sha256((REFERENCE_DIR / "reference-builder.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                         "987c0adced856312fc3581d921ec1badaec236c0230c63f25ef6f024959f32d8")
        self.assertEqual(REFERENCE["metric_certificate"]["ordered_node_pairs"], 19130481)

    def test_complete_literal_derivations_fields_mirror_and_time_variants(self):
        for name in ("standalone_stage", "mirrored_standalone_stage", "original_tick_variant_stage"):
            expected = REFERENCE[name]
            context = StageContext.from_dict(expected["document"]["context"])
            recipe = generated(contexts=(context,))
            result = regenerate(recipe)
            with self.subTest(stage=name):
                self.assertEqual(result.last_derivation, expected["document"])
                self.assertEqual(result.derivation_sha256, expected["derivation_sha256"])
                self.assertEqual(result.fields, tuple(expected["union"]["field"]))
                self.assertEqual(result.manifest.signs, tuple(expected["union"]["signs"]))
        self.assertNotEqual(regenerate(generated()).fields,
                            regenerate(generated(contexts=(replace(CONTEXT, tick=6),))).fields)

    def test_original_context_reconstruction_two_stages_and_targets(self):
        for name in ("default_mission", "mirrored_default_mission", "two_epoch_mission"):
            recipe, stages = oracle_stages(name)
            result = regenerate(recipe)
            self.assertEqual(result.fields, tuple(stages[-1]["result"]["union"]["field"]))
            self.assertEqual(result.last_derivation, stages[-1]["result"]["document"])
            self.assertEqual(result.stage_digests, tuple(item["result"]["derivation_sha256"] for item in stages))
            for length, expected in enumerate(stages, 1):
                prefix = replace(recipe, stages=recipe.stages[:length])
                certificate = regenerate(prefix)
                phase, node, _, metadata = unpack(unpair(int(prefix.stages[-1].start_pair, 16))[0])
                phase = (-phase if metadata & 16 else phase) % 256
                self.assertEqual(select_target(prefix, certificate.fields, node, phase, certificate=certificate),
                                 expected["selection"]["target"])
        recipe, _ = oracle_stages("two_epoch_mission")
        with patch("solvefinite.organogram.interpret_cpu", wraps=interpret_cpu) as producer:
            regenerate(recipe)
        self.assertEqual([call.args[3].tick for call in producer.call_args_list], [5, 10])

    def test_radius_scale_pair_and_branch_restore_across_nested_seam(self):
        document = regenerate(generated()).last_derivation
        before, restored = document["trace"][10:12]
        self.assertEqual((before["pair"], before["radius"], before["scale"]), ("91FE00B181FE004F", 2, 1))
        self.assertEqual((restored["pair"], restored["radius"], restored["scale"]), ("81020C5791020CA9", 1, 0))
        self.assertEqual(len(before["branch_path"]), 2)
        self.assertEqual(restored["branch_path"], before["branch_path"][:1])
        nested = [entry for entry in document["segments"] if len(entry["branch_path"]) == 2]
        self.assertEqual([unpack(unpair(int(entry["pair"], 16))[0])[1] for entry in nested], [11, 10, 15, 0])
        self.assertEqual(document["final_context"]["pair"], "81011145910111BB")

    def test_priority_mutation_changes_actual_union_field(self):
        grammar = BINDING.to_dict()
        grammar["rules"][2], grammar["rules"][3] = grammar["rules"][3], grammar["rules"][2]
        result = regenerate(generated(OrganogramBinding.from_dict(grammar)))
        expected = REFERENCE["priority_mutation"]["stage"]
        self.assertEqual(result.fields, tuple(expected["union"]["field"]))
        self.assertEqual(result.last_derivation, expected["document"])
        self.assertEqual([i for i, value in enumerate(result.fields) if value == 0], [13])

    def test_tie_banks_choose_cardinals_and_full_mirror_commutes(self):
        binding = simple_binding([token("F", 1), token("S")])
        routing = HadamardBinding(((0, 0),) * 4)
        for bank, direction in enumerate(("u+", "v+", "u-", "v-")):
            source = pair(pack(64 * bank, 0, FIELDS[0], int(Opcode.EMIT)))
            context = replace(CONTEXT, start_pair=f"{source:016X}")
            document = interpret_cpu(BASE, FIELDS, binding, context, routing)
            destination = BASE.domain().step(0, direction)[0]
            self.assertEqual(document["balls"][0]["center"], destination)
            self.assertEqual(certify_derivation(BASE, FIELDS, binding, context, routing, document),
                             hashlib.sha256(canonical_bytes(document)).hexdigest())
            mirrored = replace(context, start_pair=context.start_pair[8:] + context.start_pair[:8])
            reverse = interpret_cpu(BASE, FIELDS, binding, mirrored, routing)
            for entry, other in zip(document["trace"], reverse["trace"]):
                self.assertEqual(entry["pair"], other["pair"][8:] + other["pair"][:8])

    def test_union_is_redistanced_and_empty_boundary_rejected(self):
        case = REFERENCE["union_counterexample"]
        base = KleinFieldRecipe(3, 3, 0, 1)
        recipe = GeneratedFieldRecipe(base, BINDING, ROUTING,
                                      (replace(CONTEXT, start_pair=f"{pair(pack(0, 0, -1, 6)):016X}"),))
        signs = union_signs_cpu(recipe, case["balls"])
        field = evaluate_field(recipe.field_manifest_from_signs(signs))
        self.assertEqual(field, tuple(case["field"]))
        self.assertEqual([i for i, (q, phi) in enumerate(zip(case["margin"], field)) if q != phi], [2, 3])
        with self.assertRaises(ValueError):
            union_signs_cpu(recipe, REFERENCE["empty_boundary_vector"]["balls"])
        with self.assertRaises(ValueError):
            union_signs_cpu(recipe, [])
        binding = simple_binding([token("R", 127), token("S")])
        with self.assertRaises(ValueError):
            regenerate(generated(binding))

    def test_closed_metric_every_supported_geometry_against_independent_bfs(self):
        geometries = comparisons = 0
        for width in range(3, 86):
            for height in range(3, 256 // width + 1):
                if width * height > 256:
                    continue
                oracle = ORACLE.BASE.Quotient(width, height)
                geometries += 1
                sources = range(oracle.count) if oracle.count <= 36 else sorted({0, oracle.count // 2, oracle.count - 1})
                for source in sources:
                    distances = oracle.distance((source,))
                    for destination, expected in enumerate(distances):
                        self.assertEqual(closed_distance(width, height, source, destination), expected)
                        comparisons += 1
        self.assertEqual(geometries, 702)
        self.assertGreater(comparisons, 300000)

    def test_target_all_ties_and_strict_supplied_field(self):
        recipe = generated()
        certificate = regenerate(recipe)
        for phase in range(256):
            self.assertEqual(select_target(recipe, certificate.fields, 17, phase, certificate=certificate), (6, 9, 10)[phase % 3])
        values = list(certificate.fields)
        values[3] = False
        for field in (tuple(values), list(certificate.fields), certificate.fields[:-1]):
            with self.assertRaises(ValueError):
                select_target(recipe, field, 17, 69, certificate=certificate)
        for node, phase in ((True, 0), (20, 0), (0, True), (0, 256)):
            with self.assertRaises(ValueError):
                select_target(recipe, certificate.fields, node, phase, certificate=certificate)


class OrganogramAdmissionTests(unittest.TestCase):
    def test_shared_certificate_boundary_rejects_numerically_equal_nonintegers(self):
        recipe = generated()
        certificate = regenerate(recipe)
        with patch("solvefinite.organogram.regenerate", side_effect=AssertionError("CPU reconstruction")), \
                patch.object(GeneratedFieldRecipe, "field_manifest", side_effect=AssertionError("CPU manifest")):
            for container in (tuple, list):
                self.assertIs(resolve_field_certificate(recipe, container(certificate.fields), certificate), certificate)
                for replacement in (False, True, 0.0, 1.0, -1.0, -2.0):
                    supplied = list(certificate.fields)
                    index = certificate.fields.index(int(replacement))
                    supplied[index] = replacement
                    self.assertEqual(tuple(supplied), certificate.fields)
                    with self.subTest(container=container, replacement=replacement), self.assertRaises(ValueError):
                        resolve_field_certificate(recipe, container(supplied), certificate)
            for malformed in (certificate.fields[:-1], (*certificate.fields, 0), "field"):
                with self.assertRaises(ValueError):
                    resolve_field_certificate(recipe, malformed, certificate)

    def test_malformed_structured_documents_reject_without_python_coercions(self):
        expected = REFERENCE["standalone_stage"]
        documents = [None, [], {}, {**expected["document"], "extra": 0}]
        for value in (1.0, float("nan"), True, None, object()):
            document = deepcopy(expected["document"])
            document["trace"][0]["radius"] = value
            documents.append(document)
        document = deepcopy(expected["document"])
        document["trace"][0][1] = 1
        documents.append(document)
        document = deepcopy(expected["document"])
        document["final_context"]["branch_path"].append(document)
        documents.append(document)
        document = deepcopy(expected["document"])
        document["segments"] = [document["segments"][0]] * 4097
        documents.append(document)
        for document in documents:
            with self.assertRaises(ValueError):
                certify_stage(generated(), FIELDS, document, tuple(expected["union"]["signs"]), tuple(expected["union"]["field"]))

    def test_device_outputs_admitted_with_every_cpu_producer_disabled(self):
        recipe, stages = oracle_stages("two_epoch_mission")
        forbidden = ("interpret_cpu", "union_signs_cpu", "regenerate", "evaluate_field")
        certificate = None
        with ExitStack() as stack:
            for name in forbidden:
                stack.enter_context(patch(f"solvefinite.organogram.{name}", side_effect=AssertionError(f"CPU producer {name}")))
            stack.enter_context(patch.object(GeneratedFieldRecipe, "field_manifest", side_effect=AssertionError("generated reconstruction")))
            stack.enter_context(patch("solvefinite.psi.field_axes", side_effect=AssertionError("CPU Psi compiler")))
            for length, expected in enumerate(stages, 1):
                prefix = replace(recipe, stages=recipe.stages[:length])
                output = expected["result"]
                certificate = certify_stage(prefix, tuple(expected["prior_field"]), output["document"],
                                            tuple(output["union"]["signs"]), tuple(output["union"]["field"]),
                                            prior_certificate=certificate)
            self.assertEqual(select_target(recipe, certificate.fields, 6, 186, certificate=certificate), 14)
        self.assertEqual(certificate.stage_digests, tuple(stage["result"]["derivation_sha256"] for stage in stages))

    def test_certificate_is_immutable_and_cannot_be_directly_constructed(self):
        with self.assertRaises(ValueError):
            GeneratedFieldCertificate()
        certificate = regenerate(generated())
        with self.assertRaises(FrozenInstanceError):
            certificate.fields = ()
        document = certificate.last_derivation
        document["trace"][0]["radius"] = 99
        self.assertEqual(certificate.last_derivation["trace"][0]["radius"], 1)
        self.assertFalse(hasattr(certificate, "__dict__"))

    def test_corrupt_trajectory_tape_context_stack_and_outputs_reject(self):
        expected = REFERENCE["standalone_stage"]
        mutations = []
        for section, index, key, value in (("trace", 0, "radius", 2), ("trace", 10, "scale", 0),
                                          ("trace", 11, "pair", "91FE00B181FE004F"),
                                          ("trace", 11, "branch_path", []), ("segments", 0, "step", True),
                                          ("segments", 0, "pair", "81011145910111BB"),
                                          ("balls", 0, "center", 13), ("balls", 1, "radius", 1),
                                          ("tape", 0, "address", [0]), ("tape", 2, "args", [2])):
            document = deepcopy(expected["document"])
            document[section][index][key] = value
            mutations.append(document)
        for section in ("trace", "segments", "balls"):
            document = deepcopy(expected["document"])
            document[section].pop()
            mutations.append(document)
        document = deepcopy(expected["document"])
        document["context"]["tick"] = 6
        mutations.append(document)
        document = deepcopy(expected["document"])
        document["final_context"]["radius"] = True
        mutations.append(document)
        document = deepcopy(expected["document"])
        document["trace"][0]["address"] = tuple(document["trace"][0]["address"])
        mutations.append(document)
        for document in mutations:
            with self.subTest(document=document), self.assertRaises(ValueError):
                certify_stage(generated(), FIELDS, document, tuple(expected["union"]["signs"]), tuple(expected["union"]["field"]))
        for key in ("signs", "field"):
            values = deepcopy(expected["union"])
            values[key][0] = 1
            with self.assertRaises(ValueError):
                certify_stage(generated(), FIELDS, expected["document"], tuple(values["signs"]), tuple(values["field"]))

    def test_contiguous_prior_certificate_and_prefix_identity(self):
        recipe, stages = oracle_stages("two_epoch_mission")
        first = regenerate(replace(recipe, stages=recipe.stages[:1]))
        second = stages[1]["result"]
        for previous in (None, first.fields, regenerate(generated(OrganogramBinding(2)))):
            with self.assertRaises(ValueError):
                certify_stage(recipe, first.fields, second["document"], tuple(second["union"]["signs"]),
                              tuple(second["union"]["field"]), prior_certificate=previous)
        alternate = generated(contexts=(replace(CONTEXT, prefix_sha256="1" * 64),))
        a, b = regenerate(generated()), regenerate(alternate)
        self.assertEqual(a.fields, b.fields)
        self.assertNotEqual(a.derivation_sha256, b.derivation_sha256)
        with self.assertRaises(ValueError):
            select_target(alternate, a.fields, 17, 69, certificate=a)
        bad = replace(CONTEXT, start_pair=f"{pair(pack(187, 17, 0, 22)):016X}")
        with self.assertRaises(ValueError):
            regenerate(generated(contexts=(bad,)))


if __name__ == "__main__":
    unittest.main()
