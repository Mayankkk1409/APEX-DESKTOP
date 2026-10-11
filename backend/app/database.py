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
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        kwargs["pool_pre_ping"] = True
    return kwargs


settings = get_settings()
engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _sqlite_busy_timeout(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


if settings.database_url.startswith("sqlite"):
    from sqlalchemy import event

    event.listen(engine.sync_engine, "connect", _sqlite_busy_timeout)


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


def _repair_sqlite_order_columns() -> None:
    """Add fill columns when the stamped revision is ahead of this tree.

    create_all does not alter an existing orders table. P&L history selects
    filled_qty, so a missing column becomes HTTP 500 for the portfolio graph.
    """
    url = settings.database_url
    if not url.startswith("sqlite"):
        return
    import sqlite3

    raw = url.split("///", 1)[-1]
    path = raw.split("?", 1)[0]
    if path in {"", ":memory:"}:
        return
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    if not db_path.exists():
        return
    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "orders" not in tables:
            return
        cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
        if "filled_qty" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN filled_qty FLOAT NOT NULL DEFAULT 0")
        if "venue" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN venue VARCHAR(16)")
        if "broker_order_id" not in cols:
            conn.execute("ALTER TABLE orders ADD COLUMN broker_order_id VARCHAR(64)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_orders_broker_order_id ON orders (broker_order_id)")
        conn.commit()


async def init_db() -> None:
    from app.models import brokerage as _brokerage  # noqa: F401
    from app.models import otp_device as _otp_device  # noqa: F401
    from app.models import trading as _trading  # noqa: F401
    from app.models import user as _user  # noqa: F401
    from app.models import user_settings as _user_settings  # noqa: F401

    try:
        await asyncio.to_thread(_run_alembic_migrations)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alembic migration skipped or failed ({}); falling back to create_all", exc)
    try:
        await asyncio.to_thread(_repair_sqlite_order_columns)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Order column repair failed ({})", exc)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
