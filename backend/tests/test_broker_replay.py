from datetime import date

from app.services.broker_replay import rebuild_equity_points


def _closes(symbol: str, rows: list[tuple[str, float]]) -> dict[str, dict[date, float]]:
    return {symbol: {date.fromisoformat(day): price for day, price in rows}}


def test_deposit_is_not_profit_and_daily_pnl_matches_the_session_change() -> None:
    activities = [
        {"type": "CONTRIBUTION", "amount": 1000, "units": 0, "trade_date": "2026-01-05"},
        {"type": "BUY", "symbol": {"raw_symbol": "AAA"}, "amount": -500, "units": 10, "trade_date": "2026-01-06"},
        {"type": "CONTRIBUTION", "amount": 200, "units": 0, "trade_date": "2026-01-07"},
    ]
    closes = _closes("AAA", [("2026-01-05", 50), ("2026-01-06", 50), ("2026-01-07", 60)])
    # Cash 700 and 10 shares at 60 is 1300. Equity matches, so the pin does not move the last point.
    starting, points, note, day_pnl, day_pct = rebuild_equity_points(
        cash=700,
        equity=1300,
        positions={"AAA": 10},
        activities=activities,
        closes=closes,
        as_of=date(2026, 1, 7),
    )
    assert starting == 1000
    assert points[-1]["portfolio_value"] == 1300
    assert points[-1]["cumulative_pl"] == 100
    assert day_pnl == 100
    assert day_pct == 10
    assert "Deposits" in note or "deposits" in note
    assert all(point["cumulative_pl"] <= 100 for point in points)


def test_split_adds_shares_and_does_not_add_cash() -> None:
    activities = [
        {"type": "CONTRIBUTION", "amount": 500, "units": 0, "trade_date": "2026-01-05"},
        {"type": "BUY", "symbol": {"raw_symbol": "AAA"}, "amount": -500, "units": 10, "trade_date": "2026-01-05"},
        {"type": "SPLIT", "symbol": {"raw_symbol": "AAA"}, "amount": 500, "units": 10, "trade_date": "2026-01-06"},
    ]
    closes = _closes("AAA", [("2026-01-05", 50), ("2026-01-06", 25)])
    _starting, points, _note, _day, _pct = rebuild_equity_points(
        cash=0,
        equity=500,
        positions={"AAA": 20},
        activities=activities,
        closes=closes,
        as_of=date(2026, 1, 6),
    )
    assert points[-1]["portfolio_value"] == 500
    assert points[-1]["cumulative_pl"] == 0


def test_day_without_a_close_is_omitted() -> None:
    activities = [
        {"type": "CONTRIBUTION", "amount": 150, "units": 0, "trade_date": "2026-01-05"},
        {"type": "BUY", "symbol": {"raw_symbol": "AAA"}, "amount": -100, "units": 2, "trade_date": "2026-01-05"},
        {"type": "BUY", "symbol": {"raw_symbol": "BBB"}, "amount": -50, "units": 1, "trade_date": "2026-01-05"},
    ]
    closes = {
        "AAA": {date(2026, 1, 5): 50},
        "BBB": {date(2026, 1, 5): 50, date(2026, 1, 20): 55},
    }
    _starting, points, note, _day, _pct = rebuild_equity_points(
        cash=0,
        equity=150,
        positions={"AAA": 2, "BBB": 1},
        activities=activities,
        closes=closes,
        as_of=date(2026, 1, 20),
    )
    assert len(points) == 1
    assert str(points[0]["t"]).startswith("2026-01-05")
    assert "left out" in note
