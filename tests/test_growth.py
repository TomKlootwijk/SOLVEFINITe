"""GD arithmetic against retained, preimplementation independent references."""

from collections import deque
from dataclasses import FrozenInstanceError, replace
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.field import evaluate_field
from solvefinite.field_world import KleinFieldRecipe
from solvefinite.growth import (
    PROFILE, EpochFieldNode, GrowthBinding, grow_recipe, map_node,
    recipe_at_epoch, select_target, validate_growth_budget,
)
from solvefinite.rp32 import Opcode, pack, pair


REFERENCE_DIR = Path(__file__).resolve().parents[1] / "docs/evidence/growth-v1"
REFERENCE = json.loads((REFERENCE_DIR / "formal-reference.json").read_text(encoding="utf-8"))
SPEC = importlib.util.spec_from_file_location("independent_growth_reference",
                                           REFERENCE_DIR / "reference-builder.py")
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


def from_reference(value):
    return KleinFieldRecipe(**{**value, "turns": tuple(value["turns"])})


def graph_distances(domain, start):
    neighbors = [[] for _ in domain.nodes]
    for source, target, _ in domain.edges:
        neighbors[source].append(target)
        neighbors[target].append(source)
    values = [-1] * len(neighbors)
    values[start] = 0
    pending = deque((start,))
    while pending:
        source = pending.popleft()
        for target in neighbors[source]:
            if values[target] == -1:
                values[target] = values[source] + 1
                pending.append(target)
    return values


class GrowthBindingTests(unittest.TestCase):
    def test_exact_schema_roundtrip_and_immutable_binding(self):
        binding = GrowthBinding()
        self.assertEqual(binding.to_dict(), {"format": PROFILE, "max_epochs": 1, "cost": 1})
        source = binding.to_dict()
        self.assertEqual(GrowthBinding.from_dict(json.loads(json.dumps(source))), binding)
        source["cost"] = 127
        self.assertEqual(binding.cost, 1)
        with self.assertRaises(FrozenInstanceError):
            binding.max_epochs = 2
        self.assertFalse(hasattr(binding, "__dict__"))

    def test_strict_types_formats_keys_and_declared_ranges(self):
        defaults = GrowthBinding().to_dict()
        invalid = [None, [], {}, {**defaults, "extra": 0}]
        for key in defaults:
            invalid.append({name: value for name, value in defaults.items() if name != key})
        for value in (None, True, 1, "other"):
            invalid.append({**defaults, "format": value})
        for value in (-1, 3, True, False, 1.0, "1", None):
            invalid.append({**defaults, "max_epochs": value})
            with self.subTest(epoch=value), self.assertRaises(ValueError):
                GrowthBinding(max_epochs=value)
        for value in (0, -1, 128, True, False, 1.0, "1", None):
            invalid.append({**defaults, "cost": value})
            with self.subTest(cost=value), self.assertRaises(ValueError):
                GrowthBinding(cost=value)
        for value in invalid:
            with self.subTest(json=value), self.assertRaises(ValueError):
                GrowthBinding.from_dict(value)
        self.assertEqual(GrowthBinding(0, 127).max_epochs, 0)
        self.assertEqual(GrowthBinding(2, 127).cost, 127)

    def test_full_depth_budget_before_any_candidate_allocation(self):
        small = KleinFieldRecipe(3, 3, 0, 1)
        default = KleinFieldRecipe()
        large = KleinFieldRecipe(16, 16, 0, 1)
        with patch.object(KleinFieldRecipe, "domain", side_effect=AssertionError("allocated geometry")):
            for recipe, epochs in ((small, 2), (default, 1), (large, 0)):
                GrowthBinding(epochs).validate_recipe(recipe)
                validate_growth_budget(recipe, GrowthBinding(epochs))
            for recipe, epochs in ((default, 2), (large, 1), (large, 2)):
                with self.assertRaises(ValueError):
                    validate_growth_budget(recipe, GrowthBinding(epochs))
            with self.assertRaises(ValueError):
                grow_recipe(large)
            with self.assertRaises(ValueError):
                map_node(large, 0)
            with self.assertRaises(ValueError):
                recipe_at_epoch(default, GrowthBinding(2), 0)
        for recipe, binding in ((None, GrowthBinding()), (default, None),
                                (default.to_dict(), GrowthBinding()), (default, {})):
            with self.assertRaises(ValueError):
                validate_growth_budget(recipe, binding)


