"""SQLite must not hold a write lock across network. That hung sign-in overnight."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.mark.asyncio
async def test_sqlite_file_opens_in_wal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "desk.db"
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url, future=True, poolclass=NullPool, connect_args={"check_same_thread": False})
        event.listen(engine.sync_engine, "connect", _pragmas)
        async with engine.connect() as conn:
            mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        await engine.dispose()
    assert str(mode).lower() == "wal"


@pytest.mark.asyncio
async def test_release_before_network_keeps_login_write_unblocked() -> None:
    """A quote that takes seconds must not block the login audit insert."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "desk.db"
        url = f"sqlite+aiosqlite:///{path}"
        engine = create_async_engine(url, future=True, poolclass=NullPool, connect_args={"check_same_thread": False})
        event.listen(engine.sync_engine, "connect", _pragmas)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE login_audit (id INTEGER PRIMARY KEY, username TEXT)"))

        async def quote_path() -> None:
            async with Session() as db:
                await db.execute(text("INSERT INTO login_audit (username) VALUES ('quote-holder')"))
                # Same rule as production: commit before the network wait.
                await db.commit()
                await asyncio.sleep(0.4)

        async def login_path() -> float:
            started = asyncio.get_running_loop().time()
            async with Session() as db:
                await db.execute(text("INSERT INTO login_audit (username) VALUES ('login')"))
                await db.commit()
            return asyncio.get_running_loop().time() - started

        quote_task = asyncio.create_task(quote_path())
        await asyncio.sleep(0.05)
        elapsed = await login_path()
        await quote_task
        await engine.dispose()

    assert elapsed < 0.25, f"login write waited {elapsed:.3f}s; the quote still held the lock"
