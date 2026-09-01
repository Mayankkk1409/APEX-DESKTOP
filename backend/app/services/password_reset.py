from __future__ import annotations

from app.config import Settings
from app.redis_client import get_redis


def _key(username: str) -> str:
    return f"pwd_reset:{username.lower()}"


async def store_pending_reset(settings: Settings, username: str, password_hash: str) -> None:
    redis = await get_redis(settings)
    await redis.set(_key(username), password_hash, ex=settings.otp_ttl_seconds)


async def consume_pending_reset(settings: Settings, username: str) -> str | None:
    redis = await get_redis(settings)
    stored = await redis.get(_key(username))
    if not stored:
        return None
    await redis.delete(_key(username))
    return stored


async def clear_pending_reset(settings: Settings, username: str) -> None:
    redis = await get_redis(settings)
    await redis.delete(_key(username))
