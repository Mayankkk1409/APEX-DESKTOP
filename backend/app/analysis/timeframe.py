"""Chart-interval identity shared by market data and both research modes.

The candle interval is not the visible zoom, the indicator warm-up, the holding
horizon, or the option expiry. Historical volatility for the options IV comparison
stays on daily closes (sample stdev × √252). It is not recomputed from intraday
candles.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Selector and Full Document §3.3, plus 30m which the desk offers and the table does not name.
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W")

# Alpaca has no native 4-hour bar. 4H is built from 1-hour bars.
ALPACA_TIMEFRAME = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1H": "1Hour",
    "1D": "1Day",
    "1W": "1Week",
}

YAHOO_RANGE = {
    "1m": ("1m", "7d"),
    "5m": ("5m", "1mo"),
    "15m": ("15m", "1mo"),
    "30m": ("30m", "1mo"),
    "1H": ("60m", "3mo"),
    "4H": ("60m", "6mo"),
    "1D": ("1d", "2y"),
    "1W": ("1wk", "5y"),
}

_STEP = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1H": timedelta(hours=1),
    "4H": timedelta(hours=4),
    "1D": timedelta(days=1),
    "1W": timedelta(weeks=1),
}

# Full Document timeframe table. 30m is a desk interval with no row in that table.
_HORIZON = {
    "1m": ("Scalping", "1-minute candles are the scalping / day-trading row. Review inside the session. The exit is the stop or the target.", 1),
    "5m": ("Active intraday", "5-minute candles are the active-intraday row. Review inside the session. The exit is the stop or the target.", 1),
    "15m": ("Momentum intraday", "15-minute candles are the momentum-intraday row. Review inside the session. The exit is the stop or the target.", 1),
    "1H": ("Swing confirmation", "1-hour candles are the swing-confirmation row. This is not a same-session exit. The table does not fix a holding-day count, so the exit is the stop or the target.", 0),
    "4H": ("Multi-day positioning", "4-hour candles are the multi-day positioning row. The table does not fix a holding-day count, so the exit is the stop or the target.", 0),
    "1D": ("Standard swing", "Daily candles are the standard swing row. The table does not fix a holding-day count, so the exit is the stop or the target.", 0),
    "1W": ("Multi-month positioning", "Weekly candles are the multi-month row. The table does not fix a holding-day count, so the exit is the stop or the target.", 0),
}


def is_supported(timeframe: str) -> bool:
    return timeframe in SUPPORTED_TIMEFRAMES


def alpaca_timeframe(timeframe: str) -> str | None:
    """Native Alpaca bar size. None means unsupported, including a missing 4-hour size. Never daily by default."""
    if timeframe == "4H":
        return "1Hour"
    return ALPACA_TIMEFRAME.get(timeframe)


def yahoo_range(timeframe: str) -> tuple[str, str] | None:
    """Yahoo interval and range. None means unsupported. Never a silent daily chart."""
    return YAHOO_RANGE.get(timeframe)


def step(timeframe: str) -> timedelta | None:
    return _STEP.get(timeframe)


def horizon_for(timeframe: str) -> dict[str, Any]:
    """Holding language from the options timeframe table. 30m is named as a gap, not given an invented day count."""
    if timeframe == "30m":
        return {
            "label": "30-minute chart",
            "detail": (
                "30-minute candles are on the desk and are not in the options timeframe table. "
                "No holding-day count is invented for them. The exit is the stop or the target."
            ),
            "calendar_days": 0,
            "day_basis": "unspecified",
            "source": "desk interval; no Full Document row",
        }
    label, detail, days = _HORIZON.get(
        timeframe,
        ("Chart interval", "This interval is not in the options timeframe table. The exit is the stop or the target.", 0),
    )
    return {
        "label": label,
        "detail": detail,
        "calendar_days": days,
        "day_basis": "session" if days == 1 else "unspecified",
        "source": "Full Document timeframe table",
    }


def parse_bar_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or len(value) < 10:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def completed_bars(bars: list[dict], timeframe: str, as_of: datetime) -> tuple[list[dict], bool]:
    """Drop a still-forming last candle. Confirmation uses completed candles only."""
    if not bars:
        return [], False
    dur = step(timeframe)
    opened = parse_bar_time(bars[-1].get("t"))
    if dur is None or opened is None:
        return list(bars), False
    moment = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    if opened + dur > moment:
        return list(bars[:-1]), True
    return list(bars), False


def resample_hours(bars: list[dict], hours: int = 4) -> list[dict]:
    """Group consecutive hourly candles into clock-aligned blocks. A short trailing block is left off."""
    if hours <= 1 or not bars:
        return list(bars)
    buckets: dict[int, list[dict]] = {}
    order: list[int] = []
    for bar in bars:
        opened = parse_bar_time(bar.get("t"))
        if opened is None:
            continue
        key = int(opened.timestamp()) // (hours * 3600)
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(bar)
    out: list[dict] = []
    for key in order:
        chunk = buckets[key]
        if len(chunk) < hours:
            continue
        out.append(
            {
                "t": chunk[0]["t"],
                "o": chunk[0]["o"],
                "h": max(b["h"] for b in chunk),
                "l": min(b["l"] for b in chunk),
                "c": chunk[-1]["c"],
                "v": sum(float(b.get("v") or 0) for b in chunk),
                "resampled_from": "1H",
                "interval": f"{hours}H",
            }
        )
    return out
