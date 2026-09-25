"""Named-node planning extends hop reach without relaxing legacy contracts."""

import unittest

from solvefinite.klein import KleinDomain
from solvefinite.navigation import RouteSearch, SearchBudgetExceeded, normalize_graph


class RelationalRouteTests(unittest.TestCase):
    def test_named_route_ties_and_costs_survive_incremental_search(self):
        graph = {"start": ("beta", "alpha"), "alpha": ("target",),
                 "beta": ("target",), "target": ()}
        for quantum in (1, 100):
            cursor = RouteSearch.start(graph, "start", "target", lambda _: 1,
                                       max_hops=255, node_profile="relational-node-v1")
            result = None
            while result is None:
                cursor, result = cursor.advance(quantum)
            self.assertEqual((result.route, result.cost), (("alpha", "target"), 2))
        for cost, route in ((5, ("beta", "target")), (1, ("alpha", "target"))):
            cursor = RouteSearch.start(graph, "start", "target",
                                       lambda name: cost if name == "alpha" else 1,
                                       max_hops=255, node_profile="relational-node-v1")
            self.assertEqual(cursor.advance(100)[1].route, route)

    def test_supported_klein_world_has_a_route_beyond_legacy_hop_bound(self):
        domain = KleinDomain(85, 3)
        graph = {name: [] for name in domain.nodes}
        for u, v, _ in domain.edges:
            graph[domain.nodes[u]].append(domain.nodes[v])
            graph[domain.nodes[v]].append(domain.nodes[u])
        with self.assertRaises(SearchBudgetExceeded):
            RouteSearch.start(graph, "k:0:0", "k:42:0", lambda _: 1,
                              max_hops=32, node_profile="relational-node-v1")
        cursor = RouteSearch.start(graph, "k:0:0", "k:42:0", lambda _: 1,
                                   node_profile="relational-node-v1")
        result = None
        while result is None:
            cursor, result = cursor.advance(65536)
        self.assertEqual(result.cost, 42)
        self.assertEqual(result.route, tuple(f"k:{u}:0" for u in range(1, 43)))

    def test_relational_mode_retains_strict_names_profiles_and_hop_limits(self):
        for name in ("", " ", True, 4, None, "x" * 129):
            with self.subTest(name=name), self.assertRaises(ValueError):
                normalize_graph({name: ()}, node_profile="relational-node-v1")
        for profile in (None, True, "future", [], 1):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                normalize_graph({"a": ()}, node_profile=profile)
        for hops in (0, -1, True, 1.0, 256, None):
            with self.subTest(hops=hops), self.assertRaises(ValueError):
                RouteSearch.start({"a": ()}, "a", "a", lambda _: 1,
                                  max_hops=hops, node_profile="relational-node-v1")

    def test_default_binary_validation_and_hop_bound_remain_unchanged(self):
        with self.assertRaises(ValueError):
            normalize_graph({"k:0:0": ()})
        with self.assertRaises(ValueError):
            RouteSearch.start({"": ()}, "", "", lambda _: 1, max_hops=33)
        with self.assertRaises(ValueError):
            RouteSearch.start({"named": ()}, "named", "named", lambda _: 1)


if __name__ == "__main__":
    unittest.main()
