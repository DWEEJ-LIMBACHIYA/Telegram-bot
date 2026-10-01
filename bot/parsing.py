"""Turn short human text into dates and times.

Understood date words:   today, tomorrow (tmr, tmrw), monday..sunday (mon..sun),
                         next <weekday>, +3, in 3 days, 2026-10-05, 5 oct, oct 5
Understood time formats: 19:00, 7pm, 7:30pm, 7 pm, 7.30pm, noon, midnight

A weekday name means its next occurrence, counting today ("fri" on a Friday is
today). "next fri" always means a later day.
"""

import re
from datetime import date, time, timedelta

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_TIME_RE = re.compile(r"^(\d{1,2})(?:[:.](\d{2}))?(am|pm)?$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_PLUS_RE = re.compile(r"^\+(\d{1,3})d?$")
_DAYNUM_RE = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?$")


_FILLER = {"at", "on", "@", "by"}


def _clean(token: str) -> str:
    return token.lower().strip(",")


def _title(tokens: list[str]) -> str:
    """Join the leftover words, dropping filler like 'at' left at either end."""
    while tokens and _clean(tokens[0]) in _FILLER:
        tokens = tokens[1:]
    while tokens and _clean(tokens[-1]) in _FILLER:
        tokens = tokens[:-1]
    return " ".join(tokens).strip()


def _month_day(month: int, day: int, today: date) -> date | None:
    """A month/day with no year: this year, or next year if already past."""
    try:
        d = date(today.year, month, day)
    except ValueError:
        return None
    if d < today:
        try:
            d = date(today.year + 1, month, day)
        except ValueError:  # Feb 29
            return None
    return d


def _date_at(tokens: list[str], i: int, today: date) -> tuple[date | None, int]:
    """Try to read a date starting at tokens[i]. Returns (date, tokens_used)."""
    if i >= len(tokens):
        return None, 0
    t = _clean(tokens[i])
    nxt = _clean(tokens[i + 1]) if i + 1 < len(tokens) else ""
    nxt2 = _clean(tokens[i + 2]) if i + 2 < len(tokens) else ""

    if t in ("today", "tod", "tonight"):
        return today, 1
    if t in ("tomorrow", "tmr", "tmrw", "tomorow", "tommorow"):
        return today + timedelta(days=1), 1
    if t in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS[t] - today.weekday()) % 7), 1
    if t == "next" and nxt in WEEKDAYS:
        return today + timedelta(days=(WEEKDAYS[nxt] - today.weekday() - 1) % 7 + 1), 2
    if t == "next" and nxt == "week":
        return today + timedelta(days=7), 2

    m = _PLUS_RE.match(t)
    if m:
        return today + timedelta(days=int(m.group(1))), 1
    if t == "in" and nxt.isdigit() and nxt2 in ("day", "days"):
        return today + timedelta(days=int(nxt)), 3

    m = _ISO_RE.match(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))), 1
        except ValueError:
            return None, 0

    # "oct 5" / "october 5th"
    if t in MONTHS:
        m = _DAYNUM_RE.match(nxt)
        if m:
            d = _month_day(MONTHS[t], int(m.group(1)), today)
            if d:
                return d, 2
    # "5 oct" / "5th october"
    m = _DAYNUM_RE.match(t)
    if m and nxt in MONTHS:
        d = _month_day(MONTHS[nxt], int(m.group(1)), today)
        if d:
            return d, 2

    return None, 0


def _time_at(tokens: list[str], i: int) -> tuple[time | None, int]:
    """Try to read a time starting at tokens[i]. Returns (time, tokens_used)."""
    if i >= len(tokens):
        return None, 0
    t = _clean(tokens[i])
    if t == "noon":
        return time(12, 0), 1
    if t == "midnight":
        return time(0, 0), 1

    used = 1
    nxt = _clean(tokens[i + 1]) if i + 1 < len(tokens) else ""
    if nxt in ("am", "pm") and re.match(r"^\d{1,2}(?:[:.]\d{2})?$", t):
        t, used = t + nxt, 2

    m = _TIME_RE.match(t)
    if not m:
        return None, 0
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if not ampm and m.group(2) is None:
        return None, 0  # a bare number like "5" is too ambiguous to be a time
    if ampm:
        if not 1 <= hour <= 12:
            return None, 0
        hour = hour % 12 + (12 if ampm == "pm" else 0)
    if hour > 23 or minute > 59:
        return None, 0
    return time(hour, minute), used


