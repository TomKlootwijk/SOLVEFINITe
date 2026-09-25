"""Checks for the explicit demonstration grammar and disposable active cache."""

import json
import unittest
from dataclasses import FrozenInstanceError, replace

from solvefinite.rp32 import pack, pair, unpack, unpair
from solvefinite.world import Node, World, WorldConfig


class DerivationTests(unittest.TestCase):
    def setUp(self):
        self.config = WorldConfig()
        self.world = World(self.config, capacity=2)

    def test_manually_calculated_reference_tree(self):
        # Calculated from branch arithmetic, independent of World.derive.
        # At root (3 XOR (250 >> 6)) & 3 = 0; branch 0 uses delta 11.
        # At path 0 (10 XOR (5 >> 6)) & 3 = 2; branch 1 uses delta 101.
        expected = {
            "": (250, 3, 20, 2),
            "0": (5, 10, 17, 2),
            "00": (52, 31, 14, 2),
            "000": (123, 94, 11, 2),
            "001": (189, 95, 18, 2),
            "01": (106, 32, 21, 2),
            "010": (135, 97, 18, 2),
            "011": (189, 98, 25, 2),
            "1": (47, 11, 24, 2),
            "10": (118, 34, 21, 2),
            "11": (184, 35, 28, 2),
            "111": (11, 107, 32, 2),
        }
        for path, lanes in expected.items():
            with self.subTest(path=path):
                node = self.world.derive(path)
                self.assertEqual(node, Node(path, pair(pack(*lanes)), len(path)))
                left, right = unpair(node.pair)
                self.assertEqual(unpack(left), lanes)
                self.assertEqual(unpack(right), ((-lanes[0]) % 256,
                                                lanes[1], lanes[2], lanes[3] ^ 16))

    def test_phase_selects_its_own_next_transition(self):
        changed = World(replace(self.config, seed=(10, 3, 20, 2)), 2)
        before = unpack(unpair(self.world.derive("0").pair)[0])
        after = unpack(unpair(changed.derive("0").pair)[0])
        # Changing only phase changes the table row from 0 to 3, hence the
        # increment changes from 11 to 71. It is not just a phase translation.
        self.assertEqual(before, (5, 10, 17, 2))
        self.assertEqual(after, (81, 10, 17, 2))
        self.assertNotEqual((after[0] - 10) % 256, (before[0] - 250) % 256)

    def test_orientation_and_nonopcode_flags_survive(self):
        world = World(replace(self.config, seed=(250, 3, 20, 16 | 8 | 64 | 5)), 1)
        # Orientation reverses phase progression; the grammar replaces only
        # the opcode, leaving jitter, orientation, and other metadata intact.
        self.assertEqual(unpack(unpair(world.derive("0").pair)[0]),
                         (239, 10, 17, 16 | 8 | 64 | 2))

    def test_field_clipping_and_selector_wrap(self):
        low = World(replace(self.config, seed=(0, 255, -127, 2)), 1)
        high = World(replace(self.config, seed=(0, 255, 126, 2)), 1)
        self.assertEqual(unpack(unpair(low.derive("0").pair)[0])[1:3], (254, -128))
        self.assertEqual(unpack(unpair(high.derive("1").pair)[0])[1:3], (255, 127))

    def test_derive_is_pure_and_nodes_are_immutable(self):
        node = self.world.derive("011")
        self.assertEqual(node, self.world.derive("011"))
        self.assertEqual(self.world.active_paths, ())
        self.assertEqual(self.world.evicted_paths, ())
        self.assertEqual(self.world.hit_count, 0)
        self.assertEqual(self.world.regeneration_count, 0)
        with self.assertRaises(FrozenInstanceError):
            node.path = "1"
        with self.assertRaises(AttributeError):
            self.world.config = WorldConfig()

    def test_path_validation(self):
        for path in (None, 1, True, [], "2", "0 1", "\n", "0" * 9):
            for method in (self.world.get, self.world.derive):
                with self.subTest(path=path, method=method.__name__):
                    with self.assertRaises(ValueError):
                        method(path)
        self.assertEqual(self.world.active_paths, ())
        root_only = World(replace(self.config, max_depth=0), 1)
        self.assertEqual(root_only.get("").log_radius, 0)
        with self.assertRaises(ValueError):
            root_only.get("0")


