"""Conformance to TK-LPLUT-SDF-1.0 using independent intrinsic-distance checks."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import random
import unittest

from solvefinite.field import (
    FieldManifest, FieldMachine, build_operators, certify_field, evaluate_field,
)
from solvefinite.rp32 import Opcode, pack, pair, unpair, unpack


def graph_manifest(nodes, edges, signs, **changes):
    count = len(nodes)
    return FieldManifest(nodes=tuple(nodes), edges=tuple(sorted(edges)), signs=tuple(signs),
                         routes=tuple((index, index, index) for index in range(count)),
                         turns=tuple((11, 53, 137) for _ in range(count)), **changes)


def floyd_warshall(manifest):
    count = len(manifest.nodes)
    distances = [[0 if i == j else 10 ** 9 for j in range(count)] for i in range(count)]
    for left, right, length in manifest.edges:
        distances[left][right] = distances[right][left] = length
    for through in range(count):
        for source in range(count):
            for target in range(count):
                distances[source][target] = min(
                    distances[source][target], distances[source][through] + distances[through][target])
    return distances


def independent_field(manifest):
    distances = floyd_warshall(manifest)
    boundary = [index for index, sign in enumerate(manifest.signs) if sign == 0]
    return tuple(sign * min(distances[index][other] for other in boundary)
                 for index, sign in enumerate(manifest.signs))


class IntrinsicFieldTests(unittest.TestCase):
    def test_default_weighted_chain_has_exact_signed_distances_and_units(self):
        manifest = FieldManifest()
        expected = (-6, -4, -3, 0, 2, 3, 5)
        self.assertEqual(evaluate_field(manifest), expected)
        self.assertIsNone(certify_field(manifest, expected))
        self.assertEqual(evaluate_field(replace(manifest, unit_num=3, unit_den=5)), expected)
        self.assertEqual(evaluate_field(replace(manifest, unit_num=1_000_000, unit_den=999_999)), expected)

    def test_multiple_boundaries_and_one_node_domains(self):
        manifest = replace(FieldManifest(), signs=(-1, 0, 1, 1, 0, -1, -1))
        self.assertEqual(evaluate_field(manifest), (-2, 0, 1, 2, 0, -1, -3))
        certify_field(manifest, evaluate_field(manifest))
        single = graph_manifest(("boundary",), (), (0,))
        self.assertEqual(evaluate_field(single), (0,))
        machine = FieldMachine(single)
        self.assertEqual(unpack(unpair(machine.agent_pair)[0])[1:3], (0, 0))
        machine.advance(4)
        self.assertEqual(machine.snapshot()["node"], "boundary")

    def test_random_weighted_graphs_match_independent_floyd_warshall_oracle(self):
        rng = random.Random(20260925)
        for case in range(30):
            count = rng.randrange(2, 21)
            edges = {(index, index + 1): rng.randrange(1, 8) for index in range(count - 1)}
            for left in range(count):
                for right in range(left + 2, count):
                    if rng.random() < 0.15:
                        edges[left, right] = rng.randrange(1, 8)
            boundary = set(rng.sample(range(count), rng.randrange(1, min(4, count) + 1)))
            signs = [0 if index in boundary else 1 for index in range(count)]
            manifest = graph_manifest(tuple(f"vertex-{index}" for index in range(count)),
                                      tuple((a, b, w) for (a, b), w in edges.items()), signs)
            with self.subTest(case=case):
                values = evaluate_field(manifest)
                self.assertEqual(values, independent_field(manifest))
                certify_field(manifest, values)
                distances = floyd_warshall(manifest)
                for left in range(count):
                    self.assertEqual(values[left] == 0, left in boundary)
                    for right in range(count):
                        self.assertLessEqual(abs(values[left] - values[right]), distances[left][right])

    def test_signed_lipschitz_and_second_difference_bounds_follow_intrinsic_edges(self):
        manifest = FieldManifest()
        values = evaluate_field(manifest)
        distances = floyd_warshall(manifest)
        neighbors = {index: {} for index in range(len(values))}
        for left, right, length in manifest.edges:
            neighbors[left][right] = neighbors[right][left] = length
        for left in range(len(values)):
            for right in range(len(values)):
                self.assertLessEqual(abs(values[left] - values[right]), distances[left][right])
            for previous, first_length in neighbors[left].items():
                for following, second_length in neighbors[left].items():
                    second_difference = values[following] - 2 * values[left] + values[previous]
                    self.assertLessEqual(abs(second_difference), first_length + second_length)

    def test_distance_codes_127_are_exact_and_128_are_rejected_without_saturation(self):
        extremes = graph_manifest(("inside", "boundary", "outside"),
                                  ((0, 1, 127), (1, 2, 127)), (-1, 0, 1))
        self.assertEqual(evaluate_field(extremes), (-127, 0, 127))
        certify_field(extremes, (-127, 0, 127))
        for side in (-1, 1):
            manifest = graph_manifest(("boundary", "near", "far"),
                                      ((0, 1, 127), (1, 2, 1)), (0, side, side))
            with self.subTest(side=side):
                with self.assertRaises(ValueError):
                    evaluate_field(manifest)
                with self.assertRaises(ValueError):
                    FieldMachine(manifest)
                with self.assertRaises(ValueError):
                    certify_field(manifest, (0, 127 * side, 127 * side))

    def test_certificate_rejects_geometric_errors_even_with_valid_parity(self):
        manifest = FieldManifest()
        exact = evaluate_field(manifest)
        wrong = (-5, -3, -2, 0, 1, 2, 4)
        # All edge differences still obey their weights, but the decreasing
        # exact-distance witness is absent next to the boundary.
        for left, right, length in manifest.edges:
            self.assertLessEqual(abs(abs(wrong[left]) - abs(wrong[right])), length)
        for index, field in enumerate(wrong):
            self.assertEqual(unpack(pack(0, index, field, Opcode.STEP))[2], field)
        candidates = (wrong, tuple(-value for value in exact), (0,) * 7,
                      (-128, *exact[1:]), (*exact[:-1], 127), exact[:-1],
                      (True, *exact[1:]), (float(exact[0]), *exact[1:]))
        for candidate in candidates:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                certify_field(manifest, candidate)
        with self.assertRaises(ValueError):
            build_operators(manifest, wrong)
        self.assertIsNone(certify_field(manifest, list(exact)))

    def test_maximum_256_node_index_is_representable(self):
        manifest = graph_manifest(tuple(f"n{index}" for index in range(256)),
                                  tuple((0, index, 127) for index in range(1, 256)),
                                  (0,) + (1,) * 255, initial_node=255)
        routes = list(manifest.routes)
        routes[0], routes[255] = (255, 255, 255), (0, 0, 0)
        manifest = replace(manifest, routes=tuple(routes))
        self.assertEqual(evaluate_field(manifest), (0,) + (127,) * 255)
        machine = FieldMachine(manifest)
        self.assertEqual(unpack(unpair(machine.agent_pair)[0])[1:3], (255, 127))
        self.assertEqual([unpack(unpair(value)[0])[1] for value in machine.advance(2)], [0, 255])
        with self.assertRaises(ValueError):
            graph_manifest(tuple(f"n{index}" for index in range(257)),
                           tuple((0, index, 1) for index in range(1, 257)), (0,) * 257)


class FieldManifestTests(unittest.TestCase):
    def test_frozen_manifest_exact_json_schema_and_independent_copies(self):
        manifest = FieldManifest()
        encoded = manifest.to_dict()
        self.assertEqual(set(encoded), {"format", "identity", "nodes", "edges", "signs", "routes",
                                       "turns", "unit_num", "unit_den", "initial_node",
                                       "initial_phase", "initial_orientation", "max_ticks"})
        self.assertEqual(encoded["format"], "relational-sdf-v1")
        self.assertEqual(FieldManifest.from_dict(encoded), manifest)
        with self.assertRaises(FrozenInstanceError):
            manifest.initial_phase = 1
        for key in encoded:
            changed = deepcopy(encoded)
            changed.pop(key)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                FieldManifest.from_dict(changed)
        for invalid in (None, [], {}, {**encoded, "extra": 1}, {**encoded, "format": "future"}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                FieldManifest.from_dict(invalid)
        encoded["nodes"][0] = "changed"
        encoded["edges"][0][2] = 127
        encoded["routes"][0][0] = 6
        self.assertEqual(manifest.nodes[0], "n0")
        self.assertEqual(manifest.edges[0], (0, 1, 2))
        self.assertEqual(manifest.routes[0][0], 1)

    def test_invalid_graph_boundary_units_and_unused_operator_columns_rejected(self):
        manifest = FieldManifest()
        invalid = (
            {"identity": ""}, {"identity": " "}, {"identity": "x" * 129},
            {"nodes": ()}, {"nodes": tuple("same" for _ in range(7))},
            {"nodes": ("", *manifest.nodes[1:])}, {"nodes": list(manifest.nodes)},
            {"edges": manifest.edges[:-1]}, {"edges": tuple(reversed(manifest.edges))},
            {"edges": ((1, 0, 2), *manifest.edges[1:])},
            {"edges": ((0, 0, 2), *manifest.edges[1:])},
            {"edges": ((0, 1, 0), *manifest.edges[1:])},
            {"edges": ((0, 1, 128), *manifest.edges[1:])},
            {"edges": ((0, 1, True), *manifest.edges[1:])},
            {"edges": ((0, 1, 2), (0, 1, 3), *manifest.edges[1:])},
            {"signs": (-1,) * 7}, {"signs": (-1, -1, 1, 0, 1, 1, 1)},
            {"signs": (-2, *manifest.signs[1:])}, {"signs": (True, *manifest.signs[1:])},
            {"routes": ((1, 1, 6), *manifest.routes[1:])},
            {"routes": ((True, 1, 1), *manifest.routes[1:])},
            {"turns": ((11, 53, 256), *manifest.turns[1:])},
            {"turns": ((11, 53, 1.0), *manifest.turns[1:])},
            {"unit_num": 0}, {"unit_den": -1}, {"unit_num": True},
            {"unit_num": 2, "unit_den": 4}, {"unit_num": 1_000_001},
            {"initial_node": 7}, {"initial_phase": 256}, {"initial_orientation": 2},
            {"initial_orientation": True}, {"max_ticks": 0}, {"max_ticks": 65537},
            {"max_ticks": True},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(manifest, **change)
        encoded = manifest.to_dict()
        for key in ("nodes", "edges", "signs", "routes", "turns"):
            changed = deepcopy(encoded)
            changed[key] = tuple(changed[key])
            with self.subTest(json_collection=key), self.assertRaises(ValueError):
                FieldManifest.from_dict(changed)


class FieldExecutionTests(unittest.TestCase):
    def test_compiled_operator_lanes_are_geometrically_bound_for_every_class(self):
        manifest = FieldManifest()
        fields = evaluate_field(manifest)
        operators = build_operators(manifest, fields)
        for source, row in enumerate(operators):
            for column, word in enumerate(row):
                target = manifest.routes[source][column]
                self.assertEqual(unpack(word), (manifest.turns[source][column], target,
                                               fields[target], Opcode.STEP))

    def test_default_trace_uses_current_field_class_and_destination_field(self):
        machine = FieldMachine()
        expected = tuple(pair(pack(phase, node, field, Opcode.STEP))
                         for phase, node, field in ((5, 1, -4), (16, 2, -3),
                                                    (27, 3, 0), (80, 4, 2),
                                                    (217, 3, 0), (14, 4, 2)))
        self.assertEqual(machine.advance(6), expected)
        self.assertEqual(machine.tick, 6)
        self.assertEqual(machine.snapshot()["node"], "n4")
        self.assertEqual(machine.agent_pair, expected[-1])
        self.assertEqual(machine.fields, (-6, -4, -3, 0, 2, 3, 5))

    def test_scalar_field_and_entire_transition_are_preserved_under_mirror(self):
        forward = FieldMachine(FieldManifest())
        mirrored = FieldMachine(replace(FieldManifest(), initial_phase=6, initial_orientation=1))
        original_trace = (forward.agent_pair, *forward.advance(16))
        mirrored_trace = (mirrored.agent_pair, *mirrored.advance(16))
        for original, changed in zip(original_trace, mirrored_trace):
            left, right = unpair(original)
            self.assertEqual(unpair(changed), (right, left))
            self.assertEqual(unpack(left)[2], unpack(unpair(changed)[0])[2])

    def test_label_and_index_transport_preserves_decoded_relational_execution(self):
        original = FieldManifest()
        order = (3, 0, 6, 2, 4, 1, 5)
        reindex = {old: new for new, old in enumerate(order)}
        edges = tuple(sorted((*sorted((reindex[left], reindex[right])), length)
                             for left, right, length in original.edges))
        transported = replace(original,
                              nodes=tuple(original.nodes[old] for old in order), edges=edges,
                              signs=tuple(original.signs[old] for old in order),
                              routes=tuple(tuple(reindex[target] for target in original.routes[old])
                                           for old in order),
                              turns=tuple(original.turns[old] for old in order),
                              initial_node=reindex[original.initial_node])
        left, right = FieldMachine(original), FieldMachine(transported)
        self.assertEqual(right.fields, tuple(left.fields[old] for old in order))
        self.assertNotEqual(left.agent_pair, right.agent_pair)
        for first, second in zip(left.advance(20), right.advance(20)):
            r1, g1, b1, a1 = unpack(unpair(first)[0])
            r2, g2, b2, a2 = unpack(unpair(second)[0])
            self.assertEqual((r1, original.nodes[g1], b1, a1),
                             (r2, transported.nodes[g2], b2, a2))

    def test_split_batches_and_replay_keep_every_output_identical(self):
        reference = FieldMachine()
        expected = reference.advance(48)
        split = FieldMachine()
        actual = []
        for count in (3, 7, 1, 12, 25):
            actual.extend(split.advance(count))
            split = FieldMachine.from_archive(split.archive())
        self.assertEqual(tuple(actual), expected)
        self.assertEqual(split.archive(), reference.archive())

    def test_budget_and_invalid_ticks_fail_before_state_changes(self):
        machine = FieldMachine(replace(FieldManifest(), max_ticks=5))
        machine.advance(4)
        before = machine.archive()
        for count in (0, -1, True, 1.0, "1", 4097, 2):
            with self.subTest(count=count), self.assertRaises(ValueError):
                machine.advance(count)
            self.assertEqual(machine.archive(), before)
        machine.advance(1)
        self.assertEqual(machine.tick, 5)
        before = machine.archive()
        with self.assertRaises(ValueError):
            machine.advance(1)
        self.assertEqual(machine.archive(), before)
        large = FieldMachine()
        self.assertEqual(len(large.advance(4096)), 4096)

    def test_archive_exact_schema_replay_and_tamper_detection(self):
        empty = FieldMachine()
        self.assertEqual(FieldMachine.from_archive(empty.archive()).archive(), empty.archive())
        machine = FieldMachine()
        machine.advance(3)
        original = machine.archive()
        self.assertEqual(set(original), {"format", "manifest", "trace", "expected"})
        self.assertEqual(original["format"], "relational-sdf-machine-v1")
        self.assertEqual(set(original["expected"]), {"identity", "tick", "node", "agent_pair"})
        self.assertEqual(original["trace"], [f"{value:016X}" for value in
                                             FieldMachine().advance(3)])
        valid_wrong_pair = f"{pair(pack(6, 1, -4, Opcode.STEP)):016X}"
        changes = {
            "format": lambda a: a.update(format="future"),
            "extra field": lambda a: a.update(extra=1),
            "missing manifest": lambda a: a.pop("manifest"),
            "missing output": lambda a: a["trace"].pop(0),
            "wrong trace shape": lambda a: a.update(trace=tuple(a["trace"])),
            "reordered trace": lambda a: a["trace"].reverse(),
            "valid parity wrong transition": lambda a: a["trace"].__setitem__(0, valid_wrong_pair),
            "lowercase pair": lambda a: a["trace"].__setitem__(0, a["trace"][0].lower()),
            "integer pair": lambda a: a["trace"].__setitem__(0, int(a["trace"][0], 16)),
            "extra tick": lambda a: a["trace"].append(a["trace"][-1]),
            "wrong final node": lambda a: a["expected"].update(node="n0"),
            "boolean tick": lambda a: a["expected"].update(tick=True),
            "wrong final pair": lambda a: a["expected"].update(agent_pair=valid_wrong_pair),
            "missing expected": lambda a: a.pop("expected"),
            "changed geometry": lambda a: a["manifest"]["edges"][1].__setitem__(2, 2),
        }
        for label, mutate in changes.items():
            damaged = deepcopy(original)
            mutate(damaged)
            with self.subTest(case=label), self.assertRaises(ValueError):
                FieldMachine.from_archive(damaged)
        detached = machine.archive()
        detached["trace"].clear()
        detached["expected"].clear()
        detached["manifest"]["routes"][0].clear()
        self.assertEqual(machine.archive(), original)


if __name__ == "__main__":
    unittest.main()
