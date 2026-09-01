from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.database import SessionLocal, init_db
from app.logging_setup import setup_logging
from app.workers.sentiment import scrape_sentiment


async def job() -> None:
    async with SessionLocal() as session:
        await scrape_sentiment(session)


async def main() -> None:
    setup_logging()
    await init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job, "interval", minutes=15, id="sentiment")
    scheduler.start()
    logger.info("APEX worker started — sentiment scrape every 15m")
    await job()
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
