"""Independent covering-coordinate, phase and tree witnesses for PX1-PX8."""

from collections import deque
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from solvefinite.f8 import (F8Index, IndexBinding, MAX_EPOCH, NULL,
                            build_geometry)
from solvefinite.field_world import KleinFieldRecipe


REFERENCE = Path(__file__).resolve().parents[1] / "docs/evidence/psi-f8-v1/formal-reference.json"


def independent(recipe, binding=IndexBinding()):
    """Cover arithmetic and BFS; no field, Klein, Psi or index helpers."""
    width, height = recipe.width, recipe.height
    count = width * height

    def reduce(u, v):
        wrap, canonical_u = divmod(u, width)
        return canonical_u * height + (-v if wrap % 2 else v) % height

    directions = tuple(tuple(reduce(u + du, v + dv)
                             for du, dv in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                       for u in range(width) for v in range(height))

    def bfs(seeds):
        distances = [None] * count
        queue = deque(seeds)
        for seed in seeds:
            distances[seed] = 0
        while queue:
            node = queue.popleft()
            for neighbor in directions[node]:
                if distances[neighbor] is None:
                    distances[neighbor] = distances[node] + 1
                    queue.append(neighbor)
        return tuple(distances)

    distances = bfs((recipe.center,))
    boundary = tuple(node for node in range(count) if distances[node] == recipe.radius)
    unsigned = bfs(boundary)
    fields = tuple(-unsigned[node] if distance < recipe.radius else unsigned[node]
                   for node, distance in enumerate(distances))
    parents = tuple(recipe.center if distance == 0 else
                    min(neighbor for neighbor in directions[node]
                        if distances[neighbor] == distance - 1)
                    for node, distance in enumerate(distances))
    records = []
    for node, adjacent in enumerate(directions):
        gu = fields[adjacent[0]] - fields[adjacent[1]]
        gv = fields[adjacent[2]] - fields[adjacent[3]]
        # All possible gradients fit [-2,2]; enumerate allowed primitive scale.
        if gu == gv == 0:
            pu, pv = 1, 0
        else:
            divisor = 2 if gu % 2 == 0 and gv % 2 == 0 else 1
            pu, pv = gu // divisor, gv // divisor
        source, path = node, []
        while source != recipe.center:
            path.insert(0, source)
            source = parents[source]
        phase, eta = binding.phase_origin, 0
        for destination in path:
            increment = recipe.turns[0 if fields[source] < 0 else 1 if fields[source] == 0 else 2]
            phase = (phase + (1 if eta == 0 else -1) * increment) % 256
            if {source // height, destination // height} == {0, width - 1}:
                phase, eta = (-phase) % 256, 1 - eta
            source = destination
        theta = phase if eta == 0 else (-phase) % 256
        rho, remaining = 0, distances[node] + 1
        while remaining >= 2:
            rho, remaining = rho + 1, remaining // 2
        records.append((binding.psi_sign * pu + 2, binding.psi_sign * pv + 2,
                        rho, theta, node, gu * gu + gv * gv, gu + 2, gv + 2))
    records = tuple(records)
    return directions, distances, parents, fields, records, independent_rows(records)


def independent_rows(records, upper_median=False):
    """Find each rank's binary address, then sort addresses into preorder."""
    ordered = sorted(record[:5] for record in records)
    paths = {}
    for rank, key in enumerate(ordered):
        lo, hi, path = 0, len(records), ()
        while True:
            middle = (lo + hi - (0 if upper_median else 1)) // 2
            if rank == middle:
                paths[path] = key
                break
            if rank < middle:
                hi, path = middle, path + (0,)
            else:
                lo, path = middle + 1, path + (1,)
    addresses = sorted(paths)
    positions = {address: row for row, address in enumerate(addresses)}
    return tuple((*paths[address], positions.get(address + (0,), NULL),
                  positions.get(address + (1,), NULL), 0) for address in addresses)


class IndexBindingTests(unittest.TestCase):
    def test_strict_json_round_trip_and_immutability(self):
        binding = IndexBinding(epoch=7, psi_sign=-1, phase_origin=219)
        value = {"format": "f8-klein-sdf-v1", "epoch": 7,
                 "psi_sign": -1, "phase_origin": 219}
        self.assertEqual(binding.to_dict(), value)
        self.assertEqual(IndexBinding.from_dict(json.loads(json.dumps(value))), binding)
        value["epoch"] = 8
        self.assertEqual(binding.epoch, 7)
        with self.assertRaises(FrozenInstanceError):
            binding.epoch = 8

    def test_rejects_noncanonical_types_ranges_shapes_and_versions(self):
        for change in ({"epoch": True}, {"epoch": -1}, {"epoch": MAX_EPOCH + 1},
                       {"epoch": 1.0}, {"psi_sign": True}, {"psi_sign": 0},
                       {"psi_sign": 2}, {"psi_sign": -1.0}, {"phase_origin": True},
                       {"phase_origin": -1}, {"phase_origin": 256},
                       {"phase_origin": "0"}, {"format": True}, {"format": "future"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                IndexBinding(**change)
        good = IndexBinding().to_dict()
        invalid = [None, (), [], {}, dict(good, extra=0)]
        invalid += [{key: value for key, value in good.items() if key != absent}
                    for absent in good]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                IndexBinding.from_dict(value)

    def test_next_is_exactly_one_epoch_and_overflow_rejects_without_mutation(self):
        initial = IndexBinding(3, -1, 255)
        self.assertEqual(initial.next(), IndexBinding(4, -1, 255))
        self.assertEqual(initial.next(psi_sign=1, phase_origin=0), IndexBinding(4, 1, 0))
        for kwargs in ({"psi_sign": True}, {"psi_sign": 0}, {"phase_origin": 256}):
            with self.assertRaises(ValueError):
                initial.next(**kwargs)
            self.assertEqual(initial, IndexBinding(3, -1, 255))
        limit = IndexBinding(MAX_EPOCH)
        with self.assertRaises(ValueError):
            limit.next()
        self.assertEqual(limit.epoch, MAX_EPOCH)


class F8GeometryTests(unittest.TestCase):
    def test_geometry_matches_independent_cover_bfs_and_numeric_parent_ties(self):
        for recipe in (KleinFieldRecipe(), KleinFieldRecipe(3, 3, 4, 1),
                       KleinFieldRecipe(5, 7, 11, 3), KleinFieldRecipe(16, 16, 255, 4),
                       KleinFieldRecipe(85, 3, 127, 20)):
            with self.subTest(recipe=recipe):
                expected = independent(recipe)
                geometry = build_geometry(recipe)
                self.assertEqual((geometry.directions, geometry.distances, geometry.parents),
                                 expected[:3])
                for node, parent in enumerate(geometry.parents):
                    if node != recipe.center:
                        self.assertEqual(geometry.distances[parent] + 1, geometry.distances[node])
                with self.assertRaises(FrozenInstanceError):
                    geometry.parents = ()
        for bad in (None, {}, KleinFieldRecipe().to_dict()):
            with self.assertRaises(ValueError):
                build_geometry(bad)


class F8IndexTests(unittest.TestCase):
    def test_complete_literal_formal_reference(self):
        reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        recipe = KleinFieldRecipe()
        index = F8Index.build(recipe)
        oracle = independent(recipe)
        self.assertEqual(index.records, oracle[4])
        self.assertEqual(index.rows, oracle[5])
        expected_records = tuple((*item["key"], item["eigenvalue"],
                                  item["g"][0] + 2, item["g"][1] + 2)
                                 for item in reference["records"])
        expected_rows = tuple((*expected_records[item["node"]][:5],
                               item["left"], item["right"], 0)
                              for item in reference["rows"])
        self.assertEqual(index.records, expected_records)
        self.assertEqual(index.rows, expected_rows)
        self.assertEqual([record[4] for record in sorted(index.records)], reference["sorted_nodes"])
        self.assertEqual(index.rows[0][4], 1)
        self.assertEqual(index.rows[index.rows[0][5]][4], 16)
        self.assertNotIn(16, oracle[0][1])  # A real tree edge is not a movement edge.

    def test_nondefault_recipes_bindings_and_all_nodes_match_independent_oracle(self):
        recipes = (KleinFieldRecipe(3, 3, 4, 1), KleinFieldRecipe(5, 7, 11, 3, (0, 127, 255)),
                   KleinFieldRecipe(16, 16, 255, 7), KleinFieldRecipe(85, 3, 127, 20))
        for recipe in recipes:
            for binding in (IndexBinding(), IndexBinding(9, -1, 240)):
                with self.subTest(recipe=recipe, binding=binding):
                    oracle = independent(recipe, binding)
                    index = F8Index.build(recipe, binding, oracle[3])
                    self.assertEqual((index.records, index.rows), oracle[4:])
                    for node in range(recipe.width * recipe.height):
                        row = index.resolve(node)
                        self.assertEqual(index.rows[row][4], node)
                        self.assertEqual(index.lookup(list(index.key(node))), row)

    def test_aliases_canonicalize_before_lookup_including_negative_large_wraps(self):
        for recipe in (KleinFieldRecipe(), KleinFieldRecipe(3, 7, 8, 2)):
            index = F8Index.build(recipe)
            for u in (-1001, -17, -1, 0, 1, 7, 1000):
                for v in (-1003, -1, 0, 1, 7, 1002):
                    wraps, canonical_u = divmod(u, recipe.width)
                    expected_node = canonical_u * recipe.height + (-v if wraps % 2 else v) % recipe.height
                    self.assertEqual(index.lookup_chart(u, v), index.resolve(expected_node))
            for invalid in ((True, 0), (0, 1.0), ("1", 0)):
                with self.assertRaises(ValueError):
                    index.lookup_chart(*invalid)
        self.assertEqual(F8Index.build(KleinFieldRecipe()).rows[
            F8Index.build(KleinFieldRecipe()).lookup_chart(7, -1)][4], 16)
        with self.assertRaises(ValueError):
            KleinFieldRecipe().index("k:7:-1")

    def test_well_formed_missing_keys_are_pure_and_query_types_are_strict(self):
        index = F8Index.build(KleinFieldRecipe())
        before = index.snapshot()
        for key in ((0, 0, 0, 0, 0), (4, 4, 8, 255, 255), ((1 << 32) - 1,) * 5,
                    (*index.key(0)[:4], 255)):
            self.assertIsNone(index.lookup(key))
        for bad in (None, {}, "12345", (), (0,) * 4, (0,) * 6,
                    (True, 0, 0, 0, 0), (-1, 0, 0, 0, 0),
                    (0, 0, 0, 0, 1 << 32), (0.0, 0, 0, 0, 0)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                index.lookup(bad)
        for bad in (True, -1, 20, 1.0, "0"):
            with self.assertRaises(ValueError):
                index.resolve(bad)
        self.assertEqual(index.snapshot(), before)

    def test_resolve_performs_tree_walk_with_logarithmic_read_bound(self):
        index = F8Index.build(KleinFieldRecipe(16, 16, 0, 4))

        class CountedRows(tuple):
            reads = 0

            def __getitem__(self, item):
                self.reads += 1
                return super().__getitem__(item)

        counted = CountedRows(index.rows)
        # Test instrumentation only: the public object is immutable.
        object.__setattr__(index, "_rows", counted)
        deepest = 0
        for node in range(256):
            counted.reads = 0
            row = index.resolve(node)
            self.assertEqual(tuple.__getitem__(counted, row)[4], node)
            # resolve's final identity check uses one additional row read.
            self.assertLessEqual(counted.reads, (256).bit_length() + 1)
            deepest = max(deepest, counted.reads)
        self.assertGreater(deepest, 3)
        with patch.object(F8Index, "lookup", return_value=None) as lookup:
            with self.assertRaises(ValueError):
                index.resolve(0)
            lookup.assert_called_once_with(index.key(0))

    def test_index_is_immutable_and_retains_no_scalar_or_packed_samples(self):
        index = F8Index.build(KleinFieldRecipe())
        self.assertEqual(set(F8Index.__slots__), {"_recipe", "_binding", "_records", "_rows"})
        for name in ("_recipe", "_binding", "_records", "_rows"):
            with self.assertRaises(FrozenInstanceError):
                setattr(index, name, None)
        self.assertIs(type(index.records), tuple)
        self.assertTrue(all(type(row) is tuple for row in index.records + index.rows))
        with self.assertRaises(TypeError):
            F8Index()

    def test_rebuild_changes_storage_and_keeps_old_version_and_identity_intact(self):
        index = F8Index.build(KleinFieldRecipe())
        before = index.snapshot()
        newer = index.rebuild(psi_sign=-1, phase_origin=240)
        self.assertEqual(newer.binding, IndexBinding(1, -1, 240))
        self.assertNotEqual(newer.rows, index.rows)
        self.assertEqual(newer.recipe, index.recipe)
        self.assertEqual(index.snapshot(), before)
        oracle = independent(index.recipe, newer.binding)
        self.assertEqual((newer.records, newer.rows), oracle[4:])
        unchanged = newer.rebuild()
        self.assertEqual(unchanged.binding.epoch, 2)
        self.assertEqual((unchanged.records, unchanged.rows), (newer.records, newer.rows))
        sign_only = index.rebuild(psi_sign=-1)
        phase_only = index.rebuild(phase_origin=240)
        self.assertNotEqual(sign_only.rows, index.rows)
        self.assertNotEqual(phase_only.rows, index.rows)
        self.assertEqual([record[3] for record in sign_only.records],
                         [record[3] for record in index.records])
        self.assertEqual([record[:3] for record in phase_only.records],
                         [record[:3] for record in index.records])
        with self.assertRaises(ValueError):
            index.rebuild(phase_origin=256)
        self.assertEqual(index.snapshot(), before)
        limit = F8Index.build(index.recipe, IndexBinding(MAX_EPOCH))
        with patch("solvefinite.f8.evaluate_field", side_effect=AssertionError("must reject first")):
            with self.assertRaises(ValueError):
                limit.rebuild()

    def test_build_rejects_invalid_context_and_uncertified_scalar_fields(self):
        recipe = KleinFieldRecipe()
        fields = independent(recipe)[3]
        for bad in (None, {}, recipe.to_dict()):
            with self.assertRaises(ValueError):
                F8Index.build(bad)
        for binding in (False, {}, IndexBinding().to_dict()):
            with self.assertRaises(ValueError):
                F8Index.build(recipe, binding)
        for bad in ((), list(fields[:-1]), tuple([True] + list(fields[1:])),
                    tuple([-1] + list(fields[1:]))):
            with self.assertRaises(ValueError):
                F8Index.build(recipe, fields=bad)


class F8CertificateTests(unittest.TestCase):
    def setUp(self):
        self.recipe = KleinFieldRecipe()
        self.binding = IndexBinding()
        oracle = independent(self.recipe)
        self.fields, self.records, self.rows = oracle[3:]

    def certify(self, records=None, rows=None, fields=None):
        return F8Index.certified(self.recipe, self.binding,
                                 self.records if records is None else records,
                                 self.rows if rows is None else rows,
                                 self.fields if fields is None else fields)

    def test_certificate_uses_equations_and_witnesses_without_cpu_compilers(self):
        with patch("solvefinite.f8._compile_records", side_effect=AssertionError("key compiler")), \
                patch("solvefinite.f8._compile_rows", side_effect=AssertionError("tree compiler")), \
                patch("solvefinite.f8.evaluate_field", side_effect=AssertionError("field evaluator")), \
                patch("solvefinite.psi.field_axes", side_effect=AssertionError("Psi compiler")), \
                patch("solvefinite.psi.axis_from_gradient", side_effect=AssertionError("Psi compiler")):
            index = self.certify([list(record) for record in self.records],
                                 [list(row) for row in self.rows])
        self.assertEqual(index.records, self.records)
        self.assertEqual(index.rows, self.rows)

    def test_each_record_component_is_checked_against_actual_recipe_and_field(self):
        for node, component in ((0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
                                (16, 0), (16, 1), (16, 5), (16, 6), (16, 7)):
            records = [list(record) for record in self.records]
            records[node][component] += 1
            with self.subTest(node=node, component=component), self.assertRaises(ValueError):
                self.certify(records=records)
        # Reversing both gradient and axis passes a local eigen-equation, but
        # disagrees with the actual SDF and therefore cannot be admitted.
        records = [list(record) for record in self.records]
        for component in (0, 1, 6, 7):
            records[16][component] = 4 - records[16][component]
        with self.assertRaises(ValueError):
            self.certify(records=records)

    def test_record_and_row_shapes_reject_non_u32_and_boolean_values(self):
        invalid = [None, (), self.records[:-1], (self.records[0][:-1],) + self.records[1:]]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                F8Index.certified(self.recipe, self.binding, value, self.rows, self.fields)
        for component in (True, -1, 1 << 32, 1.0, "0"):
            for target in ("records", "rows"):
                data = [list(row) for row in getattr(self, target)]
                data[0][0] = component
                with self.subTest(target=target, component=component), self.assertRaises(ValueError):
                    self.certify(**{target: data})

    def test_rejects_upper_median_tree_despite_valid_bst_and_complete_coverage(self):
        upper = independent_rows(self.records, upper_median=True)
        self.assertEqual(len({row[4] for row in upper}), len(self.rows))
        with self.assertRaisesRegex(ValueError, "lower-median"):
            self.certify(rows=upper)

    def test_rejects_wrong_preorder_even_when_links_preserve_the_same_tree(self):
        count = len(self.rows)
        permutation = list(range(count))
        permutation[1], permutation[2] = 2, 1
        remap = {old: new for new, old in enumerate(permutation)}
        rows = tuple((*self.rows[old][:5],
                      NULL if self.rows[old][5] == NULL else remap[self.rows[old][5]],
                      NULL if self.rows[old][6] == NULL else remap[self.rows[old][6]], 0)
                     for old in permutation)
        with self.assertRaisesRegex(ValueError, "preorder"):
            self.certify(rows=rows)

    def test_rejects_cycles_omissions_duplicates_wrong_links_keys_and_padding(self):
        variants = []
        for row, column, value in ((0, 5, 0), (0, 5, NULL), (0, 6, 1),
                                   (0, 5, 20), (0, 6, 255), (0, 7, 1),
                                   (0, 4, 20), (1, 4, 1), (0, 3, 250)):
            rows = [list(item) for item in self.rows]
            rows[row][column] = value
            variants.append(rows)
        for rows in variants:
            with self.subTest(root=rows[0]), self.assertRaises(ValueError):
                self.certify(rows=rows)

    def test_field_certificate_and_recipe_binding_are_required(self):
        bad_field = list(self.fields)
        bad_field[0] = -1
        with self.assertRaises(ValueError):
            self.certify(fields=bad_field)
        changed = replace(self.recipe, turns=(12, 53, 137))
        with self.assertRaises(ValueError):
            F8Index.certified(changed, self.binding, self.records, self.rows, self.fields)
        with self.assertRaises(ValueError):
            F8Index.certified(self.recipe, IndexBinding(0, -1, 0),
                              self.records, self.rows, self.fields)


class F8SnapshotTests(unittest.TestCase):
    def test_snapshot_roundtrip_recomputes_and_owns_immutable_witnesses(self):
        index = F8Index.build(KleinFieldRecipe(), IndexBinding(17, -1, 240))
        snapshot = json.loads(json.dumps(index.snapshot()))
        restored = F8Index.from_snapshot(snapshot)
        self.assertEqual(restored, index)
        snapshot["records"][0][0] = 99
        snapshot["recipe"]["baseline_id"] = "elsewhere"
        self.assertEqual(restored, index)

    def test_snapshot_rejects_structural_and_semantic_tampering(self):
        original = F8Index.build(KleinFieldRecipe()).snapshot()
        variants = [None, [], {}, dict(original, format="future"), dict(original, extra=0),
                    dict(original, records=tuple(original["records"])),
                    dict(original, rows=[tuple(row) for row in original["rows"]])]
        variants += [{key: value for key, value in original.items() if key != absent}
                     for absent in original]
        for section, key, value in (("binding", "phase_origin", 1),
                                     ("recipe", "turns", [12, 53, 137]),
                                     ("binding", "epoch", True)):
            item = deepcopy(original)
            item[section][key] = value
            variants.append(item)
        item = deepcopy(original)
        item["records"][0][0] += 1
        variants.append(item)
        item = deepcopy(original)
        item["rows"][0][5] = NULL
        variants.append(item)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                F8Index.from_snapshot(value)

    def test_full_recipe_and_binding_distinguish_version_context(self):
        first = F8Index.build(KleinFieldRecipe())
        renamed = F8Index.build(replace(first.recipe, baseline_id="separate-lineage"))
        later = first.rebuild()
        self.assertEqual(first.records, renamed.records)
        self.assertEqual(first.rows, later.rows)
        self.assertNotEqual(first.snapshot()["recipe"], renamed.snapshot()["recipe"])
        self.assertNotEqual(first.snapshot()["binding"], later.snapshot()["binding"])
        # Witness replay establishes consistency, not authenticity: a complete
        # valid lineage change is representable and retains its distinct name.
        self.assertEqual(F8Index.from_snapshot(renamed.snapshot()), renamed)


if __name__ == "__main__":
    unittest.main()
