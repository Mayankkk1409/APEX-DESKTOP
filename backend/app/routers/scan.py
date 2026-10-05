from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.alpaca import _is_cash_index
from app.analysis.layers import DEFAULT_AUTO_EXEC_THRESHOLD, DEEP_SCAN_LAYERS, SCAN_SLIDE_LAYERS
from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user, get_adapter
from app.models.trading import Scan
from app.models.user import User
from app.models.user_settings import UserTradingSettings
from app.schemas.market import ChartSnapshot
from app.services.fundamentals_layer import build_fundamentals_layer
from app.services.scan_engine import build_layers
from app.services.sentiment_layer import build_sentiment_layer
from app.strategies.expiry_utils import next_expiry_after

router = APIRouter(prefix="/scan", tags=["scan"])


class ScanIn(BaseModel):
    snapshot: ChartSnapshot
    #: Same expiry the trader picked on the dashboard, carried through the scan session.
    expiry: str | None = None
    #: §5.5 spread cap. Default 10% of mid; the engine clamps to the 15% documented maximum.
    spread_max_pct: float | None = Field(default=None, ge=0.01, le=0.15)
    #: §5.3 explicit override for long Vega in a catalyst environment.
    vega_cap_override: bool = False
    #: §5.4 / §9.2 APEX Strategy structure selected, which absorbs the Gamma flag.
    structure_absorbs_gamma: bool = False


@router.get("/layers")
async def layer_catalog() -> dict:
    return {
        "layers": [l.value for l in DEEP_SCAN_LAYERS],
        "slide_layers": list(SCAN_SLIDE_LAYERS),
    }


@router.post("")
async def create_scan(
    body: ScanIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    adapter=Depends(get_adapter),
    settings: Settings = Depends(get_settings),
) -> dict:
    snap = body.snapshot
    quote = await adapter.quote(snap.symbol)
    bars = await adapter.bars(snap.symbol, snap.timeframe, 180)
    daily_bars = await adapter.bars(snap.symbol, "1D", 400)
    chain = None
    back_month_chain = None
    if body.expiry:
        chain = await adapter.option_chain(snap.symbol, body.expiry)
        if chain and chain.expiry_valid:
            expirations = await adapter.expirations(snap.symbol)
            exp_dates = [e.date for e in expirations]
            back_exp = next_expiry_after(exp_dates, body.expiry)
            if back_exp:
                back_month_chain = await adapter.option_chain(snap.symbol, back_exp)
    elif _is_cash_index(snap.symbol):
        # Cash indexes have no listed equity-options chain and no dashboard expiry.
        # Still probe so the options slide reports unsupported_underlying instead of
        # a generic "pick an expiry" empty state.
        probe = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        chain = await adapter.option_chain(snap.symbol, probe)

    fundamentals = await build_fundamentals_layer(snap.symbol, quote, settings)
    sentiment = await build_sentiment_layer(
        snap.symbol,
        settings,
        chain=chain,
        chain_summary=None,
        fundamentals=fundamentals,
    )

    trading_settings = await db.scalar(select(UserTradingSettings).where(UserTradingSettings.user_id == user.id))
    # Saved account value is the only score gate. 85 applies only when no row exists yet.
    auto_exec_threshold = (
        float(trading_settings.auto_execution_threshold)
        if trading_settings is not None
        else float(DEFAULT_AUTO_EXEC_THRESHOLD)
    )
    risk_profile = trading_settings.risk_profile if trading_settings else "moderate"
    from app.models.trading import Position
    from app.services.stock_leg import read_holdings

    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    held = read_holdings(list(positions), snap.symbol)

    layers = build_layers(
        snap,
        quote,
        bars,
        chain,
        sentiment_score=(
            float(sentiment["score_0_100"])
            if isinstance(sentiment.get("score_0_100"), (int, float))
            else None
        ),
        expiry=body.expiry,
        daily_bars=daily_bars,
        spread_max_pct=body.spread_max_pct,
        vega_cap_override=body.vega_cap_override,
        structure_absorbs_gamma=body.structure_absorbs_gamma,
        sentiment_layer=sentiment,
        fundamentals_layer=fundamentals,
        auto_execution_threshold=auto_exec_threshold,
        risk_profile=risk_profile,
        back_month_chain=back_month_chain,
        shares_held=held.shares_long,
        shares_encumbered=held.shares_encumbered,
        shares_short=held.shares_short,
        share_avg_cost=float(held.avg_cost) if held.avg_cost is not None else None,
        stock_ask=quote.ask,
    )
    score = layers["apex_score"]["composite_score"]
    scan = Scan(user_id=user.id, symbol=snap.symbol.upper(), snapshot=snap.model_dump(), layers=layers, composite_score=score)
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    options_layer = layers.get("options_chain_greeks") or {}
    recommended = options_layer.get("recommendedContract")
    return {
        "id": scan.id,
        "symbol": scan.symbol,
        "composite_score": score,
        "recommendedContract": recommended,
        "layers": [l.value for l in DEEP_SCAN_LAYERS],
        "slide_layers": list(SCAN_SLIDE_LAYERS),
        "layer_data": layers,
    }


@router.get("/{scan_id}")
async def get_scan(scan_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    scan = await db.get(Scan, scan_id)
    if not scan or scan.user_id != user.id:
        raise HTTPException(404, "Scan not found")
    layers = scan.layers or {}
    recommended = (layers.get("options_chain_greeks") or {}).get("recommendedContract")
    return {
        "id": scan.id,
        "symbol": scan.symbol,
        "snapshot": scan.snapshot,
        "composite_score": scan.composite_score,
        "recommendedContract": recommended,
        "layers": [l.value for l in DEEP_SCAN_LAYERS],
        "slide_layers": list(SCAN_SLIDE_LAYERS),
        "layer_data": layers,
    }
