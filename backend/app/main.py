from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import get_settings
from app.database import init_db
from app.logging_setup import setup_logging
from app.routers import assistant, auth, brokerage, expiry, health, ledger, market, portfolio, scan, volatility, watchlist, ws
from app.strategies.knowledge_base import validate_knowledge_base
from app.routers import settings as settings_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    await init_db()
    settings = get_settings()
    logger.info(
        "APEX backend up env={} adapter={} feed_hint={}",
        settings.app_env,
        "alpaca" if settings.alpaca_keys_present else "demo",
        settings.alpaca_trading_mode,
    )
    kb_errors = validate_knowledge_base()
    if kb_errors:
        raise RuntimeError("Knowledge base failed validation: " + "; ".join(kb_errors[:8]))

    from app.services.expiry_close import expiry_close_job, start_expiry_scheduler

    scheduler = start_expiry_scheduler()
    if scheduler is not None:
        asyncio.create_task(expiry_close_job())
    queue_stop = asyncio.Event()

    async def _queued_orders() -> None:
        from app.database import SessionLocal
        from app.deps import get_adapter
        from app.services.order_queue import process_queued_orders

        while not queue_stop.is_set():
            try:
                adapter = get_adapter(settings)
                # One short session per job. A single session across quotes and
                # broker reads kept SQLite locked and made sign-in hang.
                async with SessionLocal() as session:
                    await process_queued_orders(session, adapter)
                from app.services.order_queue import reconcile_broker_orders

                async with SessionLocal() as session:
                    await reconcile_broker_orders(session, adapter)
                from app.services.exit_guard import enforce_exit_guards

                async with SessionLocal() as session:
                    await enforce_exit_guards(session, adapter)
            except Exception as exc:  # noqa: BLE001
                logger.warning("queued order pass failed ({}): {}", type(exc).__name__, exc)
            try:
                await asyncio.wait_for(queue_stop.wait(), timeout=15)
            except TimeoutError:
                continue

    queue_task = asyncio.create_task(_queued_orders())
    from app.services.broker_stream import start_trade_stream

    stream_task = start_trade_stream(queue_stop)
    yield
    queue_stop.set()
    queue_task.cancel()
    if stream_task is not None:
        stream_task.cancel()
    if scheduler is not None:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app_settings = get_settings()
    app = FastAPI(title="APEX Desktop API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(assistant.router)
    app.include_router(auth.router)
    app.include_router(brokerage.router)
    app.include_router(market.router)
    app.include_router(volatility.router)
    app.include_router(portfolio.router)
    app.include_router(expiry.router)
    app.include_router(settings_router.router)
    app.include_router(scan.router)
    app.include_router(ledger.router)
    app.include_router(watchlist.router)
    app.include_router(ws.router)
    return app


app = create_app()
