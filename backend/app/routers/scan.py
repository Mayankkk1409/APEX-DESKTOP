from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.alpaca import _is_cash_index
from app.analysis.layers import DEFAULT_AUTO_EXEC_THRESHOLD, DEEP_SCAN_LAYERS, EQUITY_SLIDE_LAYERS, SCAN_SLIDE_LAYERS
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
from app.services.strategy_recommendation import PROFILE_SELECTION_REASON, profile_is_supported
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
    #: Options keeps the current terminal. Equity is a separate research plan.
    research_mode: Literal["options", "equity"] = "options"


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
    from app.analysis.timeframe import completed_bars, is_supported, parse_bar_time

    if not is_supported(snap.timeframe):
        raise HTTPException(400, f"{snap.timeframe} is not a supported chart interval. No daily series was substituted.")
    from app.database import release_db_lock
    from app.models.trading import Position
    from app.services.stock_leg import read_holdings

    trading_settings = await db.scalar(select(UserTradingSettings).where(UserTradingSettings.user_id == user.id))
    auto_exec_threshold = (
        float(trading_settings.auto_execution_threshold)
        if trading_settings is not None
        else float(DEFAULT_AUTO_EXEC_THRESHOLD)
    )
    risk_profile = trading_settings.risk_profile if trading_settings else "moderate"
    positions = (await db.scalars(select(Position).where(Position.user_id == user.id))).all()
    held = read_holdings(list(positions), snap.symbol)
    await release_db_lock(db)
    quote = await adapter.quote(snap.symbol)
    # 600 matches the chart request and covers the 200-period EMA warm-up. 180 did not.
    as_of = parse_bar_time(snap.captured_at) or datetime.now(timezone.utc)
    raw_bars = await adapter.bars(snap.symbol, snap.timeframe, 600)
    bars, provisional = completed_bars(raw_bars, snap.timeframe, as_of)
    origin = str(getattr(quote, "source", "") or "")
    if origin == "not_found":
        raise HTTPException(
            404,
            f"{snap.symbol.upper()} is not a listed instrument. No analysis or trade levels were produced.",
        )
    from datetime import time as clock_time

    from app.services.bar_quality import assess_bars
    from app.services.market_session import NY, is_trading_day

    local_as_of = as_of.astimezone(NY)
    session_open = is_trading_day(local_as_of.date()) and clock_time(9, 30) <= local_as_of.time() < clock_time(16, 0)
    if origin == "provider_unavailable" and not bars:
        quality_reason = (
            "The quote provider did not answer, so this symbol was not analyzed. No generated price was used."
        )
    else:
        quality_reason = assess_bars(
            snap.timeframe,
            bars,
            quote_price=getattr(quote, "price", None),
            as_of=as_of,
            session_open=session_open,
        )
    daily_raw = await adapter.bars(snap.symbol, "1D", 400)
    daily_bars, _daily_open = completed_bars(daily_raw, "1D", as_of)
    equity_mode = body.research_mode == "equity"
    chain = None
    back_month_chain = None
    if not equity_mode and body.expiry:
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
        provisional_candle=provisional,
        research_mode="equity" if equity_mode else "options",
    )
    analysts: list = []
    if equity_mode:
        from app.services.equity_research import assemble_equity_research, parse_analyst_ratings
        from app.services.fundamentals_layer import _http_json, _nasdaq_headers

        raw_ratings = await _http_json(
            f"https://api.nasdaq.com/api/analyst/{snap.symbol}/ratings",
            headers=_nasdaq_headers(snap.symbol),
        )
        analysts = parse_analyst_ratings(raw_ratings)
        layers["equity"] = assemble_equity_research(
            symbol=snap.symbol,
            timeframe=snap.timeframe,
            as_of=str(snap.captured_at) if snap.captured_at else None,
            quote=quote,
            bars=bars,
            technical=layers.get("technical") or {},
            volume=layers.get("volume") or {},
            fundamentals=fundamentals,
            sentiment=sentiment,
            risk_profile=risk_profile,
            shares_held=held.shares_long,
            analysts=analysts,
            provisional_candle=provisional,
            quality_reason=quality_reason,
        )
        for key in ("options_chain_greeks", "volatility", "strategy", "risk_review", "apex_score"):
            layers.pop(key, None)
    if quality_reason:
        layers["data_quality"] = {"ok": False, "reason": quality_reason, "interval": snap.timeframe}
        if equity_mode and isinstance(layers.get("equity"), dict):
            layers["equity"]["action"] = "Insufficient data"
            layers["equity"]["why"] = quality_reason
        review = layers.get("risk_review")
        if isinstance(review, dict):
            review["placeable"] = False
            review["executable"] = False
            review["block_reason"] = quality_reason
            review["equity_legs"] = []
        strategy = layers.get("strategy")
        if isinstance(strategy, dict):
            strategy["placeable"] = False
            strategy["clears_threshold"] = False
            strategy["hard_block_reasons"] = [quality_reason]
    else:
        layers["data_quality"] = {
            "ok": True,
            "interval": snap.timeframe,
            "bar_count": len(bars),
            "last_completed": bars[-1].get("t") if bars else None,
        }
    if equity_mode:
        reported_score = layers["equity"]["scores"]["overall"]
        stored_score = 0.0 if reported_score is None else float(reported_score)
    else:
        raw_score = layers["apex_score"]["composite_score"]
        stored_score = 0.0 if raw_score is None else float(raw_score)
        reported_score = stored_score
    scan = Scan(user_id=user.id, symbol=snap.symbol.upper(), snapshot=snap.model_dump(), layers=layers, composite_score=stored_score)
    db.add(scan)
    await db.commit()
    await db.refresh(scan)
    options_layer = layers.get("options_chain_greeks") or {}
    recommended = options_layer.get("recommendedContract")
    return {
        "id": scan.id,
        "symbol": scan.symbol,
        "composite_score": reported_score,
        "recommendedContract": recommended,
        "research_mode": "equity" if equity_mode else "options",
        "layers": list(EQUITY_SLIDE_LAYERS) if equity_mode else [l.value for l in DEEP_SCAN_LAYERS],
        "slide_layers": list(EQUITY_SLIDE_LAYERS) if equity_mode else list(SCAN_SLIDE_LAYERS),
        "layer_data": layers,
    }


