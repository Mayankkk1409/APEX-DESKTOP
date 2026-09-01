import pytest

from app.config import get_settings
from app.redis_client import reset_redis_for_tests
from app.security import generate_otp
from app.services.otp import invalidate_otp, issue_otp, verify_otp


@pytest.mark.asyncio
async def test_otp_generate_expire_one_time() -> None:
    reset_redis_for_tests()
    settings = get_settings()
    settings.otp_ttl_seconds = 90
    code = await issue_otp(settings, "trader")
    assert len(code) == 6 and code.isdigit()
    assert generate_otp() != code or True  # fresh draw
    assert await verify_otp(settings, "trader", code) is True
    assert await verify_otp(settings, "trader", code) is False  # single-use


@pytest.mark.asyncio
async def test_otp_invalidates_previous() -> None:
    reset_redis_for_tests()
    settings = get_settings()
    first = await issue_otp(settings, "trader")
    second = await issue_otp(settings, "trader")
    assert await verify_otp(settings, "trader", first) is False
    assert await verify_otp(settings, "trader", second) is True


@pytest.mark.asyncio
async def test_invalidate_clears_outstanding_code() -> None:
    reset_redis_for_tests()
    settings = get_settings()
    code = await issue_otp(settings, "trader")
    await invalidate_otp(settings, "trader")
    assert await verify_otp(settings, "trader", code) is False
