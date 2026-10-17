"""The selected candle interval is the series that gets analyzed. Daily is not a silent substitute."""

from datetime import datetime, timezone

from app.analysis.indicators import historical_vol
from app.analysis.timeframe import (
    alpaca_timeframe,
    completed_bars,
    horizon_for,
    resample_hours,
    yahoo_range,
)
from app.services.equity_research import score_equity


def _bar(ts: str, price: float) -> dict:
    return {"t": ts, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 1000}


def test_unknown_interval_is_not_mapped_to_daily() -> None:
    assert alpaca_timeframe("15m") == "15Min"
    assert alpaca_timeframe("4H") == "1Hour"
    assert alpaca_timeframe("2H") is None
    assert yahoo_range("15m") == ("15m", "1mo")
    assert yahoo_range("2H") is None


def test_four_hour_blocks_come_from_hourly_candles() -> None:
    hours = [_bar(f"2026-10-15T{hour:02d}:00:00+00:00", 100 + hour) for hour in range(8)]
    out = resample_hours(hours, 4)
    assert len(out) == 2
    assert out[0]["o"] == hours[0]["o"]
    assert out[0]["c"] == hours[3]["c"]
    assert out[0]["h"] == max(b["h"] for b in hours[:4])
    assert out[0]["resampled_from"] == "1H"
    assert out[1]["t"] == hours[4]["t"]


def test_a_forming_candle_is_not_treated_as_complete() -> None:
    bars = [
        _bar("2026-10-15T14:45:00+00:00", 100),
        _bar("2026-10-15T15:00:00+00:00", 101),
    ]
    done, provisional = completed_bars(bars, "15m", datetime(2026, 10, 15, 15, 7, tzinfo=timezone.utc))
    assert provisional is True
    assert [b["t"] for b in done] == ["2026-10-15T14:45:00+00:00"]
    closed, still = completed_bars(bars, "15m", datetime(2026, 10, 15, 15, 15, tzinfo=timezone.utc))
    assert still is False
    assert len(closed) == 2


def test_options_hv_sample_is_daily_not_the_intraday_step() -> None:
    """A 1% step every 15 minutes must not be annualized as if it were a daily close."""
    intraday = [100 * (1.05 if i % 2 == 0 else 0.95) for i in range(30)]
    daily = [100 + (i % 3) * 0.2 for i in range(30)]
    misread = historical_vol(intraday)
    daily_hv = historical_vol(daily)
    assert misread > daily_hv * 5
    assert horizon_for("15m")["label"] == "Momentum intraday"
    assert horizon_for("1H")["calendar_days"] == 0
    assert "not in the options timeframe table" in horizon_for("30m")["detail"]


def test_equity_horizon_follows_the_selected_interval() -> None:
    facts = {
        "symbol": "AAPL",
        "timeframe": "15m",
        "as_of": "2026-10-14",
        "price": 100.0,
        "atr": 1.0,
        "support": 97.0,
        "resistance": 104.0,
        "trend": "up",
        "volume_ratio": 1.2,
        "technical_score": 70.0,
        "sentiment_score": 25.0,
        "news_count": 2,
        "fundamental_score": 60.0,
        "fundamental_trend": "neutral",
        "is_etf": False,
        "earnings_date": None,
        "earnings_confirmed": False,
        "spread_pct": 0.001,
        "bars": 80,
        "shares_held": 0,
        "risk_profile": "moderate",
    }
    plan = score_equity(facts)
    assert plan["timeframe"] == "15m"
    assert plan["horizon"]["label"] == "Momentum intraday"
    assert plan["levels"]["stop"] < plan["levels"]["entry"]
