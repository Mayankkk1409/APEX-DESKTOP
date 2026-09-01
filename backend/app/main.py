from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import get_settings
from app.database import init_db
from app.logging_setup import setup_logging
from app.routers import auth, brokerage, health, market, portfolio, scan, volatility, watchlist, ws


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
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="APEX Desktop API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(brokerage.router)
    app.include_router(market.router)
    app.include_router(volatility.router)
    app.include_router(portfolio.router)
    app.include_router(scan.router)
    app.include_router(watchlist.router)
    app.include_router(ws.router)
    return app


app = create_app()
