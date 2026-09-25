"""Recipe regeneration, FIFO ownership, and pure scalar-field motion."""

from dataclasses import FrozenInstanceError, replace
import json
import unittest
from unittest.mock import patch

from solvefinite.field import evaluate_field
from solvefinite.f8 import F8Index
from solvefinite.field_world import FieldNode, FieldWorld, KleinFieldRecipe
from solvefinite.rp32 import Opcode, pack, pair, unpack, unpair


DEFAULT_FIELD = (-2, -1, 0, 0, -1, -1, 0, 1, 1, 0,
                 0, 1, 2, 2, 1, -1, 0, 1, 1, 0)


def cache_state(world):
    return (world.active_paths, world.evicted_paths,
            world.hit_count, world.regeneration_count)


class KleinRecipeTests(unittest.TestCase):
    def test_exact_json_round_trip_and_immutable_recipe(self):
        recipe = KleinFieldRecipe(turns=(0, 128, 255), baseline_id="test-baseline")
        value = json.loads(json.dumps(recipe.to_dict()))
        self.assertEqual(set(value), {"format", "width", "height", "center", "radius",
                                     "turns", "baseline_id"})
        self.assertEqual(value["format"], "klein-ball-world-v1")
        restored = KleinFieldRecipe.from_dict(value)
        self.assertEqual(restored, recipe)
        value["turns"][0] = 7
        self.assertEqual(restored.turns, (0, 128, 255))
        self.assertEqual(KleinFieldRecipe(baseline_id="x" * 129).baseline_id, "x" * 129)
        with self.assertRaises(FrozenInstanceError):
            recipe.radius = 1

    def test_strict_recipe_values_and_json_shapes(self):
        invalid = (
            {"width": True}, {"height": 3.0}, {"width": 2}, {"width": 17, "height": 16},
            {"center": True}, {"center": -1}, {"center": 20}, {"center": "0"},
            {"radius": True}, {"radius": 0}, {"radius": 5}, {"radius": 2.0},
            {"turns": [11, 53, 137]}, {"turns": (11, 53)}, {"turns": (0, 1, True)},
            {"turns": (-1, 0, 0)}, {"turns": (0, 0, 256)},
            {"baseline_id": ""}, {"baseline_id": "  "}, {"baseline_id": True},
            {"version": "future"}, {"version": True},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                KleinFieldRecipe(**change)
        good = KleinFieldRecipe().to_dict()
        malformed = [None, [], {}, dict(good, extra=0), dict(good, format="future"),
                     dict(good, turns=(11, 53, 137)), dict(good, turns=[True, 1, 2])]
        malformed.extend({key: value for key, value in good.items() if key != missing}
                         for missing in good)
        for value in malformed:
            with self.subTest(value=value), self.assertRaises(ValueError):
                KleinFieldRecipe.from_dict(value)

    def test_canonical_names_reject_chart_aliases(self):
        recipe = KleinFieldRecipe()
        for index, name in enumerate(recipe.domain().nodes):
            self.assertEqual(recipe.index(name), index)
        for name in (None, True, 0, [], "", "0", "k:0", "k:0:0:0", "k:4:0",
                     "k:0:5", "k:-1:0", "k:00:0", "k:0:01", "k:+0:0",
                     "k: 0:0", "k:0:0 ", "k:٠:٠", "K:0:0", "k:" + "0" * 129 + ":0"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                recipe.index(name)

    def test_generated_manifest_and_graph_come_from_the_same_quotient(self):
        recipe = KleinFieldRecipe(width=5, height=7, center=11, radius=3, turns=(3, 7, 13))
        domain, manifest, graph = recipe.domain(), recipe.field_manifest(), recipe.graph()
        self.assertEqual(manifest.profile, "relational-sdf-v2")
        self.assertEqual(manifest.topology, (5, 7))
        self.assertEqual((manifest.nodes, manifest.edges, manifest.seams),
                         (domain.nodes, domain.edges, domain.seams))
        self.assertEqual(manifest.signs, domain.ball_signs(11, 3))
        self.assertEqual(manifest.turns, ((3, 7, 13),) * 35)
        self.assertEqual(graph, tuple(sorted(graph)))
        observed = set()
        for source, neighbors in graph:
            self.assertIs(type(neighbors), tuple)
            self.assertEqual(neighbors, tuple(sorted(neighbors)))
            self.assertEqual(len(neighbors), 4)
            for target in neighbors:
                self.assertIn(source, dict(graph)[target])
                observed.add(tuple(sorted((recipe.index(source), recipe.index(target)))))
        self.assertEqual(observed, {edge[:2] for edge in domain.edges})


class FieldWorldCacheTests(unittest.TestCase):
    def test_derive_exact_data_pairs_without_cache_mutation(self):
        world = FieldWorld(KleinFieldRecipe(), 2)
        for index, signed in enumerate(DEFAULT_FIELD):
            path = f"k:{index // 5}:{index % 5}"
            node = world.derive(path)
            self.assertEqual(node, FieldNode(path, pair(pack(0, index, signed, Opcode.DATA))))
            self.assertEqual(unpack(unpair(node.pair)[0]), (0, index, signed, 0))
            self.assertEqual(unpack(unpair(node.pair)[1]), (0, index, signed, 16))
        self.assertEqual(cache_state(world), ((), (), 0, 0))
        with self.assertRaises(FrozenInstanceError):
            node.pair = 0
        with self.assertRaises(AttributeError):
            world.config = KleinFieldRecipe()

    def test_fifo_misses_recompute_fields_and_regenerate_after_eviction(self):
        world = FieldWorld(KleinFieldRecipe(), 2)
        with patch("solvefinite.field_world.evaluate_field", wraps=evaluate_field) as evaluated:
            original = world.get("k:0:0")
            world.get("k:0:1")
            self.assertEqual(evaluated.call_count, 2)
            self.assertIs(world.get("k:0:0"), original)
            self.assertEqual(evaluated.call_count, 2)
            self.assertEqual(world.active_paths, ("k:0:0", "k:0:1"))
            world.get("k:0:2")
            self.assertEqual(world.evicted_paths, ("k:0:0",))
            restored = world.get("k:0:0")
            self.assertEqual(evaluated.call_count, 4)
            self.assertEqual(restored, original)
            self.assertIsNot(restored, original)
            self.assertEqual(cache_state(world),
                             (("k:0:2", "k:0:0"), ("k:0:0", "k:0:1"), 1, 1))
            # Pure derivation also reconstructs, even for an actively cached node.
            self.assertEqual(world.derive("k:0:0"), original)
            self.assertEqual(evaluated.call_count, 5)
        fresh_recipe = KleinFieldRecipe.from_dict(json.loads(json.dumps(world.config.to_dict())))
        self.assertEqual(FieldWorld(fresh_recipe, 1).derive("k:0:0"), original)

    def test_resize_and_capacity_do_not_change_results(self):
        recipe = KleinFieldRecipe()
        paths = ("k:0:0", "k:1:0", "k:3:4", "k:0:0", "k:2:2", "k:3:4")
        reference = [FieldWorld(recipe, 1).derive(path) for path in paths]
        for capacity in (1, 2, 20):
            world = FieldWorld(recipe, capacity)
            actual = []
            for index, path in enumerate(paths):
                if index == 3:
                    world.resize(1)
                actual.append(world.get(path))
                self.assertLessEqual(len(world.active_paths), world.capacity)
            self.assertEqual(actual, reference)
        world = FieldWorld(recipe, 3)
        for path in paths[:3]:
            world.get(path)
        world.resize(1)
        self.assertEqual(world.active_paths, (paths[2],))
        self.assertEqual(world.evicted_paths, paths[:2])

    def test_invalid_construction_paths_and_resize_leave_cache_unchanged(self):
        recipe = KleinFieldRecipe()
        for invalid in (None, {}, recipe.to_dict()):
            with self.assertRaises(ValueError):
                FieldWorld(invalid, 2)
        for invalid in (0, -1, True, 1.0, "2", None):
            with self.assertRaises(ValueError):
                FieldWorld(recipe, invalid)
            world = FieldWorld(recipe, 2)
            world.get("k:0:0")
            before = cache_state(world)
            with self.assertRaises(ValueError):
                world.resize(invalid)
            self.assertEqual(cache_state(world), before)
            self.assertEqual(world.capacity, 2)
        for method in (world.derive, world.get):
            with self.assertRaises(ValueError):
                method("k:00:0")
            self.assertEqual(cache_state(world), before)
        with self.assertRaises(ValueError):
            FieldWorld(recipe, 2, object())


class FieldWorldForecastTests(unittest.TestCase):
    def setUp(self):
        self.world = FieldWorld(KleinFieldRecipe(), 2)
        self.initial = pair(pack(250, 0, -2, Opcode.STEP))

    def test_independent_seam_and_reverse_vectors_preserve_scalar_B(self):
        # k:3:1 has phi=0. 250+53=47, then the seam reflects to 209.
        # k:0:4 has phi=-1. In eta1, 209-11=198, reflected back to 58.
        seed = pair(pack(250, 16, 0, Opcode.STEP))
        forecast, costs = self.world.forecast(seed, ("k:0:4", "k:3:1"), (3, 2))
        self.assertEqual(tuple(unpack(unpair(value)[0]) for value in forecast),
                         ((209, 4, -1, 17), (58, 16, 0, 1)))
        self.assertEqual(costs, (5, 3))
        for source, destination, source_phi, target_phi, phase in (
                (15, "k:0:0", -1, -2, 251),
                (16, "k:0:4", 0, -1, 209),
                (17, "k:0:3", 1, 0, 125)):
            outputs, _ = self.world.forecast(pair(pack(250, source, source_phi, 1)),
                                             (destination,), (0,))
            self.assertEqual(unpack(unpair(outputs[0])[0]),
                             (phase, self.world.config.index(destination), target_phi, 17))

    def test_complete_mirror_transport_and_hazard_independent_scalar_state(self):
        route = ("k:3:0", "k:0:0", "k:0:1", "k:0:2")
        original, costs = self.world.forecast(self.initial, route, (0, 1, 2, 3))
        reflected_seed = pair(unpair(self.initial)[1])
        reflected, reflected_costs = self.world.forecast(reflected_seed, route, (0, 1, 2, 3))
        self.assertEqual(costs, reflected_costs)
        for before, after in zip(original, reflected):
            self.assertEqual(unpair(after), unpair(before)[::-1])
        costly, expensive = self.world.forecast(self.initial, route, (127,) * 4)
        self.assertEqual(costly, original)
        self.assertEqual(expensive, (129, 130, 129, 128))

    def test_forecasting_and_cost_queries_leave_cache_and_input_unchanged(self):
        self.world.get("k:3:4")
        self.world.get("k:2:2")
        before = cache_state(self.world)
        self.assertEqual(self.world.entry_cost("k:0:0", 127), 130)
        self.world.forecast(self.initial, ("k:0:1", "k:0:2"), (1, 2))
        self.assertEqual(self.world.forecast(self.initial, (), ()), ((), ()))
        self.assertEqual(cache_state(self.world), before)
        self.assertEqual(self.initial, pair(pack(250, 0, -2, Opcode.STEP)))

    def test_radius_ablation_changes_distance_cost_and_field_selected_phase(self):
        altered = FieldWorld(KleinFieldRecipe(radius=1), 1)
        route = ("k:0:2",)
        original, original_cost = self.world.forecast(pair(pack(250, 1, -1, 1)), route, (0,))
        changed, changed_cost = altered.forecast(pair(pack(250, 1, 0, 1)), route, (0,))
        self.assertEqual(unpack(unpair(original[0])[0]), (5, 2, 0, 1))
        self.assertEqual(unpack(unpair(changed[0])[0]), (47, 2, 1, 1))
        self.assertEqual((original_cost, changed_cost), ((1,), (2,)))

    def test_maximum_bounded_route_keeps_cost_outside_packed_field(self):
        route = tuple("k:0:1" if index % 2 == 0 else "k:0:0" for index in range(255))
        outputs, costs = self.world.forecast(self.initial, route, (127,) * 255)
        self.assertEqual(len(outputs), 255)
        self.assertEqual(sum(costs), 128 * 129 + 127 * 130)
        self.assertEqual(unpack(unpair(outputs[-1])[0])[2], -1)
        self.assertEqual(cache_state(self.world), ((), (), 0, 0))

    def test_bad_forecasts_are_rejected_without_mutation(self):
        invalid = (
            (self.initial, ["k:0:1"], (0,)),
            (self.initial, ("k:0:1",), [0]),
            (self.initial, ("k:0:1",), ()),
            (self.initial, ("k:0:1",), (True,)),
            (self.initial, ("k:0:1",), (-1,)),
            (self.initial, ("k:0:1",), (128,)),
            (self.initial, ("k:0:0",), (0,)),
            (self.initial, ("k:2:2",), (0,)),
            (self.initial, ("k:0:1", "k:2:2"), (0, 0)),
            (self.initial, ("k:00:1",), (0,)),
            (self.initial, ("k:0:1",) * 256, (0,) * 256),
            (self.initial ^ 1, (), ()),
            (pair(pack(250, 0, 100, 1)), (), ()),
            (pair(pack(250, 20, 0, 1)), (), ()),
            (pair(pack(250, 0, -2, 0)), (), ()),
            (pair(pack(250, 0, -2, 65)), (), ()),
            (True, (), ()),
        )
        before = cache_state(self.world)
        for args in invalid:
            with self.subTest(arguments=args), self.assertRaises(ValueError):
                self.world.forecast(*args)
            self.assertEqual(cache_state(self.world), before)
        for hazard in (True, -1, 128, 1.0, "0", None):
            with self.assertRaises(ValueError):
                self.world.entry_cost("k:0:0", hazard)


class FieldWorldExecutorProtocolTests(unittest.TestCase):
    def test_executor_derivation_and_forecast_never_use_cpu_field_oracle(self):
        # A protocol double verifies delegation. Actual-device tests exercise
        # the real executor separately, without substituting this fixture.
        class Executor:
            recipe = KleinFieldRecipe()
            fields = DEFAULT_FIELD

            def __init__(self):
                self.index = F8Index.build(self.recipe, fields=self.fields)
                self.derivations = []
                self.forecasts = []

            def derive_node(self, index):
                self.derivations.append(index)
                return pair(pack(0, index, self.fields[index], 0))

            def forecast(self, agent_pair, route, hazards):
                self.forecasts.append((agent_pair, route, hazards))
                return (pair(pack(5, 1, -1, 1)),), (2,)

        executor = Executor()
        with patch("solvefinite.field_world.evaluate_field", side_effect=AssertionError("CPU fallback")):
            world = FieldWorld(executor.recipe, 1, executor)
            node = world.get("k:0:0")
            world.get("k:0:1")
            self.assertEqual(world.get("k:0:0"), node)
            self.assertEqual(executor.derivations, [0, 1, 0])
            initial = pair(pack(250, 0, -2, 1))
            before = cache_state(world)
            self.assertEqual(world.forecast(initial, ("k:0:1",), (0,)),
                             ((pair(pack(5, 1, -1, 1)),), (2,)))
            self.assertEqual(executor.forecasts, [(initial, ("k:0:1",), (0,))])
            self.assertEqual(cache_state(world), before)
        with self.assertRaises(ValueError):
            FieldWorld(replace(executor.recipe, radius=1), 1, executor)


if __name__ == "__main__":
    unittest.main()
