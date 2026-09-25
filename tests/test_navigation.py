"""Independent graph-path checks for bounded deterministic route discovery."""

from dataclasses import FrozenInstanceError
from itertools import product
from types import MappingProxyType
import unittest

from solvefinite.navigation import (
    NoRoute, SearchBudgetExceeded, normalize_graph, shortest_route,
)


def simple_paths(graph, start, target, weights, max_hops):
    """Exhaustive oracle; positive weights make repeated nodes unnecessary."""
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


class RouteSearchTests(unittest.TestCase):
    def test_all_small_graphs_match_exhaustive_simple_path_oracle(self):
        nodes = ("", "0", "1")
        possible_edges = tuple((left, right) for left in nodes for right in nodes
                               if left != right)
        for selected in product((False, True), repeat=len(possible_edges)):
            graph = {node: [] for node in nodes}
            for enabled, (left, right) in zip(selected, possible_edges):
                if enabled:
                    graph[left].append(right)
            for values in ((1, 1, 1), (1, 7, 2), (3, 1, 9)):
                weights = dict(zip(nodes, values))
                for start, target, hops in product(nodes, nodes, (1, 2, 3)):
                    with self.subTest(graph=graph, weights=weights,
                                      start=start, target=target, hops=hops):
                        expected = simple_paths(graph, start, target, weights, hops)
                        if expected is None:
                            reachable = simple_paths(graph, start, target, weights, 3)
                            error = NoRoute if reachable is None else SearchBudgetExceeded
                            with self.assertRaises(error):
                                shortest_route(graph, start, target, weights.__getitem__,
                                               max_hops=hops)
                        else:
                            actual = shortest_route(graph, start, target,
                                                    weights.__getitem__, max_hops=hops)
                            self.assertEqual((actual.cost, actual.route), expected)

    def test_route_uses_entry_weights_and_only_declared_directed_edges(self):
        graph = {"": ["0", "1"], "0": ["00"], "1": ["00"], "00": []}
        costs = {"": 99, "0": 8, "1": 1, "00": 3}
        result = shortest_route(graph, "", "00", costs.__getitem__)
        self.assertEqual((result.route, result.cost), (("1", "00"), 4))
        previous = ""
        for node in result.route:
            self.assertIn(node, graph[previous])
            previous = node
        with self.assertRaises(NoRoute):
            shortest_route(graph, "00", "", costs.__getitem__)
        costs["0"] = 1
        costs["1"] = 8
        self.assertEqual(shortest_route(graph, "", "00", costs.__getitem__).route,
                         ("0", "00"))

    def test_lexicographic_ties_and_expansions_ignore_input_order(self):
        graph = {"": ["1", "0"], "0": ["01", "00"], "1": ["11"],
                 "00": ["11"], "01": ["11"], "11": []}
        weights = {"": 1, "0": 1, "1": 2, "00": 1, "01": 1, "11": 1}
        reversed_graph = {node: list(reversed(neighbors))
                          for node, neighbors in reversed(list(graph.items()))}
        result = shortest_route(graph, "", "11", weights.__getitem__)
        self.assertEqual((result.route, result.cost), (("0", "00", "11"), 3))
        self.assertEqual(result, shortest_route(reversed_graph, "", "11",
                                                weights.__getitem__))

    def test_more_expensive_short_prefix_survives_hop_constraint(self):
        # The cheap route to 01 takes three hops and cannot then reach 11 in
        # the four-hop budget. The costlier two-hop prefix must remain alive.
        graph = {"": ["0", "1"], "0": ["00"], "00": ["01"], "1": ["01"],
                 "01": ["10"], "10": ["11"], "11": []}
        weights = {node: 1 for node in graph}
        weights["1"] = 10
        limited = shortest_route(graph, "", "11", weights.__getitem__, max_hops=4)
        self.assertEqual((limited.route, limited.cost), (("1", "01", "10", "11"), 13))
        unlimited = shortest_route(graph, "", "11", weights.__getitem__, max_hops=5)
        self.assertEqual((unlimited.route, unlimited.cost),
                         (("0", "00", "01", "10", "11"), 5))

    def test_cycles_and_self_edges_do_not_change_cheapest_route(self):
        graph = {"": ["", "0"], "0": ["", "0", "1"], "1": ["0", "1"]}
        result = shortest_route(graph, "", "1", lambda node: 1)
        self.assertEqual((result.route, result.cost), (("0", "1"), 2))

    def test_short_prefix_can_take_a_cheaper_long_tail_after_shared_junction(self):
        # Both prefixes can reach 01 within the hop bound. The cheap prefix
        # leaves room only for the costly tail; retaining the other prefix
        # permits the globally cheaper admissible route through 000 and 001.
        graph = {"": ["0", "1"], "0": ["00"], "00": ["01"], "1": ["01"],
                 "01": ["10", "000"], "10": ["11"], "000": ["001"],
                 "001": ["11"], "11": []}
        weights = {node: 1 for node in graph}
        weights["1"] = 10
        weights["10"] = 100
        result = shortest_route(graph, "", "11", weights.__getitem__, max_hops=5)
        self.assertEqual((result.route, result.cost),
                         (("1", "01", "000", "001", "11"), 14))
        self.assertEqual((result.cost, result.route),
                         simple_paths(graph, "", "11", weights, 5))

    def test_route_can_use_the_full_32_hop_budget(self):
        nodes = ["0" * depth for depth in range(33)]
        graph = {node: ([nodes[index + 1]] if index < 32 else [])
                 for index, node in enumerate(nodes)}
        result = shortest_route(graph, "", nodes[-1], lambda node: 1)
        self.assertEqual((result.route, result.cost, result.expansions),
                         (tuple(nodes[1:]), 32, 32))
        with self.assertRaises(SearchBudgetExceeded):
            shortest_route(graph, "", nodes[-1], lambda node: 1, max_hops=31)

    def test_unreachable_cycles_are_no_route_even_with_tiny_budgets(self):
        graph = {"": ["0"], "0": ["", "0"], "1": ["1"]}
        with self.assertRaises(NoRoute):
            shortest_route(graph, "", "1", lambda node: 1,
                           max_hops=1, max_expansions=1)

    def test_hop_exhaustion_is_distinct_from_unreachability(self):
        graph = {"": ["0"], "0": ["1"], "1": []}
        with self.assertRaisesRegex(SearchBudgetExceeded, "max_hops"):
            shortest_route(graph, "", "1", lambda node: 1, max_hops=1)
        self.assertEqual(shortest_route(graph, "", "1", lambda node: 1,
                                        max_hops=2).route, ("0", "1"))

    def test_expansion_exhaustion_never_returns_an_uncertified_candidate(self):
        graph = {"": ["0", "1"], "0": ["1"], "1": []}
        weights = {"": 1, "0": 1, "1": 10}
        with self.assertRaisesRegex(SearchBudgetExceeded, "max_expansions"):
            shortest_route(graph, "", "1", weights.__getitem__, max_expansions=1)
        result = shortest_route(graph, "", "1", weights.__getitem__, max_expansions=2)
        self.assertEqual((result.route, result.cost, result.expansions), (("1",), 10, 2))
        # Once the target itself is cheapest, returning it costs no expansion.
        direct = shortest_route({"": ["1"], "1": []}, "", "1", lambda node: 1,
                                max_expansions=1)
        self.assertEqual(direct.expansions, 1)

    def test_same_node_and_immutable_result(self):
        result = shortest_route({"": []}, "", "", lambda node: 2)
        self.assertEqual((result.route, result.cost, result.expansions), ((), 0, 0))
        with self.assertRaises(FrozenInstanceError):
            result.cost = 5

    def test_costs_are_cached_once_per_node_in_sorted_order(self):
        graph = {"1": [], "00": ["1"], "": ["0", "00"], "0": ["1"], "01": []}
        called = []

        def cost(node):
            called.append(node)
            return 1

        shortest_route(graph, "", "1", cost)
        self.assertEqual(called, ["", "0", "00", "01", "1"])

    def test_graph_is_copied_before_cost_callback_and_accepts_mapping(self):
        graph = {"": ["0"], "0": ["1"], "1": []}

        def cost(node):
            graph[""][:] = ["1"]
            graph["0"].clear()
            return 1

        result = shortest_route(MappingProxyType(graph), "", "1", cost)
        self.assertEqual(result.route, ("0", "1"))


