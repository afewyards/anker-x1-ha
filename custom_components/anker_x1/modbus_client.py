"""Pure decode helpers for Anker SOLIX X1 Modbus registers.

No Home Assistant imports — this module is HA-agnostic so it can be
unit-tested independently.

Encoding rules (verified on real hardware):
- u16   : raw unsigned 16-bit value
- i16   : 16-bit two's complement
- u32   : little-endian word order — low word at lower address
           value = regs[0] | (regs[1] << 16)
- i32   : same word order, then 32-bit two's complement
- string: low-byte-first within each register (low byte then high byte);
           decode as ASCII; cut at first NUL; strip whitespace
"""

from __future__ import annotations

from typing import Sequence


# ---------------------------------------------------------------------------
# Scalar decoders
# ---------------------------------------------------------------------------


def decode_u16(word: int) -> int:
    """Return raw unsigned 16-bit register value."""
    return word & 0xFFFF


def decode_i16(word: int) -> int:
    """Interpret a 16-bit register as a signed integer (two's complement)."""
    word = word & 0xFFFF
    if word >= 0x8000:
        word -= 0x10000
    return word


def decode_u32_le(words: Sequence[int]) -> int:
    """Decode two consecutive registers as an unsigned 32-bit LE value.

    words[0] = low word (lower address), words[1] = high word.
    """
    low = words[0] & 0xFFFF
    high = words[1] & 0xFFFF
    return low | (high << 16)


def decode_i32_le(words: Sequence[int]) -> int:
    """Decode two consecutive registers as a signed 32-bit LE value."""
    value = decode_u32_le(words)
    if value >= 0x80000000:
        value -= 0x100000000
    return value


# ---------------------------------------------------------------------------
# String decoder
# ---------------------------------------------------------------------------


def decode_string_lowbyte(words: Sequence[int]) -> str:
    """Decode a sequence of registers as an ASCII string.

    Within each register the low byte comes first, then the high byte.
    The result is cut at the first NUL character and stripped of whitespace.
    """
    raw_bytes = bytearray()
    for word in words:
        raw_bytes.append(word & 0xFF)         # low byte first
        raw_bytes.append((word >> 8) & 0xFF)  # then high byte
    # Cut at first NUL
    nul_pos = raw_bytes.find(0)
    if nul_pos != -1:
        raw_bytes = raw_bytes[:nul_pos]
    return raw_bytes.decode("ascii", errors="replace").strip()


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def le_words(signed_int: int) -> list[int]:
    """Encode a signed 32-bit integer as two LE Modbus words [low, high].

    Negative values are stored as two's complement unsigned 32-bit.
    Returns [low_word, high_word].
    """
    u = signed_int & 0xFFFFFFFF
    return [u & 0xFFFF, (u >> 16) & 0xFFFF]
