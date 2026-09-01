from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user, get_adapter
from app.models.trading import SentimentItem, WatchlistItem
from app.models.user import User

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
async def sentiment(db: AsyncSession = Depends(get_db)) -> dict:
    """Dashboard feed. Never invent headlines — empty list when the worker has nothing."""
    rows = (await db.scalars(select(SentimentItem).order_by(SentimentItem.published_at.desc()).limit(20))).all()
    if not rows:
        return {
            "items": [],
            "fear_greed": None,
            "label": "unavailable",
            "status": "unavailable",
            "caveat": "No live sentiment rows stored. Deep Scan uses Alpaca news + chain flow instead.",
        }
    scores = [r.score for r in rows if r.score is not None]
    fear = round(sum(scores) / len(scores)) if scores else None
    return {
        "items": [
            {
                "headline": r.headline,
                "blurb": r.blurb,
                "source": r.source,
                "signal": r.signal,
                "score": r.score,
                "published_at": r.published_at.isoformat(),
                "symbol": r.symbol,
            }
            for r in rows
        ],
        "fear_greed": fear,
        "label": "neutral" if fear is None else ("greed" if fear >= 60 else "fear" if fear <= 40 else "neutral"),
        "status": "live",
    }
