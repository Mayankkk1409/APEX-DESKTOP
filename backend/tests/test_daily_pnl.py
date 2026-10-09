from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.trading import Position
from app.adapters.demo import _price_at
from app.services.daily_pnl import (
    assemble_daily_pnl,
    bars_from_option_snapshot,
    book_daily_pnl,
    clear_daily_mark_cache,
    position_daily_pnl,
)


@pytest.fixture(autouse=True)
def _isolated_mark_cache():
    clear_daily_mark_cache()
    yield
    clear_daily_mark_cache()


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


def test_book_sums_marked_positions_when_another_lacks_a_price() -> None:
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
    assert book[1] == {"date": "2026-10-06", "pnl": 2.0, "status": "marked"}


def test_book_unavailable_only_when_no_position_has_a_mark() -> None:
    book = book_daily_pnl(
        [
            [{"date": "2026-10-06", "pnl": None, "status": "unavailable"}],
            [{"date": "2026-10-06", "pnl": None, "status": "unavailable"}],
        ]
    )
    assert book == [{"date": "2026-10-06", "pnl": None, "status": "unavailable"}]


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

    clear_daily_mark_cache()
    empty = await assemble_daily_pnl(
        [pos],
        _Bars([], SimpleNamespace(price=50.0, status="live", source="demo", asset_class="us_equity")),
        as_of=date(2026, 10, 6),
    )
    assert empty["positions"][0]["days"]
    assert all(row["pnl"] is None and row["status"] == "unavailable" for row in empty["positions"][0]["days"])
    assert all(row["pnl"] is None for row in empty["book"])


def test_option_snapshot_bars_keep_session_closes_and_skip_a_same_day_trade() -> None:
    bars = bars_from_option_snapshot(
        {
            "snapshots": {
                "AAPL261030P00320000": {
                    "prevDailyBar": {"t": "2026-10-05T04:00:00Z", "c": 3.98},
                    "dailyBar": {"t": "2026-10-06T04:00:00Z", "c": 3.58},
                    "latestTrade": {"t": "2026-10-06T19:54:50Z", "p": 3.58},
                    "latestQuote": {"bp": 3.34, "ap": 3.78, "t": "2026-10-06T19:59:59Z"},
                }
            }
        },
        "AAPL261030P00320000",
    )
    assert [row["c"] for row in bars] == [3.98, 3.58]


class _OptionBook:
    def __init__(self) -> None:
        self.quoted: list[str] = []

    async def option_snapshot_bars(self, symbols: list[str]) -> dict[str, list[dict]]:
        assert symbols == ["AAPL261030P00320000"]
        return {
            "AAPL261030P00320000": [
                {"t": "2026-10-05T04:00:00Z", "c": 3.98},
                {"t": "2026-10-06T04:00:00Z", "c": 3.58},
            ]
        }

    async def vendor_daily_bars(self, symbol: str, *, start: str, end: str) -> list[dict]:
        raise AssertionError(f"stock history should not replace the option snapshot for {symbol}")

    async def quote(self, symbol: str) -> SimpleNamespace:
        self.quoted.append(symbol)
        raise AssertionError("stock quote path cannot price an option contract")


@pytest.mark.asyncio
async def test_assemble_marks_option_sessions_from_snapshot_not_demo_price() -> None:
    symbol = "AAPL261030P00320000"
    pos = Position(
        id="opt",
        user_id="u1",
        symbol=symbol,
        qty=1,
        avg_cost=3.71,
        current_price=_price_at(symbol, datetime.now(timezone.utc)),
        asset_class="us_option",
        created_at=datetime(2026, 10, 5, 19, 29, tzinfo=timezone.utc),
    )
    book = _OptionBook()
    payload = await assemble_daily_pnl([pos], book, as_of=date(2026, 10, 6))
    days = payload["positions"][0]["days"]
    assert [row["date"] for row in days] == ["2026-10-05", "2026-10-06"]
    assert days[0]["pnl"] == pytest.approx(27.0)
    assert days[1]["pnl"] == pytest.approx(-40.0)
    assert payload["book"][1]["status"] == "marked"
    assert book.quoted == []


