from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.trading import Position
from app.services.daily_pnl import assemble_daily_pnl, book_daily_pnl, position_daily_pnl


def test_position_daily_pnl_renders_each_session_and_keeps_a_gap() -> None:
    days = position_daily_pnl(
        opened_on=date(2026, 10, 5),
        as_of=date(2026, 10, 7),
        avg_cost=100.0,
        qty=2,
        multiplier=1,
        closes={
            date(2026, 10, 5): 110.0,
            date(2026, 10, 7): 120.0,
        },
    )
    assert [row["date"] for row in days] == ["2026-10-05", "2026-10-06", "2026-10-07"]
    assert days[0]["status"] == "marked"
    assert days[0]["pnl"] == pytest.approx(20.0)
    assert days[1]["status"] == "unavailable"
    assert days[1]["pnl"] is None
    # Wednesday has a close, but Tuesday has none, so the change is not invented.
    assert days[2]["status"] == "unavailable"
    assert days[2]["pnl"] is None


def test_position_daily_pnl_marks_consecutive_sessions() -> None:
    days = position_daily_pnl(
        opened_on=date(2026, 10, 5),
        as_of=date(2026, 10, 7),
        avg_cost=2.0,
        qty=1,
        multiplier=100,
        closes={
            date(2026, 10, 5): 2.0,
            date(2026, 10, 6): 2.25,
            date(2026, 10, 7): 2.0,
        },
    )
    assert [row["pnl"] for row in days] == [0.0, 25.0, -25.0]
    assert all(row["status"] == "marked" for row in days)


def test_weekend_is_not_a_session_and_monday_uses_friday_close() -> None:
    days = position_daily_pnl(
        opened_on=date(2026, 10, 2),
        as_of=date(2026, 10, 5),
        avg_cost=100.0,
        qty=1,
        multiplier=1,
        closes={date(2026, 10, 2): 100.0, date(2026, 10, 5): 103.0},
    )
    assert [row["date"] for row in days] == ["2026-10-02", "2026-10-05"]
    assert days[1]["pnl"] == pytest.approx(3.0)


def test_live_mark_is_today_only() -> None:
    days = position_daily_pnl(
        opened_on=date(2026, 10, 5),
        as_of=date(2026, 10, 6),
        avg_cost=100.0,
        qty=1,
        multiplier=1,
        closes={date(2026, 10, 5): 101.0, date(2026, 10, 6): 102.0},
        live_mark=105.0,
    )
    assert days[0]["pnl"] == pytest.approx(1.0)
    assert days[1]["pnl"] == pytest.approx(4.0)


def test_book_unavailable_when_any_position_lacks_a_mark() -> None:
    book = book_daily_pnl(
        [
            [
                {"date": "2026-10-05", "pnl": 10.0, "status": "marked"},
                {"date": "2026-10-06", "pnl": 2.0, "status": "marked"},
            ],
            [
                {"date": "2026-10-06", "pnl": None, "status": "unavailable"},
            ],
        ]
    )
    assert book[0] == {"date": "2026-10-05", "pnl": 10.0, "status": "marked"}
    assert book[1]["date"] == "2026-10-06"
    assert book[1]["status"] == "unavailable"
    assert book[1]["pnl"] is None


class _Bars:
    def __init__(self, bars: list[dict], quote: SimpleNamespace) -> None:
        self._bars = bars
        self._quote = quote

    async def vendor_daily_bars(self, symbol: str, *, start: str, end: str) -> list[dict]:
        _ = (symbol, start, end)
        return self._bars

    async def quote(self, symbol: str) -> SimpleNamespace:
        _ = symbol
        return self._quote


@pytest.mark.asyncio
async def test_assemble_uses_vendor_closes_and_drops_demo_quotes() -> None:
    pos = Position(
        id="p1",
        user_id="u1",
        symbol="AAPL",
        qty=2,
        avg_cost=100.0,
        current_price=100.0,
        asset_class="us_equity",
        created_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars(
            [
                {"t": "2026-10-05T20:00:00Z", "c": 110.0},
                {"t": "2026-10-06T20:00:00Z", "c": 111.0},
            ],
            SimpleNamespace(price=999.0, status="unavailable", source="demo", asset_class="us_equity"),
        ),
        as_of=date(2026, 10, 6),
    )
    days = payload["positions"][0]["days"]
    assert [row["date"] for row in days] == ["2026-10-05", "2026-10-06"]
    assert days[0]["pnl"] == pytest.approx(20.0)
    assert days[1]["pnl"] == pytest.approx(2.0)
    assert payload["book"][1]["pnl"] == pytest.approx(2.0)

    empty = await assemble_daily_pnl(
        [pos],
        _Bars([], SimpleNamespace(price=50.0, status="live", source="demo", asset_class="us_equity")),
        as_of=date(2026, 10, 6),
    )
    assert empty["positions"][0]["days"]
    assert all(row["pnl"] is None and row["status"] == "unavailable" for row in empty["positions"][0]["days"])
    assert all(row["pnl"] is None for row in empty["book"])
