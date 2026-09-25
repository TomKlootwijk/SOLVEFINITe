"""Independent covering-space, scalar-distance and exact eigenpair checks."""

from collections import deque
from dataclasses import FrozenInstanceError, replace
from math import gcd
import unittest

from solvefinite.klein import KleinDomain
from solvefinite.psi import PsiAxis, axis_from_gradient, field_axes


DEFAULT_FIELD = (-2, -1, 0, 0, -1, -1, 0, 1, 1, 0,
                 0, 1, 2, 2, 1, -1, 0, 1, 1, 0)


def covering_node(width, height, u, v):
    """Reduce a cover label directly, without domain.step or canonical."""
    wrap, column = divmod(u, width)
    return column * height + ((-v if wrap % 2 else v) % height)


def covering_neighbors(width, height, node):
    u, v = divmod(node, height)
    return tuple(covering_node(width, height, a, b)
                 for a, b in ((u + 1, v), (u - 1, v), (u, v + 1), (u, v - 1)))


def distances(width, height, sources):
    result = [-1] * (width * height)
    pending = deque(sources)
    for source in sources:
        result[source] = 0
    while pending:
        source = pending.popleft()
        for target in covering_neighbors(width, height, source):
            if result[target] < 0:
                result[target] = result[source] + 1
                pending.append(target)
    return tuple(result)


def independent_field(width, height, center, radius):
    centered = distances(width, height, (center,))
    signs = tuple((distance > radius) - (distance < radius) for distance in centered)
    boundary = tuple(node for node, sign in enumerate(signs) if sign == 0)
    nearest = distances(width, height, boundary)
    return tuple(sign * distance for sign, distance in zip(signs, nearest))


def covering_gradient(width, height, fields, u, v):
    sample = lambda a, b: fields[covering_node(width, height, a, b)]
    return sample(u + 1, v) - sample(u - 1, v), sample(u, v + 1) - sample(u, v - 1)


