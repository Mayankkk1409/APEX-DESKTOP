"""Candle series that cannot authorize a trade."""

from datetime import datetime, timezone

from app.services.bar_quality import assess_bars

OPEN = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)  # 11:00 New York
CLOSED = datetime(2026, 10, 15, 22, 0, tzinfo=timezone.utc)  # 18:00 New York


def _bar(day: str, close: float) -> dict:
    return {"t": f"{day}T14:30:00Z", "o": close, "h": close, "l": close, "c": close, "v": 1}


def test_empty_series_is_not_a_trade():
    reason = assess_bars("1D", [], quote_price=100, as_of=CLOSED, session_open=False)
    assert reason is not None
    assert "generated" in reason


def test_stale_intraday_series_is_rejected():
    reason = assess_bars(
        "15m",
        [_bar("2026-09-09", 315.92)],
        quote_price=341.91,
        as_of=CLOSED,
        session_open=False,
    )
    assert reason is not None
    assert "2026-09-09" in reason


def test_same_session_gap_above_two_percent_is_rejected():
    reason = assess_bars(
        "1m",
        [{"t": "2026-10-15T14:59:00Z", "o": 100, "h": 100, "l": 100, "c": 100, "v": 1}],
        quote_price=120,
        as_of=OPEN,
        session_open=True,
    )
    assert reason is not None
    assert "quoted price" in reason


def test_after_close_a_small_gap_is_kept():
    reason = assess_bars(
        "1D",
        [_bar("2026-10-15", 100)],
        quote_price=103,
        as_of=CLOSED,
        session_open=False,
    )
    assert reason is None


def test_latest_daily_bar_is_accepted():
    reason = assess_bars("1D", [_bar("2026-10-15", 341.91)], quote_price=341.91, as_of=CLOSED, session_open=False)
    assert reason is None
