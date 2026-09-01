"""Volatility routes — Deep Scan layer + standalone refresh."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from app.config import Settings, get_settings
from app.deps import get_adapter
from app.services.catalyst_calendar import fetch_catalyst_calendar
from app.services.volatility_intel import assemble_volatility_payload

router = APIRouter(prefix="/volatility", tags=["volatility"])


def _parse_recommended(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@router.get("/{symbol}")
async def volatility_snapshot(
    symbol: str,
    expiry: str | None = Query(default=None, description="Scan-selected expiry YYYY-MM-DD"),
    strike: float | None = Query(default=None, description="Recommended contract strike"),
    side: str | None = Query(default=None, description="Recommended contract side call|put"),
    contract_id: str | None = Query(default=None, description="OCC contract id"),
    recommended_contract: str | None = Query(
        default=None,
        description="JSON recommendedContract blob from scan session",
    ),
    adapter=Depends(get_adapter),
) -> dict:
    """IV/HV snapshot, ranks, expected move, analysis cards, and chart series."""
    return await assemble_volatility_payload(
        adapter,
        symbol=symbol.upper(),
        expiry=expiry,
        recommended_contract=_parse_recommended(recommended_contract),
        strike=strike,
        side=side,
        contract_id=contract_id,
    )


@router.get("/{symbol}/series")
async def volatility_series(
    symbol: str,
    expiry: str | None = Query(default=None),
    strike: float | None = Query(default=None),
    side: str | None = Query(default=None),
    contract_id: str | None = Query(default=None),
    recommended_contract: str | None = Query(default=None),
    adapter=Depends(get_adapter),
) -> dict:
    """Rolling HV series + recommended-contract IV history for the IV vs HV chart."""
    snap = await volatility_snapshot(
        symbol,
        expiry=expiry,
        strike=strike,
        side=side,
        contract_id=contract_id,
        recommended_contract=recommended_contract,
        adapter=adapter,
    )
    return {
        "symbol": snap["symbol"],
        "expiry": snap.get("expiry"),
        "current_iv": snap.get("iv"),
        "recommended_contract": snap.get("recommended_contract"),
        **(snap.get("series") or {}),
        "methodology": snap.get("methodology"),
        "notes": snap.get("notes"),
    }


@router.get("/{symbol}/events")
async def volatility_events(
    symbol: str,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Ticker + broader market catalyst calendar (real sources only)."""
    return await fetch_catalyst_calendar(symbol.upper(), settings)