class RouteValidationTests(unittest.TestCase):
    def test_normalize_graph_sorts_and_copies_without_requiring_reachability(self):
        graph = {"1": ["1"], "00": [], "": ["1", "0"], "0": ["00", ""]}
        normalized = normalize_graph(graph)
        self.assertEqual(list(normalized), ["", "0", "00", "1"])
        self.assertEqual(normalized[""], ("0", "1"))
        self.assertEqual(normalized["0"], ("", "00"))
        graph[""].clear()
        self.assertEqual(normalized[""], ("0", "1"))

    def test_invalid_graphs(self):
        invalid = [None, [], {}, {"": "0"}, {"": {"0"}}, {"": ["0"]},
                   {"": ["0", "0"], "0": []}, {"": [False]}, {"": [[]]},
                   {"": [], 1: []}, {"": [], "2": []}, {"": [], "0" * 33: []},
                   {"": [], "\n": []}, {"": [], "0 1": []}]
        invalid.append({format(index, "09b"): [] for index in range(257)})
        for graph in invalid:
            with self.subTest(graph=graph), self.assertRaises(ValueError):
                shortest_route(graph, "", "", lambda node: 1)

    def test_invalid_start_and_target(self):
        for value in (None, False, 1, [], "0", "2", "0" * 33):
            for start, target in ((value, ""), ("", value)):
                with self.subTest(start=start, target=target), self.assertRaises(ValueError):
                    shortest_route({"": []}, start, target, lambda node: 1)

    def test_invalid_weights_are_rejected_even_on_unused_nodes_and_same_target(self):
        for value in (0, -1, False, True, 1.0, "1", None, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                shortest_route({"": [], "1": []}, "", "",
                               lambda node: 1 if node == "" else value)
        with self.assertRaises(ValueError):
            shortest_route({"": []}, "", "", 1)

    def test_invalid_budgets(self):
        for name, high in (("max_hops", 32), ("max_expansions", 65536)):
            for value in (0, -1, high + 1, False, True, 1.0, "1", None):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    shortest_route({"": []}, "", "", lambda node: 1, **{name: value})

    def test_graph_and_argument_validation_precede_cost_callback(self):
        called = []
        with self.assertRaises(ValueError):
            shortest_route({"": ["0"]}, "", "", lambda node: called.append(node))
        self.assertEqual(called, [])

    def test_limits_are_inclusive(self):
        nodes = [format(index, "08b") for index in range(255)] + ["1" * 32]
        graph = {node: [] for node in nodes}
        result = shortest_route(graph, nodes[0], nodes[0], lambda node: 1,
                                max_hops=32, max_expansions=65536)
        self.assertEqual(result.route, ())


if __name__ == "__main__":
    unittest.main()
