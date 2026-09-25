"""Behavioral checks for imagination, retained observations, and recovery."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
import tempfile
import unittest

from solvefinite.rp32 import Opcode, pack, unpack, unpair
from solvefinite.runtime import InfeasiblePlan, Manifest, Runtime


LEFT = ("0", "00", "000")
RIGHT = ("1", "10", "100")
ROUTES = (LEFT, RIGHT)


def cache_state(runtime):
    world = runtime.world
    return (
        world.active_paths,
        world.evicted_paths,
        world.hit_count,
        world.regeneration_count,
    )


def started_runtime(capacity=2):
    runtime = Runtime(capacity=capacity)
    runtime.observe("0", 40)
    runtime.select_plan(ROUTES)
    runtime.advance()
    return runtime


class RuntimePlanningTests(unittest.TestCase):
    def test_candidate_selection_is_repeatable_and_order_independent(self):
        reference = Runtime()
        expected = min((reference.evaluate(route) for route in ROUTES),
                       key=lambda item: (item.cost, item.route))
        for candidates in (ROUTES, tuple(reversed(ROUTES)), (RIGHT, LEFT, RIGHT)):
            with self.subTest(candidates=candidates):
                runtime = Runtime()
                chosen = runtime.select_plan(candidates)
                self.assertEqual(chosen, expected)
                self.assertEqual(runtime.plan, chosen.route)
                self.assertEqual(runtime.cursor, 0)

    def test_equal_cost_routes_are_tied_by_path(self):
        # One-waypoint paths can share a cost. Find a real tie without making
        # the test depend on the particular demonstration cost equation.
        runtime = Runtime()
        costs = {}
        for value in range(256):
            route = (format(value, "08b"),)
            proposal = runtime.evaluate(route)
            if proposal.cost in costs:
                first = costs[proposal.cost]
                expected = min(first.route, route)
                for candidates in ((first.route, route), (route, first.route)):
                    self.assertEqual(Runtime().select_plan(candidates).route, expected)
                return
            costs[proposal.cost] = proposal
        self.fail("No equal-cost routes available to exercise deterministic tie breaking")

    def test_imagination_is_pure_even_with_a_populated_cache_and_plan(self):
        runtime = started_runtime(capacity=1)
        runtime.world.get("111")
        before = (runtime.snapshot(), runtime.events, cache_state(runtime))
        imagined = runtime.evaluate(LEFT)
        self.assertEqual((runtime.snapshot(), runtime.events, cache_state(runtime)), before)
        self.assertEqual(imagined.route, LEFT)
        self.assertEqual(len(imagined.states), len(LEFT))
        self.assertEqual(imagined.final_pair, imagined.states[-1])
        for state in imagined.states:
            unpair(state)
        with self.assertRaises(FrozenInstanceError):
            imagined.cost = 0

    def test_each_executed_state_matches_the_imagined_state(self):
        runtime = Runtime()
        runtime.observe("0", 40)
        proposal = runtime.select_plan(ROUTES)
        for cursor, (path, projected) in enumerate(zip(proposal.route, proposal.states), 1):
            runtime.advance()
            self.assertEqual(runtime.agent_pair, projected)
            self.assertEqual(runtime.position, path)
            self.assertEqual(runtime.cursor, cursor)
            unpair(runtime.agent_pair)
        self.assertEqual(runtime.agent_pair, proposal.final_pair)
        runtime.repair()
        self.assertTrue(runtime.repaired)

    def test_observations_change_choice_and_invalidate_a_pending_plan(self):
        runtime = Runtime()
        self.assertLess(runtime.evaluate(LEFT).cost, runtime.evaluate(RIGHT).cost)
        runtime.select_plan(ROUTES)
        runtime.advance()
        runtime.observe("0", 40)
        self.assertEqual(runtime.plan, ())
        self.assertEqual(runtime.cursor, 0)
        self.assertEqual(runtime.events[-1]["kind"], "OBSERVE")
        self.assertEqual(unpack(int(runtime.events[-1]["word"], 16))[3] & 7, Opcode.DATA)
        with self.assertRaises(ValueError):
            runtime.advance()
        self.assertLess(runtime.evaluate(RIGHT).cost, runtime.evaluate(LEFT).cost)
        self.assertEqual(runtime.select_plan(ROUTES).route, RIGHT)

    def test_eviction_reconstructs_exact_world_pairs(self):
        runtime = Runtime(capacity=1)
        original = runtime.world.get("001")
        runtime.world.get("111")
        self.assertNotIn("001", runtime.world.active_paths)
        restored = runtime.world.get("001")
        self.assertEqual(restored, original)
        self.assertEqual(restored, runtime.world.derive("001"))
        self.assertEqual(runtime.world.regeneration_count, 1)
        self.assertEqual(len(runtime.world.active_paths), 1)


class RuntimeRecoveryTests(unittest.TestCase):
    def test_recovery_on_different_cache_capacities_matches_uninterrupted_run(self):
        runtime = started_runtime()
        archive = runtime.archive()
        runtime.finish()
        for capacity in (1, 2, 8):
            with self.subTest(capacity=capacity):
                restored = Runtime.from_archive(archive, capacity=capacity)
                self.assertEqual(restored.world.capacity, capacity)
                self.assertFalse(restored.repaired)
                restored.finish()
                self.assertEqual(restored.snapshot(), runtime.snapshot())
                self.assertEqual(restored.events, runtime.events)
                self.assertEqual(restored.archive(), runtime.archive())

    def test_retained_measurements_survive_reconstruction(self):
        runtime = Runtime()
        runtime.observe("0", 40)
        restored = Runtime.from_archive(runtime.archive(), capacity=1)
        for route in ROUTES:
            self.assertEqual(restored.evaluate(route), runtime.evaluate(route))
        self.assertEqual(restored.select_plan(ROUTES).route, RIGHT)

    def test_disk_round_trip_preserves_journal_and_continuation(self):
        runtime = started_runtime()
        with tempfile.TemporaryDirectory() as directory:
            archive_file = Path(directory) / "colony-journal.json"
            runtime.save(archive_file)
            restored = Runtime.load(archive_file, capacity=1)
            self.assertEqual(restored.archive(), runtime.archive())
            runtime.finish()
            restored.finish()
            self.assertEqual(restored.snapshot(), runtime.snapshot())

    def test_returned_journal_and_events_are_defensive_copies(self):
        runtime = started_runtime()
        canonical = deepcopy(runtime.archive())
        events = runtime.events
        events[0]["path"] = "111"
        events[1]["candidates"][0][0] = "111"
        events.clear()
        archive = runtime.archive()
        archive["manifest"]["world"]["seed"][0] = 0
        archive["events"][0]["word"] = "00000001"
        archive["expected"].clear()
        self.assertEqual(runtime.archive(), canonical)

    def test_malformed_or_incomplete_archives_are_rejected(self):
        archive = started_runtime().archive()
        alterations = {
            "unsupported format": lambda a: a.update(format="future-journal"),
            "unknown top-level field": lambda a: a.update(extra=True),
            "missing manifest": lambda a: a.pop("manifest"),
            "missing expected state": lambda a: a.pop("expected"),
            "missing event": lambda a: a["events"].pop(0),
            "truncated journal": lambda a: a["events"].pop(),
            "reordered events": lambda a: a["events"].reverse(),
            "corrupt packet": lambda a: a["events"][0].update(
                word=f"{int(a['events'][0]['word'], 16) ^ 1:08X}"),
            "negative packet": lambda a: a["events"][0].update(word=-1),
            "oversized packet": lambda a: a["events"][0].update(word=1 << 32),
            "non-hex packet": lambda a: a["events"][0].update(word="ZZZZZZZZ"),
            "wrong plan command": lambda a: a["events"][1].update(
                word=f"{pack(0, 0, 0, Opcode.STEP):08X}"),
            "wrong advance command": lambda a: a["events"][2].update(word="00000000"),
            "malformed plan payload": lambda a: a["events"][1].update(candidates="010"),
            "unknown event": lambda a: a["events"][0].update(kind="TELEPORT"),
            "extra event field": lambda a: a["events"][0].update(extra=True),
            "missing event path": lambda a: a["events"][0].pop("path"),
            "wrong sequence": lambda a: a["events"][1].update(seq=999),
            "wrong tick": lambda a: a["events"][1].update(tick=999),
            "boolean tick": lambda a: a["events"][0].update(tick=True),
            "boolean sequence": lambda a: a["events"][0].update(seq=True),
            "wrong observed path": lambda a: a["events"][0].update(path="111"),
            "missing derivation input": lambda a: a["manifest"]["world"].pop("seed"),
            "unsupported runtime": lambda a: a["manifest"].update(version="future"),
            "unsupported profile": lambda a: a["manifest"].update(word_profile="RP64"),
            "unsupported planner": lambda a: a["manifest"].update(planner="future"),
            "unsupported world rules": lambda a: a["manifest"]["world"].update(version="future"),
            "wrong expected state": lambda a: a["expected"].clear(),
            "boolean expected cursor": lambda a: a["expected"].update(cursor=True),
            "extra expected state": lambda a: a["expected"].update(extra=True),
            "wrong expected shape": lambda a: a.update(expected=[]),
        }
        for label, alter in alterations.items():
            with self.subTest(case=label):
                damaged = deepcopy(archive)
                alter(damaged)
                with self.assertRaises(ValueError):
                    Runtime.from_archive(damaged, capacity=1)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive_file = Path(directory) / "ambiguous-journal.json"
            archive_file.write_text('{"format":"a","format":"b"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                Runtime.load(archive_file)


class RuntimeValidationTests(unittest.TestCase):
    def test_manifest_round_trip_and_strict_schema(self):
        manifest = Manifest()
        self.assertEqual(Manifest.from_dict(manifest.to_dict()), manifest)
        encoded = manifest.to_dict()
        for key in encoded:
            invalid = deepcopy(encoded)
            del invalid[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                Manifest.from_dict(invalid)
        encoded["extra"] = True
        with self.assertRaises(ValueError):
            Manifest.from_dict(encoded)

    def test_low_energy_is_infeasible_without_mutating_runtime(self):
        runtime = Runtime(Manifest(agent_seed=(250, 3, 5, 1), repair_cost=5))
        before = (runtime.snapshot(), runtime.events, cache_state(runtime))
        with self.assertRaises(InfeasiblePlan):
            runtime.evaluate(LEFT)
        with self.assertRaises(InfeasiblePlan):
            runtime.select_plan(ROUTES)
        self.assertEqual((runtime.snapshot(), runtime.events, cache_state(runtime)), before)

    def test_selection_skips_infeasible_candidate_and_keeps_repair_energy(self):
        reference = Runtime()
        reference.observe("0", 40)
        required = reference.evaluate(RIGHT).cost + 5
        self.assertLessEqual(required, 127)
        runtime = Runtime(Manifest(agent_seed=(250, 3, required, 1), repair_cost=5))
        runtime.observe("0", 40)
        with self.assertRaises(InfeasiblePlan):
            runtime.evaluate(LEFT)
        self.assertEqual(runtime.select_plan(ROUTES).route, RIGHT)
        runtime.finish()
        self.assertTrue(runtime.repaired)
        self.assertEqual(unpack(unpair(runtime.agent_pair)[0])[2], 0)

    def test_invalid_transitions_do_not_change_state(self):
        runtime = Runtime()
        before = (runtime.snapshot(), runtime.events)
        for action in (runtime.advance, runtime.repair, runtime.finish):
            with self.subTest(action=action.__name__), self.assertRaises(ValueError):
                action()
            self.assertEqual((runtime.snapshot(), runtime.events), before)
        runtime.select_plan(ROUTES)
        with self.assertRaises(ValueError):
            runtime.repair()
        runtime.finish()
        before = (runtime.snapshot(), runtime.events)
        actions = (runtime.advance, runtime.repair,
                   lambda: runtime.observe("0", 1),
                   lambda: runtime.select_plan(ROUTES))
        for action in actions:
            with self.assertRaises(ValueError):
                action()
            self.assertEqual((runtime.snapshot(), runtime.events), before)

    def test_invalid_measurements_and_routes_are_rejected_atomically(self):
        runtime = Runtime()
        before = (runtime.snapshot(), runtime.events, cache_state(runtime))
        for hazard in (-1, 128, True, 1.5, "40", None):
            with self.subTest(hazard=hazard), self.assertRaises(ValueError):
                runtime.observe("0", hazard)
        for path in ("2", "0" * 33, 0, None):
            with self.subTest(path=path), self.assertRaises(ValueError):
                runtime.observe(path, 1)
        for route in ((), ("2",), ("0",) * 33, "010", None):
            with self.subTest(route=route), self.assertRaises(ValueError):
                runtime.evaluate(route)
        for candidates in ((), ((),), (LEFT,) * 33, (LEFT, ("2",)), None):
            with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                runtime.select_plan(candidates)
        self.assertEqual((runtime.snapshot(), runtime.events, cache_state(runtime)), before)


if __name__ == "__main__":
    unittest.main()
