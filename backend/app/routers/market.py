from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.services.live_quotes import get_live_fundamentals, get_live_quote
from app.services.article_reader import fetch_article_content
from app.services.fundamentals_layer import build_fundamentals_layer
from app.services.options_analysis import build_chain_analysis
from app.services.sentiment_layer import build_sentiment_layer
from app.config import Settings, get_settings
from app.deps import get_adapter
from app.analysis.indicators import compute_all, historical_vol

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/search")
async def search(q: str = Query(min_length=1), adapter=Depends(get_adapter)) -> dict:
    hits = await adapter.search(q)
    return {"hits": [h.model_dump() for h in hits]}


@router.get("/quote/{symbol}")
async def quote(symbol: str, settings: Settings = Depends(get_settings)) -> dict:
    q = await get_live_quote(symbol, settings)
    return q.model_dump()


@router.get("/fundamentals/{symbol}")
async def fundamentals(symbol: str, settings: Settings = Depends(get_settings)) -> dict:
    f = await get_live_fundamentals(symbol, settings)
    return f.model_dump()


@router.get("/fundamentals/{symbol}/deep")
async def fundamentals_deep(symbol: str, settings: Settings = Depends(get_settings)) -> dict:
    """§7.2 Deep Scan fundamentals — EPS, revenue, calendar, consensus, sector rotation."""
    quote = await get_live_quote(symbol, settings)
    return await build_fundamentals_layer(symbol, quote, settings)


@router.get("/news/article")
async def news_article(
    url: str = Query(min_length=8),
    fallback_text: str | None = Query(default=None, max_length=12000),
) -> dict:
    """Fetch publisher HTML and extract readable article body for the sentiment modal."""
    return await fetch_article_content(url, fallback_text=fallback_text)


@router.get("/sentiment/{symbol}")
async def sentiment_deep(
    symbol: str,
    expiry: str | None = None,
    adapter=Depends(get_adapter),
    settings: Settings = Depends(get_settings),
) -> dict:
    """§7.1 Deep Scan sentiment — Alpaca news NLP + chain-derived flow/P/C."""
    chain = await adapter.option_chain(symbol, expiry) if expiry else None
    fundamentals = await build_fundamentals_layer(symbol, await get_live_quote(symbol, settings), settings)
    return await build_sentiment_layer(
        symbol,
        settings,
        chain=chain,
        chain_summary=None,
        fundamentals=fundamentals,
    )


@router.get("/bars/{symbol}")
async def bars(symbol: str, timeframe: str = "1D", limit: int = 400, adapter=Depends(get_adapter)) -> dict:
    data = await adapter.bars(symbol, timeframe, limit)
    return {"symbol": symbol.upper(), "timeframe": timeframe, "bars": data}


@router.get("/indicators/{symbol}")
async def indicators(symbol: str, timeframe: str = "1D", adapter=Depends(get_adapter)) -> dict:
    data = await adapter.bars(symbol, timeframe, 400)
    highs = [b["h"] for b in data]
    lows = [b["l"] for b in data]
    closes = [b["c"] for b in data]
    vols = [b["v"] for b in data]
    return {"symbol": symbol.upper(), "timeframe": timeframe, **compute_all(highs, lows, closes, vols)}


@router.get("/expirations/{symbol}")
async def expirations(symbol: str, adapter=Depends(get_adapter)) -> dict:
    exps = await adapter.expirations(symbol)
    return {"symbol": symbol.upper(), "expirations": [e.model_dump() for e in exps]}


@router.get("/options/{symbol}")
async def options(symbol: str, expiry: str, adapter=Depends(get_adapter)) -> dict:
    chain = await adapter.option_chain(symbol, expiry)
    return chain.model_dump()


@router.get("/options/{symbol}/analysis")
async def options_analysis(
    symbol: str,
    expiry: str,
    spread_max_pct: float | None = Query(default=None, ge=0.01, le=0.15),
    vega_cap_override: bool = False,
    structure_absorbs_gamma: bool = False,
    adapter=Depends(get_adapter),
) -> dict:
    """Combined chain + Greeks evaluation for one expiry (Full Document §5).

    Same payload the ``options_chain_greeks`` scan layer carries, exposed standalone so the
    chain can be refreshed without re-running a whole scan.
    """
    chain = await adapter.option_chain(symbol, expiry)
    bars = await adapter.bars(symbol, "1D", 180)
    hv = historical_vol([float(b["c"]) for b in bars]) if bars else None
    return build_chain_analysis(
        chain,
        symbol=symbol,
        expiry=expiry,
        hv=hv,
        spread_max_pct=spread_max_pct,
        vega_cap_override=vega_cap_override,
        structure_absorbs_gamma=structure_absorbs_gamma,
    )


@router.get("/feed")
async def feed(settings: Settings = Depends(get_settings), adapter=Depends(get_adapter)) -> dict:
    return {
        "adapter": getattr(adapter, "name", "demo"),
        "feed": getattr(adapter, "feed", "indicative"),
        "alpaca_keys": settings.alpaca_keys_present,
        "trading_mode": settings.alpaca_trading_mode,
        "default_symbol": settings.default_symbol,
    }
