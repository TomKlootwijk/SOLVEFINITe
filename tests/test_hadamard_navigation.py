"""Phase-state search checked against independent quotient/layer arithmetic."""

from collections import deque
from dataclasses import FrozenInstanceError, replace
import json
from math import gcd
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from solvefinite.field_world import KleinFieldRecipe
from solvefinite.hadamard import HadamardBinding, RoutingModel
from solvefinite.hadamard_navigation import HadamardRouteSearch
from solvefinite.navigation import SearchBudgetExceeded, SearchResult


REFERENCE = json.loads((Path(__file__).parents[1] / "docs/evidence/hadamard-v1/formal-reference.json")
                       .read_text(encoding="utf-8"))
DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class IndependentWorld:
    """No runtime field, topology, penalty or search methods in this oracle."""

    def __init__(self, recipe, gains):
        self.width, self.height = recipe.width, recipe.height
        self.turns, self.gains = recipe.turns, gains
        self.nodes = tuple(f"k:{u}:{v}" for u in range(self.width) for v in range(self.height))
        self.directions = tuple(tuple(self.step(i, direction) for direction in DIRECTIONS)
                                for i in range(len(self.nodes)))
        self.neighbors = tuple(tuple(sorted(row)) for row in self.directions)
        radii = self.distances((recipe.center,))
        sides = tuple((distance > recipe.radius) - (distance < recipe.radius) for distance in radii)
        boundary = self.distances(tuple(i for i, side in enumerate(sides) if side == 0))
        self.fields = tuple(side * distance for side, distance in zip(sides, boundary))
        self.gradients = tuple((self.fields[up] - self.fields[um],
                                self.fields[vp] - self.fields[vm])
                               for up, um, vp, vm in self.directions)

    def step(self, node, direction):
        u, v = divmod(node, self.height)
        du, dv = direction
        winding, u = divmod(u + du, self.width)
        v = (-v - dv if winding % 2 else v + dv) % self.height
        return u * self.height + v

    def distances(self, seeds):
        result = [None] * len(self.nodes)
        pending = deque(seeds)
        for node in seeds:
            result[node] = 0
        while pending:
            node = pending.popleft()
            for neighbor in self.neighbors[node]:
                if result[neighbor] is None:
                    result[neighbor] = result[node] + 1
                    pending.append(neighbor)
        return tuple(result)

    def next_phase(self, node, phase):
        signed = self.fields[node]
        column = 0 if signed < 0 else 1 if signed == 0 else 2
        return (phase + self.turns[column]) % 256

    def penalty(self, source, phase, destination):
        gu, gv = self.gradients[source]
        divisor = gcd(abs(gu), abs(gv))
        pu, pv = (gu // divisor, gv // divisor) if divisor else (1, 0)
        au, av = self.gains[phase // 64]
        qu, qv = au * (1 + pu * pu) * gu, av * (1 + pv * pv) * gv
        eu, ev = DIRECTIONS[self.directions[source].index(destination)]
        return max(abs(qu), abs(qv)) - qu * eu - qv * ev

    def route(self, start, target, phase, weights, max_hops):
        """Layered dynamic programming; no heap, Dijkstra or runtime model."""
        current = {(start, phase): (0, ())}
        answer = None
        for hops in range(max_hops + 1):
            following = {}
            for (source, intrinsic), (total, path) in current.items():
                if source == target:
                    candidate = total, path
                    if answer is None or candidate < answer:
                        answer = candidate
                    continue  # First arrival terminates a candidate route.
                if hops == max_hops:
                    continue
                for destination in self.neighbors[source]:
                    candidate = (total + weights[destination]
                                 + self.penalty(source, intrinsic, destination),
                                 path + (self.nodes[destination],))
                    # Positive costs cannot recover after exceeding a known goal.
                    if answer is not None and candidate[0] > answer[0]:
                        continue
                    state = destination, self.next_phase(source, intrinsic)
                    if state not in following or candidate < following[state]:
                        following[state] = candidate
            current = following
        return answer


class HadamardNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recipe = KleinFieldRecipe()
        cls.binding = HadamardBinding()
        cls.model = RoutingModel.build(cls.recipe, cls.binding)
        cls.oracle = IndependentWorld(cls.recipe, cls.binding.gains)
        cls.weights = tuple(1 + abs(value) for value in cls.oracle.fields)

    def cursor(self, start=0, target=17, phase=250, hops=255, model=None, weights=None):
        model = self.model if model is None else model
        nodes = model.recipe.domain().nodes
        weights = self.weights if weights is None else weights
        return HadamardRouteSearch.start(model, nodes[start], nodes[target],
                                        lambda path: weights[model.recipe.index(path)],
                                        max_hops=hops, initial_phase=phase)

    def finish(self, cursor, quantum):
        bound = len(cursor._nodes) * 256 * (cursor._max_hops + 1)
        while cursor.expansions <= bound:
            previous = cursor
            cursor, result = cursor.advance(quantum)
            self.assertIsNot(cursor, previous)
            self.assertLessEqual(cursor.expansions - previous.expansions, quantum)
            if result is not None:
                self.assertEqual(cursor.pending_states, 0)
                self.assertEqual(result.expansions, cursor.expansions)
                return cursor, result
            self.assertGreater(cursor.expansions, previous.expansions)
            self.assertGreater(cursor.pending_states, 0)
        self.fail("finite phase-state search failed to terminate")

    def test_default_mission_matches_literal_routes_costs_and_expansions(self):
        start, phase = 0, 250
        hazards = {}
        for event in REFERENCE["mission"]["events"]:
            for path, hazard in event["input"].items():
                hazards[self.recipe.index(path)] = hazard
            if event["kind"] != "MOVE":
                break
            weights = tuple(value + hazards.get(node, 0) for node, value in enumerate(self.weights))
            initial = self.cursor(start, 17, phase, weights=weights)
            expected = SearchResult(tuple(event["paths"]), event["cost"], event["expansions"])
            for quantum in (1, 2, 7, 65536):
                with self.subTest(cycle=event["cycle"], quantum=quantum):
                    _, result = self.finish(initial, quantum)
                    self.assertEqual(result, expected)
            phase = self.oracle.next_phase(start, phase)
            start = event["node"]
        self.assertEqual([event["expansions"] for event in REFERENCE["mission"]["events"]
                          if event["kind"] == "MOVE"], [23, 6, 2])

    def test_phase_collapse_counterexample_keeps_distinct_arrivals(self):
        example = REFERENCE["phase_state_counterexample"]
        initial = self.cursor(example["start"], example["target"],
                              example["initial_intrinsic_phase"], example["max_hops"])
        _, result = self.finish(initial, 1)
        correct, incorrect = example["correct"], example["incorrect"]
        self.assertEqual(result, SearchResult(tuple(correct["paths"]), 10, 19))
        self.assertNotEqual((result.cost, result.route), (incorrect["cost"], tuple(incorrect["paths"])))
        oracle = self.oracle.route(0, 10, 128, self.weights, 12)
        self.assertEqual((result.cost, result.route), oracle)
        # The useful detour and the short arrival at node5 remain separate.
        phase_labels = set()
        cursor = initial
        while True:
            for (node, phase, hops), _ in cursor._best:
                if node == 5:
                    phase_labels.add((phase, hops))
            cursor, answer = cursor.advance(1)
            if answer is not None:
                break
        self.assertGreater(len({phase for phase, _ in phase_labels}), 1)

    def test_revisiting_a_node_at_a_new_phase_can_beat_every_simple_route(self):
        binding = HadamardBinding(gains=((4, 4), (-4, 4), (-4, -4), (4, -4)))
        model = RoutingModel.build(self.recipe, binding)
        oracle = IndependentWorld(self.recipe, binding.gains)
        initial = self.cursor(start=1, target=13, phase=26, hops=12, model=model)
        _, result = self.finish(initial, 1)
        expected_nodes = (2, 3, 2, 1, 0, 5, 10, 14, 13)
        self.assertEqual(result, SearchResult(tuple(oracle.nodes[node] for node in expected_nodes), 16, 37))
        self.assertEqual((result.cost, result.route), oracle.route(1, 13, 26, self.weights, 12))
        source, phase = 1, 26
        phases_at_two = []
        for destination in expected_nodes:
            phase = oracle.next_phase(source, phase)
            source = destination
            if source == 2:
                phases_at_two.append(phase)
        self.assertEqual(phases_at_two, [37, 143])

        def simple_route_at_most(node, phase, seen, total):
            if node == 13:
                return True
            if len(seen) == 13:
                return False
            for destination in oracle.neighbors[node]:
                if destination in seen:
                    continue
                value = total + self.weights[destination] + oracle.penalty(node, phase, destination)
                if value <= 16 and simple_route_at_most(destination, oracle.next_phase(node, phase),
                                                        seen | {destination}, value):
                    return True
            return False

        self.assertFalse(simple_route_at_most(1, 26, {1}, 0))

    def test_varied_domains_gains_phases_and_hop_bounds_match_layered_dp(self):
        rng = random.Random(60327)
        cases = [
            (KleinFieldRecipe(3, 3, 0, 1), ((1, 1), (-1, 1), (-1, -1), (1, -1))),
            (KleinFieldRecipe(4, 5, 7, 2), ((0, 0),) * 4),
            (KleinFieldRecipe(3, 7, 8, 2, turns=(0, 64, 255)),
             ((4, -4), (-3, 2), (0, 4), (1, -2))),
            (KleinFieldRecipe(5, 4, 13, 2, turns=(19, 128, 7)),
             ((-2, 3), (4, 1), (-4, -3), (2, 0))),
        ]
        for recipe, gains in cases:
            model = RoutingModel.build(recipe, HadamardBinding(gains=gains))
            oracle = IndependentWorld(recipe, gains)
            for trial in range(12):
                start, target = rng.randrange(len(oracle.nodes)), rng.randrange(len(oracle.nodes))
                phase = (0, 63, 64, 127, 128, 191, 192, 250)[trial % 8]
                hops = rng.randrange(1, 8)
                weights = tuple(1 + abs(field) + rng.randrange(4) for field in oracle.fields)
                expected = oracle.route(start, target, phase, weights, hops)
                with self.subTest(recipe=recipe, trial=trial, phase=phase, hops=hops):
                    if expected is None:
                        with self.assertRaises(SearchBudgetExceeded) as failure:
                            self.cursor(start, target, phase, hops, model, weights)
                        self.assertEqual(failure.exception.expansions, 0)
                        continue
                    initial = self.cursor(start, target, phase, hops, model, weights)
                    baseline = None
                    for quantum in (1, 3, 65536):
                        _, result = self.finish(initial, quantum)
                        self.assertEqual((result.cost, result.route), expected)
                        if baseline is not None:
                            self.assertEqual(result, baseline)
                        baseline = result

    def test_target_pop_is_free_at_exact_quantum_boundary(self):
        initial = self.cursor(target=1)
        completed, result = initial.advance(1)
        self.assertEqual(result, SearchResult(("k:0:1",), 2, 1))
        self.assertEqual((completed.expansions, completed.pending_states), (1, 0))
        self.assertEqual((initial.expansions, initial.pending_states), (0, 1))

    def test_stale_entries_are_free_before_and_after_quantum(self):
        initial = self.cursor(target=1)
        initial = replace(initial, _frontier=((-1, (), 0, 250, 0),
                                             (1, (), 0, 250, 0), *initial._frontier))
        # heapify without calling the implementation's heap operations
        initial = replace(initial, _frontier=tuple(sorted(initial._frontier)))
        self.assertEqual(initial.pending_states, 1)
        completed, result = initial.advance(1)
        self.assertEqual(result, SearchResult(("k:0:1",), 2, 1))
        self.assertEqual(completed.pending_states, 0)
        self.assertEqual(len(initial._frontier), 3)

    def test_branching_cursors_retain_work_and_cannot_mutate_inputs(self):
        initial = self.cursor()
        deferred, result = initial.advance(1)
        self.assertIsNone(result)
        before = deferred._frontier, deferred._best, deferred.expansions
        _, slow = self.finish(deferred, 1)
        _, fast = self.finish(deferred, 65536)
        self.assertEqual(slow, fast)
        self.assertEqual((deferred._frontier, deferred._best, deferred.expansions), before)
        with self.assertRaises(FrozenInstanceError):
            deferred.expansions = 99
        for field in (deferred._weights, deferred._remaining_hops, deferred._nodes,
                      deferred._frontier, deferred._best):
            self.assertIs(type(field), tuple)
        with self.assertRaises(TypeError):
            deferred._weights[0] = 99

    def test_entry_weights_are_copied_once_in_lexical_order(self):
        # Two-digit v makes lexical path order differ from numeric G order.
        recipe = KleinFieldRecipe(3, 11, 0, 2)
        model = RoutingModel.build(recipe, self.binding)
        world = IndependentWorld(recipe, self.binding.gains)
        weights = {name: 1 + abs(field) for name, field in zip(world.nodes, world.fields)}
        called = []
        active = True

        def cost(path):
            if not active:
                raise AssertionError("entry callback reused after search start")
            called.append(path)
            return weights[path]

        initial = HadamardRouteSearch.start(model, world.nodes[0], world.nodes[12], cost,
                                            initial_phase=128)
        self.assertEqual(called, sorted(world.nodes))
        expected = world.route(0, 12, 128, tuple(weights[name] for name in world.nodes), 8)
        active = False
        weights.clear()
        _, result = self.finish(initial, 1)
        self.assertEqual((result.cost, result.route), expected)
        self.assertEqual(called, sorted(world.nodes))

    def test_start_at_target_still_validates_all_costs_and_completion_is_idempotent(self):
        called = []
        initial = HadamardRouteSearch.start(self.model, "k:0:0", "k:0:0",
                                            lambda path: called.append(path) or 255,
                                            initial_phase=255)
        self.assertEqual(called, sorted(self.oracle.nodes))
        self.assertEqual((initial.expansions, initial.pending_states), (0, 0))
        completed, result = initial.advance(1)
        again, repeated = completed.advance(65536)
        self.assertEqual(result, SearchResult((), 0, 0))
        self.assertEqual((again, repeated), (completed, result))
        with self.assertRaisesRegex(ValueError, "entry cost"):
            HadamardRouteSearch.start(self.model, "k:0:0", "k:0:0",
                                      lambda path: 256 if path == "k:3:4" else 1,
                                      initial_phase=0)

    def test_topological_edges_are_used_without_f8_tree_children(self):
        self.assertNotIn(16, self.model.neighbors[1])  # The default f8 root's left child.
        with patch("solvefinite.f8.F8Index.resolve", side_effect=AssertionError("index is not a graph")):
            _, result = self.finish(self.cursor(start=1, target=16), 1)
        previous = 1
        for path in result.route:
            node = self.recipe.index(path)
            self.assertIn(node, self.oracle.neighbors[previous])
            previous = node
        self.assertGreater(len(result.route), 1)

    def test_zero_gains_preserve_lexical_ties_independent_of_numeric_iteration(self):
        recipe = KleinFieldRecipe(3, 11, 0, 2)
        binding = HadamardBinding(gains=((0, 0),) * 4)
        model = RoutingModel.build(recipe, binding)
        world = IndependentWorld(recipe, binding.gains)
        weights = (1,) * len(world.nodes)
        # Many equal-cost shortest walks wrap the v seam; compare full lexical tuples.
        for start, target in ((1, 10), (9, 21), (12, 10)):
            expected = world.route(start, target, 192, weights, 8)
            _, result = self.finish(self.cursor(start, target, 192, 8, model, weights), 1)
            self.assertEqual((result.cost, result.route), expected)

    def test_hop_preflight_and_admission_are_strict_before_callback(self):
        with self.assertRaises(SearchBudgetExceeded) as failure:
            self.cursor(target=17, hops=1)
        self.assertEqual(failure.exception.expansions, 0)
        self.assertEqual(str(failure.exception), "target cannot be reached within max_hops")
        called = []
        valid = {"model": self.model, "start": "k:0:0", "target": "k:0:1",
                 "cost": lambda path: called.append(path) or 1, "initial_phase": 0}
        for change in ({"model": None}, {"model": object()}, {"start": True},
                       {"start": "k:00:0"}, {"target": "k:4:0"},
                       *({"max_hops": value} for value in (True, False, 0, -1, 256, 1.0, "1", None)),
                       *({"initial_phase": value} for value in (True, False, -1, 256, 1.0, "1", None))):
            called.clear()
            with self.subTest(change=change), self.assertRaises(ValueError):
                HadamardRouteSearch.start(**{**valid, **change})
            self.assertEqual(called, [])
        for value in (True, False, 0, -1, 256, None, 1.0, "1"):
            with self.subTest(cost=value), self.assertRaises(ValueError):
                HadamardRouteSearch.start(**{**valid, "cost": lambda path: value})
        with self.assertRaisesRegex(ValueError, "callable"):
            HadamardRouteSearch.start(**{**valid, "cost": None})

    def test_invalid_quantum_preserves_pending_and_completed_cursors(self):
        initial = self.cursor(target=1)
        complete, _ = initial.advance(1)
        for cursor in (initial, complete):
            before = cursor._frontier, cursor._best, cursor.expansions, cursor._result
            for quantum in (True, False, None, 0, -1, 65537, 1.0, "1", []):
                with self.subTest(quantum=quantum), self.assertRaises(ValueError):
                    cursor.advance(quantum)
                self.assertEqual((cursor._frontier, cursor._best, cursor.expansions, cursor._result), before)


if __name__ == "__main__":
    unittest.main()
