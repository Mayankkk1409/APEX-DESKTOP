"""Close a paper share position when its armed stop or take-profit is reached.

The guard is stored only after the trader checks the exit box on the order popup.
An order without that box is never closed by this pass.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.trading import Order, Position
from app.models.user import User
from app.services.order_queue import session_open
from datetime import datetime, timezone


def exit_trigger(side: str, price: float, stop: float | None, take_profit: float | None) -> str | None:
    """Long protection only. A short is not armed by this desk."""
    if side != "buy" or price <= 0:
        return None
    if stop is not None and stop > 0 and price <= stop:
        return "stop"
    if take_profit is not None and take_profit > 0 and price >= take_profit:
        return "take_profit"
    return None


def _guard(order: Order) -> dict[str, Any] | None:
    raw = order.settlement if isinstance(order.settlement, dict) else None
    guard = raw.get("exit_guard") if isinstance(raw, dict) else None
    if not isinstance(guard, dict) or guard.get("armed") is not True:
        return None
    return guard


async def enforce_exit_guards(db: AsyncSession, adapter: Any) -> int:
    """Sell an open paper lot when its live price has reached the armed level."""
    if not session_open(datetime.now(timezone.utc)):
        return 0
    rows = (
        await db.scalars(select(Order).where(Order.asset_class == "us_equity", Order.status == "filled"))
    ).all()
    closed = 0
    dirty = False
    for order in rows:
        guard = _guard(order)
        if guard is None or (order.venue or "") == "live":
            continue
        user = await db.get(User, order.user_id)
        if user is None:
            continue
        position = await db.scalar(
            select(Position).where(
                Position.user_id == order.user_id,
                Position.symbol == order.symbol,
                Position.asset_class == "us_equity",
            )
        )
        if position is None or float(position.qty or 0) <= 0:
            guard["armed"] = False
            guard["reason"] = "The share position is already closed."
            flag_modified(order, "settlement")
            dirty = True
            continue
        await db.commit()
        try:
            quote = await adapter.quote(order.symbol)
            price = float(getattr(quote, "price", None))
        except (TypeError, ValueError, Exception):  # noqa: BLE001
            continue
        reason = exit_trigger(
            str(guard.get("side") or order.side or ""),
            price,
            _num(guard.get("stop")),
            _num(guard.get("take_profit")),
        )
        if reason is None:
            continue
        qty = min(float(position.qty), float(guard.get("qty") or order.qty or position.qty))
        if qty <= 0:
            continue
        from app.services.fills import execute_market_fill

        try:
            await execute_market_fill(
                user=user,
                db=db,
                adapter=adapter,
                symbol=order.symbol,
                side="sell",
                qty=qty,
                asset_class="us_equity",
                order_type="market",
                scan_id=order.scan_id,
                strategy_name="Equity exit",
                closing=True,
                submission_path="exit_guard",
                paper_book=True,
            )
        except ValueError as exc:
            logger.info("exit guard left armed symbol={} reason={}", order.symbol, exc)
            continue
        guard["armed"] = False
        guard["closed_by"] = reason
        guard["trigger_price"] = price
        flag_modified(order, "settlement")
        dirty = True
        closed += 1
    if dirty:
        await db.commit()
    return closed


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number