class GrowthGeometryTests(unittest.TestCase):
    def test_every_refinable_quotient_embedding_edges_distances_and_orientation(self):
        domains = edges = distances = aliases = 0
        direction_names = ("u+", "u-", "v+", "v-")
        for width in range(3, 22):
            for height in range(3, 22):
                if 4 * width * height > 256:
                    continue
                domains += 1
                recipe = KleinFieldRecipe(width, height, 0, 1)
                new_recipe = grow_recipe(recipe)
                old, new = recipe.domain(), new_recipe.domain()
                old.audit()
                new.audit()
                independent = ORACLE.Quotient(width, height)
                for source in range(width * height):
                    mapped = map_node(recipe, source)
                    self.assertEqual(mapped, independent.doubled_node(source))
                    for name, vector in zip(direction_names, ORACLE.DIRECTIONS):
                        target, seam = old.step(source, name)
                        self.assertEqual((target, seam), independent.step(source, vector))
                        midpoint, first = new.step(mapped, name)
                        destination, second = new.step(midpoint, name)
                        self.assertEqual(destination, map_node(recipe, target))
                        self.assertEqual(first ^ second, seam)
                        edges += 1
                    coarse = independent.distance((source,))
                    fine = graph_distances(new, mapped)
                    for target in range(width * height):
                        self.assertEqual(fine[map_node(recipe, target)], 2 * coarse[target])
                        distances += 1
                    u, v = divmod(source, height)
                    for horizontal in range(-2, 3):
                        for vertical in range(-2, 3):
                            for eta in (0, 1):
                                au = u + horizontal * width
                                av = (-v if horizontal & 1 else v) + vertical * height
                                ae = eta ^ (horizontal & 1)
                                self.assertEqual(old.canonical(au, av, ae), (u, v, eta))
                                self.assertEqual(new.canonical(2 * au, 2 * av, ae), (2 * u, 2 * v, eta))
                                aliases += 1
        certificate = REFERENCE["refinement_certificates"]
        self.assertEqual(domains, certificate["all_refinable_quotients_checked"])
        self.assertEqual(edges, certificate["directed_edge_two_step_and_seam_checks"])
        self.assertEqual(distances, certificate["old_vertex_pair_distance_checks"])
        self.assertEqual(aliases, certificate["oriented_equivalent_representative_checks"])

    def test_nonzero_center_boundary_and_recipe_dependencies_preserved(self):
        recipe = KleinFieldRecipe(3, 5, 1, 3, (0, 128, 255), "retained-root")
        grown = grow_recipe(recipe)
        self.assertEqual((grown.width, grown.height, grown.center, grown.radius), (6, 10, 2, 6))
        self.assertEqual((grown.turns, grown.baseline_id, grown.version),
                         (recipe.turns, recipe.baseline_id, recipe.version))
        old_signs = recipe.domain().ball_signs(recipe.center, recipe.radius)
        new_signs = grown.domain().ball_signs(grown.center, grown.radius)
        self.assertEqual(tuple(new_signs[map_node(recipe, i)] for i in range(15)), old_signs)

    def test_literal_field_counterexample_requires_recomputation(self):
        reference = REFERENCE["field_recomputation_counterexample"]
        old = from_reference(reference["old_recipe"])
        new = grow_recipe(old)
        coarse = evaluate_field(old.field_manifest())
        fine = evaluate_field(new.field_manifest())
        self.assertEqual(coarse, tuple(reference["old_fields"]))
        self.assertEqual(fine, tuple(reference["new_fields"]))
        self.assertEqual(coarse[0], -3)
        self.assertEqual(fine[map_node(old, 0)], -4)
        self.assertNotEqual(fine[map_node(old, 0)], 2 * coarse[0])

    def test_epoch_derivation_and_strict_node_epoch_validation(self):
        initial = KleinFieldRecipe(3, 3, 0, 1)
        binding = GrowthBinding(2)
        self.assertIs(recipe_at_epoch(initial, binding, 0), initial)
        final = recipe_at_epoch(initial, binding, 2)
        self.assertEqual((final.width, final.height, final.radius), (12, 12, 4))
        for value in (-1, 3, True, False, 1.0, "1", None):
            with self.subTest(epoch=value), self.assertRaises(ValueError):
                recipe_at_epoch(initial, binding, value)
        for value in (-1, 9, True, False, 0.0, "0", None):
            with self.subTest(node=value), self.assertRaises(ValueError):
                map_node(initial, value)
        for value in (None, initial.to_dict()):
            with self.assertRaises(ValueError):
                grow_recipe(value)
            with self.assertRaises(ValueError):
                map_node(value, 0)