class ExactPsiTests(unittest.TestCase):
    def assert_certificate(self, axis, sign):
        gu, gv = axis.gradient
        a, b, c, d = axis.tensor
        pu, pv = axis.vector
        value = axis.eigenvalue
        self.assertEqual((a * pu + b * pv, c * pu + d * pv),
                         (value * pu, value * pv))
        self.assertEqual(a + d, value)
        self.assertEqual(a * d - b * c, 0)
        self.assertGreaterEqual(value, 0)
        self.assertEqual(b, c)
        self.assertEqual(gcd(abs(pu), abs(pv)), 1)
        self.assertIn(value, (0, 1, 2, 4, 5, 8))
        self.assertTrue(all(-2 <= component <= 2 for component in axis.vector))
        self.assertEqual(axis.degenerate, (gu, gv) == (0, 0))
        # The other eigenvalue is zero: trace/determinant certify maximality.
        # The Rayleigh upper bound is also checked in independent directions.
        for u, v in ((1, 0), (0, 1), (1, 1), (1, -1), (2, -1)):
            quadratic = a * u * u + (b + c) * u * v + d * v * v
            self.assertLessEqual(0, quadratic)
            self.assertLessEqual(quadratic, value * (u * u + v * v))
        if value:
            self.assertEqual(gu * pv, gv * pu)
            self.assertGreater(sign * (gu * pu + gv * pv), 0)
        else:
            self.assertEqual(axis.vector, (sign, 0))

    def test_all_25_gradients_both_signs_and_frames(self):
        for gu in range(-2, 3):
            for gv in range(-2, 3):
                for sign in (-1, 1):
                    axis = axis_from_gradient(gu, gv, sign)
                    self.assertEqual(axis.gradient, (gu, gv))
                    self.assert_certificate(axis, sign)
                    for orientation in (0, 1):
                        with self.subTest(g=(gu, gv), sign=sign, eta=orientation):
                            transported = axis.transport(orientation)
                            reflection = 1 - 2 * orientation
                            self.assertEqual(transported.gradient, (gu, reflection * gv))
                            self.assertEqual(transported.tensor,
                                             (gu * gu, reflection * gu * gv,
                                              reflection * gu * gv, gv * gv))
                            self.assertEqual(transported.vector,
                                             (axis.vector[0], reflection * axis.vector[1]))
                            self.assert_certificate(transported, sign)
                            self.assertEqual(transported.transport(orientation), axis)

    def test_default_literal_eigenpairs_and_zero_tie(self):
        self.assertEqual(independent_field(4, 5, 0, 2), DEFAULT_FIELD)
        axes = field_axes(KleinDomain(4, 5), DEFAULT_FIELD)
        expected = {
            0: ((0, 0), (0, 0, 0, 0), 0, (1, 0), True),
            6: ((2, 2), (4, 4, 4, 4), 8, (1, 1), False),
            7: ((2, 1), (4, 2, 2, 1), 5, (2, 1), False),
            16: ((-2, 2), (4, -4, -4, 4), 8, (-1, 1), False),
            17: ((-2, 1), (4, -2, -2, 1), 5, (-2, 1), False),
        }
        for node, values in expected.items():
            with self.subTest(node=node):
                self.assertEqual(axes[node], PsiAxis(*values))
        self.assertEqual(axes[10].gradient, (0, 0))
        self.assertEqual(axes[10].vector, (1, 0))
        self.assertIs(axes[10].degenerate, True)

    def test_field_stencils_against_independent_cover_and_bfs(self):
        for width, height in ((3, 3), (3, 4), (4, 3), (4, 5), (5, 7),
                              (8, 8), (3, 85), (85, 3), (16, 16)):
            domain = KleinDomain(width, height)
            for center in (0, width * height // 2, width * height - 1):
                eccentricity = max(distances(width, height, (center,)))
                for radius in sorted({1, max(1, eccentricity // 2), eccentricity}):
                    fields = independent_field(width, height, center, radius)
                    for sign in (-1, 1):
                        axes = field_axes(domain, fields, sign)
                        self.assertIs(type(axes), tuple)
                        self.assertEqual(len(axes), width * height)
                        for node, axis in enumerate(axes):
                            u, v = divmod(node, height)
                            expected = covering_gradient(width, height, fields, u, v)
                            with self.subTest(size=(width, height), center=center,
                                              radius=radius, sign=sign, node=node):
                                self.assertEqual(axis.gradient, expected)
                                self.assert_certificate(axis, sign)

    def test_chart_aliases_transport_axes_without_changing_base_identity(self):
        for width, height, center, radius in ((4, 5, 0, 2), (5, 7, 11, 3), (3, 4, 5, 1)):
            fields = independent_field(width, height, center, radius)
            axes = field_axes(KleinDomain(width, height), fields)
            for node, axis in enumerate(axes):
                u, v = divmod(node, height)
                for wrap in (-5, -2, -1, 0, 1, 2, 5):
                    for vertical in (-3, 0, 4):
                        orientation = wrap % 2
                        alias_u = u + wrap * width
                        alias_v = (-v if orientation else v) + vertical * height
                        self.assertEqual(covering_node(width, height, alias_u, alias_v), node)
                        expected = covering_gradient(width, height, fields, alias_u, alias_v)
                        transported = axis.transport(orientation)
                        self.assertEqual(transported.gradient, expected)
                        # Return to the canonical chart before using the index key.
                        self.assertEqual(transported.transport(orientation), axis)
        axis = field_axes(KleinDomain(4, 5), DEFAULT_FIELD)[16]
        self.assertEqual(covering_node(4, 5, 7, -1), 16)
        self.assertEqual(covering_gradient(4, 5, DEFAULT_FIELD, 7, -1), (-2, -2))
        self.assertEqual(axis.transport(1), PsiAxis((-2, -2), (4, 4, 4, 4), 8,
                                                   (-1, -1), False))

    def test_signed_axis_is_immutable_and_transport_rejects_invalid_orientation(self):
        axis = axis_from_gradient(2, -1)
        with self.assertRaises(FrozenInstanceError):
            axis.vector = (1, 0)
        for orientation in (True, False, -1, 2, 1.0, "1", None):
            with self.subTest(orientation=orientation), self.assertRaises(ValueError):
                axis.transport(orientation)

    def test_gradient_and_sign_types_and_bounds_are_strict(self):
        for invalid in (True, False, -3, 3, 1.0, "1", None, (), []):
            for first in (True, False):
                with self.subTest(value=invalid, first=first), self.assertRaises(ValueError):
                    axis_from_gradient(invalid if first else 1, 1 if first else invalid)
        for invalid in (True, False, 0, 2, -2, 1.0, -1.0, "1", None):
            with self.subTest(sign=invalid), self.assertRaises(ValueError):
                axis_from_gradient(1, 0, invalid)

    def test_direct_axis_construction_rejects_inconsistent_certificates(self):
        axis = axis_from_gradient(2, 1)
        changes = ({"gradient": [2, 1]}, {"gradient": (True, 1)},
                   {"gradient": (2, 1, 0)}, {"gradient": (3, 1)},
                   {"tensor": [4, 2, 2, 1]}, {"tensor": (4, 2, 1, 1)},
                   {"tensor": (4, 2, 2, True)}, {"eigenvalue": True},
                   {"eigenvalue": 4}, {"eigenvalue": 5.0},
                   {"vector": [2, 1]}, {"vector": (0, 0)},
                   {"vector": (1, 1)}, {"vector": (2, True)},
                   {"degenerate": 0}, {"degenerate": True})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(axis, **change)
        for vector in ((0, 0), (0, 1), (2, 0)):
            with self.subTest(fallback=vector), self.assertRaises(ValueError):
                PsiAxis((0, 0), (0, 0, 0, 0), 0, vector, True)
        self.assertEqual(replace(axis, vector=(-2, -1)), axis_from_gradient(2, 1, -1))

    def test_field_input_shape_values_and_signed_edge_bounds(self):
        domain = KleinDomain(4, 5)
        for invalid in (None, (), [], DEFAULT_FIELD[:-1], DEFAULT_FIELD + (0,),
                        "0" * 20, set(DEFAULT_FIELD), iter(DEFAULT_FIELD)):
            with self.subTest(fields=invalid), self.assertRaises(ValueError):
                field_axes(domain, invalid)
        for invalid in (True, False, -128, 128, 0.0, "0", None):
            changed = list(DEFAULT_FIELD)
            changed[0] = invalid
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                field_axes(domain, changed)
        for invalid in (None, (4, 5), "klein", True):
            with self.subTest(domain=invalid), self.assertRaises(ValueError):
                field_axes(invalid, DEFAULT_FIELD)
        for invalid in (True, 0, 2, 1.0, None):
            with self.subTest(sign=invalid), self.assertRaises(ValueError):
                field_axes(domain, DEFAULT_FIELD, invalid)
        signed_jump = [1] * 20
        signed_jump[0] = -1
        # Absolute distances agree, but the signed edge difference is two.
        with self.assertRaisesRegex(ValueError, "signed unit-edge"):
            field_axes(domain, signed_jump)

    def test_local_axis_admission_does_not_claim_exact_sdf_certification(self):
        domain = KleinDomain(4, 5)
        for value in (-127, 0, 127):
            fields = [value] * 20
            axes = field_axes(domain, fields)
            fields[0] = value - 1
            self.assertTrue(all(axis.gradient == (0, 0) and axis.degenerate for axis in axes))
            self.assertEqual(axes, (axis_from_gradient(0, 0),) * 20)


if __name__ == "__main__":
    unittest.main()
