"""Hold a confirmed order when a price, session, or quote check is not ready.

A resting limit that already has an authorized price is sent to the broker.
The broker holds it until it fills, is canceled, or the day order expires.
A missing price, a stale quote, or a closed session stays in this queue.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Order, QueuedOrder
from app.models.user import User
from app.services.market_session import NY, is_trading_day

_PRICE_GAP = (
    "no current price is available",
    "couldn't get a price",
    "could not get a price",
    "current price for this strategy is unavailable",
    "live quote unavailable",
    "live mid is unavailable",
    "stale or suspect",
    "quote not current",
)

# Sentences that ride along with a price refusal. They are not a second defect.
_PRICE_BOILERPLATE = (
    "no order was sent",
    "the strategy was not split into separate orders",
    "no short leg was submitted",
    "refresh the quote and try again",
    "try again in a moment",
    "so a limit at mid cannot be priced",
    "so a limit at the net mid cannot be priced",
)

# Any of these means something other than a missing live price stopped the order.
_OTHER_BLOCK = (
    "buying power",
    "leg count",
    "bid/ask spread",
    "% of mid",
    "more than 5 minutes",
    "couldn't confirm when",
    "could not confirm when",
    "buy price is below",
    "equity-required",
    "equity legs",
    "strategy legs are required",
    "contracts_per_leg",
    "occ symbol",
    "broker",
    "did not accept",
    "not filled",
    "expired",
    "validation",
    "template",
    "wing",
    "not the strategy",
)

QUEUED_MESSAGE = (
    "A current price is unavailable. Your order is waiting and will be submitted automatically "
    "when the market permits trading and a valid price is available, provided it still meets "
    "your confirmed order terms. You can cancel it before submission."
)

MARKET_CLOSED_REASON = (
    "Queued — market closed. APEX will submit this order when the applicable market opens, if it remains valid."
)

ALPACA_AWAITING = "Order submitted to Alpaca — awaiting execution."

STOCK_AWAITING = (
    "The stock order is at the broker. The option legs will be sent when that fill is confirmed."
)

STOCK_FILLED_WAIT = (
    "The stock filled. The option legs will be sent when the market opens, if they remain valid."
)

UNCONFIRMED_QUEUED_MESSAGE = (
    "Your order is waiting to fill at the broker. You can follow its status in Pending orders."
)

LIMIT_WAIT_REASON = (
    "Your limit has not been reached. This order is waiting in APEX and has not been sent to the broker. "
    "It will be sent only if the market reaches the price you confirmed. Cancel it if you do not want that."
)

SPREAD_WAIT_REASON = (
    "The bid/ask is wider than the 10% limit, so this order is still waiting in APEX. "
    "It has not been sent. It will be sent only if that quote tightens before the queue expires. "
    "Cancel it if you do not want that."
)


def broker_unconfirmed(reason: str) -> bool:
    """The broker already has the order and has not reported a fill."""
    text = reason.lower()
    return "has not confirmed a fill" in text or "broker received this order" in text


def price_gap(reason: str) -> bool:
    """True only when a missing live price is the whole refusal.

    A message that also names buying power, spread, leg shape, a stale quote,
    or any other defect is not a price gap. That order keeps its own popup.
    """
    text = reason.lower()
    if not any(phrase in text for phrase in _PRICE_GAP):
        return False
    stripped = text
    for noise in _PRICE_BOILERPLATE:
        stripped = stripped.replace(noise, "")
    return not any(phrase in stripped for phrase in _OTHER_BLOCK)


async def first_non_price_block(
    adapter: Any,
    legs: list[dict[str, Any]],
    equity_legs: list[dict[str, Any]] | None,
    *,
    spread_confirmed: bool,
    contracts: float,
    spread_max: float,
) -> str | None:
    """Another leg's real defect, if the raised error was only a missing price.

    A missing price on one leg does not hide a spread, a stale quote, or a
    crossed market on another. That other sentence is what the popup should show.
    """
    from app.services.executability import (
        load_submission_quote,
        order_symbols,
        slippage_dollars,
        spread_confirmation_text,
        spread_vs_mid,
    )

    symbols = order_symbols(legs, *[str((row or {}).get("symbol") or "") for row in (equity_legs or [])])
    for symbol in symbols:
        quote, problem = await load_submission_quote(adapter, symbol)
        if problem and not price_gap(problem):
            return problem
        frac = spread_vs_mid(quote)
        if frac is not None and frac > spread_max and not spread_confirmed:
            slip = slippage_dollars(quote, qty=contracts, multiplier=100)
            return spread_confirmation_text(spread_pct=frac, threshold=spread_max, slippage=slip)
    return None


def _as_utc(moment: datetime) -> datetime:
    """SQLite returns queue deadlines without a timezone. They were stored as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def session_open(now: datetime) -> bool:
    local = now.astimezone(NY)
    if not is_trading_day(local.date()):
        return False
    clock = local.timetz().replace(tzinfo=None)
    return time(9, 30) <= clock < time(16, 0)


