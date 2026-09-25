"""Independent movement vectors and purity at the shared kernel boundary."""

from dataclasses import replace
import unittest

from solvefinite.motion import EnergyExhausted, move, movement_cost
from solvefinite.rp32 import pack, pair, unpack, unpair
from solvefinite.world import World, WorldConfig


def cache_state(world):
    return (world.active_paths, world.evicted_paths,
            world.hit_count, world.regeneration_count)


class MovementTests(unittest.TestCase):
    def setUp(self):
        self.world = World(WorldConfig(), capacity=1)
        self.agent = pair(pack(250, 3, 100, 1))

    def test_independently_calculated_three_waypoint_trace(self):
        # World G/B lanes are (11,24), (34,21), (103,18). Movement rows
        # are 3,3,2, giving phase increments 137,71,47 and costs 6,4,4.
        vectors = (
            ("1", 2, 6, 0x115E0B7D015E0B83),
            ("10", 1, 4, 0x115A2236815A22CA),
            ("100", 1, 4, 0x11566707015667F9),
        )
        agent = self.agent
        for path, hazard, expected_cost, expected_pair in vectors:
            with self.subTest(path=path):
                agent, cost = move(agent, path, self.world, hazard)
                self.assertEqual((agent, cost), (expected_pair, expected_cost))
                unpair(agent)

    def test_root_waypoint_uses_branch_zero(self):
        # The root G is 3; row 3 chooses delta 71. Phase 250+71 wraps
        # to 65, and root terrain 20 costs 3, leaving energy 97.
        self.assertEqual(move(self.agent, "", self.world),
                         (0x116103BF01610341, 3))

    def test_orientation_and_all_nonopcode_flags_are_preserved(self):
        metadata = 16 | 8 | 32 | 64 | 6
        agent = pair(pack(250, 3, 100, metadata))
        result, cost = move(agent, "0", self.world)
        left, right = unpair(result)
        # Row 2 gives delta 47, reversed by orientation: 250-47=203.
        self.assertEqual(unpack(left), (203, 10, 97, 121))
        self.assertEqual(unpack(right), (53, 10, 97, 105))
        self.assertEqual(cost, 3)

    def test_success_and_failure_leave_populated_cache_unchanged(self):
        self.world.get("111")
        self.world.get("000")
        before = cache_state(self.world)
        expected = move(self.agent, "1", self.world, 2)
        self.assertEqual(move(self.agent, "1", self.world, 2), expected)
        with self.assertRaises(EnergyExhausted):
            move(self.agent, "1", self.world, 127)
        self.assertEqual(cache_state(self.world), before)
        self.assertEqual(self.agent, pair(pack(250, 3, 100, 1)))

    def test_exact_available_energy_can_be_spent_without_underflow(self):
        world = World(replace(WorldConfig(), seed=(250, 3, 0, 2)), 1)
        result, cost = move(pair(pack(250, 3, 127, 1)), "", world, 126)
        self.assertEqual(cost, 127)
        self.assertEqual(unpack(unpair(result)[0])[2], 0)
        for energy in (-128, -1, 0, 126):
            with self.subTest(energy=energy), self.assertRaises(EnergyExhausted):
                move(pair(pack(250, 3, energy, 1)), "", world, 126)

    def test_invalid_paths_and_world_are_rejected_without_mutation(self):
        before = cache_state(self.world)
        for path in (None, True, 0, "2", "0" * 9):
            with self.subTest(path=path), self.assertRaises(ValueError):
                move(self.agent, path, self.world)
        for world in (None, WorldConfig(), 1):
            with self.subTest(world=world), self.assertRaises(ValueError):
                move(self.agent, "0", world)
        self.assertEqual(cache_state(self.world), before)

    def test_invalid_hazards_are_rejected_by_both_functions(self):
        node = self.world.derive("0").pair
        before = cache_state(self.world)
        for hazard in (-1, 128, True, False, 1.0, "1", None):
            with self.subTest(hazard=hazard):
                with self.assertRaises(ValueError):
                    movement_cost(node, hazard)
                with self.assertRaises(ValueError):
                    move(self.agent, "0", self.world, hazard)
        self.assertEqual(cache_state(self.world), before)

    def test_bad_agent_and_node_pairs_reject_parity_and_mirror_violations(self):
        left, right = unpair(self.agent)
        other_right = pack(7, 3, 100, 17)
        self.assertNotEqual(other_right, right)
        invalid_pairs = (
            None, True, -1, 1 << 64, "0", 1.0,
            self.agent ^ 1, self.agent ^ (1 << 32),
            left | (other_right << 32),
        )
        before = cache_state(self.world)
        for invalid in invalid_pairs:
            with self.subTest(pair=invalid):
                with self.assertRaises(ValueError):
                    movement_cost(invalid, 0)
                with self.assertRaises(ValueError):
                    move(invalid, "0", self.world)
        self.assertEqual(cache_state(self.world), before)

    def test_terrain_cost_uses_signed_lane_and_full_intermediate_range(self):
        for terrain, hazard, expected in (
            (-128, 127, 144), (-8, 0, 2), (-7, 0, 1),
            (0, 0, 1), (7, 0, 1), (8, 0, 2), (127, 127, 143),
        ):
            with self.subTest(terrain=terrain, hazard=hazard):
                node = pair(pack(0, 0, terrain, 2))
                self.assertEqual(movement_cost(node, hazard), expected)


if __name__ == "__main__":
    unittest.main()
