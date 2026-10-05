from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest

from app.config import get_settings
from app.security import create_access_token, create_refresh_token, decode_token, hash_password, password_strength, verify_password

_USER = UUID("00000000-0000-0000-0000-000000000001")


def test_password_hash_and_verify() -> None:
    hashed = hash_password("ApexDemo!23")
    assert hashed != "ApexDemo!23"
    assert verify_password("ApexDemo!23", hashed)
    assert not verify_password("wrong-password", hashed)


def test_password_strength_meter() -> None:
    weak = password_strength("abc")
    strong = password_strength("ApexDesk!2026")
    assert weak["score"] < strong["score"]
    assert strong["checks"]["symbol"]
    assert strong["checks"]["digit"]


def test_access_token_lifetime_stays_15_minutes() -> None:
    settings = get_settings()
    payload = decode_token(settings, create_access_token(settings, _USER), expected_type="access")
    assert payload["exp"] - payload["iat"] == 900
    assert payload["typ"] == "access"


def test_refresh_token_lifetime_stays_seven_days() -> None:
    settings = get_settings()
    payload = decode_token(settings, create_refresh_token(settings, _USER, "jti-1"), expected_type="refresh")
    assert payload["exp"] - payload["iat"] == 604800
    assert payload["jti"] == "jti-1"


def test_expired_access_token_is_rejected() -> None:
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    token = jwt.encode(
        {
            "sub": str(_USER),
            "typ": "access",
            "iat": int((past - timedelta(seconds=900)).timestamp()),
            "exp": int(past.timestamp()),
        },
        settings.app_secret_key,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(settings, token, expected_type="access")


def test_refresh_token_cannot_be_used_as_access() -> None:
    settings = get_settings()
    token = create_refresh_token(settings, _USER, "jti-2")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(settings, token, expected_type="access")
