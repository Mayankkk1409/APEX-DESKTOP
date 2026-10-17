"""Login arrival notices: closes first, then executions, then expiry is separate."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.trading import Order
from app.services.expiry_close import ny_today
from app.services.order_queue import pending_execution_notices

NY = ZoneInfo("America/New_York")


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _market_day_utc_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0, 0), tzinfo=NY).astimezone(timezone.utc)
    end = datetime.combine(day, time(23, 59, 59, 999999), tzinfo=NY).astimezone(timezone.utc)
    return start, end


def _has_close_basis(raw: object) -> bool:
    return isinstance(raw, dict) and raw.get("basis") is not None and raw.get("closed_qty") is not None


def _is_close_settlement(raw: object) -> bool:
    if not _has_close_basis(raw):
        return False
    return not bool(raw.get("login_notice_ack"))  # type: ignore[union-attr]


def _filled_on_market_day(order: Order, day: date) -> bool:
    stamp = order.filled_at or order.created_at
    if stamp is None:
        return False
    return _aware(stamp).astimezone(NY).date() == day


async def closed_today_notices(db: AsyncSession, user_id: str, *, day: date | None = None) -> list[dict[str, Any]]:
    """Legs closed today that the desk has not announced on sign-in yet."""
    market_day = day or ny_today()
    start, end = _market_day_utc_bounds(market_day)
    rows = (
        await db.scalars(
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.status == "filled",
                Order.filled_at.is_not(None),
                Order.filled_at >= start,
                Order.filled_at <= end,
            )
            .order_by(Order.filled_at.desc())
        )
    ).all()
    notices: list[dict[str, Any]] = []
    for order in rows:
        if not _is_close_settlement(order.settlement):
            continue
        if not _filled_on_market_day(order, market_day):
            continue
        settlement = order.settlement if isinstance(order.settlement, dict) else {}
        notices.append(
            {
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "qty": abs(float(settlement.get("closed_qty") or order.filled_qty or order.qty or 0)),
                "fill_price": order.fill_price,
                "basis": settlement.get("basis"),
                "kind": "close",
            }
        )
    return notices


async def ack_closed_today_notices(db: AsyncSession, user_id: str, ids: list[str]) -> int:
    if not ids:
        return 0
    rows = (await db.scalars(select(Order).where(Order.user_id == user_id, Order.id.in_(ids)))).all()
    acked = 0
    for order in rows:
        settlement = dict(order.settlement) if isinstance(order.settlement, dict) else None
        if settlement is None or not _has_close_basis(settlement):
            continue
        if settlement.get("login_notice_ack") is True:
            continue
        settlement["login_notice_ack"] = True
        order.settlement = settlement
        flag_modified(order, "settlement")
        acked += 1
    if acked:
        await db.commit()
    return acked


async def session_arrival_bundle(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """Closed legs first, then pending queue executions. Expiry stays on /expiry-watch."""
    day = ny_today()
    return {
        "market_day": day.isoformat(),
        "closed_today": await closed_today_notices(db, user_id, day=day),
        "executed_today": await pending_execution_notices(db, user_id),
    }
