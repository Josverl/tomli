# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2021 Taneli Hukkinen
# Licensed to PSF under a Contributor Agreement.

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo
import re

try:
    from functools import lru_cache as compat_lru_cache  # type: ignore[assignment]
except ImportError:
    def compat_lru_cache(maxsize=None):
        def decorator(func):
            return func

        return decorator

TYPE_CHECKING = False
if TYPE_CHECKING:
    from typing import Any, Final

    from ._types import ParseFloat

RE_VERBOSE = getattr(re, "VERBOSE", 0)

_DECIMAL_DIGITS: Final = frozenset("0123456789")
_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")
_OCTAL_DIGITS: Final = frozenset("01234567")
_BINARY_DIGITS: Final = frozenset("01")

_TIME_RE_STR: Final = r"""
([01][0-9]|2[0-3])             # hours
:([0-5][0-9])                  # minutes
(?:
    :([0-5][0-9])              # optional seconds
    (?:\.([0-9]{1,6})[0-9]*)?  # optional fractions of a second
)?
"""

_RE_NUMBER_HAS_FLOATPART = True


class _NumberMatchFallback:
    def __init__(self, text: str, has_floatpart: bool, end_pos: int):
        self._text = text
        self._has_floatpart = has_floatpart
        self._end_pos = end_pos

    def group(self, idx=0):
        if idx == 0:
            return self._text
        if idx == "floatpart":
            return "x" if self._has_floatpart else ""
        raise IndexError("invalid group")

    def end(self) -> int:
        return self._end_pos


def _scan_digits_with_underscores(
    src: str, pos: int, allowed: frozenset[str]
) -> int | None:
    if pos >= len(src) or src[pos] not in allowed:
        return None

    i = pos + 1
    while i < len(src):
        char = src[i]
        if char in allowed:
            i += 1
            continue
        if char == "_" and i + 1 < len(src) and src[i + 1] in allowed:
            i += 2
            continue
        break
    return i


def _match_number_fallback(src: str, pos: int = 0) -> _NumberMatchFallback | None:
    if pos >= len(src):
        return None

    i = pos
    signed = False
    if src[i] in "+-":
        signed = True
        i += 1
        if i >= len(src):
            return None

    # Non-decimal integers are only valid without a leading sign.
    if not signed and src.startswith("0x", i):
        end_pos = _scan_digits_with_underscores(src, i + 2, _HEX_DIGITS)
        if end_pos is not None:
            return _NumberMatchFallback(src[pos:end_pos], False, end_pos)
    if not signed and src.startswith("0o", i):
        end_pos = _scan_digits_with_underscores(src, i + 2, _OCTAL_DIGITS)
        if end_pos is not None:
            return _NumberMatchFallback(src[pos:end_pos], False, end_pos)
    if not signed and src.startswith("0b", i):
        end_pos = _scan_digits_with_underscores(src, i + 2, _BINARY_DIGITS)
        if end_pos is not None:
            return _NumberMatchFallback(src[pos:end_pos], False, end_pos)

    # Decimal integer part.
    if src.startswith("0", i):
        int_end = i + 1
    elif src[i] in "123456789":
        scanned = _scan_digits_with_underscores(src, i, _DECIMAL_DIGITS)
        if scanned is None:
            return None
        int_end = scanned
    else:
        return None

    end_pos = int_end
    has_floatpart = False

    # Optional fraction part.
    if end_pos < len(src) and src[end_pos] == ".":
        frac_end = _scan_digits_with_underscores(src, end_pos + 1, _DECIMAL_DIGITS)
        if frac_end is not None:
            end_pos = frac_end
            has_floatpart = True

    # Optional exponent part.
    if end_pos < len(src) and src[end_pos] in "eE":
        exp_start = end_pos + 1
        if exp_start < len(src) and src[exp_start] in "+-":
            exp_start += 1
        exp_end = _scan_digits_with_underscores(src, exp_start, _DECIMAL_DIGITS)
        if exp_end is not None:
            end_pos = exp_end
            has_floatpart = True

    return _NumberMatchFallback(src[pos:end_pos], has_floatpart, end_pos)


