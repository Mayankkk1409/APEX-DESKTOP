from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.otp_device import OtpCode
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


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


async def _read_db_hash(db: AsyncSession | None, username: str) -> str | None:
    if db is None:
        return None
    row = await db.scalar(select(OtpCode).where(OtpCode.username == username.lower()))
    if row is None:
        return None
    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        await db.delete(row)
        await db.commit()
        return None
    return row.code_hash


async def _write_db_hash(db: AsyncSession | None, username: str, digest: str, ttl_seconds: int) -> None:
    if db is None:
        return
    name = username.lower()
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    row = await db.scalar(select(OtpCode).where(OtpCode.username == name))
    if row is None:
        db.add(OtpCode(username=name, code_hash=digest, expires_at=expires))
    else:
        row.code_hash = digest
        row.expires_at = expires
    await db.commit()


async def _pending_within_reuse(
    db: AsyncSession | None,
    username: str,
    *,
    ttl_seconds: int,
    reuse_seconds: int,
) -> bool:
    """True when the shared row was issued inside the reuse window.

    ``expires_at - ttl`` is the issue time. A reload drops process memory, and
    that must not mint a second code while this row is still the one emailed.
    """
    if db is None or ttl_seconds <= 0:
        return False
    row = await db.scalar(select(OtpCode).where(OtpCode.username == username.lower()))
    if row is None:
        return False
    expires = _as_utc(row.expires_at)
    now = datetime.now(timezone.utc)
    if expires <= now:
        await db.delete(row)
        await db.commit()
        return False
    remaining = (expires - now).total_seconds()
    return remaining > float(ttl_seconds - reuse_seconds)


async def _delete_db_hash(db: AsyncSession | None, username: str, *, expected: str | None = None) -> None:
    if db is None:
        return
    row = await db.scalar(select(OtpCode).where(OtpCode.username == username.lower()))
    if row is None:
        return
    if expected is not None and row.code_hash != expected:
        return
    await db.delete(row)
    await db.commit()


async def invalidate_otp(settings: Settings, username: str, *, db: AsyncSession | None = None) -> None:
    redis = await get_redis(settings)
    await redis.delete(_key(username))
    await _delete_db_hash(db, username)


async def invalidate_login_code(
    settings: Settings,
    username: str,
    *,
    code: str | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Drop a sign-in code and its reuse slot so a failed send can be retried.

    When ``code`` is set, a newer stored code is left in place. A failed send of
    an older code must not erase the code that the latest email contains.
    """
    redis = await get_redis(settings)
    key = _key(username)
    if code is None:
        await redis.delete(key)
        await redis.delete(_login_claim_key(username))
        await _delete_db_hash(db, username)
        return
    expected = hash_otp(code)
    stored = await redis.get(key)
    db_hash = await _read_db_hash(db, username)
    if stored != expected and db_hash != expected:
        return
    if stored == expected:
        await redis.delete(key)
    await redis.delete(_login_claim_key(username))
    await _delete_db_hash(db, username, expected=expected)


async def issue_otp(
    settings: Settings,
    username: str,
    *,
    ttl_seconds: int | None = None,
    db: AsyncSession | None = None,
) -> str:
    redis = await get_redis(settings)
    code = generate_otp()
    ttl = settings.otp_ttl_seconds if ttl_seconds is None else ttl_seconds
    digest = hash_otp(code)
    # overwrite = invalidate previous
    await redis.set(_key(username), digest, ex=ttl)
    await _write_db_hash(db, username, digest, ttl)
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
    db: AsyncSession | None = None,
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
        digest = hash_otp(code)
        await redis.set(code_key, digest, ex=ttl_seconds)
        await _write_db_hash(db, username, digest, ttl_seconds)
        return LoginCodeClaim(code)

    claim_key = _login_claim_key(username)
    slot = await _mutex(f"login:{username.lower()}")
    async with slot:
        if await _pending_within_reuse(
            db, username, ttl_seconds=ttl_seconds, reuse_seconds=reuse_seconds
        ):
            return LoginCodeClaim(None)
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
        digest = hash_otp(code)
        await redis.set(code_key, digest, ex=ttl_seconds)
        await _write_db_hash(db, username, digest, ttl_seconds)
        return LoginCodeClaim(code)


async def verify_otp(
    settings: Settings,
    username: str,
    code: str,
    *,
    db: AsyncSession | None = None,
) -> bool:
    redis = await get_redis(settings)
    key = _key(username)
    # SQLite is the store every API process shares. A hash left in this
    # process's memory (or a different worker) must not hide the emailed code.
    shared = await _read_db_hash(db, username)
    stored = shared if shared else await redis.get(key)
    if not stored:
        return False
    if not otp_matches(code, stored):
        return False
    await redis.delete(key)
    await _delete_db_hash(db, username, expected=stored)
    return True