class GrowthTargetTests(unittest.TestCase):
    def test_each_literal_production_field_mapping_and_derived_target(self):
        for name in ("default_mission", "mirrored_default_mission", "two_epoch_mission"):
            mission = REFERENCE[name]
            recipe = from_reference(mission["initial_recipe"])
            for event in mission["events"]:
                if event["kind"] != "GROW":
                    continue
                mapped = map_node(recipe, event["before"]["node"])
                recipe = grow_recipe(recipe)
                fields = tuple(mission["worlds"][event["geometry_epoch"]]["field"])
                self.assertEqual(recipe, from_reference(event["next_recipe"]))
                self.assertEqual(evaluate_field(recipe.field_manifest()), fields)
                self.assertEqual(mapped, event["state"]["node"])
                self.assertEqual(fields[mapped], event["state"]["field"])
                self.assertEqual(select_target(recipe, fields, mapped, event["state"]["intrinsic_phase"]),
                                 event["selection"]["target"])

    def test_every_phase_selects_numeric_tie_and_full_mirror_invariant(self):
        reference = REFERENCE["phase_selected_target_ties"]
        recipe = from_reference(reference["recipe"])
        fields = tuple(ORACLE.World(recipe.width, recipe.height, recipe.center, recipe.radius).phi)
        candidates = reference["selections"][0]["tied_candidates"]
        self.assertGreater(len(candidates), 1)
        observed = set()
        for r in range(256):
            for eta in (0, 1):
                phase = (-r if eta else r) % 256
                actual = select_target(recipe, fields, reference["mapped_node"], phase)
                self.assertEqual(actual, candidates[phase % len(candidates)])
                mirrored_phase = (-((-r) % 256) if eta ^ 1 else (-r) % 256) % 256
                self.assertEqual(phase, mirrored_phase)
                observed.add(actual)
        self.assertEqual(observed, set(candidates))

    def test_supplied_certified_gpu_field_needs_no_cpu_field_compiler(self):
        mission = REFERENCE["default_mission"]
        recipe = from_reference(mission["worlds"][1]["recipe"])
        fields = tuple(mission["worlds"][1]["field"])
        with (patch("solvefinite.field.evaluate_field", side_effect=AssertionError("CPU field")),
              patch("solvefinite.field_world.evaluate_field", side_effect=AssertionError("CPU field")),
              patch("solvefinite.field.build_operators", side_effect=AssertionError("CPU operators"))):
            self.assertEqual(select_target(recipe, fields, 64, 69), 39)

    def test_no_generated_zero_boundary_uses_nearest_nonzero_layer(self):
        initial = KleinFieldRecipe(4, 4, 0, 4)
        recipe = grow_recipe(initial)
        independent = ORACLE.World(8, 8, 0, 8)
        self.assertTrue(all(not (u % 2 or v % 2)
                            for node in independent.boundary
                            for u, v in (divmod(node, 8),)))
        expected = ORACLE.select_target(independent, 0, 17)
        self.assertEqual(expected["minimum_absolute_field"], 1)
        selected = select_target(recipe, independent.phi, 0, 17)
        self.assertEqual(selected, expected["target"])
        self.assertEqual(abs(independent.phi[selected]), 1)

    def test_numeric_tie_order_differs_from_lexical_node_names(self):
        recipe = grow_recipe(KleinFieldRecipe(6, 3, 0, 1))
        independent = ORACLE.World(12, 6, 0, 2)
        candidates = (7, 11, 67, 71)
        self.assertNotEqual(candidates,
                            tuple(sorted(candidates, key=independent.names.__getitem__)))
        for phase in range(8):
            self.assertEqual(select_target(recipe, independent.phi, 0, phase),
                             candidates[phase % 4])

    def test_corrupt_fields_cannot_drive_target_selection(self):
        mission = REFERENCE["default_mission"]
        recipe = from_reference(mission["worlds"][1]["recipe"])
        fields = tuple(mission["worlds"][1]["field"])
        for index in range(len(fields)):
            corrupt = fields[:index] + (fields[index] + 1,) + fields[index + 1:]
            with self.subTest(index=index), self.assertRaises(ValueError):
                select_target(recipe, corrupt, 64, 69)
        for value in (None, list(fields), iter(fields), fields[:-1], fields + (0,),
                      (True,) + fields[1:], (0.0,) + fields[1:]):
            with self.subTest(fields_type=type(value)), self.assertRaises(ValueError):
                select_target(recipe, value, 64, 69)
        for value in (-1, 80, 1, True, False, 0.0, "0", None):
            with self.subTest(mapped=value), self.assertRaises(ValueError):
                select_target(recipe, fields, value, 69)
        for value in (-1, 256, True, False, 0.0, "0", None):
            with self.subTest(phase=value), self.assertRaises(ValueError):
                select_target(recipe, fields, 64, value)
        with self.assertRaises(ValueError):
            select_target(KleinFieldRecipe(), tuple(REFERENCE["default_mission"]["worlds"][0]["field"]), 0, 0)