def parse_time(text: str) -> time | None:
    tokens = text.split()
    t, used = _time_at(tokens, 0)
    return t if t and used == len(tokens) else None


def parse_date(text: str, today: date) -> date | None:
    """The whole text must be a date."""
    tokens = text.split()
    d, used = _date_at(tokens, 0, today)
    return d if d and used == len(tokens) else None


def _take_from_end(tokens: list[str], reader) -> tuple[object | None, list[str]]:
    """Try to read something from the last 1-3 tokens."""
    for n in (3, 2, 1):
        if len(tokens) > n:
            start = len(tokens) - n
            value, used = reader(tokens, start)
            if value is not None and used == n:
                return value, tokens[:start]
    return None, tokens


def parse_task(text: str, today: date, default: date | None = None) -> tuple[date, str]:
    """'tomorrow buy milk' or 'buy milk tomorrow' -> (date, 'buy milk'). Defaults to `default` or today."""
    tokens = text.split()
    due, used = _date_at(tokens, 0, today)
    if due and used < len(tokens):
        tokens = tokens[used:]
    else:
        due, tokens = _take_from_end(tokens, lambda tk, i: _date_at(tk, i, today))
    title = _title(tokens)
    if not title:
        raise ValueError("The task needs a name.")
    return due or default or today, title


def parse_when(tokens: list[str], today: date) -> tuple[date | None, time | None, list[str]]:
    """Read a date and/or time (in either order) from the front, else from the end."""
    day = at = None
    i = 0
    for _ in range(4):
        if i < len(tokens) and _clean(tokens[i]) in _FILLER and (day or at):
            i += 1
            continue
        if day is None:
            d, used = _date_at(tokens, i, today)
            if d:
                day, i = d, i + used
                continue
        if at is None:
            t, used = _time_at(tokens, i)
            if t:
                at, i = t, i + used
                continue
        break
    rest = tokens[i:]
    rest = _strip_end_filler(rest)
    if at is None:
        at, rest = _take_from_end(rest, _time_at)
        rest = _strip_end_filler(rest)
    if day is None:
        day, rest = _take_from_end(rest, lambda tk, j: _date_at(tk, j, today))
        rest = _strip_end_filler(rest)
    if at is None:  # e.g. "gaming 7pm tomorrow": date came off the end first
        at, rest = _take_from_end(rest, _time_at)
        rest = _strip_end_filler(rest)
    return day, at, rest


def _strip_end_filler(tokens: list[str]) -> list[str]:
    while tokens and _clean(tokens[-1]) in _FILLER:
        tokens = tokens[:-1]
    return tokens


def parse_event(text: str, today: date, default: date | None = None) -> tuple[date, time, str]:
    """'sat 7pm gaming' -> (saturday, 19:00, 'gaming'). Date defaults to `default` or today; time is required."""
    day, at, rest = parse_when(text.split(), today)
    if at is None:
        raise ValueError("I couldn't find a time. Try something like: sat 7pm Gaming night")
    title = _title(rest)
    if not title:
        raise ValueError("The event needs a name.")
    return day or default or today, at, title


def parse_reschedule(text: str, today: date) -> tuple[date | None, time | None]:
    """Text that is only a date and/or time, e.g. 'tomorrow 8pm' or '20:30'."""
    day, at, rest = parse_when(text.split(), today)
    if _title(rest) or (day is None and at is None):
        raise ValueError("I couldn't read that. Try: tomorrow 8pm, sat 19:00, or just 20:30")
    return day, at


def fmt_day(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    label = f"{d:%a} {d.day} {d:%b}"
    return label if d.year == today.year else f"{label} {d.year}"


def fmt_time(t: time) -> str:
    return f"{t:%H:%M}"
