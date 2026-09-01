from __future__ import annotations

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-prod-32b+")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_apex.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("AUTOFILL_2FA", "true")
# Integration tests run without live Alpaca credentials. Force-clear any shell/.env keys
# and enable the explicit offline simulator so scan/chain layers stay navigable.
os.environ["ALPACA_API_KEY_ID"] = ""
os.environ["ALPACA_API_SECRET_KEY"] = ""
os.environ.setdefault("ALLOW_OPTIONS_SIMULATOR", "true")
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-32-bytes-long!!")
os.environ.setdefault("SNAPTRADE_CLIENT_ID", "test-client")
os.environ.setdefault("SNAPTRADE_CONSUMER_KEY", "test-consumer-key")

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app
from app.models import (  # noqa: F401
    AccountBalance,
    AuditLog,
    BrokerageAccount,
    BrokerageConnection,
    LoginAudit,
    Order,
    PaperBalanceAudit,
    Position,
    Scan,
    User,
    UserTradingSettings,
    WatchlistItem,
)
from app.redis_client import reset_redis_for_tests

get_settings.cache_clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    reset_redis_for_tests()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with Session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", cookies={"dummy": "1"}) as ac:
        yield ac
    await engine.dispose()
