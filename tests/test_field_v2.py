"""CPU and schema conformance for K6-K8, with independent transition encoding."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import subprocess
import sys
import unittest

from solvefinite.field import FieldManifest, FieldMachine, build_operators, evaluate_field
from solvefinite.klein import KleinDomain


ROOT = Path(__file__).resolve().parents[1]
V1_KEYS = {"format", "identity", "nodes", "edges", "signs", "routes", "turns",
           "unit_num", "unit_den", "initial_node", "initial_phase",
           "initial_orientation", "max_ticks"}


def encoded_word(phase, node, field, metadata):
    """Encode lanes and even parity without calling the RP32 implementation."""
    low = phase | node << 8 | (field % 256) << 16 | metadata << 24
    return low | ((low.bit_count() % 2) << 31)


def encoded_pair(phase, node, field, orientation):
    left = encoded_word(phase, node, field, 1 | orientation << 4)
    right = encoded_word((-phase) % 256, node, field, 1 | (orientation ^ 1) << 4)
    return left | right << 32


def swap_words(value):
    return (value >> 32) | (value & 0xFFFFFFFF) << 32


def exact_fields(manifest):
    """Independent all-pairs oracle for these small weighted graphs."""
    count = len(manifest.nodes)
    distances = [[0 if left == right else 10 ** 9 for right in range(count)]
                 for left in range(count)]
    for left, right, weight in manifest.edges:
        distances[left][right] = distances[right][left] = weight
    for middle in range(count):
        for left in range(count):
            for right in range(count):
                distances[left][right] = min(distances[left][right],
                                             distances[left][middle] + distances[middle][right])
    boundary = tuple(node for node, sign in enumerate(manifest.signs) if sign == 0)
    return tuple(sign * min(distances[node][other] for other in boundary)
                 for node, sign in enumerate(manifest.signs))


def expected_trace(manifest, steps, fields=None):
    fields = exact_fields(manifest) if fields is None else fields
    phase, node, orientation = (manifest.initial_phase, manifest.initial_node,
                                manifest.initial_orientation)
    result = []
    for _ in range(steps):
        column = {-1: 0, 0: 1, 1: 2}[manifest.signs[node]]
        destination = manifest.routes[node][column]
        increment = manifest.turns[node][column]
        local_phase = phase - increment if orientation else phase + increment
        edge = (min(node, destination), max(node, destination))
        if edge in manifest.seams:
            phase, orientation = (-local_phase) % 256, 1 - orientation
        else:
            phase = local_phase % 256
        node = destination
        result.append(encoded_pair(phase, node, fields[node], orientation))
    return tuple(result)


def generic_manifest(**changes):
    defaults = dict(profile="relational-sdf-v2", nodes=("inside", "boundary", "outside"),
                    edges=((0, 1, 2), (1, 2, 3)), signs=(-1, 0, 1),
                    routes=((1, 0, 1), (0, 2, 1), (2, 1, 1)),
                    turns=((11, 53, 137),) * 3, seams=((0, 1), (1, 2)), topology=None)
    defaults.update(changes)
    return FieldManifest(**defaults)


class FieldV2SchemaTests(unittest.TestCase):
    def test_v1_serialization_and_operator_words_are_exactly_preserved(self):
        manifest = FieldManifest()
        expected = {
            "format": "relational-sdf-v1", "identity": "TOMIGIDt",
            "nodes": ["n0", "n1", "n2", "n3", "n4", "n5", "n6"],
            "edges": [[0, 1, 2], [1, 2, 1], [2, 3, 3], [3, 4, 2], [4, 5, 1], [5, 6, 2]],
            "signs": [-1, -1, -1, 0, 1, 1, 1],
            "routes": [[1, 1, 0], [2, 2, 0], [3, 3, 1], [4, 4, 2],
                       [5, 5, 3], [6, 6, 4], [6, 6, 5]],
            "turns": [[11, 53, 137] for _ in range(7)],
            "unit_num": 1, "unit_den": 1, "initial_node": 0, "initial_phase": 250,
            "initial_orientation": 0, "max_ticks": 65536,
        }
        self.assertEqual(manifest.to_dict(), expected)
        self.assertEqual(set(manifest.to_dict()), V1_KEYS)
        self.assertEqual(FieldManifest.from_dict(expected), manifest)
        fields = (-6, -4, -3, 0, 2, 3, 5)
        self.assertEqual(build_operators(manifest, fields),
                         tuple(tuple(encoded_word(increment, destination, fields[destination], 1)
                                     for increment, destination in zip(turns, routes))
                               for turns, routes in zip(manifest.turns, manifest.routes)))
        for changes in ({"seams": ((0, 1),)}, {"topology": (3, 3)}, {"seams": []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(manifest, **changes)
        for extra in ("seams", "topology"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                FieldManifest.from_dict({**expected, extra: [] if extra == "seams" else None})

    def test_v2_roundtrips_generic_and_generated_manifests_with_detached_json(self):
        for manifest in (generic_manifest(), KleinDomain(3, 4).field_manifest()):
            encoded = manifest.to_dict()
            with self.subTest(topology=manifest.topology):
                self.assertEqual(set(encoded), V1_KEYS | {"seams", "topology"})
                self.assertEqual(encoded["format"], "relational-sdf-v2")
                self.assertEqual(encoded["seams"], [list(edge) for edge in manifest.seams])
                self.assertEqual(FieldManifest.from_dict(json.loads(json.dumps(encoded))), manifest)
                self.assertEqual(encoded["topology"], None if manifest.topology is None else
                                 {"format": "klein-grid-v1", "width": 3, "height": 4})
                for attribute in ("profile", "seams", "topology"):
                    with self.assertRaises(FrozenInstanceError):
                        setattr(manifest, attribute, None)
                encoded["seams"][0][0] = 255
                encoded["nodes"][0] = "changed"
                if encoded["topology"] is not None:
                    encoded["topology"]["width"] = 4
                self.assertNotEqual(encoded, manifest.to_dict())
                self.assertEqual(manifest.seams[0][0], 0)

    def test_exact_v2_schema_rejects_missing_extra_and_non_json_collections(self):
        encoded = generic_manifest().to_dict()
        for missing in encoded:
            changed = deepcopy(encoded)
            del changed[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                FieldManifest.from_dict(changed)
        for extra in ("extra", "profile", "route_flips", "route_seams", "cover_faces"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                FieldManifest.from_dict({**encoded, extra: []})
        for name in ("nodes", "edges", "signs", "routes", "turns", "seams"):
            for invalid in (None, {}, tuple(encoded[name])):
                with self.subTest(name=name, invalid=invalid), self.assertRaises(ValueError):
                    FieldManifest.from_dict({**encoded, name: invalid})
        for name in ("edges", "routes", "turns", "seams"):
            changed = deepcopy(encoded)
            changed[name][0] = tuple(changed[name][0])
            with self.subTest(row=name), self.assertRaises(ValueError):
                FieldManifest.from_dict(changed)
        for invalid in (None, [], {}, True, "relational-sdf-v2"):
            with self.subTest(document=invalid), self.assertRaises(ValueError):
                FieldManifest.from_dict(invalid)
        for profile in (None, 2, True, "", "relational-sdf-v3"):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                FieldManifest.from_dict({**encoded, "format": profile})
            with self.assertRaises(ValueError):
                replace(generic_manifest(), profile=profile)

    def test_seams_require_sorted_unique_strict_integer_existing_edges(self):
        manifest = generic_manifest()
        invalid = (None, [], ((0,),), ((0, 1, 2),), ((0, 1), (0, 1)),
                   ((1, 2), (0, 1)), ((1, 0),), ((0, 0),), ((0, 2),),
                   ((-1, 0),), ((0, 3),), ((False, 1),), ((0, True),),
                   ((0.0, 1),), ((0, 1.0),), (("0", 1),), ([0, 1],), (None,))
        for seams in invalid:
            with self.subTest(seams=seams), self.assertRaises(ValueError):
                replace(manifest, seams=seams)
        encoded = manifest.to_dict()
        for seams in ([0], [None], [False], [[0]], [[0, 1, 2]], [[1, 0]], [[0, 0]],
                      [[0, 2]], [[0, 3]], [[False, 1]], [[0, 1.0]], [[0, 1], [0, 1]],
                      [[1, 2], [0, 1]]):
            with self.subTest(json_seams=seams), self.assertRaises(ValueError):
                FieldManifest.from_dict({**encoded, "seams": seams})

    def test_topology_requires_exact_descriptor_and_strict_supported_dimensions(self):
        manifest = KleinDomain(3, 4).field_manifest()
        encoded = manifest.to_dict()
        invalid = (False, [], (), "klein-grid-v1", {}, {"format": "klein-grid-v1"},
                   {"format": "klein-grid-v1", "width": 3, "height": 4, "extra": 1},
                   {"format": "future", "width": 3, "height": 4})
        for topology in invalid:
            with self.subTest(topology=topology), self.assertRaises(ValueError):
                FieldManifest.from_dict({**encoded, "topology": topology})
        for key in ("format", "width", "height"):
            topology = deepcopy(encoded["topology"])
            del topology[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                FieldManifest.from_dict({**encoded, "topology": topology})
        for value in (True, 3.0, "3", None, -1, 0, 2, 256):
            for dimension in ("width", "height"):
                topology = {**encoded["topology"], dimension: value}
                with self.subTest(dimension=dimension, value=value), self.assertRaises(ValueError):
                    FieldManifest.from_dict({**encoded, "topology": topology})
        for topology in ([3, 4], (), (3,), (3, 4, 5), {"width": 3, "height": 4},
                         (True, 4), (3, 4.0), (17, 16)):
            with self.subTest(python_topology=topology), self.assertRaises(ValueError):
                replace(manifest, topology=topology)

    def test_descriptor_rejects_otherwise_valid_changed_nodes_edges_and_seams(self):
        original = KleinDomain(3, 4).field_manifest()
        generic = replace(original, topology=None,
                          routes=tuple((node,) * 3 for node in range(len(original.nodes))))
        ordinary_edge = next((left, right) for left, right, _ in generic.edges
                             if (left, right) not in generic.seams)
        first_edge = generic.edges[0]
        changes = ({"nodes": ("renamed", *generic.nodes[1:])},
                   {"nodes": tuple(reversed(generic.nodes))},
                   {"edges": ((*first_edge[:2], 2), *generic.edges[1:])},
                   {"edges": generic.edges[:-1]},
                   {"seams": generic.seams[:-1]},
                   {"seams": tuple(sorted((*generic.seams, ordinary_edge)))})
        for change in changes:
            changed = replace(generic, **change)
            self.assertIsNone(changed.topology)
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(changed, topology=(3, 4))
        with self.assertRaises(ValueError):
            replace(original, topology=(4, 3))
        with self.assertRaises(ValueError):
            replace(generic_manifest(), topology=(3, 3))

    def test_descriptor_keeps_signs_and_routes_explicit_and_generic_profile_allows_no_seams(self):
        original = KleinDomain(3, 3).field_manifest()
        stationary = replace(original, signs=(0,) * 9,
                             routes=tuple((node,) * 3 for node in range(9)),
                             turns=((0, 255, 128),) * 9)
        self.assertEqual(FieldManifest.from_dict(stationary.to_dict()), stationary)
        self.assertEqual(evaluate_field(stationary), (0,) * 9)
        generic = replace(generic_manifest(), seams=())
        self.assertIsNone(generic.to_dict()["topology"])
        self.assertEqual(generic.to_dict()["seams"], [])
        self.assertEqual(FieldManifest.from_dict(generic.to_dict()), generic)


class FieldV2TransitionTests(unittest.TestCase):
    def test_compiler_derives_every_operator_seam_without_live_orientation_bits(self):
        for manifest in (generic_manifest(), KleinDomain(3, 4).field_manifest()):
            fields = exact_fields(manifest)
            operators = build_operators(manifest, fields)
            for source, row in enumerate(operators):
                for column, word in enumerate(row):
                    destination = manifest.routes[source][column]
                    edge = (min(source, destination), max(source, destination))
                    tau = int(edge in manifest.seams)
                    self.assertEqual(word, encoded_word(manifest.turns[source][column], destination,
                                                        fields[destination], 1 | tau << 6))
                    self.assertEqual(((word >> 24) & 127) & 16, 0)
                    self.assertEqual(manifest.seam(source, destination), tau)
                    self.assertEqual(manifest.seam(destination, source), tau)
            for node in range(len(manifest.nodes)):
                self.assertEqual(manifest.seam(node, node), 0)

    def test_explicit_seam_reflects_phase_after_departure_frame_increment(self):
        cases = ((0, 250, 251, 1), (1, 250, 17, 0),
                 (0, 0, 245, 1), (1, 0, 11, 0))
        for orientation, phase, expected_phase, expected_orientation in cases:
            manifest = generic_manifest(initial_phase=phase, initial_orientation=orientation)
            machine = FieldMachine(manifest)
            with self.subTest(orientation=orientation, phase=phase):
                self.assertEqual(machine.advance(1),
                                 (encoded_pair(expected_phase, 1, 0, expected_orientation),))
        # Inverting the first declaration alone removes the seam action.
        plain = generic_manifest(seams=((1, 2),))
        self.assertEqual(FieldMachine(plain).advance(1), (encoded_pair(5, 1, 0, 0),))

    def test_all_phases_and_both_frames_match_independent_seam_arithmetic(self):
        fields = (-2, 0, 3)
        for phase in range(256):
            for orientation in (0, 1):
                for seams in ((), ((0, 1), (1, 2))):
                    for source in range(3):
                        manifest = generic_manifest(initial_phase=phase, initial_orientation=orientation,
                                                    initial_node=source, seams=seams)
                        self.assertEqual(FieldMachine(manifest).advance(1),
                                         expected_trace(manifest, 1, fields))

    def test_zero_halfturn_and_wrapping_increments_keep_full_mirror_commutation(self):
        for increment in (0, 1, 53, 128, 255):
            for phase in (0, 1, 127, 128, 250, 255):
                for orientation in (0, 1):
                    manifest = generic_manifest(initial_phase=phase, initial_orientation=orientation,
                                                turns=((increment,) * 3,) * 3)
                    mirror_manifest = replace(manifest, initial_phase=(-phase) % 256,
                                              initial_orientation=orientation ^ 1)
                    machine, mirrored = FieldMachine(manifest), FieldMachine(mirror_manifest)
                    original_trace = (machine.agent_pair, *machine.advance(12))
                    mirrored_trace = (mirrored.agent_pair, *mirrored.advance(12))
                    self.assertEqual(mirrored_trace, tuple(map(swap_words, original_trace)))
                    self.assertEqual(original_trace[1:], expected_trace(manifest, 12, (-2, 0, 3)))
                    for value in original_trace + mirrored_trace:
                        for word in (value & 0xFFFFFFFF, value >> 32):
                            self.assertEqual(word.bit_count() % 2, 0)
                            self.assertIn((word >> 24) & 127, (1, 17))

    def test_generated_tour_crosses_real_seams_and_uses_current_field_class(self):
        for width, height in ((3, 4), (4, 5), (8, 8)):
            domain = KleinDomain(width, height)
            manifest = domain.field_manifest()
            fields = exact_fields(manifest)
            machine = FieldMachine(manifest)
            actual = machine.advance(4 * width)
            self.assertEqual(actual, expected_trace(manifest, 4 * width, fields))
            self.assertEqual(machine.fields, fields)
            for tick, value in enumerate(actual, start=1):
                left = value & 0xFFFFFFFF
                orientation = (left >> 28) & 1
                self.assertEqual(orientation, (tick // width) % 2)
                self.assertEqual((left >> 8) & 255, (tick % width) * height)

    def test_stationary_v2_routes_have_zero_seam_and_retain_frame(self):
        for orientation in (0, 1):
            manifest = generic_manifest(routes=((0,) * 3, (1,) * 3, (2,) * 3),
                                        initial_orientation=orientation)
            machine = FieldMachine(manifest)
            trace = machine.advance(10)
            self.assertEqual(trace, expected_trace(manifest, 10, (-2, 0, 3)))
            for value in trace:
                self.assertEqual((value >> 28) & 1, orientation)
                self.assertEqual((value >> 8) & 255, 0)


class FieldV2ReplayTests(unittest.TestCase):
    def test_split_batches_and_roundtrip_replay_match_whole_trace(self):
        manifest = KleinDomain(4, 5).field_manifest()
        reference = FieldMachine(manifest)
        expected = reference.advance(48)
        split = FieldMachine(manifest)
        actual = []
        for length in (3, 7, 1, 12, 25):
            actual.extend(split.advance(length))
            encoded = json.loads(json.dumps(split.archive()))
            self.assertEqual(encoded["format"], "relational-sdf-machine-v1")
            self.assertEqual(encoded["manifest"]["format"], "relational-sdf-v2")
            split = FieldMachine.from_archive(encoded)
        self.assertEqual(tuple(actual), expected)
        self.assertEqual(split.archive(), reference.archive())
        self.assertEqual(FieldMachine.from_archive(FieldMachine(manifest).archive()).tick, 0)

    def test_replay_across_maximum_batch_boundary(self):
        machine = FieldMachine(KleinDomain(3, 3).field_manifest())
        machine.advance(4096)
        machine.advance(7)
        restored = FieldMachine.from_archive(machine.archive())
        self.assertEqual(restored.archive(), machine.archive())
        self.assertEqual(restored.advance(9), machine.advance(9))

    def test_fresh_process_replays_and_continues_bit_identically(self):
        machine = FieldMachine(KleinDomain(3, 4).field_manifest())
        machine.advance(17)
        archived = machine.archive()
        machine.advance(19)
        script = ("import json,sys\n"
                  "from solvefinite.field import FieldMachine\n"
                  "machine=FieldMachine.from_archive(json.load(sys.stdin))\n"
                  "machine.advance(19)\n"
                  "json.dump(machine.archive(),sys.stdout,sort_keys=True)\n")
        result = subprocess.run([sys.executable, "-c", script], input=json.dumps(archived),
                                text=True, capture_output=True, cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), machine.archive())

    def test_changed_quotient_geometry_and_descriptor_are_rejected_on_replay(self):
        machine = FieldMachine(KleinDomain(3, 4).field_manifest())
        machine.advance(12)
        original = machine.archive()
        mutations = {
            "node label": lambda manifest: manifest["nodes"].__setitem__(0, "changed"),
            "edge length": lambda manifest: manifest["edges"][0].__setitem__(2, 2),
            "removed edge": lambda manifest: manifest["edges"].pop(),
            "removed seam": lambda manifest: manifest["seams"].pop(),
            "dimensions": lambda manifest: manifest["topology"].update(width=4, height=3),
            "descriptor version": lambda manifest: manifest["topology"].update(format="future"),
            "descriptor extra": lambda manifest: manifest["topology"].update(extra=True),
        }
        for label, mutate in mutations.items():
            damaged = deepcopy(original)
            mutate(damaged["manifest"])
            with self.subTest(change=label), self.assertRaises(ValueError):
                FieldMachine.from_archive(damaged)
        self.assertEqual(machine.archive(), original)

    def test_valid_parity_wrong_transport_and_changed_generic_seams_fail_replay(self):
        machine = FieldMachine(generic_manifest())
        machine.advance(9)
        original = machine.archive()
        wrong_reflection = encoded_pair(5, 1, 0, 1)
        wrong_orientation = encoded_pair(251, 1, 0, 0)
        leaked_operator_flag = (encoded_word(251, 1, 0, 81)
                                | encoded_word(5, 1, 0, 65) << 32)
        for wrong in (wrong_reflection, wrong_orientation, leaked_operator_flag):
            damaged = deepcopy(original)
            damaged["trace"][0] = f"{wrong:016X}"
            with self.subTest(wrong=f"{wrong:016X}"), self.assertRaises(ValueError):
                FieldMachine.from_archive(damaged)
        damaged = deepcopy(original)
        damaged["manifest"]["seams"] = []
        # This changed generic manifest is valid; the retained trace disproves it.
        FieldManifest.from_dict(damaged["manifest"])
        with self.assertRaises(ValueError):
            FieldMachine.from_archive(damaged)
        damaged = deepcopy(original)
        damaged["expected"]["agent_pair"] = f"{wrong_reflection:016X}"
        with self.assertRaises(ValueError):
            FieldMachine.from_archive(damaged)

    def test_budget_rejection_preserves_v2_state_and_detached_archive(self):
        machine = FieldMachine(replace(generic_manifest(), max_ticks=5))
        machine.advance(4)
        original = machine.archive()
        for count in (0, -1, True, 1.0, "1", 4097, 2):
            with self.subTest(count=count), self.assertRaises(ValueError):
                machine.advance(count)
            self.assertEqual(machine.archive(), original)
        detached = machine.archive()
        detached["manifest"]["seams"].clear()
        detached["trace"].clear()
        detached["expected"].clear()
        self.assertEqual(machine.archive(), original)
        machine.advance(1)
        with self.assertRaises(ValueError):
            machine.advance(1)


if __name__ == "__main__":
    unittest.main()
