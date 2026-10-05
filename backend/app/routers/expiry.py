"""Login/session expiry notice. Read-only brokerage books are listed, never traded."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models.brokerage import BrokerageAccount, BrokerageConnection
from app.models.trading import Position
from app.models.user import User
from app.services.expiry_close import (
    AUTO_CLOSE_NOTICE,
    expiring_notices,
    merge_notices,
    notices_from_external,
    ny_today,
)

router = APIRouter(prefix="/api", tags=["expiry"])


async def _readonly_brokerage_notices(db: AsyncSession, user_id: str, today: date) -> list[dict]:
    from app.services import snaptrade as st

    if not st.get_snaptrade_settings().configured:
        return []
    connection = await db.scalar(
        select(BrokerageConnection).where(
            BrokerageConnection.user_id == user_id,
            BrokerageConnection.provider == "snaptrade",
            BrokerageConnection.connection_status == "connected",
        )
    )
    if connection is None:
        return []
    try:
        secret = st.decrypt_user_secret(connection.snaptrade_user_secret_encrypted)
    except Exception:  # noqa: BLE001
        logger.warning("expiry watch could not read brokerage credentials")
        return []
    accounts = (
        await db.scalars(select(BrokerageAccount).where(BrokerageAccount.connection_id == connection.id))
    ).all()
    rows: list[dict] = []
    for account in accounts:
        try:
            positions = await st.fetch_positions(connection.snaptrade_user_id, secret, account.account_id)
        except Exception:  # noqa: BLE001
            logger.warning("expiry watch brokerage positions unavailable")
            continue
        rows.extend(notices_from_external(positions, today))
    return rows


@router.get("/expiry-watch")
async def expiry_watch(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    today = ny_today()
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    paper = expiring_notices(user, list(positions), today)
    try:
        external = await _readonly_brokerage_notices(db, user.id, today)
    except Exception:  # noqa: BLE001
        logger.warning("expiry watch brokerage read skipped")
        external = []
    return {
        "market_day": today.isoformat(),
        "notice": AUTO_CLOSE_NOTICE,
        "is_paper": user.account_mode == "paper_funded",
        "items": merge_notices(paper, external),
    }