@router.get("/recent")
async def recent_scans(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.scalars(select(Scan).where(Scan.user_id == user.id).order_by(Scan.created_at.desc()).limit(8))
    ).all()
    return {
        "scans": [
            {
                "id": row.id,
                "symbol": row.symbol,
                "composite_score": row.composite_score,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


def _mark_profile_stale(layers: dict, current_profile: str) -> tuple[dict, bool]:
    """A saved scan keeps its history. It is not labeled suitable for a different profile."""
    review = layers.get("risk_review") if isinstance(layers.get("risk_review"), dict) else {}
    stored = review.get("risk_profile")
    stored_text = stored if isinstance(stored, str) else None
    stale = (not profile_is_supported(current_profile)) or (
        stored_text is not None and stored_text != current_profile
    )
    if not stale:
        return layers, False
    note = (
        PROFILE_SELECTION_REASON
        if not profile_is_supported(current_profile)
        else "This scan used a different risk profile. It is not a recommendation for the current profile."
    )
    next_layers = dict(layers)
    next_review = dict(review)
    notes = [item for item in (next_review.get("risk_notes") or []) if isinstance(item, str)]
    if note not in notes:
        notes.append(note)
    next_review["risk_notes"] = notes
    next_review["suitable_for_current_profile"] = False
    next_layers["risk_review"] = next_review
    strategy = next_layers.get("strategy") if isinstance(next_layers.get("strategy"), dict) else {}
    next_strategy = dict(strategy)
    strategy_notes = [item for item in (next_strategy.get("risk_notes") or []) if isinstance(item, str)]
    if note not in strategy_notes:
        strategy_notes.append(note)
    next_strategy["risk_notes"] = strategy_notes
    next_strategy["suitable_for_current_profile"] = False
    next_layers["strategy"] = next_strategy
    return next_layers, True


@router.get("/{scan_id}")
async def get_scan(scan_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    scan = await db.get(Scan, scan_id)
    if not scan or scan.user_id != user.id:
        raise HTTPException(404, "Scan not found")
    trading_settings = await db.scalar(select(UserTradingSettings).where(UserTradingSettings.user_id == user.id))
    current_profile = trading_settings.risk_profile if trading_settings else "moderate"
    layers, profile_stale = _mark_profile_stale(scan.layers or {}, current_profile)
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
        "profile_stale": profile_stale,
        "current_risk_profile": current_profile,
    }
