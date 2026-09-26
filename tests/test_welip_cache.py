"""W3 local invalidation: atomic selectors, FIFO identity and reconstruction."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
import unittest
from unittest.mock import patch

from solvefinite.field_agent import FieldAgentManifest, ORGANOGRAM_POLICY
from solvefinite.field_world import FieldWorld, KleinFieldRecipe
from solvefinite.tomigidt import Tomigidt


def cache_state(world):
    return (world.capacity, world.active_paths, world.evicted_paths,
            world.hit_count, world.regeneration_count)


class WelipCacheTests(unittest.TestCase):
    def world(self, capacity=4):
        return FieldWorld(KleinFieldRecipe(), capacity)

    def test_sorted_selector_removes_whole_pairs_in_fifo_order(self):
        world = self.world()
        order = ("k:3:0", "k:0:0", "k:2:0", "k:1:0")
        original = {path: world.get(path) for path in order}
        world.get("k:0:0")  # A hit must not turn FIFO into recency order.
        recipe, index = world.config, world.index
        removed = world.invalidate(["k:2:0", "k:3:0"])
        self.assertEqual(removed, ["k:3:0", "k:2:0"])
        self.assertEqual(cache_state(world),
                         (4, ("k:0:0", "k:1:0"), ("k:3:0", "k:2:0"), 1, 0))
        self.assertIs(world.config, recipe)
        self.assertIs(world.index, index)
        for path in world.active_paths:
            self.assertIs(world.get(path), original[path])
        removed.clear()
        self.assertEqual(world.evicted_paths, ("k:3:0", "k:2:0"))

    def test_every_bad_selector_preserves_complete_cache_before_any_removal(self):
        world = self.world()
        for path in ("k:0:0", "k:0:1", "k:0:2"):
            world.get(path)
        before = cache_state(world)
        bad = (None, True, "k:0:0", (), ("k:0:0",), {"k:0:0"}, [],
               ["k:0:0"] * 257, ["k:0:0", "k:0:0"],
               ["k:0:1", "k:0:0"], ["k:0:0", "k:3:4"],
               ["k:0:0", "k:4:0"], ["k:0:0", "k:00:1"],
               ["k:0:0", "k:0:+1"], ["k:0:0", "k:0:1 "],
               ["k:0:0", 1], ["k:0:0", True], ["k:0:0", []])
        for selector in bad:
            with self.subTest(selector=selector), self.assertRaises(ValueError):
                world.invalidate(selector)
            self.assertEqual(cache_state(world), before)
        self.assertEqual(world.invalidate(["k:0:0", "k:0:1", "k:0:2"]),
                         ["k:0:0", "k:0:1", "k:0:2"])
        self.assertEqual(world.active_paths, ())

    def test_invalidated_pair_is_reconstructed_on_demand_after_reindex(self):
        world = self.world(2)
        original = world.get("k:0:0")
        neighbor = world.get("k:0:1")
        with patch.object(world, "derive", wraps=world.derive) as derive:
            world.invalidate(["k:0:0"])
            self.assertEqual(derive.call_count, 0)
            world.reindex(psi_sign=-1, phase_origin=91)
            self.assertEqual(world.active_paths, ("k:0:1",))
            restored = world.get("k:0:0")
            self.assertEqual(derive.call_count, 1)
            self.assertEqual(restored, original)
            self.assertIsNot(restored, original)
            self.assertEqual(world.regeneration_count, 1)
            self.assertIs(world.get("k:0:1"), neighbor)
        self.assertEqual(world.active_paths, ("k:0:1", "k:0:0"))

    def test_invalidation_and_legacy_resize_share_one_eviction_order(self):
        world = self.world()
        order = ("k:3:0", "k:0:0", "k:2:0", "k:1:0")
        for path in order:
            world.get(path)
        world.invalidate(["k:2:0"])
        world.resize(1)
        self.assertEqual(world.evicted_paths, ("k:2:0", "k:3:0", "k:0:0"))
        self.assertEqual(world.active_paths, ("k:1:0",))
        world.get("k:2:0")
        self.assertEqual(world.active_paths, ("k:2:0",))
        self.assertEqual(world.evicted_paths[-1], "k:1:0")
        self.assertEqual(world.regeneration_count, 1)
        world.invalidate(["k:2:0"])
        world.get("k:2:0")
        self.assertEqual(world.regeneration_count, 2)

    def test_invalidation_waits_for_cache_operation_lock(self):
        world = self.world()
        world.get("k:0:0")
        entered, finished = Event(), Event()
        def invalidate():
            entered.set()
            result = world.invalidate(["k:0:0"])
            finished.set()
            return result
        with ThreadPoolExecutor(max_workers=1) as pool:
            with world._operation:
                pending = pool.submit(invalidate)
                self.assertTrue(entered.wait(2))
                self.assertFalse(finished.wait(.05))
                self.assertEqual(world.active_paths, ("k:0:0",))
            self.assertEqual(pending.result(timeout=2), ["k:0:0"])

    def test_racing_identical_selectors_admit_once_and_reject_stale_membership(self):
        world = self.world()
        world.get("k:0:0")
        barrier = Barrier(2)
        def invalidate():
            barrier.wait(timeout=2)
            try:
                return world.invalidate(["k:0:0"])
            except ValueError:
                return "inactive"
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invalidate) for _ in range(2)]
            outcomes = [future.result(timeout=3) for future in futures]
        self.assertEqual(outcomes.count(["k:0:0"]), 1)
        self.assertEqual(outcomes.count("inactive"), 1)
        self.assertEqual(cache_state(world), (4, (), ("k:0:0",), 0, 0))

    def test_local_invalidation_preserves_pending_search_observations_and_owner(self):
        agent = Tomigidt(FieldAgentManifest(max_search_expansions=1), capacity=8)
        self.addCleanup(agent.close)
        self.assertEqual(agent.step(dict.fromkeys(agent.visible_paths, 0)).kind, "DEFER")
        before = agent.archive()
        self.assertTrue(agent.pending_search)
        selected = sorted(agent.world.active_paths)[::2]
        self.assertTrue(selected)
        agent.world.invalidate(selected)
        self.assertEqual(agent.archive(), before)
        reference = Tomigidt.from_archive(before, capacity=8)
        self.addCleanup(reference.close)
        frame = dict.fromkeys(agent.visible_paths, 0)
        self.assertEqual(agent.step(frame).to_dict(), reference.step(frame).to_dict())
        self.assertEqual(agent.archive(), reference.archive())

    def test_generated_field_invalidation_keeps_current_recipe_and_owned_history(self):
        agent = Tomigidt(FieldAgentManifest(policy=ORGANOGRAM_POLICY), capacity=4)
        self.addCleanup(agent.close)
        for _ in range(5):
            agent.step(dict.fromkeys(agent.visible_paths, 0))
        self.assertEqual(agent.geometry_epoch, 1)
        recipe = agent.current_recipe
        pair = agent.world.get("k:0:2")
        before = agent.archive()
        agent.world.invalidate(["k:0:2"])
        self.assertIs(agent.current_recipe, recipe)
        self.assertEqual(agent.archive(), before)
        self.assertEqual(agent.world.get("k:0:2"), pair)
        self.assertEqual(agent.world.regeneration_count, 1)


if __name__ == "__main__":
    unittest.main()
