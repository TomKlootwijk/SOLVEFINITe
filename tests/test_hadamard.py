"""Independent HP arithmetic, quotient covariance and admission checks."""

from dataclasses import FrozenInstanceError
import json
from math import gcd
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.field_world import KleinFieldRecipe
from solvefinite.hadamard import HadamardBinding, RoutingModel, PROFILE
from tests.test_psi import covering_gradient, covering_neighbors, distances, independent_field


def reference_tables(recipe, binding, fields):
    """Build expectations from the covering chart, without runtime helpers."""
    penalties, increments, neighbors = [], [], []
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for node in range(recipe.width * recipe.height):
        u, v = divmod(node, recipe.height)
        gu, gv = covering_gradient(recipe.width, recipe.height, fields, u, v)
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        geometric = sorted(zip(covering_neighbors(recipe.width, recipe.height, node), directions))
        neighbors.append(tuple(target for target, _ in geometric))
        for a, b in binding.gains:
            q = a * (1 + pu * pu) * gu, b * (1 + pv * pv) * gv
            largest = max(map(abs, q))
            penalties.extend(largest - sum(x * y for x, y in zip(q, edge))
                             for _, edge in geometric)
        increments.append(recipe.turns[(fields[node] > 0) - (fields[node] < 0) + 1])
    return tuple(penalties), tuple(increments), tuple(neighbors)


class HadamardBindingTests(unittest.TestCase):
    def test_default_exact_schema_and_immutable_json_roundtrip(self):
        binding = HadamardBinding()
        self.assertEqual(binding.to_dict(), {"format": PROFILE,
                         "gains": [[1, 1], [-1, 1], [-1, -1], [1, -1]]})
        encoded = json.loads(json.dumps(binding.to_dict()))
        restored = HadamardBinding.from_dict(encoded)
        self.assertEqual(restored, binding)
        encoded['gains'][0][0] = 4
        self.assertEqual(restored.gains[0], (1, 1))
        with self.assertRaises(FrozenInstanceError):
            binding.gains = ((0, 0),) * 4
        with self.assertRaises(TypeError):
            binding.gains[0][0] = 0

    def test_strict_schema_shape_and_signed_gain_admission(self):
        default = HadamardBinding().to_dict()
        invalid = [None, [], {}, {**default, 'extra': 1},
                   {'format': PROFILE}, {'gains': default['gains']},
                   {**default, 'format': 'other'}, {**default, 'format': True},
                   {**default, 'gains': tuple(default['gains'])},
                   {**default, 'gains': [(1, 1)] * 4},
                   {**default, 'gains': []}, {**default, 'gains': [[1, 1]] * 3},
                   {**default, 'gains': [[1, 1]] * 5},
                   {**default, 'gains': [[1]] * 4},
                   {**default, 'gains': [[1, 1, 1]] * 4}]
        for gain in (-5, 5, True, False, 1.0, '1', None):
            invalid.append({**default, 'gains': [[gain, 1], [1, 1], [1, 1], [1, 1]]})
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                HadamardBinding.from_dict(value)
        for value in ([list(bank) for bank in HadamardBinding().gains],
                      ([1, 1],) * 4, ((1, 1),) * 3):
            with self.assertRaises(ValueError):
                HadamardBinding(value)
        self.assertEqual(HadamardBinding(((-4, 4),) * 4).gains, ((-4, 4),) * 4)


