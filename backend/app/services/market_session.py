"""Most recent NYSE regular open at or before a timezone-aware instant.

Regular hours open at 09:30 America/New_York. Weekends and full-day holidays
are not sessions. Early closes still open at 09:30. The clock is the caller's
aware datetime — never a client-supplied timestamp.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
OPEN = time(9, 30)

# NYSE full-day closures, 2024–2028. Saturday holidays are observed Friday;
# Sunday holidays are observed Monday. Source: the exchange holiday schedule
# (New Year's, MLK, Presidents, Good Friday, Memorial, Juneteenth, Independence,
# Labor, Thanksgiving, Christmas). Not early closes.
NYSE_HOLIDAYS: frozenset[date] = frozenset(
    {
        # 2024
        date(2024, 1, 1),
        date(2024, 1, 15),
        date(2024, 2, 19),
        date(2024, 3, 29),
        date(2024, 5, 27),
        date(2024, 6, 19),
        date(2024, 7, 4),
        date(2024, 9, 2),
        date(2024, 11, 28),
        date(2024, 12, 25),
        # 2025
        date(2025, 1, 1),
        date(2025, 1, 20),
        date(2025, 2, 17),
        date(2025, 4, 18),
        date(2025, 5, 26),
        date(2025, 6, 19),
        date(2025, 7, 4),
        date(2025, 9, 1),
        date(2025, 11, 27),
        date(2025, 12, 25),
        # 2026
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),  # Independence Day observed (July 4 is Saturday)
        date(2026, 9, 7),
        date(2026, 11, 26),  # Thanksgiving Day
        date(2026, 12, 25),  # Christmas Day
        # 2027
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),  # Juneteenth observed (June 19 is Saturday)
        date(2027, 7, 5),  # Independence Day observed (July 4 is Sunday)
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),  # Christmas observed (December 25 is Saturday)
        date(2027, 12, 31),  # New Year's Day 2028 observed (January 1 is Saturday)
        # 2028
        date(2028, 1, 17),
        date(2028, 2, 21),
        date(2028, 4, 14),
        date(2028, 5, 29),
        date(2028, 6, 19),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
    }
)


def _session_day(day: date) -> bool:
    return day.weekday() < 5 and day not in NYSE_HOLIDAYS


def getLastMarketOpen(now: datetime) -> datetime:
    """Return the latest regular NYSE open at or before ``now``.

    ``now`` must be timezone-aware. On a trading day before 09:30 New York,
    the result is the previous trading day's 09:30.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be timezone-aware")
    day = now.astimezone(NY).date()
    for _ in range(21):
        if _session_day(day):
            opened = datetime.combine(day, OPEN, tzinfo=NY)
            if opened <= now:
                return opened
        day -= timedelta(days=1)
    raise RuntimeError("no NYSE regular open found")
