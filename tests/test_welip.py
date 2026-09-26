"""W clock, carrier and LUS admission against the frozen independent literals."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from solvefinite.field_agent import (FieldAgentManifest, FIELD_POLICY, HADAMARD_POLICY,
                                     GROWTH_POLICY, ORGANOGRAM_POLICY)
from solvefinite.rp32 import pack, pair
from solvefinite.welip import (CONFIG_FORMAT, WORD_PROFILE, MAX_CLOCK, MAX_ENERGY,
                               WelipConfig, encode_bytes, decode_bytes, encode_state,
                               decode_state, make_record, validate_record)


REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs/evidence/welip-v1/formal-reference.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
LIFECYCLES = tuple(REFERENCE[key] for key in ("main_lifecycle", "mirrored_lifecycle", "capacity8_lifecycle"))
CONFIG = WelipConfig.from_dict(LIFECYCLES[0]["config"])
INITIAL_PAIR = int(LIFECYCLES[0]["operations"][0]["agent_pair"], 16)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


class WelipConfigTests(unittest.TestCase):
    def test_default_and_all_four_existing_field_policy_roundtrips(self):
        default = WelipConfig()
        self.assertEqual(default.manifest.policy, ORGANOGRAM_POLICY)
        self.assertEqual((default.producer, default.producer_epoch, default.clock_origin,
                          default.max_events, default.initial_capacity), ("sensor", 0, 0, 1_000_000, 2))
        self.assertEqual(CONFIG.to_dict(), LIFECYCLES[0]["config"])
        for policy in (FIELD_POLICY, HADAMARD_POLICY, GROWTH_POLICY, ORGANOGRAM_POLICY):
            config = WelipConfig(manifest=FieldAgentManifest(policy=policy))
            self.assertEqual(WelipConfig.from_dict(config.to_dict()), config)

    def test_frozen_and_detached_config_document(self):
        with self.assertRaises(FrozenInstanceError):
            CONFIG.producer = "changed"
        self.assertFalse(hasattr(CONFIG, "__dict__"))
        document = CONFIG.to_dict()
        document["agent"]["world"]["turns"][0] = 0
        document["agent"]["organogram"]["axiom"][0]["symbol"] = "bad"
        self.assertEqual(CONFIG.to_dict(), LIFECYCLES[0]["config"])

    def test_strict_config_keys_types_and_namespace(self):
        for key, values in {
            "producer": ("", " ", " sensor", "sensor ", "x" * 129, True, 1),
            "producer_epoch": (-1, 1 << 32, True, 0.0),
            "clock_origin": (-1, 1 << 48, True, 0.0),
            "max_events": (0, 1_000_001, True, 64.0),
            "initial_capacity": (0, 257, True, 3.0),
            "manifest": (None, {}, object()),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    replace(CONFIG, **{key: value})
        for mutation in (lambda d: d.update(extra=1), lambda d: d.pop("producer"),
                         lambda d: d.update(format="unknown"),
                         lambda d: d["agent"].update(initial_phase=True),
                         lambda d: d["agent"]["world"].update(turns=(11, 53, 137)),
                         lambda d: d["agent"]["routing"].update(gains=[[True, 1], [-1, 1], [-1, -1], [1, -1]])):
            value = CONFIG.to_dict()
            mutation(value)
            with self.assertRaises(ValueError):
                WelipConfig.from_dict(value)

    def test_original_clock_wrap_u48_horizon_and_sequence_bounds(self):
        for group in ("wrap", "u48_maximum"):
            for vector in REFERENCE["clock_vectors"][group]:
                config = replace(CONFIG, clock_origin=vector["origin"], max_events=vector["max_events"])
                self.assertEqual(config.clock(vector["seq"]),
                                 {key: vector[key] for key in ("clock_epoch", "tick16")})
        maximum = replace(CONFIG, clock_origin=MAX_CLOCK - 64)
        self.assertEqual(maximum.clock(64), {"clock_epoch": (1 << 32) - 1, "tick16": 65535})
        for seq in (-1, 65, True, 1.0):
            with self.assertRaises(ValueError):
                maximum.clock(seq)
        for vector in REFERENCE["clock_vectors"]["configuration_rejections"]:
            with self.assertRaises(ValueError):
                replace(CONFIG, clock_origin=vector["origin"], max_events=vector["max_events"])

    def test_load_rejects_duplicate_keys_nonfinite_and_noncanonical_nested_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            valid = json.dumps(CONFIG.to_dict())
            path.write_text(valid, encoding="utf-8")
            self.assertEqual(WelipConfig.load(path), CONFIG)
            for value in (valid.replace('"producer": "welip-reference"', '"producer": "welip-reference", "producer": "welip-reference"'),
                          valid.replace('"initial_energy": 100', '"initial_energy": NaN'),
                          valid.replace('"initial_energy": 100', '"initial_energy": 100.0'),
                          valid.replace('"initial_energy": 100', '"initial_energy": true')):
                path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    WelipConfig.load(path)


class WelipCarrierTests(unittest.TestCase):
    def test_pinned_reference_hash_and_raw_lengths(self):
        self.assertEqual(sha256(REFERENCE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                         "0ec46f6668867eb176285d821666de7e0fb3b71c5fac462d9a0e61973c71e210")
        for case in REFERENCE["raw_payload_vectors"]["length_cases"]:
            payload = bytes.fromhex(case["payload_hex"])
            self.assertEqual(encode_bytes(payload, case["tick16"], case["phase16"]), case["words"])
            actual = decode_bytes(case["words"], case["byte_length"], case["fragment_count"], case["tick16"], case["phase16"])
            self.assertEqual(actual, payload)
            self.assertEqual(sha256(actual).hexdigest(), case["decoded_sha256"])
        self.assertEqual(encode_bytes(b"\xff" * 4, 65535, 65535), ["FFFFFFFFFFFFFFFF"])
        self.assertEqual(decode_bytes(["FFFFFFFFFFFFFFFF"], 4, 1, 65535, 65535), b"\xff" * 4)

    def test_exhaustive_phase_orientation_opcode_matches_frozen_digest(self):
        transcript = []
        for phase in range(256):
            for orientation in (0, 1):
                for opcode in (1, 6):
                    owned = pair(pack(phase, 16, -2, opcode | orientation << 4))
                    encoded = f"{owned:016X}"
                    mirrored = encoded[8:] + encoded[:8]
                    phase16, words = encode_state(owned, 65535)
                    intrinsic = (-phase if orientation else phase) % 256
                    self.assertEqual(phase16, intrinsic << 8)
                    self.assertEqual(decode_state(words, 65535, phase16), owned)
                    self.assertEqual(encode_state(int(mirrored, 16), 65535), (phase16, list(reversed(words))))
                    transcript.append({"phase8": phase, "orientation": orientation, "opcode": opcode,
                                       "intrinsic_phase8": intrinsic, "phase16": phase16, "pair": encoded,
                                       "tick16": 65535, "words": words, "mirrored_pair": mirrored,
                                       "mirrored_words": list(reversed(words))})
        self.assertEqual(len(transcript), REFERENCE["phase_vectors"]["checked_cases"])
        self.assertEqual(sha256(canonical(transcript)).hexdigest(), REFERENCE["phase_vectors"]["complete_case_transcript_sha256"])
        for case in REFERENCE["phase_vectors"]["selected_literals"]:
            self.assertEqual(encode_state(int(case["pair"], 16), case["tick16"]), (case["phase16"], case["words"]))

    def test_all_frozen_malformed_carriers_are_rejected(self):
        decoders = {"decode_bytes": decode_bytes, "decode_state": decode_state}
        for case in REFERENCE["malformed_vectors"]["rejections"]:
            with self.subTest(name=case["name"]), self.assertRaises(ValueError):
                decoders[case["decoder"]](**case["input"])

    def test_strict_carrier_types_bounds_and_word_syntax(self):
        for payload in (bytearray(b"a"), memoryview(b"a"), "A5", [1], b"x" * 4097):
            with self.assertRaises(ValueError):
                encode_bytes(payload, 0, 0)
        for field in ("tick16", "phase16"):
            for invalid in (True, 0.0, -1, 65536):
                with self.assertRaises(ValueError):
                    encode_bytes(b"", **{"tick16": 0, "phase16": 0, field: invalid})
        for words in ((), "", [0], ["0" * 15], ["0" * 17], ["00000000000000ff"], ["０" * 16], [" " * 16]):
            with self.assertRaises(ValueError):
                decode_bytes(words, 4, 1, 0, 0)
        for field in ("byte_length", "fragment_count"):
            for invalid in (True, 0.0, -1):
                with self.assertRaises(ValueError):
                    decode_bytes([], **{"byte_length": 0, "fragment_count": 0, "tick16": 0, "phase16": 0, field: invalid})

    def test_state_metadata_range_parity_mirror_and_scalar(self):
        for invalid in (True, float(INITIAL_PAIR), -1, 1 << 64, INITIAL_PAIR ^ 1, INITIAL_PAIR ^ (1 << 33)):
            with self.assertRaises(ValueError):
                encode_state(invalid, 0)
        for opcode in (0, 2, 3, 4, 5, 7, 9, 33):
            with self.assertRaises(ValueError):
                encode_state(pair(pack(0, 0, 0, opcode)), 0)
        with self.assertRaises(ValueError):
            encode_state(pair(pack(0, 0, -128, 1)), 0)
        for scalar in (-127, 0, 127):
            owned = pair(pack(255, 255, scalar, 22))
            phase16, words = encode_state(owned, 65535)
            self.assertEqual(decode_state(words, 65535, phase16), owned)


class WelipRecordTests(unittest.TestCase):
    def test_all_three_literal_lifecycles_exact_records(self):
        for lifecycle in LIFECYCLES:
            config = WelipConfig.from_dict(lifecycle["config"])
            for row in lifecycle["operations"]:
                owned = int(row["agent_pair"], 16)
                for expected in row["records"]:
                    payload = bytes.fromhex(row["request"]["payload"]) if expected["payload_profile"] == "bytes-v1" else None
                    actual = make_record(config, sequence=expected["operation_seq"], record_seq=expected["record_seq"],
                                         kind=expected["kind"], agent_cycle=expected["agent_cycle"],
                                         geometry_epoch=expected["geometry_epoch"], pair=owned, energy=row["energy"], payload=payload)
                    self.assertEqual(actual, expected)
                    self.assertIsNone(validate_record(expected, config, expected_pair=owned, expected_energy=row["energy"]))

    def test_device_words_are_checked_and_preserved_without_cpu_production(self):
        for lifecycle in LIFECYCLES:
            config = WelipConfig.from_dict(lifecycle["config"])
            for row in lifecycle["operations"]:
                expected = row["records"][-1]
                supplied = list(expected["words"])
                with patch("solvefinite.welip.encode_state", side_effect=AssertionError("CPU state fallback")), \
                     patch("solvefinite.welip.encode_bytes", side_effect=AssertionError("CPU carrier fallback")):
                    actual = make_record(config, sequence=expected["operation_seq"], record_seq=expected["record_seq"],
                                         kind=expected["kind"], agent_cycle=expected["agent_cycle"],
                                         geometry_epoch=expected["geometry_epoch"], pair=int(row["agent_pair"], 16),
                                         energy=row["energy"], state_words=supplied)
                self.assertEqual(actual, expected)
                supplied[0] = "0" * 16
                self.assertEqual(actual, expected)

    def test_supplied_malformed_or_mirrored_words_never_fall_back(self):
        expected = LIFECYCLES[0]["operations"][0]["records"][1]
        for words in (list(reversed(expected["words"])), expected["words"][:1], tuple(expected["words"]),
                      ["0" * 16] * 2, [f"{int(expected['words'][0], 16) ^ 1:016X}", expected["words"][1]]):
            with patch("solvefinite.welip.encode_state", side_effect=AssertionError("CPU state fallback")), self.assertRaises(ValueError):
                make_record(CONFIG, sequence=1, record_seq=1, kind="IGNITE", agent_cycle=0,
                            geometry_epoch=0, pair=INITIAL_PAIR, energy=100, state_words=words)

    def test_coordinated_valid_mirror_is_not_the_owned_state(self):
        record = deepcopy(LIFECYCLES[0]["operations"][5]["records"][0])
        owned = int(LIFECYCLES[0]["operations"][5]["agent_pair"], 16)
        record["words"].reverse()
        validate_record(record, CONFIG)
        with self.assertRaises(ValueError):
            validate_record(record, CONFIG, expected_pair=owned)
        record = deepcopy(LIFECYCLES[0]["operations"][5]["records"][0])
        record["energy"] += 1
        validate_record(record, CONFIG, expected_pair=owned)
        with self.assertRaises(ValueError):
            validate_record(record, CONFIG, expected_pair=owned, expected_energy=93)

    def test_exact_record_schema_numeric_types_profiles_and_identity(self):
        source = LIFECYCLES[0]["operations"][5]["records"][0]
        for key, original in source.items():
            invalids = (True, float(original)) if type(original) is int else (None,)
            for invalid in invalids:
                value = {**deepcopy(source), key: invalid}
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    validate_record(value, CONFIG)
        for key, invalid in (("clock_epoch", 0), ("operation_seq", 7), ("producer_epoch", 8),
                             ("producer", "other"), ("baseline_id", "other"), ("status", "COMPLETE"),
                             ("payload_profile", "bytes-v1"), ("record_seq", 1), ("energy", MAX_ENERGY + 1),
                             ("agent_cycle", CONFIG.manifest.max_cycles + 1), ("geometry_epoch", 2),
                             ("kind", "READ"), ("words", tuple(source["words"]))):
            with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                validate_record({**deepcopy(source), key: invalid}, CONFIG)
        with self.assertRaises(ValueError):
            validate_record({**source, "unexpected": 1}, CONFIG)
        for key in source:
            value = deepcopy(source)
            value.pop(key)
            with self.assertRaises(ValueError):
                validate_record(value, CONFIG)

    def test_empty_raw_record_actual_phase_and_energy_admission(self):
        record = make_record(CONFIG, sequence=1, record_seq=0, kind="IGNITE", agent_cycle=0,
                             geometry_epoch=0, pair=INITIAL_PAIR, energy=100, payload=b"")
        self.assertEqual((record["words"], record["byte_length"], record["fragment_count"]), ([], 0, 0))
        validate_record(record, CONFIG, expected_pair=INITIAL_PAIR, expected_energy=100)
        for changed in ({"phase16": 0}, {"energy": 99}):
            with self.assertRaises(ValueError):
                validate_record({**record, **changed}, CONFIG, expected_pair=INITIAL_PAIR, expected_energy=100)
        for value in (True, 100.0, -1, MAX_ENERGY + 1):
            with self.assertRaises(ValueError):
                validate_record(record, CONFIG, expected_energy=value)
        with self.assertRaises(ValueError):
            validate_record(record, CONFIG, expected_pair=True)

    def test_record_slot_rules_and_geometry_selector_bounds(self):
        valid = dict(sequence=1, record_seq=1, kind="IGNITE", agent_cycle=0,
                     geometry_epoch=0, pair=INITIAL_PAIR, energy=100)
        for changes in ({"record_seq": 0}, {"kind": "EMIT"}, {"sequence": 2}, {"agent_cycle": 1},
                        {"geometry_epoch": 1}, {"record_seq": True}, {"energy": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                make_record(CONFIG, **{**valid, **changes})
        gd = WelipConfig(manifest=FieldAgentManifest(policy=GROWTH_POLICY))
        high_node_pair = pair(pack(0, 79, 0, 1))
        supplied = dict(sequence=2, record_seq=0, kind="EMIT", agent_cycle=5,
                        geometry_epoch=1, pair=high_node_pair, energy=1)
        validate_record(make_record(gd, **supplied), gd, expected_pair=high_node_pair)
        for config, epoch in ((gd, 0), (CONFIG, 1), (WelipConfig(manifest=FieldAgentManifest()), 1)):
            with self.assertRaises(ValueError):
                make_record(config, **{**supplied, "geometry_epoch": epoch})


if __name__ == "__main__":
    unittest.main()
