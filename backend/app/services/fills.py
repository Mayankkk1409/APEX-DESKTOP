from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Order, Position
from app.models.user import User
from app.services.orders import account_impact, estimate_order_cost
from app.ws.hub import hub


def position_multiplier(asset_class: str) -> int:
    return 100 if asset_class == "us_option" else 1


async def refresh_portfolio_value(user: User, db: AsyncSession, adapter: Any) -> float:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    live_value = user.cash_balance
    for pos in positions:
        q = await adapter.quote(pos.symbol)
        if q.price is not None:
            pos.current_price = q.price
        mult = position_multiplier(pos.asset_class)
        live_value += pos.qty * pos.current_price * mult
    user.portfolio_value = round(live_value, 2)
    user.buying_power = user.cash_balance
    return user.portfolio_value


async def execute_market_fill(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    symbol: str,
    side: str,
    qty: float,
    asset_class: str = "us_equity",
    order_type: str = "market",
    limit_price: float | None = None,
    scan_id: str | None = None,
) -> Order:
    quote = await adapter.quote(symbol)
    px = limit_price if order_type == "limit" and limit_price is not None else quote.price
    if px is None:
        raise ValueError("Live quote unavailable for this symbol")
    mult = position_multiplier(asset_class)
    cost = estimate_order_cost(qty, px, asset_class=asset_class, multiplier=mult)  # type: ignore[arg-type]
    impact = account_impact(side, cost)
    if side == "buy" and cost > user.buying_power:
        raise ValueError("Insufficient buying power")

    order = Order(
        user_id=user.id,
        scan_id=scan_id,
        symbol=symbol.upper(),
        side=side,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
        estimated_cost=cost,
        asset_class=asset_class,
        multiplier=mult,
        status="accepted",
    )
    db.add(order)
    await db.flush()

    broker = await adapter.submit_order(
        symbol=order.symbol,
        qty=order.qty,
        side=order.side,
        order_type=order.order_type,
        limit_price=order.limit_price,
    )
    fill_px = float(broker.get("filled_avg_price") or px)
    order.status = "filled"
    order.fill_price = fill_px
    order.filled_at = datetime.now(timezone.utc)

    pos = await db.scalar(select(Position).where(Position.user_id == user.id, Position.symbol == order.symbol))
    signed = order.qty if order.side == "buy" else -order.qty
    if pos:
        new_qty = pos.qty + signed
        if new_qty == 0:
            await db.delete(pos)
        elif order.side == "buy":
            pos.avg_cost = (pos.avg_cost * pos.qty + fill_px * order.qty) / new_qty
            pos.qty = new_qty
            pos.current_price = fill_px
        else:
            pos.qty = new_qty
            pos.current_price = fill_px
    elif order.side == "buy":
        db.add(
            Position(
                user_id=user.id,
                symbol=order.symbol,
                qty=order.qty,
                avg_cost=fill_px,
                current_price=fill_px,
                asset_class=asset_class,
            )
        )

    user.cash_balance = round(user.cash_balance + impact, 2)
    await refresh_portfolio_value(user, db, adapter)
    await db.commit()
    await db.refresh(order)

    await hub.broadcast(
        user.id,
        {
            "type": "fill",
            "order_id": order.id,
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "price": fill_px,
            "asset_class": order.asset_class,
            "balance": user.cash_balance,
            "buying_power": user.buying_power,
            "portfolio_value": user.portfolio_value,
        },
    )
    return order


async def execute_strategy_legs(
    *,
    user: User,
    db: AsyncSession,
    adapter: Any,
    legs: list[dict[str, Any]],
    scan_id: str | None = None,
    contracts_per_leg: float = 1,
) -> list[Order]:
    """Fill each recommended options leg as a separate us_option market order."""
    if not legs:
        raise ValueError("Strategy legs are required for options execution")
    qty = contracts_per_leg
    if qty <= 0:
        raise ValueError("contracts_per_leg must be positive")
    orders: list[Order] = []
    for leg in legs:
        occ = str(leg.get("symbol") or "").upper()
        side = str(leg.get("side") or "").lower()
        if not occ or side not in {"buy", "sell"}:
            raise ValueError("Each leg must include an OCC symbol and buy/sell side")
        order = await execute_market_fill(
            user=user,
            db=db,
            adapter=adapter,
            symbol=occ,
            side=side,
            qty=qty,
            asset_class="us_option",
            order_type="market",
            scan_id=scan_id,
        )
        orders.append(order)
    return orders
