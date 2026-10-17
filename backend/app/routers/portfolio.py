from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, release_db_lock
from app.deps import current_user, get_adapter
from app.models.trading import Order, Position, Scan, Scan
from app.models.user import User
from app.services.fills import execute_market_fill, execute_strategy_legs
from app.strategies.validator import validate_strategy_output
from app.services.orders import account_impact, estimate_order_cost
from app.services.daily_pnl import assemble_daily_pnl, quotes_for_positions
from app.services.portfolio_pnl import account_baseline, portfolio_history, symbol_pnl_rows

router = APIRouter(prefix="/api", tags=["portfolio"])


class StrategyLegIn(BaseModel):
    symbol: str
    side: str
    qty: float = 1
    strike: float | None = None
    option_side: str | None = None
    expiry: str | None = None
    price: float | None = None
    order_type: str | None = None
    limit_price: float | None = None


class OrderIn(BaseModel):
    symbol: str | None = None
    side: str | None = None
    qty: float | None = None
    order_type: str = "market"
    limit_price: float | None = None
    scan_id: str | None = None
    thesis_accepted: bool = False
    asset_class: str = "us_option"
    legs: list[StrategyLegIn] | None = None
    contracts_per_leg: float = 1
    confirm_duplicate: bool = False
    spread_confirmed: bool = False
    user_override: bool = False
    override_reasons: list[str] = Field(default_factory=list)
    data_source: str | None = None
    protect_exits: bool = False
    stop_price: float | None = None
    take_profit_price: float | None = None


async def _mark_positions(positions: list[Position], adapter: Any) -> list[Any]:
    """Apply live or cached closes. Quotes for a cold book run together."""
    quotes = await quotes_for_positions(positions, adapter)
    for pos, quote in zip(positions, quotes):
        price = getattr(quote, "price", None)
        if price is not None:
            pos.current_price = price
    return quotes


def _position_row(pos: Position) -> dict:
    return {
        "id": pos.id,
        "symbol": pos.symbol,
        "qty": pos.qty,
        "avg_cost": pos.avg_cost,
        "current": pos.current_price,
        "unrealized_pl": pos.unrealized_pl,
        "market_value": pos.market_value,
        "asset_class": pos.asset_class,
        "strategy_name": pos.strategy_name,
    }


def _position_certificate(pos: Position, scan: Scan | None = None) -> dict:
    cert = dict(pos.certificate or {})
    if scan and not cert.get("entry_composite_breakdown"):
        apex = (scan.layers or {}).get("apex_score") or {}
        strategy = (scan.layers or {}).get("strategy") or {}
        cert.setdefault("strategy_name", strategy.get("selected_strategy") or pos.strategy_name)
        cert.setdefault("entry_composite_score", scan.composite_score)
        cert.setdefault("entry_composite_breakdown", apex.get("weights"))
        metrics = strategy.get("metrics") or {}
        cert.setdefault("legs", metrics.get("legs") or [])
        cert.setdefault("max_loss", metrics.get("max_loss"))
        cert.setdefault("max_profit", metrics.get("max_profit"))
        cert.setdefault("breakevens", metrics.get("breakevens") or [])
        cert.setdefault("greeks", cert.get("greeks") or {})
    cert.setdefault("strategy_name", pos.strategy_name)
    return cert


@router.get("/portfolio")
async def portfolio(user: User = Depends(current_user), db: AsyncSession = Depends(get_db), adapter=Depends(get_adapter)) -> dict:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    await release_db_lock(db)
    live_value = user.cash_balance
    movers = []
    quotes = await _mark_positions(list(positions), adapter)
    for pos, q in zip(positions, quotes):
        marked = pos.current_price is not None
        if marked:
            live_value += pos.market_value
        movers.append(
            {
                "symbol": pos.symbol,
                "qty": pos.qty,
                "avg_cost": pos.avg_cost,
                "current": pos.current_price,
                "unrealized_pl": pos.unrealized_pl if marked else None,
                "market_value": pos.market_value if marked else None,
                "day_pct": getattr(q, "change_pct", None) if q is not None else None,
                "asset_class": pos.asset_class,
            }
        )
    user.portfolio_value = live_value
    user.buying_power = user.cash_balance
    await db.commit()
    day_pl = sum(m["unrealized_pl"] or 0 for m in movers)
    basis = user.starting_balance or user.portfolio_value or 1
    return {
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
        "day_pl": day_pl,
        "day_pct": (day_pl / basis) * 100,
        "top_movers": sorted(movers, key=lambda m: abs(m["unrealized_pl"] or 0), reverse=True)[:5],
        "brokerage_connected": user.brokerage_connected,
        "account_mode": user.account_mode,
        "starting_balance": account_baseline(user),
    }


