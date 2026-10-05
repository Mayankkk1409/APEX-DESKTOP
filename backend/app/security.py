from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import Settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def otp_matches(code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code), stored_hash)


def create_access_token(settings: Settings, user_id: UUID, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def create_refresh_token(settings: Settings, user_id: UUID, jti: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": "refresh",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.refresh_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm="HS256")


def decode_token(settings: Settings, token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    # PyJWT verifies exp against UTC by default and raises ExpiredSignatureError.
    # https://pyjwt.readthedocs.io/en/stable/usage.html#expiration-time-claim-exp
    payload = jwt.decode(
        token,
        settings.app_secret_key,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    if expected_type is not None and payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def password_strength(password: str) -> dict[str, Any]:
    score = 0
    checks = {
        "length": len(password) >= 10,
        "lower": any(c.islower() for c in password),
        "upper": any(c.isupper() for c in password),
        "digit": any(c.isdigit() for c in password),
        "symbol": any(not c.isalnum() for c in password),
    }
    score = sum(1 for ok in checks.values() if ok)
    label = ["very_weak", "weak", "fair", "good", "strong", "excellent"][score]
    return {"score": score, "label": label, "checks": checks}
