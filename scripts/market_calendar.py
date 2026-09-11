"""Minimal NYSE holiday calendar, so the brief can skip days markets are
closed instead of describing stale data as if it were live.

Covers the fixed annual holidays; doesn't account for rare one-off closures
(e.g. a day of mourning), which is an acceptable gap for this use case.
"""
from datetime import date, timedelta


def _observed(d: date) -> date:
    """Shift a fixed-date holiday off a weekend per standard market convention."""
    if d.weekday() == 5:  # Saturday -> observed Friday before
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday -> observed Monday after
        return d + timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    d = next_month - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _good_friday(year: int) -> date:
    # Anonymous Gregorian algorithm for Easter Sunday, then back up two days.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day) - timedelta(days=2)


def is_us_market_holiday(d: date) -> bool:
    year = d.year
    holidays = {
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # MLK Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _good_friday(year),
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),  # Christmas
    }
    return d in holidays


def previous_trading_day(d: date) -> date:
    """The most recent trading day strictly before d (skips weekends/holidays)."""
    d -= timedelta(days=1)
    while d.weekday() >= 5 or is_us_market_holiday(d):
        d -= timedelta(days=1)
    return d
