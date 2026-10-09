from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config import Settings
from app.redis_client import get_redis
from app.security import generate_otp, hash_otp, otp_matches

# A second login submit inside this window reuses the pending code and does not mail.
LOGIN_CODE_REUSE_SECONDS = 45

_lock_guard = asyncio.Lock()
_locks: dict[str, asyncio.Lock] = {}


def _key(username: str) -> str:
    return f"otp:{username.lower()}"


def _login_claim_key(username: str) -> str:
    return f"otp_login_claim:{username.lower()}"


async def _mutex(name: str) -> asyncio.Lock:
    async with _lock_guard:
        lock = _locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            _locks[name] = lock
        return lock


async def _set_nx(redis: object, key: str, value: str, ex: int) -> bool:
    """Set ``key`` only if it is absent. Redis SET NX, or the same check under a lock."""
    setter = getattr(redis, "set")
    try:
        result = await setter(key, value, ex=ex, nx=True)
    except TypeError:
        result = None
        native = False
    else:
        native = True
    if native:
        return bool(result)
    slot = await _mutex(f"nx:{key}")
    async with slot:
        current = await redis.get(key)  # type: ignore[attr-defined]
        if current is not None:
            return False
        await redis.set(key, value, ex=ex)  # type: ignore[attr-defined]
        return True


async def _wait_for_code(redis: object, key: str) -> str | None:
    pending = await redis.get(key)  # type: ignore[attr-defined]
    if pending:
        return pending
    for _ in range(20):
        await asyncio.sleep(0.01)
        pending = await redis.get(key)  # type: ignore[attr-defined]
        if pending:
            return pending
    return None


async def invalidate_otp(settings: Settings, username: str) -> None:
    redis = await get_redis(settings)
    await redis.delete(_key(username))


async def invalidate_login_code(settings: Settings, username: str) -> None:
    """Drop a sign-in code and its reuse slot so a failed send can be retried."""
    redis = await get_redis(settings)
    await redis.delete(_key(username))
    await redis.delete(_login_claim_key(username))


async def issue_otp(settings: Settings, username: str, *, ttl_seconds: int | None = None) -> str:
    redis = await get_redis(settings)
    code = generate_otp()
    ttl = settings.otp_ttl_seconds if ttl_seconds is None else ttl_seconds
    # overwrite = invalidate previous
    await redis.set(_key(username), hash_otp(code), ex=ttl)
    return code


@dataclass(frozen=True)
class LoginCodeClaim:
    """``code`` is set only when the caller must email it. ``None`` means reuse."""

    code: str | None


async def claim_login_code(
    settings: Settings,
    username: str,
    *,
    ttl_seconds: int,
    reuse_seconds: int = LOGIN_CODE_REUSE_SECONDS,
    force_new: bool = False,
) -> LoginCodeClaim:
    """Issue one sign-in code, or reuse a pending code from the last ``reuse_seconds``.

    Two concurrent first claims still produce one code. The plaintext is returned
    only to the claim that must be mailed. An explicit resend (``force_new``)
    replaces the code so the previous one cannot be used.
    """
    redis = await get_redis(settings)
    code_key = _key(username)
    if force_new:
        code = generate_otp()
        await redis.set(code_key, hash_otp(code), ex=ttl_seconds)
        return LoginCodeClaim(code)

    claim_key = _login_claim_key(username)
    slot = await _mutex(f"login:{username.lower()}")
    async with slot:
        acquired = await _set_nx(redis, claim_key, "1", reuse_seconds)
        if not acquired:
            if await _wait_for_code(redis, code_key):
                return LoginCodeClaim(None)
            # The reuse slot outlived the code (it was used or never stored).
            await redis.delete(claim_key)
            acquired = await _set_nx(redis, claim_key, "1", reuse_seconds)
            if not acquired:
                if await _wait_for_code(redis, code_key):
                    return LoginCodeClaim(None)
                return LoginCodeClaim(None)
        code = generate_otp()
        await redis.set(code_key, hash_otp(code), ex=ttl_seconds)
        return LoginCodeClaim(code)


async def verify_otp(settings: Settings, username: str, code: str) -> bool:
    redis = await get_redis(settings)
    stored = await redis.get(_key(username))
    if not stored:
        return False
    if not otp_matches(code, stored):
        return False
    await redis.delete(_key(username))
    return True