class _NumberRegexFallback:
    def match(self, src: str, pos: int = 0) -> _NumberMatchFallback | None:
        return _match_number_fallback(src, pos)


try:
    _re_number = re.compile(
        r"""
0
(?:
    x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*   # hex
    |
    b[01](?:_?[01])*                 # bin
    |
    o[0-7](?:_?[0-7])*               # oct
)
|
[+-]?(?:0|[1-9](?:_?[0-9])*)         # dec, integer part
(?P<floatpart>
    (?:\.[0-9](?:_?[0-9])*)?         # optional fractional part
    (?:[eE][+-]?[0-9](?:_?[0-9])*)?  # optional exponent part
)
""",
        RE_VERBOSE,
    )
except ValueError:
    _RE_NUMBER_HAS_FLOATPART = False
    _re_number = _NumberRegexFallback()
RE_NUMBER: Final = _re_number

try:
    _re_localtime = re.compile(_TIME_RE_STR, RE_VERBOSE)
except ValueError:
    _re_localtime = re.compile(
        r"([0-9][0-9]):([0-9][0-9])(?::([0-9][0-9])(?:\.([0-9]{1,6})[0-9]*)?)?"
    )
RE_LOCALTIME: Final = _re_localtime


class _DatetimeMatchFallback:
    def __init__(self, end_pos: int, groups: tuple[str | None, ...]):
        self._end_pos = end_pos
        self._groups = groups

    def groups(self) -> tuple[str | None, ...]:
        return self._groups

    def end(self) -> int:
        return self._end_pos


def _all_digits(s: str) -> bool:
    return bool(s) and all("0" <= c <= "9" for c in s)


