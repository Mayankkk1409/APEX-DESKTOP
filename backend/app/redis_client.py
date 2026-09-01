from __future__ import annotations

from typing import Optional

from loguru import logger

from app.config import Settings


class MemoryRedis:
    """In-process Redis stand-in so the app starts without Redis during tests/demo."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, Optional[float]]] = {}
        self._clock = 0.0

    def _now(self) -> float:
        import time

        return time.time()

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        exp = self._now() + ex if ex else None
        self._store[key] = (value, exp)

    async def get(self, key: str) -> Optional[str]:
        row = self._store.get(key)
        if not row:
            return None
        value, exp = row
        if exp is not None and exp < self._now():
            self._store.pop(key, None)
            return None
        return value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def ping(self) -> bool:
        return True


_memory = MemoryRedis()
_redis = None


async def get_redis(settings: Settings):
    global _redis
    if _redis is not None:
        return _redis
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        return client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable ({}), using in-memory store", exc)
        _redis = _memory
        return _memory


def reset_redis_for_tests() -> None:
    global _redis, _memory
    _memory = MemoryRedis()
    _redis = _memory
