"""Exact RP32 reference arithmetic from TK-LPLUT-1.0, Appendix B.

The low three bytes hold unsigned phase R, unsigned selector G and signed
two's-complement field B. Bits 24..30 hold metadata A; metadata bit 4 is
orientation. Bit 31 makes the complete word's parity even. A double-packed
pinion stores the left word in its low 32 bits and its mirror in the high half.

This module implements the edition's declared arithmetic, not a physical
baseline, a learned operator, or a hardware performance claim.
"""

from enum import IntEnum


class Opcode(IntEnum):
    """RP32 opcode values carried in metadata's low three bits."""

    DATA = 0
    STEP = 1
    GROW = 2
    BRANCH = 3
    SEAM = 4
    EVICT = 5
    EMIT = 6
    CONTROL = 7


def _integer_in_range(value: int, low: int, high: int, name: str) -> None:
    """Validate inclusive bounds without accepting bool as an integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def pack(r: int, g: int, b: int, a: int) -> int:
    """Encode four RP32 fields, recomputing bit 31 for even parity."""
    _integer_in_range(r, 0, 255, "RP32 phase")
    _integer_in_range(g, 0, 255, "RP32 selector")
    _integer_in_range(b, -128, 127, "RP32 signed field")
    _integer_in_range(a, 0, 127, "RP32 metadata")
    value = r | (g << 8) | ((b & 255) << 16) | (a << 24)
    return value | ((value.bit_count() & 1) << 31)


def unpack(w: int) -> tuple[int, int, int, int]:
    """Decode a 32-bit word, rejecting invalid width or odd parity."""
    _integer_in_range(w, 0, (1 << 32) - 1, "RP32 word")
    if w.bit_count() & 1:
        raise ValueError("Invalid RP32 parity")
    r, g, b = w & 255, (w >> 8) & 255, (w >> 16) & 255
    return r, g, b - 256 if b >= 128 else b, (w >> 24) & 127


def mirror(w: int) -> int:
    """Negate phase modulo 256 and flip orientation, preserving other lanes."""
    r, g, b, a = unpack(w)
    return pack((-r) % 256, g, b, a ^ 16)


def step(w: int, delta: int) -> int:
    """Advance phase by an unsigned increment with orientation's sign."""
    _integer_in_range(delta, 0, 255, "Phase increment")
    r, g, b, a = unpack(w)
    sign = -1 if a & 16 else 1
    return pack((r + sign * delta) % 256, g, b, a)


def pair(w: int) -> int:
    """Construct a 64-bit pinion with a validated left word and its mirror."""
    return w | (mirror(w) << 32)


def unpair(d: int) -> tuple[int, int]:
    """Decode a pinion, checking width, each parity and the full mirror map.

    Even parity alone does not establish mirror consistency. Both complete
    words must have the exact relationship prescribed by :func:`mirror`.
    """
    _integer_in_range(d, 0, (1 << 64) - 1, "Pinion pair")
    left, right = d & ((1 << 32) - 1), d >> 32
    unpack(left)
    unpack(right)
    if right != mirror(left):
        raise ValueError("Invalid pinion mirror relation")
    return left, right
