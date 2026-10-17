"""Queued orders wait for a real price. They do not invent one."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.trading import Order, Position, QueuedOrder
from app.models.user import User
from app.services.broker_stream import stream_url
from app.services.order_queue import (
    STOCK_AWAITING,
    STOCK_FILLED_WAIT,
    _link_existing_broker_order,
    _push_order_notices,
    ack_execution_notices,
    align_queued_with_fills,
    apply_trade_update,
    broker_unconfirmed,
    pending_execution_notices,
    price_gap,
    process_queued_orders,
    queue_deadline,
    reconcile_broker_orders,
    session_open,
    trade_update_order,
)


def test_only_a_missing_price_can_queue() -> None:
    assert price_gap("No current price is available. No order was sent. Refresh the quote and try again.")
    assert price_gap(
        "A current price for this strategy is unavailable. No order was sent, "
        "and the strategy was not split into separate orders."
    )
    assert price_gap("Live mid is unavailable, so a limit at mid cannot be priced.")
    assert not price_gap("Insufficient buying power. The account cannot cover the order.")
    assert not price_gap("Leg count 0 does not match the template.")
    assert not price_gap("This price is more than 5 minutes old. No order was sent.")
    assert not price_gap("We couldn't confirm when this price was quoted. No order was sent.")
    assert not price_gap("Bid/ask spread is 12% of mid, wider than the 10% cap.")
    assert not price_gap("No current price is available. Insufficient buying power.")
    assert not broker_unconfirmed("No current price is available. No order was sent.")


def test_broker_hold_is_queued_and_not_a_price_gap() -> None:
    text = (
        "The broker received this order but has not confirmed a fill. "
        "Check its status before sending another order."
    )
    assert broker_unconfirmed(text)
    assert not price_gap(text)
    assert not broker_unconfirmed("Insufficient buying power. The account cannot cover the order.")


def test_weekend_is_closed_and_monday_session_is_open() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    monday = datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)  # 10:00 New York
    assert session_open(saturday) is False
    assert session_open(monday) is True


def test_saturday_queue_lasts_through_monday_close_not_forever() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    deadline = queue_deadline(saturday, ["2026-10-16"])
    assert deadline.isoformat().startswith("2026-10-12")
    assert deadline.hour in {20, 21}  # 16:00 New York in October is 20:00 UTC


def test_sqlite_deadline_without_a_timezone_still_compares() -> None:
    from app.services.order_queue import _as_utc

    stored = datetime(2026, 10, 12, 20, 0, 0)
    now = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    assert _as_utc(stored) > now


def test_an_earlier_contract_expiry_caps_the_queue() -> None:
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    deadline = queue_deadline(saturday, ["2026-10-09"])
    assert deadline.date().isoformat() == "2026-10-09"


def _quote(when: datetime):
    return SimpleNamespace(bid=1.10, ask=1.20, price=1.15, as_of=when.isoformat())


async def _queue_db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _seed(session: AsyncSession, *, mode: str, now: datetime) -> str:
    user = User(
        full_name="Queue Test",
        username=f"queue-{mode}",
        email=f"{mode}@example.com",
        password_hash="not-a-real-hash",
        account_mode=mode,
        cash_balance=25000,
        buying_power=25000,
        portfolio_value=25000,
    )
    session.add(user)
    await session.flush()
    row = QueuedOrder(
        user_id=user.id,
        strategy_name="Bull Call Spread",
        symbol="VZ261113C00042000",
        side="buy",
        qty=1,
        payload={
            "legs": [
                {
                    "symbol": "VZ261113C00042000",
                    "side": "buy",
                    "expiry": "2026-11-13",
                    "limit_price": 1.74,
                    "price": 1.74,
                }
            ],
            "contracts_per_leg": 1,
            "equity_legs": [],
        },
        status="queued",
        reason="waiting for a price",
        expires_at=datetime(2026, 10, 12, 20, 0, 0),
    )
    session.add(row)
    await session.commit()
    return row.id


@pytest.mark.asyncio
async def test_closed_session_waits_and_an_open_session_submits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = await _queue_db()
    calls: list[str] = []

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)), None

    async def _execute(**kwargs):
        calls.append(kwargs["submission_path"])
        return [SimpleNamespace(id="order-1", status="filled", broker_order_id="paper-1")]

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    saturday = datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc)
    async with factory() as session:
        queued_id = await _seed(session, mode="paper_funded", now=saturday)
        started = await process_queued_orders(session, adapter=object(), now=saturday)
        row = await session.get(QueuedOrder, queued_id)
        assert started == 0
        assert calls == []
        assert row is not None and row.status == "queued"
        assert row.reason.startswith("Queued — market closed")
        monday = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
        started = await process_queued_orders(session, adapter=object(), now=monday)
        row = await session.get(QueuedOrder, queued_id)
        assert started == 1
        assert calls == ["queued_order"]
        assert row is not None and row.status == "filled"
        again = await process_queued_orders(session, adapter=object(), now=monday + timedelta(minutes=1))
        assert again == 0
        assert calls == ["queued_order"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_quote_stays_queued_and_read_only_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = await _queue_db()
    calls: list[str] = []

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)), (
            "This price is more than 5 minutes old. No order was sent. Refresh the quote and try again."
        )

    async def _execute(**_kwargs):
        calls.append("sent")
        return []

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    monday = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    async with factory() as session:
        queued_id = await _seed(session, mode="paper_funded", now=monday)
        started = await process_queued_orders(session, adapter=object(), now=monday)
        row = await session.get(QueuedOrder, queued_id)
        assert started == 0
        assert calls == []
        assert row is not None and row.status == "queued"
        assert "more than 5 minutes" in row.reason
    async with factory() as session:
        user = User(
            full_name="Broker Test",
            username="queue-broker",
            email="broker@example.com",
            password_hash="not-a-real-hash",
            account_mode="real_brokerage",
            cash_balance=0,
            buying_power=0,
            portfolio_value=0,
        )
        session.add(user)
        await session.flush()
        row = QueuedOrder(
            user_id=user.id,
            strategy_name="Bull Call Spread",
            symbol="VZ261113C00042000",
            side="buy",
            qty=1,
            payload={"legs": [{"symbol": "VZ261113C00042000", "side": "buy", "expiry": "2026-11-13", "limit_price": 1}], "equity_legs": []},
            status="queued",
            reason="waiting for a price",
            expires_at=datetime(2026, 10, 12, 20, 0, 0),
        )
        session.add(row)
        await session.commit()
        started = await process_queued_orders(session, adapter=object(), now=monday)
        fresh = await session.get(QueuedOrder, row.id)
        assert started == 0
        assert calls == []
        assert fresh is not None and fresh.status == "queued"
        assert "read-only" not in (fresh.reason or "")
        assert "more than 5 minutes" in fresh.reason
    await engine.dispose()


@pytest.mark.asyncio
async def test_wide_spread_stays_queued_and_inactive_rows_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.order_queue import archive_queued, cancel_queued

    engine, factory = await _queue_db()

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)), None

    async def _execute(**_kwargs):
        raise ValueError("Bid/ask spread is 15.4% of mid, wider than the 10% cap.")

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    monday = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    async with factory() as session:
        queued_id = await _seed(session, mode="paper_funded", now=monday)
        started = await process_queued_orders(session, adapter=object(), now=monday)
        row = await session.get(QueuedOrder, queued_id)
        assert started == 0
        assert row is not None and row.status == "rejected"
        assert "15.4%" in row.reason
        assert await archive_queued(session, row.user_id, queued_id) == "archived"
        queued_id = await _seed(session, mode="paper_second", now=monday)
        row = await session.get(QueuedOrder, queued_id)
        assert row is not None
        assert await cancel_queued(session, row.user_id, queued_id) is True
        fresh = await session.get(QueuedOrder, queued_id)
        assert fresh is not None and fresh.status == "canceled"
        assert await archive_queued(session, fresh.user_id, queued_id) == "archived"
        gone = await session.get(QueuedOrder, queued_id)
        assert gone is not None and gone.status == "archived"
        held = QueuedOrder(
            user_id=fresh.user_id,
            strategy_name="Collar",
            symbol="SBUX261030P00086000",
            side="buy",
            qty=1,
            payload={"hold_only": True, "legs": []},
            status="rejected",
            reason="broker",
            broker_order_id="broker-1",
            expires_at=datetime(2026, 10, 12, 20, 0, 0),
        )
        session.add(held)
        await session.commit()
        assert await archive_queued(session, fresh.user_id, held.id) == "broker"
        assert await cancel_queued(session, fresh.user_id, held.id) is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_stuck_submitting_row_is_checked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = await _queue_db()
    sent: list[dict] = []

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)), None

    async def _execute(**kwargs):
        sent.append(kwargs)
        return [SimpleNamespace(status="accepted", id="ord-1", broker_order_id="brk-1")]

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    monday = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    async with factory() as session:
        queued_id = await _seed(session, mode="paper_funded", now=monday)
        row = await session.get(QueuedOrder, queued_id)
        assert row is not None
        row.status = "submitting"
        payload = dict(row.payload or {})
        legs = list(payload.get("legs") or [])
        legs[0]["limit_price"] = 0.10
        legs[0]["price"] = 0.10
        payload["legs"] = legs
        row.payload = payload
        await session.commit()
        started = await process_queued_orders(session, adapter=object(), now=monday)
        fresh = await session.get(QueuedOrder, queued_id)
        assert started == 1
        assert len(sent) == 1
        assert sent[0]["legs"][0]["limit_price"] == 0.10
        assert fresh is not None and fresh.status == "accepted"
        assert fresh.broker_order_id == "brk-1"
        assert "awaiting execution" in fresh.reason
    await engine.dispose()


@pytest.mark.asyncio
async def test_paper_crossing_limit_lifts_the_offer() -> None:
    from app.services.fills import _paper_crossing_limit

    class _Quotes:
        async def quote(self, symbol: str):
            if symbol.endswith("A"):
                return SimpleNamespace(bid=1.0, ask=1.20)
            return SimpleNamespace(bid=0.40, ask=0.50)

    price = await _paper_crossing_limit(
        _Quotes(),
        [{"symbol": "A", "side": "buy"}, {"symbol": "B", "side": "sell"}],
    )
    assert price == 0.81


@pytest.mark.asyncio
async def test_a_hold_without_an_id_links_the_open_broker_order() -> None:
    engine, factory = await _queue_db()

    class _Broker:
        async def list_orders(self, *, status: str = "open", limit: int = 50):
            return [
                {
                    "id": "alpaca-vz-1",
                    "status": "new",
                    "limit_price": "-0.13",
                    "legs": [
                        {"symbol": "VZ261030P00040000"},
                        {"symbol": "VZ261030P00039000"},
                    ],
                }
            ]

    async with factory() as session:
        queued_id = await _seed(session, mode="paper_link", now=datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc))
        row = await session.get(QueuedOrder, queued_id)
        assert row is not None
        row.symbol = "VZ261030P00040000"
        row.payload = {
            "hold_only": True,
            "legs": [
                {"symbol": "VZ261030P00040000", "side": "sell", "expiry": "2026-10-30", "limit_price": 0.38},
                {"symbol": "VZ261030P00039000", "side": "buy", "expiry": "2026-10-30", "limit_price": 0.25},
            ],
        }
        await session.commit()
        linked = await _link_existing_broker_order(session, _Broker(), row)
        fresh = await session.get(QueuedOrder, queued_id)
        saved = await session.scalar(select(Order).where(Order.broker_order_id == "alpaca-vz-1"))
        assert linked is True
        assert fresh is not None and fresh.status == "accepted"
        assert fresh.broker_order_id == "alpaca-vz-1"
        assert "awaiting execution" in (fresh.reason or "")
        assert saved is not None and saved.status == "accepted"
    await engine.dispose()


@pytest.mark.asyncio
async def test_broker_status_updates_a_fill_and_ignores_a_failed_read() -> None:
    engine, factory = await _queue_db()

    class _Broker:
        def __init__(self) -> None:
            self.calls = 0

        async def get_order(self, broker_order_id: str) -> dict | None:
            self.calls += 1
            if broker_order_id == "missing":
                return None
            if broker_order_id == "filled":
                return {"status": "filled", "filled_avg_price": "0.42", "filled_qty": "1"}
            return {"status": "accepted"}

    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="paper@example.com",
            username="paper",
            password_hash="x",
            account_mode="paper_funded",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        quiet = Order(
            user_id=user.id,
            symbol="MRK",
            side="buy",
            qty=1,
            order_type="limit",
            limit_price=0.12,
            status="accepted",
            venue="paper",
            broker_order_id="missing",
            asset_class="us_option",
        )
        done = Order(
            user_id=user.id,
            symbol="PYPL",
            side="buy",
            qty=1,
            order_type="limit",
            limit_price=0.02,
            status="accepted",
            venue="paper",
            broker_order_id="filled",
            asset_class="us_option",
        )
        session.add_all([quiet, done])
        await session.commit()
        changed = await reconcile_broker_orders(session, _Broker())
        await session.refresh(quiet)
        await session.refresh(done)
        assert changed == 1
        assert quiet.status == "accepted"
        assert quiet.fill_price is None
        assert done.status == "filled"
        assert done.fill_price == 0.42
        assert done.filled_qty == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_credit_fill_books_the_absolute_price() -> None:
    engine, factory = await _queue_db()

    class _Broker:
        async def get_order(self, broker_order_id: str) -> dict:
            return {
                "status": "filled",
                "filled_avg_price": "-0.80",
                "filled_qty": "1",
                "legs": [
                    {"symbol": "AAPL261120P00320000", "side": "sell", "filled_avg_price": "3.9", "ratio_qty": "1"},
                    {"symbol": "AAPL261120P00315000", "side": "buy", "filled_avg_price": "3.1", "ratio_qty": "1"},
                ],
            }

    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="credit@example.com",
            username="credit",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        order = Order(
            user_id=user.id,
            symbol="AAPL",
            side="sell",
            qty=1,
            order_type="limit",
            limit_price=0.77,
            status="accepted",
            venue="paper",
            broker_order_id="credit-1",
            asset_class="us_option",
            multiplier=100,
        )
        waiting = QueuedOrder(
            user_id=user.id,
            symbol="AAPL261120P00320000",
            side="sell",
            qty=1,
            order_type="limit",
            payload={"legs": []},
            status="accepted",
            reason="Order submitted to Alpaca — awaiting execution.",
            expires_at=datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc),
            broker_order_id="credit-1",
        )
        session.add_all([order, waiting])
        await session.commit()
        changed = await reconcile_broker_orders(session, _Broker())
        await session.refresh(user)
        await session.refresh(order)
        await session.refresh(waiting)
        assert changed == 1
        assert order.status == "filled"
        assert order.fill_price == 0.80
        assert user.cash_balance == pytest.approx(10_080)
        assert user.buying_power == pytest.approx(10_080)
        assert waiting.status == "filled"
        positions = (await session.scalars(select(Position).where(Position.user_id == user.id))).all()
        booked = {row.symbol: row.qty for row in positions}
        assert booked["AAPL261120P00320000"] == -1
        assert booked["AAPL261120P00315000"] == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_filled_stock_sends_options_once_and_does_not_buy_shares_again(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = await _queue_db()
    sent: list[dict] = []

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)), None

    async def _execute(**kwargs):
        sent.append(kwargs)
        return [SimpleNamespace(status="filled", id="opt-1", broker_order_id="opt-broker")]

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    closed = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)  # after the close
    opened = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)  # 10:00 New York
    async with factory() as session:
        user = User(
            full_name="Collar",
            username="collar",
            email="collar@example.com",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=50_000,
            buying_power=50_000,
            portfolio_value=50_000,
        )
        session.add(user)
        await session.flush()
        stock = Order(
            user_id=user.id,
            symbol="BRK.B",
            side="buy",
            qty=100,
            order_type="market",
            status="filled",
            fill_price=521.63,
            filled_qty=100,
            asset_class="us_equity",
            multiplier=1,
            broker_order_id="stock-1",
        )
        session.add(stock)
        await session.flush()
        row = QueuedOrder(
            user_id=user.id,
            strategy_name="Collar",
            symbol="BRKB261106P00510000",
            side="buy",
            qty=1,
            payload={
                "contracts_per_leg": 1,
                "equity_satisfied": True,
                "equity_legs": [],
                "stock_order_id": stock.id,
                "legs": [
                    {"symbol": "BRKB261106P00510000", "side": "buy", "expiry": "2026-11-06", "limit_price": 2.97},
                    {"symbol": "BRKB261106C00530000", "side": "sell", "expiry": "2026-11-06", "limit_price": 2.89},
                ],
            },
            status="queued",
            reason="The stock filled. The option legs will be sent when the market opens, if they remain valid.",
            expires_at=datetime(2026, 10, 15, 20, 0),
        )
        session.add(row)
        await session.commit()

        closed_pass = await process_queued_orders(session, adapter=object(), now=closed)
        waiting = await session.get(QueuedOrder, row.id)
        assert closed_pass == 0
        assert sent == []
        assert waiting is not None and waiting.status == "queued"
        assert waiting.reason == STOCK_FILLED_WAIT

        opened_pass = await process_queued_orders(session, adapter=object(), now=opened)
        assert opened_pass == 1
        assert len(sent) == 1
        assert sent[0]["equity_satisfied"] is True
        assert sent[0]["equity_legs"] is None
        assert [leg["symbol"] for leg in sent[0]["legs"]] == [
            "BRKB261106P00510000",
            "BRKB261106C00530000",
        ]
        done = await session.get(QueuedOrder, row.id)
        assert done is not None and done.status == "filled"

        again = await process_queued_orders(session, adapter=object(), now=opened + timedelta(minutes=1))
        assert again == 0
        assert len(sent) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_resting_stock_order_is_not_sent_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.fills import StockLegAwaiting

    engine, factory = await _queue_db()
    sent: list[dict] = []

    async def _load(_adapter, _symbol):
        return _quote(datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)), None

    async def _execute(**kwargs):
        sent.append(kwargs)
        raise StockLegAwaiting("stock-order", "stock-broker")

    monkeypatch.setattr("app.services.executability.load_submission_quote", _load)
    monkeypatch.setattr("app.services.fills.execute_strategy_legs", _execute)
    opened = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
    async with factory() as session:
        queued_id = await _seed(session, mode="paper_stock", now=opened)
        row = await session.get(QueuedOrder, queued_id)
        assert row is not None
        row.payload = {
            "contracts_per_leg": 1,
            "equity_legs": [{"symbol": "BRK.B", "side": "buy", "qty": 100}],
            "legs": [
                {"symbol": "BRKB261106P00510000", "side": "buy", "expiry": "2026-11-06", "limit_price": 2.97},
                {"symbol": "BRKB261106C00530000", "side": "sell", "expiry": "2026-11-06", "limit_price": 2.89},
            ],
        }
        row.expires_at = datetime(2026, 10, 15, 20, 0)
        await session.commit()
        started = await process_queued_orders(session, adapter=object(), now=opened)
        fresh = await session.get(QueuedOrder, queued_id)
        assert started == 0
        assert len(sent) == 1
        assert fresh is not None and fresh.status == "queued"
        assert fresh.reason == STOCK_AWAITING
        assert fresh.payload["stock_order_id"] == "stock-order"
    await engine.dispose()


def test_trade_update_keeps_the_order_and_drops_acks() -> None:
    order = trade_update_order(
        {
            "stream": "trade_updates",
            "data": {"event": "fill", "order": {"id": "abc", "status": "filled", "filled_avg_price": "-0.8"}},
        }
    )
    assert order is not None and order["id"] == "abc"
    assert trade_update_order({"stream": "authorization", "data": {"status": "authorized"}}) is None
    assert stream_url("https://paper-api.alpaca.markets") == "wss://paper-api.alpaca.markets/stream"


@pytest.mark.asyncio
async def test_a_replayed_broker_fill_is_booked_and_pushed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, factory = await _queue_db()
    pushed: list[dict] = []

    async def _broadcast(_user_id: str, payload: dict) -> None:
        pushed.append(payload)

    monkeypatch.setattr("app.ws.hub.hub.broadcast", _broadcast)
    body = {
        "id": "fill-1",
        "status": "filled",
        "filled_avg_price": "-0.80",
        "filled_qty": "1",
        "legs": [
            {"symbol": "AAPL261120P00320000", "side": "sell", "filled_avg_price": "3.9", "ratio_qty": "1"},
            {"symbol": "AAPL261120P00315000", "side": "buy", "filled_avg_price": "3.1", "ratio_qty": "1"},
        ],
    }
    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="replay@example.com",
            username="replay",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
            portfolio_value=10_000,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            Order(
                user_id=user.id,
                symbol="AAPL",
                side="sell",
                qty=1,
                order_type="limit",
                limit_price=0.77,
                status="accepted",
                venue="paper",
                broker_order_id="fill-1",
                asset_class="us_option",
                multiplier=100,
            )
        )
        await session.commit()
        first = await apply_trade_update(session, body)
        assert first is not None
        await session.commit()
        await _push_order_notices([first])
        second = await apply_trade_update(session, body)
        assert second is None
        await session.refresh(user)
        assert user.cash_balance == pytest.approx(10_080)
        booked = {
            row.symbol: row.qty
            for row in (await session.scalars(select(Position).where(Position.user_id == user.id))).all()
        }
        assert booked["AAPL261120P00320000"] == -1
        assert booked["AAPL261120P00315000"] == 1
    assert len(pushed) == 1
    assert pushed[0]["type"] == "fill"
    assert pushed[0]["status"] == "filled"
    assert pushed[0]["balance"] == pytest.approx(10_080)
    assert pushed[0]["buying_power"] == pytest.approx(10_080)
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_later_partial_adds_only_the_new_contracts() -> None:
    engine, factory = await _queue_db()
    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="partial@example.com",
            username="partial",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            Order(
                user_id=user.id,
                symbol="F",
                side="buy",
                qty=2,
                order_type="market",
                status="accepted",
                venue="paper",
                broker_order_id="partial-1",
                asset_class="us_equity",
                multiplier=1,
            )
        )
        await session.commit()
        first = await apply_trade_update(
            session,
            {"id": "partial-1", "status": "partially_filled", "filled_avg_price": "10", "filled_qty": "1"},
        )
        assert first is not None
        await session.commit()
        second = await apply_trade_update(
            session,
            {"id": "partial-1", "status": "filled", "filled_avg_price": "11", "filled_qty": "2"},
        )
        assert second is not None
        await session.commit()
        await session.refresh(user)
        assert user.cash_balance == pytest.approx(9_978)
        position = await session.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == "F"))
        assert position is not None
        assert position.qty == 2
        third = await apply_trade_update(
            session,
            {"id": "partial-1", "status": "filled", "filled_avg_price": "11", "filled_qty": "2"},
        )
        assert third is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_combo_fill_without_legs_books_the_reread_and_not_the_stock() -> None:
    engine, factory = await _queue_db()

    class _Broker:
        async def get_order(self, _broker_order_id: str) -> dict:
            return {
                "id": "combo-1",
                "status": "filled",
                "filled_avg_price": "-1.05",
                "filled_qty": "1",
                "legs": [
                    {"symbol": "TJX270115P00130000", "side": "sell", "filled_avg_price": "2.15", "ratio_qty": "1"},
                    {"symbol": "TJX270115P00125000", "side": "buy", "filled_avg_price": "1.50", "ratio_qty": "1"},
                ],
            }

    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="combo@example.com",
            username="combo",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        session.add(
            Order(
                user_id=user.id,
                symbol="TJX",
                side="sell",
                qty=1,
                order_type="limit",
                status="accepted",
                venue="paper",
                broker_order_id="combo-1",
                asset_class="us_option",
                multiplier=100,
            )
        )
        await session.commit()
        notice = await apply_trade_update(
            session,
            {"id": "combo-1", "status": "filled", "filled_avg_price": "-1.05", "filled_qty": "1"},
            _Broker(),
        )
        assert notice is not None
        await session.commit()
        await session.refresh(user)
        assert user.cash_balance == pytest.approx(10_105)
        booked = {
            row.symbol: row.qty
            for row in (await session.scalars(select(Position).where(Position.user_id == user.id))).all()
        }
        assert "TJX" not in booked
        assert booked["TJX270115P00130000"] == -1
        assert booked["TJX270115P00125000"] == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_filled_broker_order_leaves_the_queue_and_can_be_announced_once() -> None:
    engine, factory = await _queue_db()
    async with factory() as session:
        user = User(
            full_name="Paper Test",
            email="announce@example.com",
            username="announce",
            password_hash="x",
            account_mode="paper_funded",
            cash_balance=10_000,
            buying_power=10_000,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        filled = Order(
            user_id=user.id,
            symbol="AAPL",
            side="sell",
            qty=1,
            order_type="limit",
            status="filled",
            fill_price=0.80,
            filled_qty=1,
            venue="paper",
            broker_order_id="filled-queue-1",
            asset_class="us_option",
            multiplier=100,
        )
        stock = Order(
            user_id=user.id,
            symbol="BRK.B",
            side="buy",
            qty=100,
            order_type="market",
            status="filled",
            fill_price=521.632,
            filled_qty=100,
            venue="paper",
            broker_order_id="stock-only",
            asset_class="us_equity",
            multiplier=1,
        )
        session.add_all([filled, stock])
        await session.commit()
        await session.refresh(filled)
        await session.refresh(stock)
        waiting = QueuedOrder(
            user_id=user.id,
            symbol="AAPL261120P00320000",
            side="sell",
            qty=1,
            order_type="limit",
            payload={"legs": []},
            status="queued",
            reason="Order submitted to Alpaca — awaiting execution.",
            expires_at=datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc),
            broker_order_id="filled-queue-1",
        )
        collar = QueuedOrder(
            user_id=user.id,
            symbol="BRKB261106P00510000",
            side="buy",
            qty=1,
            order_type="limit",
            payload={"legs": [], "stock_order_id": stock.id, "equity_satisfied": True},
            status="queued",
            reason="The stock filled. The option legs will be sent when the market opens, if they remain valid.",
            expires_at=datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc),
        )
        session.add_all([waiting, collar])
        await session.commit()
        changed = await align_queued_with_fills(session)
        assert changed == 1
        await session.refresh(waiting)
        await session.refresh(collar)
        assert waiting.status == "filled"
        assert collar.status == "queued"
        notices = await pending_execution_notices(session, user.id)
        assert [row["id"] for row in notices] == [waiting.id]
        assert notices[0]["fill_price"] == pytest.approx(0.80)
        assert await ack_execution_notices(session, user.id, [waiting.id]) == 1
        assert await pending_execution_notices(session, user.id) == []
    await engine.dispose()
