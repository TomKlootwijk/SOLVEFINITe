"""Incremental route search preserves work and certifies the same optimum."""

from dataclasses import FrozenInstanceError, replace
from itertools import product
import random
import unittest

from solvefinite.navigation import (
    NoRoute, RouteSearch, SearchBudgetExceeded, SearchResult, shortest_route,
)


def oracle(graph, start, target, weights, max_hops):
    candidates = []

    def visit(node, route, seen, total):
        if node == target:
            candidates.append((total, route))
        elif len(route) < max_hops:
            for neighbor in graph[node]:
                if neighbor not in seen:
                    visit(neighbor, route + (neighbor,), seen | {neighbor},
                          total + weights[neighbor])

    visit(start, (), {start}, 0)
    return min(candidates) if candidates else None


class IncrementalRouteTests(unittest.TestCase):
    def finish(self, cursor, quantum):
        for _ in range(8449):  # At most 256 * 33 distinct bounded-hop states.
            before = cursor.expansions
            updated, result = cursor.advance(quantum)
            self.assertIsNot(updated, cursor)
            self.assertEqual(cursor.expansions, before)
            self.assertLessEqual(updated.expansions - before, quantum)
            if result is not None:
                self.assertEqual(updated.pending_states, 0)
                self.assertEqual(result.expansions, updated.expansions)
                return updated, result
            self.assertGreater(updated.expansions, before)
            self.assertGreater(updated.pending_states, 0)
            cursor = updated
        self.fail("finite route search failed to terminate")

    def test_quantums_match_exhaustive_small_graph_oracle_and_one_shot(self):
        nodes = ("", "0", "1")
        edges = tuple((left, right) for left in nodes for right in nodes if left != right)
        for selected in product((False, True), repeat=len(edges)):
            graph = {node: [] for node in nodes}
            for enabled, (left, right) in zip(selected, edges):
                if enabled:
                    graph[left].append(right)
            for costs in ((1, 1, 1), (3, 8, 2)):
                weights = dict(zip(nodes, costs))
                for start, target, hops in product(nodes, nodes, (1, 2, 3)):
                    with self.subTest(graph=graph, costs=costs, start=start, target=target, hops=hops):
                        expected = oracle(graph, start, target, weights, hops)
                        if expected is None:
                            reachable = oracle(graph, start, target, weights, 3)
                            error = NoRoute if reachable is None else SearchBudgetExceeded
                            with self.assertRaises(error):
                                RouteSearch.start(graph, start, target, weights.__getitem__, hops)
                            continue
                        baseline = shortest_route(graph, start, target, weights.__getitem__, hops)
                        initial = RouteSearch.start(graph, start, target, weights.__getitem__, hops)
                        for quantum in (1, 2, 8):
                            _, result = self.finish(initial, quantum)
                            self.assertEqual((result.cost, result.route), expected)
                            self.assertEqual(result, baseline)

    def test_larger_graphs_with_cycles_match_independent_exhaustive_oracle(self):
        rng = random.Random(49286)
        nodes = ("", "0", "1", "00", "01", "11")
        for case in range(100):
            graph = {node: [neighbor for neighbor in nodes if rng.random() < .4] for node in nodes}
            weights = {node: rng.randint(1, 12) for node in nodes}
            hops = rng.randint(1, 6)
            expected = oracle(graph, "", "11", weights, hops)
            with self.subTest(case=case, hops=hops):
                if expected is None:
                    error = NoRoute if oracle(graph, "", "11", weights, 6) is None else SearchBudgetExceeded
                    with self.assertRaises(error):
                        RouteSearch.start(graph, "", "11", weights.__getitem__, hops)
                    continue
                baseline = shortest_route(graph, "", "11", weights.__getitem__, hops)
                initial = RouteSearch.start(graph, "", "11", weights.__getitem__, hops)
                for quantum in (1, 2, 3, 7, 65536):
                    _, result = self.finish(initial, quantum)
                    self.assertEqual((result.cost, result.route), expected)
                    self.assertEqual(result, baseline)

    def test_exact_expansion_boundary_returns_target_without_an_extra_call(self):
        graph = {"": ["0"], "0": ["1"], "1": []}
        initial = RouteSearch.start(graph, "", "1", lambda node: 1)
        self.assertEqual((initial.expansions, initial.pending_states), (0, 1))
        first, result = initial.advance(1)
        self.assertIsNone(result)
        self.assertEqual((first.expansions, first.pending_states), (1, 1))
        second, result = first.advance(1)
        self.assertEqual(result, SearchResult(("0", "1"), 2, 2))
        self.assertEqual((second.expansions, second.pending_states), (2, 0))
        self.assertEqual((initial.expansions, initial.pending_states), (0, 1))
        self.assertEqual((first.expansions, first.pending_states), (1, 1))

    def test_deferred_candidate_is_retained_and_branching_cursors_agree(self):
        graph = {"": ["0", "1"], "0": ["00"], "1": ["00"], "00": ["11"], "11": []}
        initial = RouteSearch.start(graph, "", "11", lambda node: 1)
        first, result = initial.advance(1)
        self.assertIsNone(result)
        self.assertEqual(first.pending_states, 2)
        retained_frontier = first._frontier
        _, slow = self.finish(first, 1)
        _, fast = self.finish(first, 20)
        self.assertEqual(slow, fast)
        self.assertEqual(first._frontier, retained_frontier)
        self.assertEqual(first.expansions, 1)

    def test_initial_inputs_are_copied_and_callback_never_reenters(self):
        graph = {"1": [], "": ["0"], "0": ["1"]}
        weights = {"": 5, "0": 2, "1": 3}
        called = []
        active = True

        def cost(node):
            if not active:
                raise AssertionError("cost callback used after search start")
            called.append(node)
            return weights[node]

        initial = RouteSearch.start(graph, "", "1", cost)
        self.assertEqual(called, ["", "0", "1"])
        active = False
        graph[""][:] = ["1"]
        graph["0"].clear()
        weights["1"] = 100
        _, result = self.finish(initial, 1)
        self.assertEqual(result, SearchResult(("0", "1"), 5, 2))
        self.assertEqual(called, ["", "0", "1"])

    def test_cursor_and_cached_structures_are_immutable(self):
        cursor = RouteSearch.start({"": ["1"], "1": []}, "", "1", lambda node: 1)
        with self.assertRaises(FrozenInstanceError):
            cursor.expansions = 7
        with self.assertRaises(TypeError):
            cursor._graph[""] = ()
        with self.assertRaises(TypeError):
            cursor._weights["1"] = 9
        with self.assertRaises(TypeError):
            cursor._remaining_hops[""] = 9
        self.assertIs(type(cursor._best), tuple)
        self.assertIs(type(cursor._frontier), tuple)

    def test_invalid_quantum_does_not_consume_cursor_work(self):
        initial = RouteSearch.start({"": ["1"], "1": []}, "", "1", lambda node: 1)
        for value in (None, 0, -1, 65537, True, False, "1", 1.0, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                initial.advance(value)
            self.assertEqual((initial.expansions, initial.pending_states), (0, 1))
        completed, result = initial.advance(1)
        self.assertEqual(result, SearchResult(("1",), 1, 1))
        with self.assertRaises(ValueError):
            completed.advance(0)
        self.assertEqual(completed.expansions, 1)

    def test_completed_cursor_is_idempotent_and_start_at_target_costs_zero(self):
        called = []
        initial = RouteSearch.start({"": []}, "", "", lambda node: called.append(node) or 9)
        self.assertEqual((initial.expansions, initial.pending_states), (0, 0))
        first, result = initial.advance(1)
        self.assertEqual(result, SearchResult((), 0, 0))
        second, repeated = first.advance(65536)
        self.assertEqual(second, first)
        self.assertEqual(repeated, result)
        self.assertEqual(called, [""])

    def test_hop_and_unreachable_preflights_match_one_shot_errors(self):
        graph = {"": ["0"], "0": ["", "1"], "1": []}
        with self.assertRaises(SearchBudgetExceeded) as failure:
            RouteSearch.start(graph, "", "1", lambda node: 1, max_hops=1)
        self.assertEqual(str(failure.exception), "target cannot be reached within max_hops")
        self.assertEqual(failure.exception.expansions, 0)
        graph["0"] = [""]
        with self.assertRaisesRegex(NoRoute, "no directed route"):
            RouteSearch.start(graph, "", "1", lambda node: 1)

    def test_short_and_long_prefixes_survive_across_quantums(self):
        graph = {"": ["0", "1"], "0": ["00"], "00": ["01"], "1": ["01"],
                 "01": ["10", "000"], "10": ["11"], "000": ["001"],
                 "001": ["11"], "11": []}
        weights = {node: 1 for node in graph}
        weights["1"] = 10
        weights["10"] = 100
        cursor = RouteSearch.start(graph, "", "11", weights.__getitem__, max_hops=5)
        _, result = self.finish(cursor, 1)
        self.assertEqual((result.route, result.cost), (("1", "01", "000", "001", "11"), 14))

    def test_input_order_does_not_change_frontier_progress_or_tie_result(self):
        graph = {"": ["1", "0"], "0": ["00"], "1": ["11"], "00": ["11"], "11": []}
        reverse = {node: list(reversed(adjacent)) for node, adjacent in reversed(list(graph.items()))}
        weights = {"": 1, "0": 1, "1": 2, "00": 1, "11": 1}
        left = RouteSearch.start(graph, "", "11", weights.__getitem__)
        right = RouteSearch.start(reverse, "", "11", weights.__getitem__)
        while True:
            left, actual = left.advance(1)
            right, expected = right.advance(1)
            self.assertEqual(left, right)
            self.assertEqual(actual, expected)
            if actual is not None:
                self.assertEqual(actual.route, ("0", "00", "11"))
                break

    def test_stale_entries_do_not_consume_the_quantum(self):
        # Entry-only weights normally settle labels on their first discovery.
        # Supply an obsolete heap label directly to check the cursor's stale
        # entry invariant without relying on an accidental graph ordering.
        initial = RouteSearch.start({"": ["1"], "1": []}, "", "1", lambda node: 1)
        stale = replace(initial, _frontier=((-1, (), "", 0), *initial._frontier))
        self.assertEqual(stale.pending_states, 1)
        updated, result = stale.advance(1)
        self.assertEqual(result, SearchResult(("1",), 1, 1))
        self.assertEqual(updated.pending_states, 0)
        self.assertEqual(len(stale._frontier), 2)

    def test_stale_entries_are_drained_after_the_expansion_boundary(self):
        graph = {"": ["0", "1"], "0": ["1"], "1": []}
        weights = {"": 1, "0": 1, "1": 10}
        cursor, _ = RouteSearch.start(graph, "", "1", weights.__getitem__).advance(1)
        stale = replace(cursor, _frontier=tuple(sorted((*cursor._frontier, (2, (), "", 0)))))
        self.assertEqual(stale.pending_states, 2)
        _, result = stale.advance(1)
        # The zero-cost bookkeeping after expanding 0 discards the obsolete
        # root label and then certifies the original direct target route.
        self.assertEqual(result, SearchResult(("1",), 10, 2))

    def test_full_32_hop_route_finishes_one_expansion_per_call(self):
        nodes = ["0" * index for index in range(33)]
        graph = {node: ([nodes[index + 1]] if index < 32 else [])
                 for index, node in enumerate(nodes)}
        _, result = self.finish(RouteSearch.start(graph, "", nodes[-1], lambda node: 1), 1)
        self.assertEqual(result, SearchResult(tuple(nodes[1:]), 32, 32))


class IncrementalValidationTests(unittest.TestCase):
    def test_start_validation_matches_one_shot_for_malformed_inputs(self):
        valid = {"edges": {"": ["0"], "0": []}, "start": "", "target": "0", "cost": lambda node: 1}
        examples = [
            {"edges": None}, {"edges": {}}, {"edges": {"": ["0", "0"], "0": []}},
            {"edges": {"": ["0"]}}, {"edges": {"": "0", "0": []}},
            {"edges": {"": [True]}}, {"edges": {"": [], "2": []}},
            {"start": []}, {"start": "1"}, {"target": False}, {"target": "1"},
            {"cost": None}, {"cost": lambda node: True}, {"cost": lambda node: 0},
            {"cost": lambda node: -1}, {"cost": lambda node: 1.0},
            {"max_hops": True}, {"max_hops": 0}, {"max_hops": 33},
        ]
        for change in examples:
            arguments = {**valid, **change}
            with self.subTest(change=change):
                with self.assertRaises(ValueError) as reference:
                    shortest_route(**arguments)
                with self.assertRaises(ValueError) as actual:
                    RouteSearch.start(**arguments)
                self.assertEqual(type(actual.exception), type(reference.exception))
                self.assertEqual(str(actual.exception), str(reference.exception))

    def test_invalid_unused_cost_rejected_even_when_start_is_target(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            RouteSearch.start({"": [], "0": []}, "", "", lambda node: 1 if node == "" else False)

    def test_graph_validation_precedes_callback(self):
        called = []
        with self.assertRaises(ValueError):
            RouteSearch.start({"": ["0"]}, "", "", lambda node: called.append(node))
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
