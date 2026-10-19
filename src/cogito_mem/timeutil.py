"""Times are kept as integer milliseconds since the Unix epoch, in UTC.

Requests and responses carry them as RFC 3339 strings. Responses always use one
shape: ``2026-10-15T09:12:00.031Z``.
"""

from __future__ import annotations

import datetime as _dt
import re
import time

_RFC3339 = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?"
    r"(?:([Zz])|([+-])(\d{2}):?(\d{2}))$"
)

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def parse(value: str) -> int:
    """Parse an RFC 3339 timestamp into epoch milliseconds (fractions below 1 ms are dropped).

    Raises ValueError when the string is not RFC 3339 or has no time zone.
    """
    m = _RFC3339.match(value.strip())
    if not m:
        raise ValueError(f"not an RFC 3339 timestamp with a time zone: {value!r}")
    year, month, day, hour, minute, second = (int(g) for g in m.group(1, 2, 3, 4, 5, 6))
    frac = m.group(7) or ""
    ms = int((frac + "000")[:3]) if frac else 0
    if second == 60:  # leap second: clamp, as most systems do
        second = 59
        ms = 999
    try:
        dt = _dt.datetime(year, month, day, hour, minute, second, tzinfo=_dt.timezone.utc)
    except ValueError as exc:
        raise ValueError(f"invalid date in {value!r}: {exc}") from None
    if m.group(9):
        sign = 1 if m.group(9) == "+" else -1
        offset = _dt.timedelta(hours=int(m.group(10)), minutes=int(m.group(11)))
        dt -= sign * offset
    delta = dt - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + ms


def format(ms: int) -> str:  # noqa: A001 - the module is used as timeutil.format
    dt = _EPOCH + _dt.timedelta(milliseconds=ms)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def from_datetime(dt: _dt.datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    delta = dt - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1000 + delta.microseconds // 1000


def from_epoch_seconds(seconds: float) -> int:
    return int(round(seconds * 1000))
