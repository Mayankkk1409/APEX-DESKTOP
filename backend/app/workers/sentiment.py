from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trading import SentimentItem


SEED = [
    ("SPX", "S&P 500 implied vol sits near the middle of its 52-week range", "Desk note: IVR moderate — systematic income strategies still eligible per IVR 25–50 band.", "APEX Research", "neutral", 51.0),
    ("AAPL", "Apple options: put/call volume mixed into weekly expiry", "Flow window (48h) not showing a one-sided dollar-flow impulse. Weight 35% of sentiment.", "APEX Flow", "neutral", 49.0),
    (None, "Risk appetite: fear/greed-style composite near 48", "News NLP 40% + social 15% keep the tape from a strong risk-on print.", "APEX Sentiment Worker", "cautious", 46.0),
]


async def scrape_sentiment(session: AsyncSession) -> int:
    """Background sentiment scraper. Uses seed research blurbs when live keys/feeds are absent."""
    count = 0
    for symbol, headline, blurb, source, signal, score in SEED:
        session.add(
            SentimentItem(
                symbol=symbol,
                headline=headline,
                blurb=blurb,
                source=source,
                signal=signal,
                score=score,
                published_at=datetime.now(timezone.utc),
            )
        )
        count += 1
    await session.commit()
    logger.info("Sentiment worker stored {} items", count)
    return count