def queue_deadline(now: datetime, expiries: list[str]) -> datetime:
    """Close of this session, or of the next trading day when the market is shut."""
    local = now.astimezone(NY)
    day = local.date()
    if is_trading_day(day) and local.timetz().replace(tzinfo=None) < time(16, 0):
        close_day = day
    else:
        close_day = day + timedelta(days=1)
        for _ in range(14):
            if is_trading_day(close_day):
                break
            close_day += timedelta(days=1)
    close = datetime.combine(close_day, time(16, 0), tzinfo=NY)
    for raw in expiries:
        try:
            exp = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        exp_close = datetime.combine(exp, time(16, 0), tzinfo=NY)
        if exp_close < close:
            close = exp_close
    return close.astimezone(timezone.utc)


def _authorized_limits(legs: list[dict[str, Any]]) -> bool:
    for leg in legs:
        if str(leg.get("side") or "").lower() not in {"buy", "sell"}:
            return False
        raw = leg.get("limit_price")
        if raw is None:
            raw = leg.get("price")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            return False
        if price <= 0:
            return False
    return bool(legs)


def _within_limit(side: str, live: float, authorized: float) -> bool:
    if side == "buy":
        return live <= authorized + 0.001
    return live >= authorized - 0.001


async def enqueue_price_gap(
    db: AsyncSession,
    *,
    user: User,
    reason: str,
    legs: list[dict[str, Any]],
    qty: float,
    strategy_name: str | None,
    scan_id: str | None,
    equity_legs: list[dict[str, Any]] | None,
    thesis_accepted: bool,
    now: datetime | None = None,
) -> QueuedOrder | None:
    """Persist a queue row. None when this failure must stay a refusal."""
    if not thesis_accepted or not price_gap(reason) or not _authorized_limits(legs):
        return None
    clock = now or datetime.now(timezone.utc)
    expiries = [str(leg.get("expiry") or "") for leg in legs if leg.get("expiry")]
    deadline = queue_deadline(clock, expiries)
    if deadline <= clock:
        return None
    first = legs[0]
    row = QueuedOrder(
        user_id=user.id,
        scan_id=scan_id,
        strategy_name=strategy_name,
        symbol=str(first.get("symbol") or ""),
        side=str(first.get("side") or "buy"),
        qty=float(qty),
        order_type="limit",
        payload={
            "legs": legs,
            "equity_legs": equity_legs or [],
            "contracts_per_leg": qty,
            "reason": reason,
        },
        status="queued",
        reason="waiting for a price",
        expires_at=deadline,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def enqueue_market_closed(
    db: AsyncSession,
    *,
    user: User,
    legs: list[dict[str, Any]],
    qty: float,
    strategy_name: str | None,
    scan_id: str | None,
    equity_legs: list[dict[str, Any]] | None,
    thesis_accepted: bool,
    now: datetime | None = None,
    share_only: bool = False,
) -> QueuedOrder | None:
    """Save an authorized order until the next regular session. It is not sent yet."""
    if not thesis_accepted or not _authorized_limits(legs):
        return None
    clock = now or datetime.now(timezone.utc)
    if session_open(clock):
        return None
    expiries = [str(leg.get("expiry") or "") for leg in legs if leg.get("expiry")]
    deadline = queue_deadline(clock, expiries)
    if deadline <= clock:
        return None
    first = legs[0]
    row = QueuedOrder(
        user_id=user.id,
        scan_id=scan_id,
        strategy_name=strategy_name,
        symbol=str(first.get("symbol") or ""),
        side=str(first.get("side") or "buy"),
        qty=float(qty),
        order_type="limit",
        payload={
            "legs": legs,
            "equity_legs": equity_legs or [],
            "contracts_per_leg": qty,
            "share_only": share_only,
        },
        status="queued",
        reason=MARKET_CLOSED_REASON,
        expires_at=deadline,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def enqueue_broker_hold(
    db: AsyncSession,
    *,
    user: User,
    reason: str,
    legs: list[dict[str, Any]],
    qty: float,
    strategy_name: str | None,
    scan_id: str | None,
    equity_legs: list[dict[str, Any]] | None,
    now: datetime | None = None,
) -> QueuedOrder | None:
    """Record an order the broker already accepted but has not filled.

    The row is visible in Queued. It is not submitted again.
    """
    if not broker_unconfirmed(reason) or not legs:
        return None
    clock = now or datetime.now(timezone.utc)
    expiries = [str(leg.get("expiry") or "") for leg in legs if leg.get("expiry")]
    deadline = queue_deadline(clock, expiries)
    if deadline <= clock:
        deadline = clock + timedelta(hours=12)
    first = legs[0]
    row = QueuedOrder(
        user_id=user.id,
        scan_id=scan_id,
        strategy_name=strategy_name,
        symbol=str(first.get("symbol") or ""),
        side=str(first.get("side") or "buy"),
        qty=float(qty),
        order_type="limit",
        payload={
            "legs": legs,
            "equity_legs": equity_legs or [],
            "contracts_per_leg": qty,
            "reason": reason,
            "hold_only": True,
        },
        status="queued",
        reason="Queued. The broker has this order and has not confirmed a fill.",
        expires_at=deadline,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def queued_response(row: QueuedOrder, *, asset_class: str = "us_option") -> dict[str, Any]:
    hold = bool((row.payload or {}).get("hold_only"))
    if (row.reason or "").startswith("Queued — market closed"):
        message = row.reason
    elif hold:
        message = UNCONFIRMED_QUEUED_MESSAGE
    else:
        message = QUEUED_MESSAGE
    return {
        "id": row.id,
        "status": "queued",
        "fill_price": None,
        "estimated_cost": None,
        "account_impact": None,
        "asset_class": asset_class,
        "queue_message": message,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "legs_filled": [],
    }


async def cancel_queued(db: AsyncSession, user_id: str, queued_id: str) -> bool:
    row = await db.get(QueuedOrder, queued_id)
    if row is None or row.user_id != user_id or row.status != "queued":
        return False
    if (row.payload or {}).get("hold_only") or row.broker_order_id:
        return False
    row.status = "canceled"
    row.reason = "canceled before submission"
    await db.commit()
    return True


async def archive_queued(db: AsyncSession, user_id: str, queued_id: str) -> str:
    """Hide an inactive queue row. An unsent waiting row must be canceled first.

    Returns archived, active, broker, unknown, or missing.
    """
    row = await db.get(QueuedOrder, queued_id)
    if row is None or row.user_id != user_id:
        return "missing"
    if (row.payload or {}).get("hold_only") or row.broker_order_id:
        return "broker"
    if row.status == "unknown":
        return "unknown"
    if row.status in {"queued", "submitting"}:
        return "active"
    if row.status in {"rejected", "expired", "canceled", "cancelled"}:
        row.status = "archived"
        await db.commit()
        return "archived"
    return "missing"


def _leg_symbols(legs: list[dict[str, Any]] | None) -> tuple[str, ...]:
    return tuple(sorted(str(leg.get("symbol") or "").upper() for leg in (legs or []) if leg.get("symbol")))


async def _link_existing_broker_order(db: AsyncSession, adapter: Any, row: QueuedOrder) -> bool | None:
    """Attach an Alpaca order that already matches this row. Do not submit another.

    True when linked. False when the broker list is empty of a match.
    None when the list cannot be read, so the row is left alone.
    """
    lister = getattr(adapter, "list_orders", None)
    if lister is None:
        return None
    try:
        listed = await lister(status="open")
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker order list failed reason={}", type(exc).__name__)
        return None
    if listed is None:
        return None
    wanted = _leg_symbols((row.payload or {}).get("legs"))
    if not wanted:
        return False
    matches = [order for order in listed if _leg_symbols(order.get("legs")) == wanted]
    if len(matches) != 1:
        return False
    broker = matches[0]
    broker_id = str(broker.get("id") or "")
    if not broker_id:
        return False
    existing = await db.scalar(select(Order).where(Order.broker_order_id == broker_id))
    if existing is None:
        raw_limit = broker.get("limit_price")
        try:
            limit = abs(float(raw_limit)) if raw_limit not in (None, "") else None
        except (TypeError, ValueError):
            limit = None
        existing = Order(
            user_id=row.user_id,
            scan_id=row.scan_id,
            symbol=str(row.symbol or "")[:32],
            side=row.side or "buy",
            qty=float(row.qty or 1),
            order_type="limit",
            limit_price=limit,
            status="accepted",
            venue="paper",
            broker_order_id=broker_id,
            asset_class="us_option",
            multiplier=100,
            filled_qty=0,
        )
        db.add(existing)
        await db.flush()
    row.broker_order_id = broker_id
    row.order_id = existing.id
    row.status = "accepted"
    row.reason = ALPACA_AWAITING
    await db.commit()
    return True


async def process_queued_orders(db: AsyncSession, adapter: Any, *, now: datetime | None = None) -> int:
    """Submit rows whose session is open and whose live price still fits the confirmed limit.

    Returns how many broker submissions were started. A quote that is still missing
    leaves the row queued. An uncertain error is marked unknown and is not retried.
    """
    from app.services.executability import load_submission_quote, marketable_limit
    from app.services.fills import StockLegAwaiting, execute_strategy_legs

    await align_queued_with_fills(db)
    clock = now or datetime.now(timezone.utc)
    rows = (
        await db.scalars(select(QueuedOrder).where(QueuedOrder.status.in_(("queued", "submitting"))))
    ).all()
    started = 0
    for row in rows:
        if (row.payload or {}).get("hold_only") and not row.broker_order_id:
            linked = await _link_existing_broker_order(db, adapter, row)
            if linked is not False:
                continue
            payload = dict(row.payload or {})
            payload.pop("hold_only", None)
            row.payload = payload
            flag_modified(row, "payload")
            await db.commit()
        elif (row.payload or {}).get("hold_only"):
            continue
        if row.status == "submitting":
            if row.broker_order_id or row.order_id:
                row.status = "unknown"
                row.reason = (
                    "The broker result is not confirmed. This order will not be sent again until that result is reconciled."
                )
                await db.commit()
                continue
            row.status = "queued"
            await db.commit()
            reloaded = await db.get(QueuedOrder, row.id)
            if reloaded is None or reloaded.status != "queued":
                continue
            row = reloaded
        payload = dict(row.payload or {})
        stock_id = payload.get("stock_order_id")
        stock = await db.get(Order, stock_id) if isinstance(stock_id, str) and stock_id else None
        if stock is not None and stock.status in _OPEN_BROKER:
            row.status = "queued"
            row.reason = STOCK_AWAITING
            continue
        if stock is not None and stock.status not in {"filled", "partial", "partially_filled"}:
            row.status = "rejected"
            row.reason = f"The stock order is {stock.status}. The option legs were not sent."
            continue
        if stock is not None:
            payload["equity_satisfied"] = True
            payload["equity_legs"] = []
            row.payload = payload
            flag_modified(row, "payload")
        if row.expires_at and _as_utc(row.expires_at) <= clock:
            expiries = [str(leg.get("expiry") or "") for leg in (payload.get("legs") or []) if isinstance(leg, dict)]
            rolled = queue_deadline(clock, expiries) if stock is not None else clock
            if stock is not None and rolled > clock:
                row.expires_at = rolled
            else:
                row.status = "expired"
                row.reason = "the queue window ended before a valid price arrived"
                continue
        if not session_open(clock):
            row.reason = STOCK_FILLED_WAIT if payload.get("equity_satisfied") else MARKET_CLOSED_REASON
            continue
        claim = await db.execute(
            update(QueuedOrder)
            .where(QueuedOrder.id == row.id, QueuedOrder.status == "queued")
            .values(status="submitting")
        )
        if claim.rowcount != 1:
            continue
        await db.commit()
        fresh = await db.get(QueuedOrder, row.id)
        if fresh is None or fresh.status != "submitting":
            continue
        payload = fresh.payload or {}
        legs = list(payload.get("legs") or [])
        equity_satisfied = bool(payload.get("equity_satisfied"))
        equity_legs = None if equity_satisfied else (list(payload.get("equity_legs") or []) or None)
        user = await db.get(User, fresh.user_id)
        if user is None or not legs:
            fresh.status = "rejected"
            fresh.reason = "the queued order no longer has an account or legs"
            await db.commit()
            continue
        await db.commit()
        blocked = await _price_block(
            adapter, legs, load_submission_quote, marketable_limit, today=clock.astimezone(NY).date()
        )
        if blocked is not None and blocked[0] == "wait":
            fresh.status = "queued"
            fresh.reason = f"Waiting for a quote on {blocked[1]}."
            await db.commit()
            continue
        if blocked is not None and blocked[0] == "not_current":
            fresh.status = "queued"
            fresh.reason = blocked[1]
            await db.commit()
            continue
        # A quote outside the authorized limit is still a valid resting limit.
        # Alpaca paper accepts that limit and holds it. APEX does not keep it
        # locally just because it is not marketable yet. Missing prices, stale
        # quotes, and a closed session still stay queued above.
        if blocked is not None and blocked[0] == "expired":
            fresh.status = "expired"
            fresh.reason = "a contract in this order has expired"
            await db.commit()
            continue
        await db.commit()
        try:
            if payload.get("share_only"):
                from app.services.fills import execute_market_fill

                share_leg = next((leg for leg in legs if isinstance(leg, dict)), {})
                limit_raw = share_leg.get("limit_price", share_leg.get("price"))
                orders = [
                    await execute_market_fill(
                        user=user,
                        db=db,
                        adapter=adapter,
                        symbol=str(share_leg.get("symbol") or fresh.symbol),
                        side=str(share_leg.get("side") or fresh.side or "buy"),
                        qty=float(fresh.qty or share_leg.get("qty") or 1),
                        asset_class="us_equity",
                        order_type="limit",
                        limit_price=float(limit_raw),
                        scan_id=fresh.scan_id,
                        strategy_name=fresh.strategy_name or "Equity",
                        spread_confirmed=True,
                        submission_path="queued_order",
                        paper_book=True,
                    )
                ]
                guard = share_leg.get("exit_guard")
                if isinstance(guard, dict) and guard.get("armed") is True and orders:
                    orders[0].settlement = {"exit_guard": guard}
                    flag_modified(orders[0], "settlement")
            else:
                orders = await execute_strategy_legs(
                    user=user,
                    db=db,
                    adapter=adapter,
                    legs=legs,
                    scan_id=fresh.scan_id,
                    contracts_per_leg=float(payload.get("contracts_per_leg") or fresh.qty or 1),
                    strategy_name=fresh.strategy_name,
                    equity_legs=equity_legs,
                    equity_satisfied=equity_satisfied,
                    checks_passed=True,
                    spread_confirmed=True,
                    submission_path="queued_order",
                    paper_book=True,
                )
        except StockLegAwaiting as exc:
            held = dict(fresh.payload or {})
            held["stock_order_id"] = exc.order_id
            fresh.payload = held
            flag_modified(fresh, "payload")
            fresh.status = "queued"
            fresh.reason = STOCK_AWAITING
            await db.commit()
            continue
        except ValueError as exc:
            text = str(exc)
            from app.services.executability import is_soft_warning, is_spread_note

            if is_spread_note(text):
                fresh.status = "rejected"
                fresh.reason = text
            elif price_gap(text) or is_soft_warning(text):
                fresh.status = "queued"
                fresh.reason = text
            else:
                fresh.status = "rejected"
                fresh.reason = text
            await db.commit()
            continue
        except Exception as exc:  # noqa: BLE001
            logger.warning("queued order outcome unknown id={} reason={}", fresh.id, type(exc).__name__)
            fresh.status = "unknown"
            fresh.reason = "the broker outcome is unknown; this order will not be sent again"
            await db.commit()
            continue
        last = orders[-1] if orders else None
        status = (last.status if last is not None else "accepted") or "accepted"
        fresh.status = status
        fresh.order_id = last.id if last is not None else None
        fresh.broker_order_id = getattr(last, "broker_order_id", None) if last is not None else None
        if status in {"filled", "partial", "partially_filled"}:
            fresh.reason = "submitted"
            if last is not None and status == "filled":
                _mark_execution_notice(fresh, last)
        elif status in {"accepted", "pending", "new"}:
            fresh.reason = ALPACA_AWAITING
        else:
            fresh.reason = (
                "The broker result is not confirmed. This order will not be sent again until that result is reconciled."
            )
        started += 1
        await db.commit()
    await db.commit()
    return started


_OPEN_BROKER = ("accepted", "pending", "new", "pending_new", "partial", "partially_filled", "unknown")
_BOOKED = {"filled", "partial", "partially_filled"}
_apply_locks: dict[str, asyncio.Lock] = {}


def _apply_lock(broker_id: str) -> asyncio.Lock:
    """One fill is applied at a time, so the stream and the fallback poll cannot both book it."""
    lock = _apply_locks.get(broker_id)
    if lock is None:
        lock = asyncio.Lock()
        _apply_locks[broker_id] = lock
    return lock


def trade_update_order(message: dict) -> dict | None:
    """The broker order inside a trade-update message. Auth and listen acks are ignored."""
    if not isinstance(message, dict) or message.get("stream") != "trade_updates":
        return None
    data = message.get("data")
    if not isinstance(data, dict):
        return None
    order = data.get("order")
    if not isinstance(order, dict) or not order.get("id"):
        return None
    return order


def _absolute_price(raw: Any) -> float | None:
    """Broker fill price. A credit net is negative; the booked price is its absolute value."""
    try:
        price = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if price is None or price == 0:
        return None
    return abs(price)


async def _snapshot_with_legs(adapter: Any, order: Order, broker: dict) -> dict | None:
    """Use the broker's legs for a combo. Do not book the underlying when those legs are missing."""
    from app.services.occ_symbol import parse_occ

    legs = broker.get("legs")
    if isinstance(legs, list) and any(isinstance(leg, dict) and leg.get("symbol") for leg in legs):
        return broker
    if (order.asset_class or "") != "us_option" or parse_occ(str(order.symbol or "")):
        return broker
    getter = getattr(adapter, "get_order", None)
    if getter is None:
        return None
    try:
        full = await getter(order.broker_order_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("broker fill had no legs and the reread failed ({})", type(exc).__name__)
        return None
    if isinstance(full, dict) and isinstance(full.get("legs"), list) and full.get("legs"):
        return full
    return broker


def _already_booked(order: Order) -> tuple[float, float]:
    """Quantity and price already applied to cash and positions. An unfilled row has booked nothing."""
    if order.status not in _BOOKED:
        return 0.0, 0.0
    try:
        qty = float(order.filled_qty or 0)
    except (TypeError, ValueError):
        qty = 0.0
    try:
        price = float(order.fill_price or 0)
    except (TypeError, ValueError):
        price = 0.0
    return max(qty, 0.0), max(price, 0.0)


async def apply_broker_snapshot(
    db: AsyncSession,
    user: User,
    order: Order,
    broker: dict,
    adapter: Any = None,
) -> tuple[str, dict[str, Any]] | None:
    """Apply one broker snapshot to the paper book.

    Returns a client notice when the row changed. The caller commits, then pushes it.
    A repeated snapshot of the same fill does not move cash or positions again.
    This does not submit, cancel, or replace the order.
    """
    status = str(broker.get("status") or "").lower()
    if status in {"", "accepted", "pending", "new", "pending_new", "held"}:
        return None
    if order.status == "filled" and status != "filled":
        return None
    if status in {"filled", "partially_filled", "partial"}:
        broker = await _snapshot_with_legs(adapter, order, broker)
        if broker is None:
            return None
        price = _absolute_price(broker.get("filled_avg_price"))
        if price is None:
            return None
        try:
            new_qty = float(broker.get("filled_qty") or order.qty or 0)
        except (TypeError, ValueError):
            new_qty = float(order.qty or 0)
        if new_qty <= 0:
            return None
        new_status = "partially_filled" if status in {"partially_filled", "partial"} else "filled"
        old_qty, old_px = _already_booked(order)
        premium_delta = price * new_qty - old_px * old_qty
        qty_delta = new_qty - old_qty
        if qty_delta < 0:
            qty_delta = 0.0
            premium_delta = 0.0
        multiplier = max(int(order.multiplier or 1), 1)
        notional_delta = round(premium_delta * multiplier, 2)
        if qty_delta <= 1e-9 and abs(notional_delta) < 0.005 and order.status == new_status:
            return None
        order.status = new_status
        order.fill_price = price
        order.filled_qty = new_qty
        if order.filled_at is None and new_status == "filled":
            order.filled_at = datetime.now(timezone.utc)
        if abs(notional_delta) >= 0.005:
            signed = notional_delta if (order.side or "").lower() == "sell" else -notional_delta
            user.cash_balance = round(float(user.cash_balance or 0) + signed, 2)
            user.buying_power = user.cash_balance
        if qty_delta > 1e-9:
            increment = premium_delta / qty_delta if premium_delta > 0 else price
            await _book_confirmed_fill(user, order, broker, db, qty=qty_delta, price=increment)
        await _sync_queued_status(db, order)
        await _refresh_after_fill(user, db, adapter)
        return user.id, _order_notice(user, order)
    if status in {"canceled", "cancelled"}:
        mapped = "canceled"
    elif status == "expired":
        mapped = "expired"
    elif status in {"rejected", "suspended"}:
        mapped = "rejected"
    else:
        return None
    if order.status == mapped:
        return None
    order.status = mapped
    await _sync_queued_status(db, order)
    return user.id, _order_notice(user, order)


async def apply_trade_update(
    db: AsyncSession,
    broker: dict,
    adapter: Any = None,
) -> tuple[str, dict[str, Any]] | None:
    """Apply a trade-update order body. An unknown broker id is left untouched."""
    broker_id = str(broker.get("id") or "")
    if not broker_id:
        return None
    order = await db.scalar(select(Order).where(Order.broker_order_id == broker_id))
    if order is None:
        return None
    user = await db.get(User, order.user_id)
    if user is None or (order.venue or "") == "live":
        return None
    return await apply_broker_snapshot(db, user, order, broker, adapter)


async def reconcile_broker_orders(db: AsyncSession, adapter: Any) -> int:
    """Update paper orders from the broker. A failed read leaves the row unchanged.

    This does not submit, cancel, or send a second copy. A fill is recorded only
    when the broker returns a status and a price. The same fill is applied once.
    """
    await align_queued_with_fills(db)
    getter = getattr(adapter, "get_order", None)
    if getter is None:
        return 0
    rows = list(
        (
            await db.scalars(
                select(Order).where(
                    Order.status.in_(_OPEN_BROKER),
                    Order.broker_order_id.is_not(None),
                )
            )
        ).all()
    )
    changed = 0
    for order in rows:
        user = await db.get(User, order.user_id)
        if user is None or (order.venue or "") == "live":
            continue
        broker_id = str(order.broker_order_id or "")
        await db.commit()
        try:
            broker = await getter(broker_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("broker status read failed id={} reason={}", order.id, type(exc).__name__)
            continue
        if not isinstance(broker, dict):
            continue
        async with _apply_lock(broker_id):
            await db.refresh(order)
            await db.refresh(user)
            if order.status not in _OPEN_BROKER:
                continue
            notice = await apply_broker_snapshot(db, user, order, broker, adapter)
            if notice is None:
                continue
            await db.commit()
            await _push_order_notices([notice])
            changed += 1
    return changed


def _order_notice(user: User, order: Order) -> dict[str, Any]:
    filled = order.status in _BOOKED
    return {
        "type": "fill" if filled else "order",
        "order_id": order.id,
        "symbol": order.symbol,
        "status": order.status,
        "qty": order.filled_qty,
        "side": order.side,
        "price": order.fill_price,
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
    }


async def _refresh_after_fill(user: User, db: AsyncSession, adapter: Any) -> None:
    """Reprice the book after a confirmed fill. Cash and buying power always follow the fill."""
    try:
        from app.services.fills import refresh_portfolio_value

        await refresh_portfolio_value(user, db, adapter)
    except Exception as exc:  # noqa: BLE001
        logger.warning("portfolio refresh after fill failed ({})", type(exc).__name__)
        user.cash_balance = round(float(user.cash_balance or 0), 2)
        user.buying_power = user.cash_balance
        if user.portfolio_value is None:
            user.portfolio_value = user.cash_balance


async def _push_order_notices(notices: list[tuple[str, dict[str, Any]]]) -> None:
    from app.ws.hub import hub

    for user_id, payload in notices:
        try:
            await hub.broadcast(user_id, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("order update push failed ({})", type(exc).__name__)


def _mark_execution_notice(queued: QueuedOrder, order: Order) -> None:
    """Remember a queue fill for the next sign-in. Acknowledged notices stay quiet."""
    if order.status != "filled":
        return
    payload = dict(queued.payload or {})
    if payload.get("execution_notice_ack"):
        return
    payload["execution_notice_pending"] = True
    fill_price = getattr(order, "fill_price", None)
    if isinstance(fill_price, (int, float)) and not isinstance(fill_price, bool):
        payload["execution_fill_price"] = float(fill_price)
    queued.payload = payload
    flag_modified(queued, "payload")


async def align_queued_with_fills(db: AsyncSession) -> int:
    """Take a queue row off the pending list once its broker order is already filled.

    The stock leg of a collar is not the option order. This does not submit anything.
    """
    rows = (
        await db.scalars(
            select(QueuedOrder).where(QueuedOrder.status.in_(("queued", "submitting", "unknown", "accepted")))
        )
    ).all()
    changed = 0
    for row in rows:
        order: Order | None = None
        if row.order_id:
            order = await db.get(Order, row.order_id)
        if order is None and row.broker_order_id:
            order = await db.scalar(
                select(Order).where(
                    Order.broker_order_id == row.broker_order_id,
                    Order.user_id == row.user_id,
                )
            )
        if order is None or order.user_id != row.user_id:
            continue
        stock_id = str((row.payload or {}).get("stock_order_id") or "")
        if stock_id and order.id == stock_id:
            continue
        if order.status not in {"filled", "partial", "partially_filled", "canceled", "expired", "rejected"}:
            continue
        row.order_id = order.id
        if order.broker_order_id and not row.broker_order_id:
            row.broker_order_id = order.broker_order_id
        row.status = "partially_filled" if order.status in {"partial", "partially_filled"} else order.status
        if order.status == "filled":
            row.reason = "submitted"
            _mark_execution_notice(row, order)
        elif order.status in {"canceled", "expired", "rejected"}:
            row.reason = order.status
        changed += 1
    if changed:
        await db.commit()
    return changed


async def pending_execution_notices(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """Filled queue rows the desk has not announced yet."""
    rows = (
        await db.scalars(
            select(QueuedOrder)
            .where(QueuedOrder.user_id == user_id, QueuedOrder.status == "filled")
            .order_by(QueuedOrder.updated_at.desc())
        )
    ).all()
    notices: list[dict[str, Any]] = []
    for row in rows:
        payload = row.payload or {}
        if not payload.get("execution_notice_pending") or payload.get("execution_notice_ack"):
            continue
        price = payload.get("execution_fill_price")
        notices.append(
            {
                "id": row.id,
                "symbol": row.symbol,
                "strategy_name": row.strategy_name,
                "side": row.side,
                "qty": row.qty,
                "fill_price": float(price) if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
            }
        )
    return notices


async def ack_execution_notices(db: AsyncSession, user_id: str, ids: list[str]) -> int:
    """Mark announced fills so the next sign-in does not repeat them."""
    if not ids:
        return 0
    rows = (
        await db.scalars(
            select(QueuedOrder).where(QueuedOrder.user_id == user_id, QueuedOrder.id.in_(ids))
        )
    ).all()
    acked = 0
    for row in rows:
        payload = dict(row.payload or {})
        if not payload.get("execution_notice_pending"):
            continue
        payload["execution_notice_pending"] = False
        payload["execution_notice_ack"] = True
        row.payload = payload
        flag_modified(row, "payload")
        acked += 1
    if acked:
        await db.commit()
    return acked


async def _sync_queued_status(db: AsyncSession, order: Order) -> None:
    """Keep the pending row on the same result as the broker order. Does not submit anything."""
    from sqlalchemy import or_

    matched = [QueuedOrder.order_id == order.id]
    if order.broker_order_id:
        matched.append(QueuedOrder.broker_order_id == order.broker_order_id)
    rows = (
        await db.scalars(select(QueuedOrder).where(QueuedOrder.user_id == order.user_id, or_(*matched)))
    ).all()
    for queued in rows:
        stock_id = str((queued.payload or {}).get("stock_order_id") or "")
        if stock_id and order.id == stock_id and queued.order_id != order.id:
            continue
        queued.status = order.status
        if order.broker_order_id and not queued.broker_order_id and order.id != stock_id:
            queued.broker_order_id = order.broker_order_id
        if order.status == "filled":
            queued.reason = "submitted"
            queued.order_id = order.id
            _mark_execution_notice(queued, order)
        elif order.status in {"canceled", "expired", "rejected"}:
            queued.reason = order.status


async def _book_confirmed_fill(
    user: User,
    order: Order,
    broker: dict,
    db: AsyncSession,
    *,
    qty: float,
    price: float,
) -> None:
    """Record the newly filled quantity on the paper book. Cash is applied by the caller.

    ``qty`` is only the quantity that was not booked yet, so a repeated fill does not
    add the position twice.
    """
    from app.services.fills import _apply_fill_to_book

    legs = [leg for leg in (broker.get("legs") or []) if isinstance(leg, dict) and leg.get("symbol")]
    if qty <= 0 or price <= 0:
        return
    if not legs:
        from app.services.occ_symbol import parse_occ

        if (order.asset_class or "") == "us_option" and not parse_occ(str(order.symbol or "")):
            return
        await _apply_fill_to_book(
            user=user,
            db=db,
            symbol=order.symbol,
            side=str(order.side or "buy"),
            qty=qty,
            fill_px=price,
            asset_class=order.asset_class or "us_equity",
            strategy_name=None,
            certificate=None,
        )
        return
    for leg in legs:
        leg_px = _absolute_price(leg.get("filled_avg_price"))
        if leg_px is None:
            continue
        ratio = float(leg.get("ratio_qty") or 1)
        await _apply_fill_to_book(
            user=user,
            db=db,
            symbol=str(leg["symbol"]),
            side=str(leg.get("side") or order.side or "buy"),
            qty=qty * ratio,
            fill_px=leg_px,
            asset_class="us_option",
            strategy_name=None,
            certificate=None,
        )


async def _price_block(
    adapter: Any,
    legs: list[dict[str, Any]],
    load_quote: Any,
    marketable: Any,
    *,
    today: date,
) -> tuple[str, str] | None:
    """Why this row cannot be sent yet. None when every leg has a usable price inside the limit."""
    for leg in legs:
        raw_exp = str(leg.get("expiry") or "")
        if len(raw_exp) >= 10:
            try:
                if date.fromisoformat(raw_exp[:10]) < today:
                    return ("expired", "")
            except ValueError:
                return ("expired", "")
        symbol = str(leg.get("symbol") or "")
        side = str(leg.get("side") or "").lower()
        quote, problem = await load_quote(adapter, symbol)
        if problem or quote is None:
            if problem and not price_gap(problem):
                return ("not_current", problem)
            return ("wait", symbol or "a leg")
        live = marketable(side, quote)
        if live is None:
            return ("wait", symbol or "a leg")
        authorized = leg.get("limit_price")
        if authorized is None:
            authorized = leg.get("price")
        try:
            cap = float(authorized)
        except (TypeError, ValueError):
            return ("outside", "")
        if not _within_limit(side, float(live[0]), cap):
            return ("outside", "")
    return None
