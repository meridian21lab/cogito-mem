"""UUIDv7 ids (RFC 9562) that sort by time, so the log order is the id order."""

from __future__ import annotations

import os
import uuid


def _parts(id_: str) -> tuple[int, int]:
    """Return (unix ms, 12-bit counter) of a UUIDv7 string."""
    value = uuid.UUID(id_).int
    return value >> 80, (value >> 64) & 0xFFF


class Uuid7Generator:
    """Makes strictly increasing UUIDv7 ids.

    The 12 ``rand_a`` bits are a counter within one millisecond (RFC 9562, method 1),
    so ids made in the same millisecond still sort in the order they were made.
    """

    def __init__(self, last_id: str | None = None):
        self._ms = -1
        self._counter = 0
        if last_id:
            self._ms, self._counter = _parts(last_id)

    def next(self, now_ms: int) -> str:
        if now_ms > self._ms:
            self._ms = now_ms
            self._counter = int.from_bytes(os.urandom(2), "big") & 0x3FF  # leave room to count up
        else:
            self._counter += 1
            if self._counter > 0xFFF:
                self._ms += 1
                self._counter = 0
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (self._ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= self._counter << 64
        value |= 0b10 << 62
        value |= rand_b
        return str(uuid.UUID(int=value))


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True
