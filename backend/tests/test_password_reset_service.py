import pytest

from app.config import get_settings
from app.redis_client import reset_redis_for_tests
from app.security import hash_password
from app.services.password_reset import clear_pending_reset, consume_pending_reset, store_pending_reset


@pytest.mark.asyncio
async def test_pending_reset_store_and_consume() -> None:
    reset_redis_for_tests()
    settings = get_settings()
    pending = hash_password("NewApexDesk!45")
    await store_pending_reset(settings, "trader", pending)
    consumed = await consume_pending_reset(settings, "trader")
    assert consumed == pending
    assert await consume_pending_reset(settings, "trader") is None


@pytest.mark.asyncio
async def test_pending_reset_clear() -> None:
    reset_redis_for_tests()
    settings = get_settings()
    pending = hash_password("NewApexDesk!45")
    await store_pending_reset(settings, "trader", pending)
    await clear_pending_reset(settings, "trader")
    assert await consume_pending_reset(settings, "trader") is None
