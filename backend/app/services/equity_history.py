from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage import AccountBalance


async def brokerage_equity_history_points(db: AsyncSession, account_pk: str) -> tuple[float, list[dict]]:
    """Build equity history from cached balance snapshots for a brokerage account."""
    rows = (
        await db.scalars(
            select(AccountBalance)
            .where(AccountBalance.account_id == account_pk)
            .order_by(AccountBalance.as_of_timestamp.asc())
        )
    ).all()
    if not rows:
        return 0.0, []

    starting = rows[0].total_equity
    points: list[dict] = []
    for row in rows:
        equity = row.total_equity
        points.append(
            {
                "t": row.as_of_timestamp.isoformat(),
                "portfolio_value": equity,
                "balance": row.cash_balance,
                "cumulative_pl": round(equity - starting, 2),
            }
        )
    return starting, points