@pytest.mark.asyncio
async def test_assemble_uses_stored_mark_on_entry_day_when_history_is_missing() -> None:
    pos = Position(
        id="opt",
        user_id="u1",
        symbol="AAPL261030C00100000",
        qty=1,
        avg_cost=2.0,
        current_price=2.5,
        asset_class="us_option",
        created_at=datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc),
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars([], SimpleNamespace(price=50.0, status="live", source="demo", asset_class="us_equity")),
        as_of=date(2026, 10, 6),
    )
    days = payload["positions"][0]["days"]
    assert [row["date"] for row in days] == ["2026-10-06"]
    assert days[0]["status"] == "marked"
    assert days[0]["pnl"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_assemble_ignores_demo_option_price_when_nothing_else_is_marked() -> None:
    symbol = "MSFT261030C00500000"
    pos = Position(
        id="opt",
        user_id="u1",
        symbol=symbol,
        qty=1,
        avg_cost=1.2,
        current_price=_price_at(symbol, datetime.now(timezone.utc)),
        asset_class="us_option",
        created_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars([], SimpleNamespace(price=99.0, status="unavailable", source="demo", asset_class="us_equity")),
        as_of=date(2026, 10, 6),
    )
    assert all(row["status"] == "unavailable" and row["pnl"] is None for row in payload["positions"][0]["days"])
    assert payload["book"][-1]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_assemble_uses_quote_previous_close_when_bars_are_missing() -> None:
    pos = Position(
        id="eq",
        user_id="u1",
        symbol="AAPL",
        qty=1,
        avg_cost=100.0,
        current_price=0.0,
        asset_class="us_equity",
        created_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars(
            [],
            SimpleNamespace(price=110.0, change=1.0, status="live", source="Alpaca", asset_class="us_equity"),
        ),
        as_of=date(2026, 10, 6),
    )
    days = payload["positions"][0]["days"]
    assert days[0]["pnl"] == pytest.approx(9.0)
    assert days[1]["pnl"] == pytest.approx(1.0)
    assert payload["book"][1]["pnl"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_closed_session_without_a_new_print_uses_the_prior_close() -> None:
    pos = Position(
        id="opt",
        user_id="u1",
        symbol="AAPL261030C00100000",
        qty=1,
        avg_cost=2.0,
        current_price=0.0,
        asset_class="us_option",
        created_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars([{"t": "2026-10-05T20:00:00Z", "c": 2.25}], SimpleNamespace(price=9.0, status="unavailable", source="demo")),
        as_of=date(2026, 10, 6),
    )
    days = payload["positions"][0]["days"]
    assert days[0]["pnl"] == pytest.approx(25.0)
    assert days[1]["status"] == "marked"
    assert days[1]["pnl"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_demo_option_fill_is_not_an_entry_baseline() -> None:
    symbol = "BAC261016P00052000"
    opened = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    mid = _price_at(symbol, opened)
    pos = Position(
        id="opt",
        user_id="u1",
        symbol=symbol,
        qty=-1,
        avg_cost=round(mid * 0.999, 2),
        current_price=mid,
        asset_class="us_option",
        created_at=opened,
    )
    payload = await assemble_daily_pnl(
        [pos],
        _Bars([{"t": "2026-10-06T20:00:00Z", "c": 0.42}], SimpleNamespace(price=1.0, status="live", source="demo")),
        as_of=date(2026, 10, 6),
    )
    assert payload["positions"][0]["days"][0]["status"] == "unavailable"
    assert payload["positions"][0]["days"][0]["pnl"] is None


class _CountingFeed:
    def __init__(self) -> None:
        self.bars = 0
        self.quotes = 0

    async def vendor_daily_bars(self, symbol: str, *, start: str, end: str) -> list[dict]:
        _ = (symbol, start, end)
        self.bars += 1
        return []

    async def quote(self, symbol: str) -> SimpleNamespace:
        _ = symbol
        self.quotes += 1
        return SimpleNamespace(price=110.0, change=1.0, status="live", source="Alpaca", asset_class="us_equity")


@pytest.mark.asyncio
async def test_second_daily_pnl_reuses_cached_close() -> None:
    pos = Position(
        id="eq",
        user_id="u1",
        symbol="NVDA",
        qty=1,
        avg_cost=100.0,
        current_price=0.0,
        asset_class="us_equity",
        created_at=datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc),
    )
    feed = _CountingFeed()
    first = await assemble_daily_pnl([pos], feed, as_of=date(2026, 10, 6))
    second = await assemble_daily_pnl([pos], feed, as_of=date(2026, 10, 6))
    assert feed.bars == 1
    assert feed.quotes == 1
    assert first["positions"][0]["days"][0]["pnl"] == pytest.approx(9.0)
    assert first["positions"][0]["days"][1]["pnl"] == pytest.approx(1.0)
    assert second["positions"][0]["days"] == first["positions"][0]["days"]
    assert second["book"][1]["pnl"] == pytest.approx(1.0)
