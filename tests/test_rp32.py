"""Conformance vectors and invalid-input checks for the edition's RP32."""

from collections import deque
from itertools import product
import unittest

from solvefinite.rp32 import Opcode, mirror, pack, pair, step, unpair, unpack


class RP32ConformanceTests(unittest.TestCase):
    TRACE = (
        0x11F9030681F903FA,
        0x91F903FB81F90305,
        0x91F903F201F9030E,
    )

    def test_appendix_a_trace_serialization_and_replay(self):
        def replay():
            word = pack(250, 3, -7, Opcode.STEP)
            trace = [pair(word)]
            for delta in (11, 9):
                word = step(word, delta)
                trace.append(pair(word))
            return trace

        trace = replay()
        self.assertEqual(tuple(trace), self.TRACE)
        self.assertEqual(
            trace[0].to_bytes(8, "little"),
            bytes.fromhex("FA 03 F9 81 06 03 F9 11"),
        )
        self.assertEqual(
            [unpair(item) for item in trace],
            [
                (0x81F903FA, 0x11F90306),
                (0x81F90305, 0x91F903FB),
                (0x01F9030E, 0x91F903F2),
            ],
        )
        fifo = deque(maxlen=2)
        for item in trace:
            fifo.append(item)
        self.assertEqual(list(fifo), trace[-2:])
        self.assertEqual(replay(), trace)

    def test_512_mirror_involutions(self):
        count = 0
        for phase, orientation in product(range(256), range(2)):
            word = pack(phase, 3, -7, Opcode.STEP | (orientation << 4))
            self.assertEqual(mirror(mirror(word)), word)
            count += 1
        self.assertEqual(count, 512)

    def test_131072_step_mirror_commutations(self):
        count = 0
        for phase, orientation, delta in product(range(256), range(2), range(256)):
            word = pack(phase, 3, -7, Opcode.STEP | (orientation << 4))
            self.assertEqual(mirror(step(word, delta)), step(mirror(word), delta))
            count += 1
        self.assertEqual(count, 131072)

    def test_96_single_bit_corruptions_fail_parity(self):
        count = 0
        for item in self.TRACE:
            left, _ = unpair(item)
            for bit in range(32):
                with self.assertRaises(ValueError):
                    unpack(left ^ (1 << bit))
                count += 1
        self.assertEqual(count, 96)

    def test_field_boundaries_round_trip_and_even_parity(self):
        for fields in product((0, 255), (0, 255), (-128, -1, 0, 127), (0, 127)):
            with self.subTest(fields=fields):
                word = pack(*fields)
                self.assertEqual(unpack(word), fields)
                self.assertEqual(word.bit_count() % 2, 0)
                self.assertLess(word, 1 << 32)

    def test_phase_wrap_and_metadata_preservation(self):
        forward = pack(250, 91, -128, Opcode.STEP | 0b1100000)
        reverse = mirror(forward)
        self.assertEqual(unpack(step(forward, 11)), (5, 91, -128, 97))
        self.assertEqual(unpack(step(reverse, 11)), (251, 91, -128, 113))
        self.assertEqual(step(forward, 0), forward)

    def test_pair_checks_each_half_parity(self):
        valid = self.TRACE[0]
        for bit in range(64):
            with self.subTest(bit=bit), self.assertRaises(ValueError):
                unpair(valid ^ (1 << bit))

    def test_even_parity_pair_with_incorrect_mirror_is_rejected(self):
        left, _ = unpair(self.TRACE[0])
        # Both halves pass parity, but their phases/orientations are not mirrors.
        self.assertEqual(unpack(left), (250, 3, -7, 1))
        with self.assertRaisesRegex(ValueError, "mirror"):
            unpair(left | (left << 32))

    def test_opcode_values(self):
        self.assertEqual(
            [(opcode.name, opcode.value) for opcode in Opcode],
            [("DATA", 0), ("STEP", 1), ("GROW", 2), ("BRANCH", 3),
             ("SEAM", 4), ("EVICT", 5), ("EMIT", 6), ("CONTROL", 7)],
        )


class RP32ValidationTests(unittest.TestCase):
    INVALID_TYPES = (True, False, 1.0, "1", None, b"1", [], {})

    def test_pack_rejects_each_invalid_field_type(self):
        for index, value in product(range(4), self.INVALID_TYPES):
            fields = [0, 0, 0, 0]
            fields[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                pack(*fields)

    def test_pack_rejects_each_out_of_range_field(self):
        for index, invalid in enumerate(((-1, 256), (-1, 256), (-129, 128), (-1, 128))):
            for value in invalid:
                fields = [0, 0, 0, 0]
                fields[index] = value
                with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                    pack(*fields)

    def test_word_functions_reject_bad_types_width_and_parity(self):
        for function in (unpack, mirror, pair, lambda word: step(word, 1)):
            for value in (*self.INVALID_TYPES, -1, 1 << 32, 1):
                with self.subTest(function=function, value=value), self.assertRaises(ValueError):
                    function(value)

    def test_step_rejects_bad_increment(self):
        for value in (*self.INVALID_TYPES, -1, 256):
            with self.subTest(value=value), self.assertRaises(ValueError):
                step(pack(0, 0, 0, 0), value)

    def test_unpair_rejects_bad_types_and_width(self):
        for value in (*self.INVALID_TYPES, -1, 1 << 64):
            with self.subTest(value=value), self.assertRaises(ValueError):
                unpair(value)


if __name__ == "__main__":
    unittest.main()
