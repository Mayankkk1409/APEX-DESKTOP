from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage import AccountBalance

# SnapTrade balance history is an optional add-on and looks back at most one year.
BROKER_HISTORY_LIMIT = (
    "The broker’s account-value history goes back at most one year, and only when that "
    "history is enabled on the connection. Earlier points are not estimated."
)
LOCAL_HISTORY_LIMIT = (
    "Broker account-value history was not available. This chart starts at the first balance "
    "APEX recorded for this account, not at the brokerage account’s opening date. "
    "Deposits are not shown as profit."
)

_DEPOSITS = {"CONTRIBUTION", "DEPOSIT", "EXTERNAL_ASSET_TRANSFER_IN"}
_WITHDRAWALS = {"WITHDRAWAL", "EXTERNAL_ASSET_TRANSFER_OUT"}


def broker_value_points(
    history: list[dict],
    cash_flows: list[dict] | None,
    *,
    flows_complete: bool,
) -> tuple[float, list[dict], str]:
    """Portfolio value from broker account-value rows.

    P&L is value change since the first broker point, minus deposits and plus withdrawals
    in that window. Without a complete cash-flow list, P&L is omitted so a deposit is not
    drawn as profit.
    """
    rows = sorted(
        (row for row in history if _value(row) is not None and _when(row)),
        key=lambda row: _when(row) or "",
    )
    if not rows:
        return 0.0, [], LOCAL_HISTORY_LIMIT
    first = _value(rows[0]) or 0.0
    flows = cash_flows if flows_complete and cash_flows is not None else None
    points: list[dict] = []
    for row in rows:
        value = _value(row) or 0.0
        stamp = _when(row) or ""
        point = {
            "t": stamp,
            "portfolio_value": round(value, 2),
            "balance": None,
            "cumulative_pl": _pnl(first, value, stamp, flows) if flows is not None else None,
        }
        points.append(point)
    start = points[0]["t"][:10]
    end = points[-1]["t"][:10]
    note = f"Broker account value from {start} through {end}. {BROKER_HISTORY_LIMIT}"
    if flows is None:
        note += " Cash flows were not available, so the P&L line is omitted."
    return round(first, 2), points, note


def _pnl(first: float, value: float, stamp: str, flows: list[dict]) -> float:
    net = 0.0
    day = stamp[:10]
    for flow in flows:
        when = str(flow.get("t") or "")[:10]
        if not when or when > day:
            continue
        kind = str(flow.get("type") or "").upper()
        amount = abs(float(flow.get("amount") or 0))
        if kind in _DEPOSITS:
            net += amount
        elif kind in _WITHDRAWALS:
            net -= amount
    return round(value - first - net, 2)


def _value(row: dict) -> float | None:
    raw = row.get("total_value", row.get("portfolio_value"))
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _when(row: dict) -> str | None:
    raw = row.get("date") or row.get("t")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.isoformat()
    text = str(raw).strip()
    return text or None


async def brokerage_equity_history_points(db: AsyncSession, account_pk: str) -> tuple[float, list[dict], str]:
    """Cached balances only. Used when the broker does not return earlier history."""
    rows = (
        await db.scalars(
            select(AccountBalance)
            .where(AccountBalance.account_id == account_pk)
            .order_by(AccountBalance.as_of_timestamp.asc())
        )
    ).all()
    if not rows:
        return 0.0, [], LOCAL_HISTORY_LIMIT

    starting = rows[0].total_equity
    points: list[dict] = []
    for row in rows:
        points.append(
            {
                "t": row.as_of_timestamp.isoformat(),
                "portfolio_value": row.total_equity,
                "balance": row.cash_balance,
                "cumulative_pl": None,
            }
        )
    return starting, points, LOCAL_HISTORY_LIMIT
