from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user, get_adapter
from app.models.trading import WatchlistItem
from app.models.user import User
from app.services.news_authenticity import map_provider_news, no_recent_news_message
from app.services.sentiment_layer import fetch_alpaca_news

router = APIRouter(tags=["watchlist"])


class WatchIn(BaseModel):
    symbol: str


@router.get("/watchlist")
async def list_watch(user: User = Depends(current_user), db: AsyncSession = Depends(get_db), adapter=Depends(get_adapter)) -> dict:
    rows = (await db.scalars(select(WatchlistItem).where(WatchlistItem.user_id == user.id))).all()
    items = []
    for row in rows:
        q = await adapter.quote(row.symbol)
        items.append({"symbol": row.symbol, "name": q.name, "price": q.price, "change_pct": q.change_pct})
    return {"items": items}


@router.post("/watchlist")
async def add_watch(body: WatchIn, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    sym = body.symbol.upper()
    existing = await db.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == sym))
    if not existing:
        db.add(WatchlistItem(user_id=user.id, symbol=sym))
        await db.commit()
    return {"ok": True, "symbol": sym}


@router.delete("/watchlist/{symbol}")
async def del_watch(symbol: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.scalar(select(WatchlistItem).where(WatchlistItem.user_id == user.id, WatchlistItem.symbol == symbol.upper()))
    if not row:
        raise HTTPException(404, "Not on watchlist")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.get("/sentiment")
async def sentiment(symbol: str | None = None, settings: Settings = Depends(get_settings)) -> dict:
    """Live Alpaca News for one symbol. Headlines are the provider payload, not a local cache."""
    sym = symbol.strip().upper() if symbol and symbol.strip() else None
    raw_news, err = await fetch_alpaca_news(settings, symbol=sym, limit=20)
    if err:
        return {
            "items": [],
            "fear_greed": None,
            "label": "unavailable",
            "status": "unavailable",
            "caveat": err,
            "symbol": sym,
            "score_method": None,
        }
    rows = map_provider_news(raw_news)
    if not rows:
        caveat = (
            "Alpaca News returned articles that were missing a headline, source, or timestamp."
            if raw_news
            else no_recent_news_message(sym)
        )
        return {
            "items": [],
            "fear_greed": None,
            "label": "unavailable" if raw_news else "neutral",
            "status": "unavailable" if raw_news else "empty",
            "caveat": caveat,
            "symbol": sym,
            "score_method": None,
        }
    scores = [r["score"] for r in rows if isinstance(r.get("score"), (int, float))]
    fear = round(sum(scores) / len(scores)) if scores else None
    return {
        "items": rows,
        "fear_greed": fear,
        "label": "neutral" if fear is None else ("greed" if fear >= 60 else "fear" if fear <= 40 else "neutral"),
        "status": "live",
        "caveat": None,
        "symbol": sym,
        "score_method": "lexicon_v1",
        "news_provider": "Alpaca News",
    }