def _match_datetime_fallback(src: str, pos: int = 0) -> _DatetimeMatchFallback | None:
    if pos + 10 > len(src):
        return None

    year_str = src[pos : pos + 4]
    month_str = src[pos + 5 : pos + 7]
    day_str = src[pos + 8 : pos + 10]
    if (
        src[pos + 4 : pos + 5] != "-"
        or src[pos + 7 : pos + 8] != "-"
        or not _all_digits(year_str)
        or not _all_digits(month_str)
        or not _all_digits(day_str)
    ):
        return None

    i = pos + 10
    if i >= len(src) or src[i] not in "Tt ":
        return _DatetimeMatchFallback(
            i,
            (
                year_str,
                month_str,
                day_str,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        )

    i += 1
    if i + 5 > len(src):
        return None
    hour_str = src[i : i + 2]
    i += 2
    if src[i : i + 1] != ":":
        return None
    i += 1
    minute_str = src[i : i + 2]
    i += 2
    if not _all_digits(hour_str) or not _all_digits(minute_str):
        return None

    sec_str: str | None = None
    micros_str: str | None = None
    if src[i : i + 1] == ":":
        i += 1
        if i + 2 > len(src):
            return None
        sec_str = src[i : i + 2]
        i += 2
        if not _all_digits(sec_str):
            return None
        if src[i : i + 1] == ".":
            i += 1
            frac_start = i
            while i < len(src) and "0" <= src[i] <= "9":
                i += 1
            if i == frac_start:
                return None
            micros_str = src[frac_start : frac_start + 6]

    zulu_time: str | None = None
    offset_sign_str: str | None = None
    offset_hour_str: str | None = None
    offset_minute_str: str | None = None

    if i < len(src) and src[i] in "Zz":
        zulu_time = src[i]
        i += 1
    elif i < len(src) and src[i] in "+-":
        offset_sign_str = src[i]
        i += 1
        if i + 5 > len(src):
            return None
        offset_hour_str = src[i : i + 2]
        i += 2
        if src[i : i + 1] != ":":
            return None
        i += 1
        offset_minute_str = src[i : i + 2]
        i += 2
        if not _all_digits(offset_hour_str) or not _all_digits(offset_minute_str):
            return None

    return _DatetimeMatchFallback(
        i,
        (
            year_str,
            month_str,
            day_str,
            hour_str,
            minute_str,
            sec_str,
            micros_str,
            zulu_time,
            offset_sign_str,
            offset_hour_str,
            offset_minute_str,
        ),
    )


class _DatetimeRegexFallback:
    def match(self, src: str, pos: int = 0) -> _DatetimeMatchFallback | None:
        return _match_datetime_fallback(src, pos)


try:
    _re_datetime = re.compile(
        rf"""
([0-9]{{4}})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])  # date, e.g. 1988-10-27
(?:
    [Tt ]
    {_TIME_RE_STR}
    (?:([Zz])|([+-])([01][0-9]|2[0-3]):([0-5][0-9]))?  # optional time offset
)?
""",
        RE_VERBOSE,
    )
except ValueError:
    _re_datetime = _DatetimeRegexFallback()
RE_DATETIME: Final = _re_datetime


def match_to_datetime(match: Any) -> datetime | date:
    """Convert a `RE_DATETIME` match to `datetime.datetime` or `datetime.date`.

    Raises ValueError if the match does not correspond to a valid date
    or datetime.
    """
    try:
        groups = match.groups()
    except AttributeError:
        groups = tuple(match.group(i) for i in range(1, 12))

    (
        year_str,
        month_str,
        day_str,
        hour_str,
        minute_str,
        sec_str,
        micros_str,
        zulu_time,
        offset_sign_str,
        offset_hour_str,
        offset_minute_str,
    ) = groups
    year, month, day = int(year_str), int(month_str), int(day_str)
    if hour_str is None:
        return date(year, month, day)
    hour, minute = int(hour_str), int(minute_str)
    sec = int(sec_str) if sec_str else 0
    micros = int(micros_str.ljust(6, "0")) if micros_str else 0
    if offset_sign_str:
        tz: tzinfo | None = cached_tz(
            offset_hour_str, offset_minute_str, offset_sign_str
        )
    elif zulu_time:
        tz = timezone.utc
    else:  # local date-time
        tz = None
    return datetime(year, month, day, hour, minute, sec, micros, tzinfo=tz)


# No need to limit cache size. This is only ever called on input
# that matched RE_DATETIME, so there is an implicit bound of
# 24 (hours) * 60 (minutes) * 2 (offset direction) = 2880.
@compat_lru_cache(maxsize=None)
def cached_tz(hour_str: str, minute_str: str, sign_str: str) -> timezone:
    sign = 1 if sign_str == "+" else -1
    return timezone(
        timedelta(
            hours=sign * int(hour_str),
            minutes=sign * int(minute_str),
        )
    )


def match_to_localtime(match: Any) -> time:
    try:
        hour_str, minute_str, sec_str, micros_str = match.groups()
    except AttributeError:
        hour_str = match.group(1)
        minute_str = match.group(2)
        sec_str = match.group(3)
        micros_str = match.group(4)
    sec = int(sec_str) if sec_str else 0
    micros = int(micros_str.ljust(6, "0")) if micros_str else 0
    return time(int(hour_str), int(minute_str), sec, micros)


def match_to_number(match: Any, parse_float: ParseFloat) -> Any:
    num_str = match.group(0)
    try:
        has_floatpart = bool(match.group("floatpart"))
    except Exception:
        has_floatpart = ("." in num_str) or ("e" in num_str) or ("E" in num_str)

    if not _RE_NUMBER_HAS_FLOATPART:
        # MicroPython numeric constructors may reject underscore separators,
        # while TOML requires treating underscores as visual separators.
        num_str = num_str.replace("_", "")

    if has_floatpart:
        return parse_float(num_str)
    return int(num_str, 0)
