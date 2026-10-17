"""Decide whether the candles used for a scan can authorize a trade.

A missing feed is not filled with a generated price. A large move is not
called corrupt just because a later quote differs from an older session.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from app.analysis.timeframe import parse_bar_time, step
from app.services.market_session import NY, is_trading_day

# Same-session comparison only. A later session can gap by more than this
# without the candle series being invented.
SAME_SESSION_TOLERANCE = 0.02
# After the close, only a disagreement this large is treated as a different series.
CLOSED_SESSION_TOLERANCE = 0.15


def latest_completed_session(as_of: datetime) -> date:
    """The trading day whose candles are the latest ones a scan may use."""
    local = as_of.astimezone(NY)
    day = local.date()
    if not is_trading_day(day) or local.time() < time(9, 30):
        day = day - timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def _previous_session(day: date) -> date:
    cursor = day - timedelta(days=1)
    while not is_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def assess_bars(
    timeframe: str,
    bars: list[dict[str, Any]],
    *,
    quote_price: float | None,
    as_of: datetime,
    session_open: bool,
) -> str | None:
    """Return a reason the series cannot be traded, or None when it can.

    Daily and weekly candles may be the latest session or the one before it,
    because the provider often publishes the official bar after the close.
    Intraday candles must belong to the latest session. During the session
    they also have to be within two intervals of ``as_of``.
    """
    if not bars:
        return "No completed candles were returned for this interval. No trade was built from a generated price."
    opened = parse_bar_time(bars[-1].get("t"))
    if opened is None:
        return "The last candle has no timestamp, so the series was not used."
    bar_day = opened.astimezone(NY).date()
    session_day = latest_completed_session(as_of)
    previous = _previous_session(session_day)
    if timeframe == "1W":
        if bar_day < session_day - timedelta(days=12):
            return (
                f"The last weekly candle is {bar_day.isoformat()}, before the latest session "
                f"{session_day.isoformat()}. No trade was built from that series."
            )
    elif timeframe == "1D":
        if bar_day not in {session_day, previous}:
            return (
                f"The last daily candle is {bar_day.isoformat()}. The latest session is "
                f"{session_day.isoformat()}. No trade was built from that series."
            )
    else:
        if bar_day != session_day:
            return (
                f"The last {timeframe} candle is {bar_day.isoformat()}, before the latest session "
                f"{session_day.isoformat()}. No trade was built from that series."
            )
        interval = step(timeframe)
        if session_open and interval is not None and opened + (interval * 2) < as_of:
            return (
                f"The last {timeframe} candle is more than two intervals behind the current session. "
                "No trade was built from that series."
            )
    close = bars[-1].get("c")
    if (
        isinstance(quote_price, (int, float))
        and not isinstance(quote_price, bool)
        and quote_price > 0
        and isinstance(close, (int, float))
        and not isinstance(close, bool)
        and close > 0
    ):
        gap = abs(float(close) - float(quote_price)) / float(quote_price)
        limit = SAME_SESSION_TOLERANCE if session_open else CLOSED_SESSION_TOLERANCE
        if gap > limit:
            return (
                "The last candle close does not match the quoted price for this session. "
                "No trade was built from that series."
            )
    return None
