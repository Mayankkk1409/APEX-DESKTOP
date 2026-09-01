from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
    return kwargs


settings = get_settings()
engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def _run_alembic_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


async def init_db() -> None:
    from app.models import brokerage as _brokerage  # noqa: F401
    from app.models import trading as _trading  # noqa: F401
    from app.models import user as _user  # noqa: F401
    from app.models import user_settings as _user_settings  # noqa: F401

    try:
        await asyncio.to_thread(_run_alembic_migrations)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alembic migration skipped or failed ({}); falling back to create_all", exc)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