class EpochFieldNodeTests(unittest.TestCase):
    def setUp(self):
        self.initial = KleinFieldRecipe()
        self.binding = GrowthBinding()
        self.empty_prefix = hashlib.sha256(b"[]").hexdigest()
        self.original_prefix = hashlib.sha256(b'[{"seq":5}]').hexdigest()
        self.old = EpochFieldNode(0, 0, self.initial, self.binding, "k:0:0",
                                  pair(pack(0, 0, -2, Opcode.DATA)), self.empty_prefix)
        self.new = EpochFieldNode(1, 5, self.initial, self.binding, "k:6:4",
                                  pair(pack(0, 64, 2, Opcode.DATA)), self.original_prefix)

    def test_original_context_is_immutable_and_serializes_without_field_arena(self):
        self.assertEqual(self.new.to_dict(), {
            "geometry_epoch": 1, "origin_sequence": 5, "initial_recipe": self.initial.to_dict(),
            "growth": self.binding.to_dict(), "path": "k:6:4", "pair": f"{self.new.pair:016X}",
            "prefix_sha256": self.original_prefix})
        self.assertEqual(set(EpochFieldNode.__slots__), {"geometry_epoch", "origin_sequence",
                         "initial_recipe", "growth", "path", "pair", "prefix_sha256"})
        self.assertFalse(hasattr(self.new, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            self.new.origin_sequence = 6
        same_name_new_epoch = EpochFieldNode(1, 5, self.initial, self.binding, "k:0:0",
                                            pair(pack(0, 0, -4, Opcode.DATA)), self.original_prefix)
        self.assertNotEqual(self.old, same_name_new_epoch)
        self.assertNotEqual(self.old.to_dict(), same_name_new_epoch.to_dict())
        other_history = replace(self.new, prefix_sha256=hashlib.sha256(b'[{"seq":5,"different":true}]').hexdigest())
        self.assertNotEqual(other_history, self.new)
        self.assertNotEqual(other_history.to_dict(), self.new.to_dict())

    def test_strict_epoch_origin_pair_and_canonical_sample_identity(self):
        invalid = [dict(geometry_epoch=-1), dict(geometry_epoch=2), dict(geometry_epoch=True),
                   dict(origin_sequence=0), dict(origin_sequence=True), dict(origin_sequence=1.0),
                   dict(origin_sequence=1_000_001), dict(initial_recipe=None), dict(growth=None),
                   dict(path="k:06:4"), dict(path="k:6:5"), dict(path="k:8:0"),
                   dict(pair=True), dict(pair=self.new.pair ^ 1),
                   dict(pair=pair(pack(0, 64, 2, Opcode.STEP))),
                   dict(pair=pair(pack(1, 64, 2, Opcode.DATA))),
                   dict(pair=pair(pack(0, 64, 2, int(Opcode.DATA) | 16)))]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.new, **changes)
        with self.assertRaises(ValueError):
            replace(self.old, origin_sequence=1)
        for value in (None, 0, True, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, " " * 64):
            with self.subTest(prefix=value), self.assertRaises(ValueError):
                replace(self.new, prefix_sha256=value)


if __name__ == "__main__":
    unittest.main()
