from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user, get_adapter
from app.models.trading import Order, Position
from app.models.user import User
from app.services.fills import execute_market_fill, execute_strategy_legs
from app.services.orders import account_impact, estimate_order_cost
from app.services.portfolio_pnl import account_baseline, pnl_history_points, symbol_pnl_rows

router = APIRouter(prefix="/api", tags=["portfolio"])


class StrategyLegIn(BaseModel):
    symbol: str
    side: str
    qty: float = Field(gt=0, default=1)
    strike: float | None = None
    option_side: str | None = None
    expiry: str | None = None


class OrderIn(BaseModel):
    symbol: str | None = None
    side: str | None = None
    qty: float | None = Field(default=None, gt=0)
    order_type: str = "market"
    limit_price: float | None = None
    scan_id: str | None = None
    thesis_accepted: bool = False
    asset_class: str = "us_option"
    legs: list[StrategyLegIn] | None = None
    contracts_per_leg: float = Field(default=1, gt=0)


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
    }


@router.get("/portfolio")
async def portfolio(user: User = Depends(current_user), db: AsyncSession = Depends(get_db), adapter=Depends(get_adapter)) -> dict:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    live_value = user.cash_balance
    movers = []
    for pos in positions:
        q = await adapter.quote(pos.symbol)
        if q.price is not None:
            pos.current_price = q.price
        live_value += pos.market_value
        movers.append(
            {
                "symbol": pos.symbol,
                "qty": pos.qty,
                "avg_cost": pos.avg_cost,
                "current": pos.current_price,
                "unrealized_pl": pos.unrealized_pl,
                "market_value": pos.market_value,
                "day_pct": q.change_pct,
                "asset_class": pos.asset_class,
            }
        )
    user.portfolio_value = live_value
    user.buying_power = user.cash_balance
    await db.commit()
    day_pl = sum(m["unrealized_pl"] for m in movers)
    basis = user.starting_balance or user.portfolio_value or 1
    return {
        "balance": user.cash_balance,
        "buying_power": user.buying_power,
        "portfolio_value": user.portfolio_value,
        "day_pl": day_pl,
        "day_pct": (day_pl / basis) * 100,
        "top_movers": sorted(movers, key=lambda m: abs(m["unrealized_pl"]), reverse=True)[:5],
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
    for pos in positions:
        q = await adapter.quote(pos.symbol)
        if q.price is not None:
            pos.current_price = q.price
    orders = (await db.scalars(select(Order).where(Order.user_id == user.id))).all()
    baseline = account_baseline(user)
    points = pnl_history_points(user, list(orders), list(positions))
    await db.commit()
    return {
        "starting_balance": baseline,
        "account_mode": user.account_mode,
        "points": points,
    }


@router.get("/portfolio/overall-pnl")
async def portfolio_overall_pnl(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    for pos in positions:
        q = await adapter.quote(pos.symbol)
        if q.price is not None:
            pos.current_price = q.price
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
    out = []
    for pos in rows:
        q = await adapter.quote(pos.symbol)
        if q.price is not None:
            pos.current_price = q.price
        out.append(_position_row(pos))
    await db.commit()
    return {"positions": out}


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


@router.get("/orders")
async def order_history(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.scalars(select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()))
    ).all()
    return {
        "orders": [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": o.qty,
                "order_type": o.order_type,
                "fill_price": o.fill_price,
                "status": o.status,
                "asset_class": o.asset_class,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            }
            for o in rows
        ]
    }


@router.post("/orders")
async def place_order(
    body: OrderIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
) -> dict:
    if body.scan_id and not body.thesis_accepted:
        raise HTTPException(400, "Thesis checkbox required before submitting a scanned order")

    if body.legs:
        try:
            orders = await execute_strategy_legs(
                user=user,
                db=db,
                adapter=adapter,
                legs=[leg.model_dump() for leg in body.legs],
                scan_id=body.scan_id,
                contracts_per_leg=body.contracts_per_leg,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        last = orders[-1]
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
            "legs_filled": [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "qty": o.qty,
                    "fill_price": o.fill_price,
                    "asset_class": o.asset_class,
                }
                for o in orders
            ],
        }

    if not body.symbol or not body.side or body.qty is None:
        raise HTTPException(400, "symbol, side, and qty are required when legs are omitted")
    if body.asset_class != "us_option":
        raise HTTPException(400, "APEX terminal is options-only — asset_class must be us_option")

    quote = await adapter.quote(body.symbol)
    px = body.limit_price if body.order_type == "limit" and body.limit_price is not None else quote.price
    if px is None:
        raise HTTPException(503, "Live quote unavailable for this symbol")
    mult = 100 if body.asset_class == "us_option" else 1
    cost = estimate_order_cost(body.qty, px, asset_class=body.asset_class, multiplier=mult)  # type: ignore[arg-type]
    if body.side == "buy" and cost > user.buying_power:
        raise HTTPException(400, "Insufficient buying power")
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
        )
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    impact = account_impact(body.side, cost)
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
