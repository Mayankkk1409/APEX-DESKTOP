from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.database import SessionLocal, init_db
from app.logging_setup import setup_logging
from app.services.expiry_close import expiry_close_job
from app.workers.sentiment import scrape_sentiment


async def job() -> None:
    async with SessionLocal() as session:
        await scrape_sentiment(session)


async def main() -> None:
    setup_logging()
    await init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(job, "interval", minutes=15, id="sentiment")
    scheduler.add_job(
        expiry_close_job,
        "cron",
        hour=16,
        minute=5,
        timezone="America/New_York",
        id="expiry_close_cutoff",
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.add_job(
        expiry_close_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=35,
        timezone="America/New_York",
        id="expiry_close_catchup",
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    logger.info("APEX worker started — sentiment scrape every 15m; expiry close 16:05 America/New_York")
    await job()
    await expiry_close_job()
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
