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

Note: this little-word-first order applies to the native Anker register
bank (10000-11134) only. The embedded SunSpec bank (10698+ / 40000+) uses
the opposite, standard SunSpec big-word-first order and is not decoded by
the helpers below.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Awaitable, Callable, NamedTuple, Sequence

from pymodbus.exceptions import ConnectionException, ModbusException

# Failures that say the LINK is in doubt, as opposed to the device answering
# with a Modbus error code. ``ConnectionException`` and ``ModbusIOException``
# both derive from ``ModbusException``, so the one entry covers them.
TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    ModbusException,
    asyncio.TimeoutError,
    OSError,
)


def unit_kwarg_name(client: object) -> str:
    """Return the slave/unit keyword name for the installed pymodbus version.

    pymodbus <3.9 uses ``slave=``; pymodbus >=3.9 renamed it to ``device_id=``.
    Detect it from the client method signature so the integration works on
    whatever version Home Assistant ships.
    """
    try:
        params = inspect.signature(client.read_input_registers).parameters
    except (TypeError, ValueError, AttributeError):
        return "slave"
    if "slave" in params:
        return "slave"
    if "device_id" in params:
        return "device_id"
    return "slave"


async def guarded_call(
    call: Callable[..., Awaitable[Any]],
    *args: Any,
    on_transport_error: Callable[[], None],
    **kwargs: Any,
) -> Any:
    """Run one pymodbus call; on a transport failure run the hook, then re-raise.

    pymodbus leaves the socket OPEN when a request exhausts its retries
    ("No response received after 3 retries, continue with next request").
    The reply can still arrive afterwards, and it is then matched against the
    NEXT request's transaction id — from that point every read logs
    "request ask for transaction_id=X but got id=Y, Skipping" and the client
    never resynchronises, because nothing in it notices the skew. The socket
    still reports ``connected``, so a connect-if-not-connected guard is no
    help either.

    Reconnecting is the only recovery: a new connection restarts the
    transaction counter. So every call that touches the wire routes through
    here and hands the caller a chance to drop the socket before the next
    request goes out.

    Errors outside :data:`TRANSPORT_ERRORS` (a decode bug, a cancelled task)
    say nothing about the link and pass through untouched.
    """
    try:
        return await call(*args, **kwargs)
    except TRANSPORT_ERRORS:
        on_transport_error()
        raise


class OptionalBlocks:
    """Skip-list for register blocks a unit may not implement.

    Two failure modes look identical from one poll, and telling them apart is
    the whole point of this class — conflating them cost a live site its meter
    sensors for nine hours:

    - the unit genuinely lacks the register: every poll pays a full
      retry/timeout cycle, so the block has to be retired;
    - the LINK glitched: one IO error skews the pymodbus transaction stream
      and every read in that cycle times out, including blocks the unit does
      implement.

    Retiring on the first timeout cannot distinguish them, so a block is
    retired only after ``threshold`` CONSECUTIVE timeouts. A retired block is
    re-probed once ``retry_after_s`` has passed, so hardware that comes back —
    a meter power-cycled, a link repaired — recovers on its own instead of
    waiting for someone to reload the integration.

    ``monotonic`` is injectable so tests can drive the clock.
    """

    def __init__(
        self,
        threshold: int = 3,
        retry_after_s: float = 900.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be at least 1")
        if retry_after_s <= 0:
            raise ValueError("retry_after_s must be positive")
        self.threshold = threshold
        self.retry_after_s = retry_after_s
        self._monotonic = monotonic
        self._timeouts: dict[str, int] = {}
        self._retired_at: dict[str, float] = {}

    def should_read(self, block: str) -> bool:
        """Is it worth spending a poll on *block* this cycle?

        A retired block answers False until its re-probe is due; the streak
        counter is cleared at that point so a re-probe that fails has to earn
        the full ``threshold`` again rather than retiring on its first miss.
        """
        retired_at = self._retired_at.get(block)
        if retired_at is None:
            return True
        if self._monotonic() - retired_at < self.retry_after_s:
            return False
        del self._retired_at[block]
        self._timeouts.pop(block, None)
        return True

    def record_success(self, block: str) -> None:
        """The block answered: clear the streak and any retirement."""
        self._timeouts.pop(block, None)
        self._retired_at.pop(block, None)

    def record_timeout(self, block: str) -> bool:
        """Count a timeout; return True only on the poll that retires *block*.

        The single-transition return keeps the caller's warning to one line
        per retirement instead of one per poll.
        """
        count = self._timeouts.get(block, 0) + 1
        self._timeouts[block] = count
        if count >= self.threshold and block not in self._retired_at:
            self._retired_at[block] = self._monotonic()
            return True
        return False


class OptionalRead(NamedTuple):
    """Outcome of reading registers that a unit may not implement."""

    registers: list[int] | None
    timed_out: bool


async def read_optional(
    read: Callable[..., Awaitable[Any]], address: int, count: int, **unit: Any
) -> OptionalRead:
    """Read registers that may be absent, absorbing the failure either way.

    ``read`` is a bound client method such as ``client.read_input_registers``.
    pymodbus >=3.6 raises ``ModbusIOException`` once a request exhausts its
    retries instead of returning a response, so ``isError()`` alone cannot
    make a register optional.

    ``timed_out`` separates the expensive failure from the cheap ones:

    - socket down (``ConnectionException``) — raised immediately, and says
      nothing about the register, so ``timed_out=False``: ask again;
    - clean Modbus error response (the device answered, e.g. "illegal data
      address") — also cheap, ``timed_out=False``: ask again;
    - the device is up but this register never answers — ``timed_out=True``
      after a full retry/timeout cycle, so callers should stop asking.
    """
    try:
        result = await read(address, count=count, **unit)
    except ConnectionException:
        return OptionalRead(None, False)
    except (ModbusException, asyncio.TimeoutError, OSError):
        return OptionalRead(None, True)
    if result.isError():
        return OptionalRead(None, False)
    return OptionalRead(list(result.registers), False)


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


def decode_meter_voltages(words: Sequence[int]) -> tuple[float, float, float]:
    """Decode three phase-voltage words; firmware differs between 0.1 V and 1 V units."""
    # shortcut: a real sub-100 V brownout on 0.1 V firmware would read 10x high, upgrade if a per-firmware scale is known
    scale = 10.0 if max(decode_u16(w) for w in words) >= 1000 else 1.0
    a, b, c = (decode_u16(w) / scale for w in words)
    return a, b, c


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
