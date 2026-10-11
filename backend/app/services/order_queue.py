"""Hold a confirmed order when the only failure is a missing price.

The row is not a broker order. It stays queued until the next regular NYSE
close, or until the earliest leg expires, whichever is sooner. A later quote
must still fit the limit the user confirmed. A wider price is not submitted.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import QueuedOrder
from app.models.user import User
from app.services.market_session import NY, is_trading_day

_PRICE_GAP = (
    "no current price is available",
    "couldn't get a price",
    "could not get a price",
    "current price for this strategy is unavailable",
    "live quote unavailable",
    "live mid is unavailable",
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

UNCONFIRMED_QUEUED_MESSAGE = (
    "Your order is queued. The broker received it and has not confirmed a fill. "
    "It is listed under Queued and will not be sent again."
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


def queued_response(row: QueuedOrder) -> dict[str, Any]:
    hold = bool((row.payload or {}).get("hold_only"))
    return {
        "id": row.id,
        "status": "queued",
        "fill_price": None,
        "estimated_cost": None,
        "account_impact": None,
        "asset_class": "us_option",
        "queue_message": UNCONFIRMED_QUEUED_MESSAGE if hold else QUEUED_MESSAGE,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "legs_filled": [],
    }


async def cancel_queued(db: AsyncSession, user_id: str, queued_id: str) -> bool:
    row = await db.get(QueuedOrder, queued_id)
    if row is None or row.user_id != user_id or row.status != "queued":
        return False
    row.status = "canceled"
    row.reason = "canceled before submission"
    await db.commit()
    return True


async def process_queued_orders(db: AsyncSession, adapter: Any, *, now: datetime | None = None) -> int:
    """Submit rows whose session is open and whose live price still fits the confirmed limit.

    Returns how many broker submissions were started. A quote that is still missing
    leaves the row queued. An uncertain error is marked unknown and is not retried.
    """
    from app.services.executability import load_submission_quote, marketable_limit
    from app.services.fills import execute_strategy_legs

    clock = now or datetime.now(timezone.utc)
    rows = (
        await db.scalars(select(QueuedOrder).where(QueuedOrder.status == "queued"))
    ).all()
    started = 0
    for row in rows:
        if (row.payload or {}).get("hold_only"):
            continue
        if row.expires_at and row.expires_at <= clock:
            row.status = "expired"
            row.reason = "the queue window ended before a valid price arrived"
            continue
        if not session_open(clock):
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
        user = await db.get(User, fresh.user_id)
        if user is not None and user.account_mode == "real_brokerage":
            fresh.status = "rejected"
            fresh.reason = "You're in read-only mode. APEX can't place this brokerage trade."
            await db.commit()
            continue
        if user is None or not legs:
            fresh.status = "rejected"
            fresh.reason = "the queued order no longer has an account or legs"
            await db.commit()
            continue
        blocked = await _price_block(
            adapter, legs, load_submission_quote, marketable_limit, today=clock.astimezone(NY).date()
        )
        if blocked == "wait":
            fresh.status = "queued"
            fresh.reason = "waiting for a price"
            await db.commit()
            continue
        if blocked == "outside":
            fresh.status = "queued"
            fresh.reason = "waiting for an authorized price"
            await db.commit()
            continue
        if blocked == "expired":
            fresh.status = "expired"
            fresh.reason = "a contract in this order has expired"
            await db.commit()
            continue
        try:
            orders = await execute_strategy_legs(
                user=user,
                db=db,
                adapter=adapter,
                legs=legs,
                scan_id=fresh.scan_id,
                contracts_per_leg=float(payload.get("contracts_per_leg") or fresh.qty or 1),
                strategy_name=fresh.strategy_name,
                equity_legs=list(payload.get("equity_legs") or []) or None,
                checks_passed=True,
                submission_path="queued_order",
            )
        except ValueError as exc:
            text = str(exc)
            fresh.status = "queued" if price_gap(text) else "rejected"
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
        fresh.status = (last.status if last is not None else "accepted") or "accepted"
        fresh.order_id = last.id if last is not None else None
        fresh.broker_order_id = getattr(last, "broker_order_id", None) if last is not None else None
        fresh.reason = "submitted"
        started += 1
        await db.commit()
    await db.commit()
    return started


async def _price_block(
    adapter: Any,
    legs: list[dict[str, Any]],
    load_quote: Any,
    marketable: Any,
    *,
    today: date,
) -> str | None:
    for leg in legs:
        raw_exp = str(leg.get("expiry") or "")
        if len(raw_exp) >= 10:
            try:
                if date.fromisoformat(raw_exp[:10]) < today:
                    return "expired"
            except ValueError:
                return "expired"
        symbol = str(leg.get("symbol") or "")
        side = str(leg.get("side") or "").lower()
        quote, problem = await load_quote(adapter, symbol)
        if problem or quote is None:
            return "wait"
        live = marketable(side, quote)
        if live is None:
            return "wait"
        authorized = leg.get("limit_price")
        if authorized is None:
            authorized = leg.get("price")
        try:
            cap = float(authorized)
        except (TypeError, ValueError):
            return "outside"
        if not _within_limit(side, float(live[0]), cap):
            return "outside"
    return None
