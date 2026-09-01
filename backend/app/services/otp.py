from __future__ import annotations

from app.config import Settings
from app.redis_client import get_redis
from app.security import generate_otp, hash_otp, otp_matches


def _key(username: str) -> str:
    return f"otp:{username.lower()}"


async def invalidate_otp(settings: Settings, username: str) -> None:
    redis = await get_redis(settings)
    await redis.delete(_key(username))


async def issue_otp(settings: Settings, username: str) -> str:
    redis = await get_redis(settings)
    code = generate_otp()
    # overwrite = invalidate previous
    await redis.set(_key(username), hash_otp(code), ex=settings.otp_ttl_seconds)
    return code


async def verify_otp(settings: Settings, username: str, code: str) -> bool:
    redis = await get_redis(settings)
    stored = await redis.get(_key(username))
    if not stored:
        return False
    if not otp_matches(code, stored):
        return False
    await redis.delete(_key(username))
    return True