class CacheTests(unittest.TestCase):
    def test_fifo_hits_do_not_refresh_and_evicted_nodes_regenerate(self):
        world = World(WorldConfig(), 2)
        original = world.get("0")
        world.get("1")
        self.assertIs(world.get("0"), original)
        self.assertEqual(world.active_paths, ("0", "1"))
        self.assertEqual(world.hit_count, 1)
        world.get("00")
        self.assertEqual(world.active_paths, ("1", "00"))
        self.assertEqual(world.evicted_paths, ("0",))
        self.assertEqual(world.regeneration_count, 0)
        restored = world.get("0")
        self.assertEqual(restored, original)
        self.assertIsNot(restored, original)
        self.assertEqual(world.active_paths, ("00", "0"))
        self.assertEqual(world.evicted_paths, ("0", "1"))
        self.assertEqual(world.regeneration_count, 1)

    def test_capacity_and_resize_schedule_do_not_change_results(self):
        paths = ("", "0", "1", "01", "11", "0", "", "01", "000", "11")
        reference = [World(WorldConfig(), 1).derive(path) for path in paths]
        for capacity in (1, 2, 8):
            with self.subTest(capacity=capacity):
                world = World(WorldConfig(), capacity)
                actual = []
                for index, path in enumerate(paths):
                    if index in (3, 7):
                        world.resize(1 if index == 3 else capacity + 1)
                    actual.append(world.get(path))
                    self.assertLessEqual(len(world.active_paths), world.capacity)
                self.assertEqual(actual, reference)

    def test_resize_evicts_oldest_immediately(self):
        world = World(WorldConfig(), 4)
        for path in ("0", "1", "00", "01"):
            world.get(path)
        world.resize(2)
        self.assertEqual(world.capacity, 2)
        self.assertEqual(world.active_paths, ("00", "01"))
        self.assertEqual(world.evicted_paths, ("0", "1"))
        world.resize(5)
        self.assertEqual(world.active_paths, ("00", "01"))
        self.assertEqual(world.evicted_paths, ("0", "1"))

    def test_invalid_capacity_never_changes_the_cache(self):
        for value in (0, -1, True, 1.0, "1", None):
            with self.subTest(capacity=value):
                with self.assertRaises(ValueError):
                    World(WorldConfig(), value)
                world = World(WorldConfig(), 2)
                world.get("0")
                with self.assertRaises(ValueError):
                    world.resize(value)
                self.assertEqual(world.capacity, 2)
                self.assertEqual(world.active_paths, ("0",))
                self.assertEqual(world.evicted_paths, ())
        with self.assertRaises(ValueError):
            World({}, 2)


class ConfigurationTests(unittest.TestCase):
    def test_json_round_trip_preserves_all_derivation_inputs(self):
        original = WorldConfig(seed=(128, 20, -100, 18), baseline_id="user-baseline")
        encoded = json.loads(json.dumps(original.to_dict()))
        restored = WorldConfig.from_dict(encoded)
        self.assertEqual(original, restored)
        self.assertEqual(World(original, 1).derive("101"), World(restored, 2).derive("101"))
        encoded["seed"][0] = 0
        self.assertEqual(restored.seed[0], 128)
        with self.assertRaises(FrozenInstanceError):
            restored.max_depth = 3

    def test_rejects_unknown_missing_fields_and_versions(self):
        good = WorldConfig().to_dict()
        examples = [None, [], {}, dict(good, surprise=1), dict(good, version="future-v2")]
        for field in good:
            examples.append({key: value for key, value in good.items() if key != field})
        for data in examples:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    WorldConfig.from_dict(data)

    def test_rejects_non_json_shapes_and_bad_values(self):
        invalid = {
            "seed": [(), [0, 0, 0], [True, 0, 0, 0], [256, 0, 0, 0],
                     [0, -1, 0, 0], [0, 0, 128, 0], [0, 0, 0, 128]],
            "phase_turns": [(), [], [[0, 0]] * 3, [[0, 0, 0]] * 4,
                            [[True, 0]] * 4, [[-1, 0]] * 4, [[256, 0]] * 4],
            "field_changes": [(), [], [0], [0, 0, 0], [False, 1]],
            "max_depth": [-1, 33, True, 1.0, "8"],
            "baseline_id": [None, 5, "", "   "],
            "version": [None, True, "", "binary-organogram-v2"],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    data = WorldConfig().to_dict()
                    data[key] = value
                    with self.assertRaises(ValueError):
                        WorldConfig.from_dict(data)

    def test_constructor_requires_immutable_tuples(self):
        for changes in ({"seed": [1, 2, 3, 4]},
                        {"phase_turns": [[0, 0]] * 4},
                        {"field_changes": [-3, 4]}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    WorldConfig(**changes)


if __name__ == "__main__":
    unittest.main()
