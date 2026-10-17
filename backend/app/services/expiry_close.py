"""Expiry-day alerts and idempotent paper closes.

Paper and Alpaca ledger positions that are still open at the regular-session
cutoff (16:00 America/New_York) on their expiry date are closed through the
existing quote and fill path. SnapTrade read-only accounts are never submitted.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import Position
from app.models.user import User
from app.services.executability import marketable_limit
from app.services.fills import execute_market_fill
from app.services.occ_symbol import expiry_iso_from_text, parse_occ, parse_occ_expiry

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
ALERT_WINDOW_DAYS = 7
AUTO_CLOSE_NOTICE = (
    "Positions still open at the cutoff on their expiry day will be closed automatically."
)


def as_ny(now: datetime | None = None) -> datetime:
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(NY)


def ny_today(now: datetime | None = None) -> date:
    return as_ny(now).date()


def market_is_open(local: datetime) -> bool:
    if local.weekday() >= 5:
        return False
    clock = local.time()
    return MARKET_OPEN <= clock < MARKET_CLOSE


def within_alert_window(expiry: date, today: date) -> bool:
    days = (expiry - today).days
    return 0 <= days <= ALERT_WINDOW_DAYS


def due_for_auto_close(expiry: date, today: date, local: datetime, cutoff: time) -> bool:
    if expiry < today:
        return True
    return expiry == today and local.time() >= cutoff


def _direction(qty: float | None) -> str | None:
    if qty is None or qty == 0:
        return None
    return "short" if qty < 0 else "long"


def _contract_fields(symbol: str, qty: float | None) -> dict[str, Any]:
    """Strike, call/put, and long/short from the same OCC row the close job reads."""
    parsed = parse_occ(symbol)
    if parsed is None:
        return {"strike": None, "right": None, "direction": _direction(qty)}
    return {
        "strike": parsed.strike,
        "right": "call" if parsed.right == "C" else "put",
        "direction": _direction(qty),
    }


def _qty_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def expiring_notices(user: User, positions: list[Position], today: date) -> list[dict[str, Any]]:
    closable = user.account_mode == "paper_funded"
    rows: list[dict[str, Any]] = []
    for pos in positions:
        if pos.qty == 0:
            continue
        expiry = parse_occ_expiry(pos.symbol)
        if expiry is None or not within_alert_window(expiry, today):
            continue
        rows.append(
            {
                "position_id": pos.id,
                "symbol": pos.symbol,
                "strategy": pos.strategy_name or "—",
                "expiry": expiry.isoformat(),
                "days_left": (expiry - today).days,
                "can_close": bool(closable and pos.qty > 0),
                **_contract_fields(pos.symbol, float(pos.qty)),
            }
        )
    rows.sort(key=lambda row: (row["expiry"], row["symbol"]))
    return rows


def notices_from_external(rows: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """SnapTrade (and any other read-only book) — alert only, never closable here."""
    out: list[dict[str, Any]] = []
    for row in rows:
        iso = row.get("expiry") or expiry_iso_from_text(row.get("symbol"))
        if not iso:
            continue
        try:
            expiry = date.fromisoformat(str(iso)[:10])
        except ValueError:
            continue
        if not within_alert_window(expiry, today):
            continue
        symbol = str(row.get("symbol") or "").strip()
        if not symbol:
            continue
        qty = _qty_or_none(row.get("quantity") if row.get("quantity") is not None else row.get("qty"))
        out.append(
            {
                "position_id": None,
                "symbol": symbol,
                "strategy": str(row.get("strategy") or "—"),
                "expiry": expiry.isoformat(),
                "days_left": (expiry - today).days,
                "can_close": False,
                **_contract_fields(symbol, qty),
            }
        )
    return out


def merge_notices(primary: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(row["symbol"]) for row in primary}
    merged = list(primary)
    for row in extra:
        symbol = str(row["symbol"])
        if symbol in seen:
            continue
        merged.append(row)
        seen.add(symbol)
    merged.sort(key=lambda row: (row["expiry"], row["symbol"]))
    return merged


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


async def _settlement_price(adapter: Any, symbol: str, side: str, stored_mark: float | None) -> float | None:
    """Price an expiring contract from the live quote, then the mark already on the position.

    An explicit zero quote is a worthless settlement. A missing quote is not turned into zero.
    """
    quote = None
    try:
        quote = await adapter.quote(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("expiry quote failed symbol={} reason={}", symbol, type(exc).__name__)
    price = _number(getattr(quote, "price", None)) if quote is not None else None
    bid = _number(getattr(quote, "bid", None)) if quote is not None else None
    ask = _number(getattr(quote, "ask", None)) if quote is not None else None
    if price == 0 and not (bid is not None and bid > 0) and not (ask is not None and ask > 0):
        return 0.0
    if quote is not None:
        live = marketable_limit(side, quote)
        if live is not None:
            return live[0]
    if stored_mark is not None and stored_mark > 0:
        return round(float(stored_mark), 2)
    return None


async def close_expiring_paper_positions(
    db: AsyncSession,
    adapter: Any,
    *,
    now: datetime | None = None,
    cutoff: time = MARKET_CLOSE,
) -> dict[str, int]:
    """Close paper/Alpaca positions that expire today once the cutoff has passed.

    A second call is a no-op for anything already filled: the position row is
    removed in the same transaction as the fill. Read-only brokerage accounts
    are not loaded and no order is submitted for them.
    """
    local = as_ny(now)
    today = local.date()
    # Paper books always settle locally at expiry. A live broker reject during the
    # morning catch-up would leave an expired contract open and cash wrong.
    users = (await db.scalars(select(User).where(User.account_mode == "paper_funded"))).all()
    closed = 0
    for user in users:
        await db.refresh(user)
        positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
        due: list[tuple[str, float, str, float | None]] = []
        for pos in positions:
            expiry = parse_occ_expiry(pos.symbol)
            if expiry is None or pos.qty == 0:
                continue
            if not due_for_auto_close(expiry, today, local, cutoff):
                continue
            stored = _number(pos.current_price)
            due.append((pos.symbol, float(pos.qty), pos.asset_class or "us_option", stored))
        await db.commit()
        for symbol, qty, asset_class, stored in due:
            side = "sell" if qty > 0 else "buy"
            price = await _settlement_price(adapter, symbol, side, stored)
            if price is None:
                logger.warning("expiry close skipped symbol={} reason=no settlement price", symbol)
                continue
            try:
                await db.refresh(user)
                await execute_market_fill(
                    user=user,
                    db=db,
                    adapter=adapter,
                    symbol=symbol,
                    side=side,
                    qty=abs(qty),
                    asset_class=asset_class,
                    force_paper=True,
                    closing=True,
                    mark_price=price,
                    submission_path="expiry_close",
                    strategy_name="Expiry close",
                    paper_book=True,
                )
                closed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("expiry close skipped symbol={} reason={}", symbol, exc)
    if closed:
        logger.info("expiry close finished closed={}", closed)
    return {"closed": closed}


def jobs_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENTTEST"):
        return False
    if os.environ.get("APEX_DISABLE_EXPIRY_JOB") == "1":
        return False
    return True


async def expiry_close_job() -> None:
    from app.adapters.alpaca import AlpacaAdapter
    from app.config import get_settings
    from app.database import SessionLocal

    adapter = AlpacaAdapter(get_settings())
    async with SessionLocal() as session:
        try:
            await close_expiring_paper_positions(session, adapter)
        except Exception as exc:  # noqa: BLE001
            logger.warning("expiry close job failed reason={}", type(exc).__name__)


def start_expiry_scheduler():
    """Daily cutoff plus a weekday morning catch-up. Returns None under pytest."""
    if not jobs_enabled():
        return None
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    opts = {"timezone": "America/New_York", "misfire_grace_time": 3600, "coalesce": True}
    scheduler.add_job(expiry_close_job, "cron", hour=16, minute=5, id="expiry_close_cutoff", **opts)
    scheduler.add_job(
        expiry_close_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=35,
        id="expiry_close_catchup",
        **opts,
    )
    scheduler.start()
    logger.info("expiry close scheduled 16:05 America/New_York and weekday 09:35 catch-up")
    return scheduler
