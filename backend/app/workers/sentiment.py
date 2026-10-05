from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.trading import SentimentItem
from app.services.news_authenticity import is_fabricated_sentiment_item, map_provider_news
from app.services.sentiment_layer import fetch_alpaca_news


def _published_at(raw: str) -> datetime | None:
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed


async def _purge_fabricated(session: AsyncSession) -> int:
    rows = (await session.scalars(select(SentimentItem))).all()
    removed = 0
    for row in rows:
        if is_fabricated_sentiment_item(row.headline, row.source):
            await session.delete(row)
            removed += 1
    return removed


async def scrape_sentiment(session: AsyncSession) -> int:
    """Store live Alpaca headlines. Never inserts desk-note seeds when the feed is down."""
    purged = await _purge_fabricated(session)
    settings = get_settings()
    raw_news, err = await fetch_alpaca_news(settings, limit=20)
    if err or not raw_news:
        await session.commit()
        logger.info("Sentiment worker stored 0 items ({})", err or "no articles")
        return 0

    mapped = map_provider_news(raw_news)
    if not mapped:
        await session.commit()
        logger.info("Sentiment worker stored 0 items (provider rows lacked headline, source, or timestamp)")
        return 0

    await session.execute(delete(SentimentItem))
    count = 0
    for item in mapped:
        published = _published_at(str(item["published_at"]))
        if published is None:
            continue
        session.add(
            SentimentItem(
                symbol=item["symbol"],
                headline=item["headline"],
                blurb=item["blurb"] or "",
                source=item["source"],
                signal=item["signal"],
                score=item["score"],
                published_at=published,
            )
        )
        count += 1
    await session.commit()
    logger.info("Sentiment worker stored {} live items (purged {} fabricated)", count, purged)
    return count