@router.get("/portfolio/pnl-history")
async def portfolio_pnl_history(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    await release_db_lock(db)
    await _mark_positions(list(positions), adapter)
    orders = (await db.scalars(select(Order).where(Order.user_id == user.id))).all()
    baseline = account_baseline(user)
    points, history_note = portfolio_history(user, list(orders), list(positions))
    await db.commit()
    return {
        "starting_balance": baseline,
        "account_mode": user.account_mode,
        "points": points,
        "history_note": history_note,
    }


@router.get("/portfolio/daily-pnl")
async def portfolio_daily_pnl(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    """Per-position and book daily P&L. Missing feed prices stay unavailable."""
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    await release_db_lock(db)
    return await assemble_daily_pnl(list(positions), adapter)


@router.get("/portfolio/overall-pnl")
async def portfolio_overall_pnl(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    await release_db_lock(db)
    await _mark_positions(list(positions), adapter)
    orders = (await db.scalars(select(Order).where(Order.user_id == user.id))).all()
    rows = symbol_pnl_rows(list(orders), list(positions))
    await db.commit()
    return {
        "rows": [
            {
                "symbol": r.symbol,
                "asset_class": r.asset_class,
                "qty": r.qty,
                "realized_pl": r.realized_pl,
                "unrealized_pl": r.unrealized_pl,
                "total_pl": r.total_pl,
                "is_open": r.is_open,
            }
            for r in rows
        ]
    }


@router.get("/positions")
async def positions(user: User = Depends(current_user), db: AsyncSession = Depends(get_db), adapter=Depends(get_adapter)) -> dict:
    rows = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    await release_db_lock(db)
    await _mark_positions(list(rows), adapter)
    out = [_position_row(pos) for pos in rows]
    await db.commit()
    return {"positions": out}


@router.get("/positions/{position_id}")
async def position_detail(
    position_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    pos = await db.scalar(select(Position).where(Position.id == position_id, Position.user_id == user.id))
    if not pos:
        raise HTTPException(404, "Position not found")
    await release_db_lock(db)
    q = await adapter.quote(pos.symbol)
    if q.price is not None:
        pos.current_price = q.price
    scan = None
    order = await db.scalar(
        select(Order)
        .where(Order.user_id == user.id, Order.symbol == pos.symbol, Order.scan_id.isnot(None))
        .order_by(Order.created_at.desc())
    )
    if order and order.scan_id:
        scan = await db.get(Scan, order.scan_id)
    cert = _position_certificate(pos, scan)
    await db.commit()
    return {
        "position": _position_row(pos),
        "certificate": {
            "strategy_name": cert.get("strategy_name"),
            "legs": cert.get("legs") or [],
            "entry_composite_score": cert.get("entry_composite_score"),
            "entry_composite_breakdown": cert.get("entry_composite_breakdown"),
            "greeks": cert.get("greeks") or {},
            "max_loss": cert.get("max_loss"),
            "max_profit": cert.get("max_profit"),
            "breakevens": cert.get("breakevens") or [],
            "net_debit_credit": cert.get("net_debit_credit"),
            "net_type": cert.get("net_type"),
        },
    }


@router.post("/positions/{position_id}/close")
async def close_position(
    position_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    pos = await db.scalar(select(Position).where(Position.id == position_id, Position.user_id == user.id))
    if not pos:
        raise HTTPException(404, "Position not found")
    if pos.qty <= 0:
        raise HTTPException(400, "Position already closed")
    try:
        order = await execute_market_fill(
            user=user,
            db=db,
            adapter=adapter,
            symbol=pos.symbol,
            side="sell",
            qty=pos.qty,
            asset_class=pos.asset_class,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": True,
        "order_id": order.id,
        "symbol": order.symbol,
        "qty": order.qty,
        "fill_price": order.fill_price,
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
    }


def _price_can_queue(note: str) -> bool:
    """A missing or not-current price waits. It does not cancel the order."""
    text = note.lower()
    return "stale or suspect" in text or "quote not current" in text or "no current price" in text


def _queued_limit(payload: dict) -> float | None:
    """The limit lives on the queued ticket. This table has no limit column."""
    raw = payload.get("limit_price")
    legs = payload.get("legs")
    if raw is None and isinstance(legs, list) and legs and isinstance(legs[0], dict):
        raw = legs[0].get("limit_price", legs[0].get("price"))
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


@router.get("/orders")
async def order_history(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    from app.models.trading import QueuedOrder

    rows = (
        await db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()))
    ).all()
    waiting = (
        await db.scalars(
            select(QueuedOrder)
            .where(
                QueuedOrder.user_id == user.id,
                QueuedOrder.status.in_(("queued", "submitting", "unknown", "rejected")),
            )
            .order_by(QueuedOrder.created_at.desc())
        )
    ).all()
    queued_rows = []
    for row in waiting:
        payload = row.payload if isinstance(row.payload, dict) else {}
        held = bool(payload.get("hold_only"))
        has_broker = bool(row.broker_order_id)
        if held and not has_broker:
            shown_status = "unknown"
            shown_reason = (
                "This was marked as sent to the broker, but APEX has no broker id for it. "
                "It will not be sent again, and a fill cannot be confirmed from here."
            )
        elif held:
            shown_status = "accepted"
            shown_reason = "The broker has this order. It has not filled yet."
        else:
            shown_status = row.status
            shown_reason = row.reason
        queued_rows.append(
            {
                "id": row.id,
                "symbol": row.symbol,
                "side": row.side,
                "qty": row.qty,
                "order_type": row.order_type,
                "limit_price": _queued_limit(payload),
                "fill_price": None,
                "status": shown_status,
                "asset_class": (
                    "us_equity"
                    if payload.get("share_only") or payload.get("asset_class") == "us_equity"
                    else "us_option"
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "filled_at": None,
                "queue_reason": shown_reason,
                "strategy_name": row.strategy_name,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            }
        )
    return {
        "orders": queued_rows
        + [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "order_type": o.order_type,
                "limit_price": o.limit_price,
                "fill_price": o.fill_price,
                "status": o.status,
                "asset_class": o.asset_class,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            }
            for o in rows
        ]
    }


@router.get("/session-notices")
async def session_notices(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """Closed legs first, then queue fills waiting to be announced."""
    from app.services.session_notices import session_arrival_bundle

    return await session_arrival_bundle(db, user.id)


class ExecutionNoticeAck(BaseModel):
    ids: list[str] = Field(default_factory=list)


@router.post("/session-notices/ack-closed")
async def ack_closed_session_notices(
    body: ExecutionNoticeAck,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.session_notices import ack_closed_today_notices

    acked = await ack_closed_today_notices(db, user.id, body.ids)
    return {"acked": acked}


@router.get("/orders/execution-notices")
async def execution_notices(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.order_queue import pending_execution_notices

    return {"notices": await pending_execution_notices(db, user.id)}


@router.post("/orders/execution-notices/ack")
async def ack_execution_notices_route(
    body: ExecutionNoticeAck,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.order_queue import ack_execution_notices

    acked = await ack_execution_notices(db, user.id, body.ids)
    return {"acked": acked}


@router.post("/orders/queued/{queued_id}/cancel")
async def cancel_queued_order(
    queued_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.order_queue import cancel_queued

    if not await cancel_queued(db, user.id, queued_id):
        raise HTTPException(
            404,
            "That order is not an unsent waiting order. A broker order is not canceled from this list.",
        )
    return {"id": queued_id, "status": "canceled"}


@router.post("/orders/queued/{queued_id}/remove")
async def remove_queued_order(
    queued_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.order_queue import archive_queued

    result = await archive_queued(db, user.id, queued_id)
    if result == "archived":
        return {"id": queued_id, "status": "archived"}
    if result == "active":
        raise HTTPException(400, "Cancel this waiting order before removing it. Cancel stops it from being sent.")
    if result == "broker":
        raise HTTPException(400, "The broker already has this order. Remove cannot hide it.")
    if result == "unknown":
        raise HTTPException(400, "The result is not confirmed. Reconcile it before removing it.")
    raise HTTPException(404, "That order is not in the queue list")


def _exit_guard_payload(body: OrderIn, side: str) -> dict | None:
    """Armed only when the trader checked the exit box and both levels face the right way."""
    if not body.protect_exits or side != "buy":
        return None
    try:
        stop = float(body.stop_price)
        target = float(body.take_profit_price)
    except (TypeError, ValueError):
        return None
    if stop <= 0 or target <= 0 or stop >= target:
        return None
    try:
        limit = float(body.limit_price) if body.limit_price is not None else None
    except (TypeError, ValueError):
        limit = None
    if limit is not None and limit > 0 and not (stop < limit < target):
        return None
    return {
        "stop": stop,
        "take_profit": target,
        "side": side,
        "qty": body.qty,
        "armed": True,
    }


async def _place_equity_share(body: OrderIn, user: User, db: AsyncSession, adapter: Any) -> dict:
    """A share order from an equity research scan. A bare stock ticket stays refused."""
    if not body.scan_id or not body.thesis_accepted or not body.symbol or not body.side or body.qty is None:
        raise HTTPException(400, "APEX terminal is options-only — asset_class must be us_option")
    scan = await db.get(Scan, body.scan_id)
    layers = scan.layers if scan is not None and scan.user_id == user.id and isinstance(scan.layers, dict) else None
    equity = layers.get("equity") if isinstance(layers, dict) else None
    if scan is None or not isinstance(equity, dict) or equity.get("research_mode") != "equity":
        raise HTTPException(400, "APEX terminal is options-only — asset_class must be us_option")
    if str(scan.symbol).upper() != body.symbol.strip().upper():
        raise HTTPException(400, "The order symbol does not match this equity scan.")
    action = equity.get("action")
    levels = equity.get("levels") if isinstance(equity.get("levels"), dict) else {}
    try:
        entry = float(levels.get("entry"))
        stop = float(levels.get("stop"))
        target = float(levels.get("take_profit"))
    except (TypeError, ValueError):
        entry = stop = target = 0.0
    downside = entry > 0 and stop > entry and target < entry
    if action == "Sell" or (action == "Avoid" and downside):
        expected = "sell"
    elif action == "Buy":
        expected = "buy"
    else:
        raise HTTPException(400, "This equity research has no share order to send.")
    if body.side.strip().lower() != expected:
        raise HTTPException(400, "The order side does not match the equity plan.")
    raw_limit = body.limit_price if body.limit_price is not None else levels.get("entry")
    try:
        limit = float(raw_limit)
    except (TypeError, ValueError):
        limit = 0.0
    if limit <= 0:
        raise HTTPException(400, "This equity plan has no entry price, so no order was sent.")
    from app.analysis.layers import DEFAULT_AUTO_EXEC_THRESHOLD
    from app.models.user_settings import UserTradingSettings
    from app.services.executability import displayed_below_minimum
    from app.services.order_queue import enqueue_market_closed, queued_response, session_open

    trading_settings = await db.scalar(select(UserTradingSettings).where(UserTradingSettings.user_id == user.id))
    minimum = (
        float(trading_settings.auto_execution_threshold)
        if trading_settings is not None
        else float(DEFAULT_AUTO_EXEC_THRESHOLD)
    )
    scores = equity.get("scores") if isinstance(equity.get("scores"), dict) else {}
    raw_score = scores.get("overall")
    if displayed_below_minimum(raw_score, minimum) and not body.user_override:
        shown = float(f"{float(raw_score):.1f}")
        floor = float(f"{float(minimum):.1f}")
        raise HTTPException(
            400,
            (
                f"Not recommended. Composite {shown:.1f}. Your minimum {floor:.1f}. "
                "This trade is below your minimum score. No order was sent. "
                "Review the warning and confirm Proceed at my own risk if you still want to continue."
            ),
        )
    share_leg = {
        "symbol": body.symbol.strip().upper(),
        "side": expected,
        "qty": body.qty,
        "limit_price": limit,
        "asset_class": "us_equity",
    }
    guard = _exit_guard_payload(body, expected)
    if guard is not None:
        share_leg["exit_guard"] = guard
    if not session_open(datetime.now(timezone.utc)):
        queued = await enqueue_market_closed(
            db,
            user=user,
            legs=[share_leg],
            qty=body.qty,
            strategy_name="Equity",
            scan_id=body.scan_id,
            equity_legs=None,
            thesis_accepted=True,
            share_only=True,
        )
        if queued is not None:
            return queued_response(queued, asset_class="us_equity")
        raise HTTPException(
            400,
            "The market is closed. This order was not saved. Confirm the order terms and try again when the market is open.",
        )
    await release_db_lock(db)
    try:
        order = await execute_market_fill(
            user=user,
            db=db,
            adapter=adapter,
            symbol=share_leg["symbol"],
            side=expected,
            qty=body.qty,
            asset_class="us_equity",
            order_type="limit",
            limit_price=limit,
            scan_id=body.scan_id,
            strategy_name="Equity",
            spread_confirmed=body.spread_confirmed,
            submission_path="place_order",
            user_override=bool(body.user_override),
            paper_book=True,
        )
    except ValueError as exc:
        from app.services.order_queue import enqueue_price_gap, price_gap

        reason = str(exc)
        if price_gap(reason):
            queued = await enqueue_price_gap(
                db,
                user=user,
                reason=reason,
                legs=[share_leg],
                qty=body.qty or 1,
                strategy_name="Equity",
                scan_id=body.scan_id,
                equity_legs=None,
                thesis_accepted=True,
            )
            if queued is not None:
                held = dict(queued.payload or {})
                held["share_only"] = True
                held["asset_class"] = "us_equity"
                queued.payload = held
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(queued, "payload")
                await db.commit()
                return queued_response(queued, asset_class="us_equity")
        raise HTTPException(400, reason) from exc
    if guard is not None:
        order.settlement = {"exit_guard": guard}
        await db.commit()
    return {
        "id": order.id,
        "status": order.status,
        "fill_price": order.fill_price,
        "estimated_cost": order.estimated_cost,
        "account_impact": account_impact(order.side, order.estimated_cost or 0),
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
        "asset_class": "us_equity",
        "status_message": getattr(order, "status_message", None),
    }


def _reject_quantity(value: float | None, label: str) -> None:
    """Refuse a size that is not a whole number the account can send."""
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{label} must be a whole number from 1 to 1,000,000.") from None
    if (
        isinstance(value, bool)
        or not math.isfinite(number)
        or number != int(number)
        or int(number) < 1
        or int(number) > 1_000_000
    ):
        raise HTTPException(
            400,
            f"{label} must be a whole number from 1 to 1,000,000. Fractions, zero, and negative sizes are not sent.",
        )


def _order_identity(body: OrderIn) -> tuple:
    legs = tuple(
        (leg.symbol.upper(), leg.side.lower(), float(leg.qty), leg.limit_price)
        for leg in (body.legs or [])
    )
    return (
        (body.symbol or "").upper(),
        (body.side or "").lower(),
        None if body.qty is None else float(body.qty),
        body.limit_price,
        body.asset_class,
        legs,
    )


async def _reject_recent_duplicate(db: AsyncSession, user_id: str, body: OrderIn) -> None:
    """A retry of the same ticket within 60 seconds is not a second order."""
    if body.confirm_duplicate:
        return
    from app.models.trading import QueuedOrder

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    wanted = _order_identity(body)
    recent = (
        await db.scalars(select(Order).where(Order.user_id == user_id, Order.created_at >= cutoff))
    ).all()
    for row in recent:
        if (
            (row.symbol or "").upper(),
            (row.side or "").lower(),
            None if row.qty is None else float(row.qty),
            row.limit_price,
            row.asset_class,
        ) == wanted[:5] and not wanted[5]:
            raise HTTPException(
                409,
                "An identical order was submitted in the last 60 seconds. Submit again only if you intend a second order.",
            )
    waiting = (
        await db.scalars(
            select(QueuedOrder).where(
                QueuedOrder.user_id == user_id,
                QueuedOrder.status.in_(("queued", "submitting", "accepted")),
                QueuedOrder.created_at >= cutoff,
            )
        )
    ).all()
    for row in waiting:
        payload = row.payload if isinstance(row.payload, dict) else {}
        stored_legs = tuple(
            (
                str(leg.get("symbol") or "").upper(),
                str(leg.get("side") or "").lower(),
                float(leg.get("qty") or 0),
                leg.get("limit_price", leg.get("price")),
            )
            for leg in (payload.get("legs") or [])
            if isinstance(leg, dict)
        )
        stored = (
            (row.symbol or "").upper(),
            (row.side or "").lower(),
            None if row.qty is None else float(row.qty),
            row.limit_price,
            str(payload.get("asset_class") or body.asset_class),
            stored_legs,
        )
        if stored == wanted or (not wanted[5] and stored[:5] == wanted[:5]):
            raise HTTPException(
                409,
                "An identical order was submitted in the last 60 seconds. Submit again only if you intend a second order.",
            )


@router.post("/orders")
async def place_order(
    body: OrderIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    if body.scan_id and not body.thesis_accepted:
        raise HTTPException(400, "Thesis checkbox required before submitting a scanned order")
    _reject_quantity(body.qty, "Quantity")
    _reject_quantity(body.contracts_per_leg, "Contracts per leg")
    for leg in body.legs or []:
        _reject_quantity(leg.qty, "Leg quantity")
    if body.scan_id:
        scanned = await db.get(Scan, body.scan_id)
        if scanned and scanned.user_id == user.id:
            quality = (scanned.layers or {}).get("data_quality") or {}
            if isinstance(quality, dict) and quality.get("ok") is False:
                raise HTTPException(
                    400,
                    str(quality.get("reason") or "This scan does not have usable prices. No order was sent."),
                )
            review = (scanned.layers or {}).get("risk_review") or {}
            strategy_layer = (scanned.layers or {}).get("strategy") or {}
            needs_spread = bool(review.get("spread_confirmation_required")) or bool(
                strategy_layer.get("spread_block_reasons")
            )
            if needs_spread and not body.spread_confirmed:
                raise HTTPException(400, "Confirm the spread warning before this order can be sent.")
            equity_plan = (scanned.layers or {}).get("equity") or {}
            if equity_plan.get("action") == "Insufficient data":
                raise HTTPException(400, str(equity_plan.get("why") or "This scan does not have usable prices. No order was sent."))
    await _reject_recent_duplicate(db, user.id, body)
    if (body.data_source or "").strip().lower() == "brokerage":
        raise HTTPException(
            400,
            "You're in read-only mode. You can view this brokerage account, but APEX can't place this trade.",
        )

    if body.legs:
        strategy_name: str | None = None
        strategy_layer: dict = {}
        certificate: dict | None = None
        equity_legs: list[dict] | None = None
        equity_satisfied = False
        if body.scan_id:
            scan = await db.get(Scan, body.scan_id)
            if scan and scan.user_id == user.id:
                layers = scan.layers or {}
                strategy_layer = layers.get("strategy") or {}
                strategy_name = strategy_layer.get("selected_strategy")
                apex = layers.get("apex_score") or {}
                metrics = strategy_layer.get("metrics") or {}
                certificate = {
                    "strategy_name": strategy_name,
                    "entry_composite_score": scan.composite_score,
                    "entry_composite_breakdown": apex.get("weights"),
                    "legs": metrics.get("legs") or [],
                    "max_loss": metrics.get("max_loss"),
                    "max_profit": metrics.get("max_profit"),
                    "breakevens": metrics.get("breakevens") or [],
                    "greeks": metrics.get("greeks") or {},
                    "net_debit_credit": metrics.get("net_debit_credit"),
                    "net_type": metrics.get("net_type"),
                }
                user_override = bool(body.user_override)
                if user_override and not body.override_reasons:
                    raise HTTPException(400, "Override reasons are required")
                from app.services.executability import is_soft_warning

                hard_notes = [
                    note
                    for note in (strategy_layer.get("hard_block_reasons") or [])
                    if isinstance(note, str)
                    and note.strip()
                    and not is_soft_warning(note)
                    and not _price_can_queue(note)
                ]
                soft_notes = [
                    note
                    for note in (strategy_layer.get("spread_block_reasons") or [])
                    if isinstance(note, str) and note.strip()
                ]
                if hard_notes:
                    raise HTTPException(400, hard_notes[0])
                if soft_notes and not user_override:
                    raise HTTPException(400, soft_notes[0])
                from app.analysis.layers import DEFAULT_AUTO_EXEC_THRESHOLD
                from app.models.user_settings import UserTradingSettings
                from app.services.executability import displayed_below_minimum

                trading_settings = await db.scalar(
                    select(UserTradingSettings).where(UserTradingSettings.user_id == user.id)
                )
                minimum = (
                    float(trading_settings.auto_execution_threshold)
                    if trading_settings is not None
                    else float(DEFAULT_AUTO_EXEC_THRESHOLD)
                )
                raw_score = strategy_layer.get("composite_score")
                if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                    raw_score = scan.composite_score
                if displayed_below_minimum(raw_score, minimum) and not user_override:
                    shown = float(f"{float(raw_score):.1f}")
                    floor = float(f"{float(minimum):.1f}")
                    raise HTTPException(
                        400,
                        (
                            f"Not recommended. Composite {shown:.1f}. Your minimum {floor:.1f}. "
                            "This trade is below your minimum score. No order was sent. "
                            "Review the warning and confirm Proceed at my own risk if you still want to continue."
                        ),
                    )
                from app.analysis.gate_config import refuse_if_checks_failed

                if not user_override:
                    try:
                        refuse_if_checks_failed(
                            checks_passed=strategy_layer.get("checks_passed"),
                            auto_execute=bool(strategy_layer.get("clears_threshold")),
                        )
                    except ValueError as exc:
                        from loguru import logger

                        logger.warning("order blocked reason={}", exc)
                        raise HTTPException(400, str(exc)) from exc
                if strategy_name:
                    validation = validate_strategy_output(
                        strategy_name,
                        metrics,
                        scan.symbol,
                        order_legs=[leg.model_dump() for leg in body.legs],
                    )
                    if not validation.valid:
                        from loguru import logger

                        detail = validation.errors[0].to_log_dict() if validation.errors else {"check": "validation"}
                        logger.warning("strategy validation failed {}", detail)
                        message = (
                            validation.errors[0].trader_message()
                            if validation.errors
                            else "Strategy validation failed. This order was not sent. Review the reason, then try again if you still want the trade."
                        )
                        raise HTTPException(400, message)
                equity_legs = (layers.get("risk_review") or {}).get("equity_legs") or []
                from app.services.stock_leg import submission_equity

                positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
                await release_db_lock(db)
                ask = None
                try:
                    live = await adapter.quote(scan.symbol)
                    ask = live.ask
                except Exception:  # noqa: BLE001
                    ask = None
                planned = submission_equity(
                    strategy_name=strategy_name,
                    ticker=scan.symbol,
                    contracts=body.contracts_per_leg,
                    multiplier=int((metrics.get("per_contract_multiplier") or 100)),
                    positions=list(positions),
                    ask=ask,
                )
                equity_legs = planned.order_legs
                equity_satisfied = planned.covered_by_holdings
        from app.services.order_queue import enqueue_market_closed, queued_response, session_open

        if not session_open(datetime.now(timezone.utc)):
            queued = await enqueue_market_closed(
                db,
                user=user,
                legs=[leg.model_dump() for leg in body.legs],
                qty=body.contracts_per_leg,
                strategy_name=strategy_name,
                scan_id=body.scan_id,
                equity_legs=equity_legs,
                thesis_accepted=bool(body.thesis_accepted),
            )
            if queued is not None:
                return queued_response(queued)
            raise HTTPException(
                400,
                "The market is closed. This order was not saved. Confirm the order terms and try again when the market is open.",
            )
        await release_db_lock(db)
        try:
            orders = await execute_strategy_legs(
                user=user,
                db=db,
                adapter=adapter,
                legs=[leg.model_dump() for leg in body.legs],
                scan_id=body.scan_id,
                contracts_per_leg=body.contracts_per_leg,
                strategy_name=strategy_name,
                certificate=certificate,
                equity_legs=equity_legs if body.scan_id else None,
                equity_satisfied=equity_satisfied if body.scan_id else False,
                checks_passed=strategy_layer.get("checks_passed") if strategy_name else None,
                spread_confirmed=body.spread_confirmed,
                wide_spread_only=bool(strategy_layer.get("placeable"))
                and bool(strategy_layer.get("spread_block_reasons")),
                submission_path="place_order",
                user_override=bool(body.user_override),
                override_reasons=list(body.override_reasons),
                paper_book=True,
            )
        except ValueError as exc:
            from app.services.order_queue import broker_unconfirmed

            reason = str(exc)
            if broker_unconfirmed(reason):
                raise HTTPException(
                    409,
                    "The broker may already have this order, and the fill is not confirmed. "
                    "Check Portfolio before you send it again. APEX did not add it to the waiting queue.",
                ) from exc
            raise HTTPException(400, reason) from exc
        last = orders[-1]
        status_message = getattr(last, "status_message", None)
        total_cost = sum(o.estimated_cost or 0 for o in orders)
        impact = sum(account_impact(o.side, o.estimated_cost or 0) for o in orders)
        return {
            "id": last.id,
            "status": last.status,
            "fill_price": last.fill_price,
            "estimated_cost": round(total_cost, 2),
            "account_impact": round(impact, 2),
            "balance": user.cash_balance,
            "buying_power": user.buying_power,
            "portfolio_value": user.portfolio_value,
            "asset_class": "us_option",
            "status_message": status_message,
            "legs_filled": [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "fill_price": o.fill_price,
                    "asset_class": o.asset_class,
                    "order_type": o.order_type,
                }
                for o in orders
            ],
        }

    if body.asset_class == "us_equity" and not body.legs:
        return await _place_equity_share(body, user, db, adapter)
    if not body.symbol or not body.side or body.qty is None:
        raise HTTPException(400, "symbol, side, and qty are required when legs are omitted")
    if body.asset_class != "us_option":
        raise HTTPException(400, "APEX terminal is options-only — asset_class must be us_option")

    await release_db_lock(db)
    quote = await adapter.quote(body.symbol)
    px = body.limit_price if body.order_type == "limit" and body.limit_price is not None else quote.price
    if px is None:
        raise HTTPException(503, "Live quote unavailable for this symbol")
    mult = 100 if body.asset_class == "us_option" else 1
    cost = estimate_order_cost(body.qty, px, asset_class=body.asset_class, multiplier=mult)  # type: ignore[arg-type]
    if body.side == "buy" and cost > user.buying_power:
        raise HTTPException(400, "Insufficient buying power. The account cannot cover the order.")
    try:
        order = await execute_market_fill(
            user=user,
            db=db,
            adapter=adapter,
            symbol=body.symbol,
            side=body.side,
            qty=body.qty,
            asset_class=body.asset_class,
            order_type=body.order_type,
            limit_price=body.limit_price,
            scan_id=body.scan_id,
            spread_confirmed=body.spread_confirmed,
            submission_path="place_order",
            paper_book=True,
        )
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    if order.fill_price is not None and order.status in {"filled", "partial"}:
        filled_qty = float(order.filled_qty or order.qty)
        actual = estimate_order_cost(
            filled_qty,
            order.fill_price,
            asset_class=order.asset_class,  # type: ignore[arg-type]
            multiplier=order.multiplier,
        )
        impact = account_impact(order.side, actual)
    else:
        impact = 0.0
    return {
        "id": order.id,
        "status": order.status,
        "fill_price": order.fill_price,
        "estimated_cost": cost,
        "account_impact": impact,
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
        "asset_class": order.asset_class,
    }