class HadamardModelTests(unittest.TestCase):
    def setUp(self):
        self.recipe = KleinFieldRecipe()
        self.binding = HadamardBinding()
        self.fields = independent_field(4, 5, 0, 2)
        self.penalties, self.increments, self.neighbors = reference_tables(
            self.recipe, self.binding, self.fields)

    def test_all_rows_banks_against_independent_cover_and_bfs(self):
        sizes = ((3, 3), (3, 4), (4, 3), (4, 5), (5, 7),
                 (8, 8), (3, 85), (85, 3), (16, 16))
        bindings = (self.binding, HadamardBinding(((0, 0),) * 4),
                    HadamardBinding(((-4, 4), (4, -4), (-4, -4), (4, 4))))
        for width, height in sizes:
            for center in (0, width * height - 1):
                radius = max(distances(width, height, (center,)))
                for radius in sorted({1, radius}):
                    recipe = KleinFieldRecipe(width, height, center, radius,
                                              turns=(0, 128, 255))
                    fields = independent_field(width, height, center, radius)
                    for binding in bindings:
                        with self.subTest(size=(width, height), center=center,
                                          radius=radius, gains=binding.gains):
                            model = RoutingModel.build(recipe, binding)
                            expected = reference_tables(recipe, binding, fields)
                            self.assertEqual((model.penalties, model.increments,
                                              model.neighbors), expected)
                            self.assertTrue(all(0 <= p <= 80 for p in model.penalties))
                            self.assertTrue(all(1 <= 1 + abs(fields[j]) + 127 +
                                                model.penalty(i, t, j) <= 335
                                                for i in range(width * height)
                                                for t in (0, 64, 128, 192)
                                                for j in model.neighbors[i]))

    def test_golden_action_costs_and_phase_banks(self):
        path = Path(__file__).resolve().parents[1] / 'docs/evidence/hadamard-v1/formal-reference.json'
        golden = json.loads(path.read_text(encoding='utf-8'))
        model = RoutingModel.build(self.recipe, self.binding)
        node, t = 0, 250
        for event in golden['mission']['events']:
            if event['kind'] != 'MOVE':
                continue
            destination = event['route'][0]
            self.assertEqual(model.penalty(node, t, destination), event['action']['penalty'])
            self.assertEqual(1 + abs(self.fields[destination]) +
                             model.penalty(node, t, destination), event['action']['cost'])
            t = model.next_phase(node, t)
            self.assertEqual(t, (-event['phase'] if event['orientation'] else event['phase']) % 256)
            node = destination
        for source, adjacent in enumerate(model.neighbors):
            for bank in range(4):
                for destination in adjacent:
                    self.assertEqual(model.penalty(source, bank * 64, destination),
                                     model.penalty(source, bank * 64 + 63, destination))

    def test_certification_needs_no_cpu_compiler_field_evaluator_or_psi_helpers(self):
        with (patch('solvefinite.hadamard._compile_model', side_effect=AssertionError('CPU compiler')),
              patch('solvefinite.hadamard.evaluate_field', side_effect=AssertionError('CPU field')),
              patch('solvefinite.psi.field_axes', side_effect=AssertionError('CPU Psi')),
              patch('solvefinite.psi.axis_from_gradient', side_effect=AssertionError('CPU axis'))):
            model = RoutingModel.certified(self.recipe, self.binding,
                                           list(self.penalties), list(self.increments),
                                           list(self.fields))
        self.assertEqual(model.penalties, self.penalties)
        self.assertEqual(model.neighbors, self.neighbors)

    def test_every_exported_entry_is_certified_including_unselected_banks(self):
        for index in range(len(self.penalties)):
            corrupt = list(self.penalties)
            corrupt[index] = (corrupt[index] + 1) % 81
            with self.subTest(penalty=index), self.assertRaises(ValueError):
                RoutingModel.certified(self.recipe, self.binding, corrupt,
                                       self.increments, self.fields)
        for index in range(len(self.increments)):
            corrupt = list(self.increments)
            corrupt[index] = (corrupt[index] + 1) % 256
            with self.subTest(increment=index), self.assertRaises(ValueError):
                RoutingModel.certified(self.recipe, self.binding, self.penalties,
                                       corrupt, self.fields)
        wrong = list(self.fields)
        wrong[0] += 1
        with self.assertRaises(ValueError):
            RoutingModel.certified(self.recipe, self.binding, self.penalties,
                                   self.increments, wrong)
        with self.assertRaises(ValueError):
            RoutingModel.certified(self.recipe, HadamardBinding(((0, 0),) * 4),
                                   self.penalties, self.increments, self.fields)

    def test_cpu_compiler_mistakes_cannot_bypass_admission(self):
        wrong = list(self.penalties)
        wrong[16] = (wrong[16] + 1) % 81
        with patch('solvefinite.hadamard._compile_model', return_value=(wrong, self.increments)):
            with self.assertRaises(ValueError):
                RoutingModel.build(self.recipe, self.binding, self.fields)

    def test_table_shapes_exact_types_and_field_certificate(self):
        def admit(p=self.penalties, inc=self.increments, fields=self.fields):
            return RoutingModel.certified(self.recipe, self.binding, p, inc, fields)
        for value in (None, self.penalties[:-1], self.penalties + (0,),
                      iter(self.penalties), bytes(len(self.penalties))):
            with self.assertRaises(ValueError):
                admit(p=value)
        for value in (None, self.increments[:-1], self.increments + (0,),
                      iter(self.increments), bytes(len(self.increments))):
            with self.assertRaises(ValueError):
                admit(inc=value)
        for value in (-1, 81, True, False, 0.0, '0', None):
            with self.assertRaises(ValueError):
                admit(p=(value,) + self.penalties[1:])
        for value in (-1, 256, True, False, 11.0, '11', None):
            with self.assertRaises(ValueError):
                admit(inc=(value,) + self.increments[1:])
        for value in (None, iter(self.fields), self.fields[:-1], (0,) * 20,
                      (True,) + self.fields[1:]):
            with self.assertRaises(ValueError):
                admit(fields=value)
        with patch('solvefinite.hadamard.evaluate_field', side_effect=AssertionError('too early')):
            for recipe, binding in ((None, self.binding), (self.recipe, None),
                                    (self.recipe.to_dict(), self.binding),
                                    (self.recipe, self.binding.to_dict())):
                with self.assertRaises(ValueError):
                    RoutingModel.build(recipe, binding)

    def test_immutable_admission_does_not_retain_mutable_inputs_or_scalar_arena(self):
        penalties, increments, fields = list(self.penalties), list(self.increments), list(self.fields)
        model = RoutingModel.certified(self.recipe, self.binding, penalties, increments, fields)
        penalties[0], increments[0], fields[0] = 80, 0, 0
        self.assertEqual(model.penalties, self.penalties)
        self.assertEqual(model.increments, self.increments)
        self.assertEqual(set(model.__slots__), {'recipe', 'binding', 'neighbors',
                                               'penalties', 'increments'})
        self.assertFalse(hasattr(model, '__dict__'))
        with self.assertRaises(FrozenInstanceError):
            model.penalties = ()
        with self.assertRaises(ValueError):
            RoutingModel(self.recipe, self.binding, self.penalties, self.increments)

    def test_query_validation_rejects_non_edges_and_non_intrinsic_phase(self):
        model = RoutingModel.build(self.recipe, self.binding)
        for bad in (-1, 20, True, 0.0, '0', None):
            with self.assertRaises(ValueError):model.penalty(bad, 0, 1)
            with self.assertRaises(ValueError):model.penalty(0, 0, bad)
            with self.assertRaises(ValueError):model.next_phase(bad, 0)
        for bad in (-1, 256, True, 0.0, '0', None):
            with self.assertRaises(ValueError):model.penalty(0, bad, 1)
            with self.assertRaises(ValueError):model.next_phase(0, bad)
        for destination in (0, 2, 6, 17):
            with self.assertRaises(ValueError):model.penalty(0, 0, destination)
        self.assertEqual(model.next_phase(0, 250), 5)

    def test_zero_gain_and_zero_gradient_are_neutral(self):
        model = RoutingModel.build(self.recipe, self.binding)
        self.assertEqual(model.penalties[:16], (0,) * 16)
        self.assertEqual(model.penalties[160:176], (0,) * 16)
        zero = RoutingModel.build(self.recipe, HadamardBinding(((0, 0),) * 4))
        self.assertEqual(zero.penalties, (0,) * 320)
        self.assertEqual(zero.increments, model.increments)

    def test_signed_gain_extremes_all_primitive_axes_and_reflected_directions(self):
        # Exhaust the HP2 finite scalar domain independently of the compiler.
        maximum_seen = 0
        for gu in range(-2, 3):
            for gv in range(-2, 3):
                divisor = gcd(abs(gu), abs(gv))
                pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
                for au in range(-4, 5):
                    for av in range(-4, 5):
                        q = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
                        self.assertLessEqual(max(map(abs, q)), 40)
                        for epsilon in (-1, 1):
                            mirrored = (au * (1 + (epsilon * pu) ** 2) * gu,
                                        av * (1 + (-epsilon * pv) ** 2) * (-gv))
                            self.assertEqual(mirrored, (q[0], -q[1]))
                            for eu, ev in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                p = max(map(abs, q)) - q[0] * eu - q[1] * ev
                                reflected = max(map(abs, mirrored)) - mirrored[0] * eu + mirrored[1] * ev
                                self.assertEqual(p, reflected)
                                self.assertGreaterEqual(p, 0)
                                self.assertLessEqual(p, 80)
                                maximum_seen = max(maximum_seen, p)
        self.assertEqual(maximum_seen, 80)

    def test_quotient_aliases_preserve_directional_penalties(self):
        model = RoutingModel.build(self.recipe, self.binding)
        for node in range(20):
            u, v = divmod(node, 5)
            gu, gv = covering_gradient(4, 5, self.fields, u + 4, -v)
            divisor = gcd(abs(gu), abs(gv))
            pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
            # Crossing u once reverses the v component of each local edge.
            for bank, (au, av) in enumerate(self.binding.gains):
                q = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
                for destination, (eu, ev) in zip(covering_neighbors(4, 5, node),
                                                ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    expected = max(map(abs, q)) - q[0] * eu + q[1] * ev
                    self.assertEqual(model.penalty(node, bank * 64, destination), expected)


if __name__ == '__main__':
    unittest.main()
