"""Silent refresh keeps a session alive after the access token expires.

Eight access-token lifetimes are 8 * 900s = 7200s, a two-hour desk session.
The test does not sleep; it presents an already-expired access token and
exchanges the httpOnly refresh cookie.
"""

from __future__ import annotations

import http.cookies
from datetime import datetime, timezone

import jwt
import pytest
from httpx import AsyncClient

from app.config import Settings, get_settings
from app.routers.auth import REFRESH_COOKIE

ACCESS_TTL = 900
TWO_HOURS = 2 * 60 * 60
REFRESH_SLICES = TWO_HOURS // ACCESS_TTL


def _cookie_jar(response) -> http.cookies.SimpleCookie:
    jar: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return jar


def _assert_refresh_cookie(response) -> str:
    jar = _cookie_jar(response)
    assert REFRESH_COOKIE in jar
    morsel = jar[REFRESH_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert str(morsel["samesite"]).lower() == "strict"
    assert morsel["path"] == "/"
    body = response.json()
    assert "refresh_token" not in body
    assert body["access_token"] != morsel.value
    assert body["expires_in"] == ACCESS_TTL
    assert body["refresh_in"] == ACCESS_TTL - 60
    return morsel.value


def _remember(client: AsyncClient, refresh: str) -> None:
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, refresh)


async def _login(client: AsyncClient, username: str) -> tuple[str, str, str]:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Session Trader",
            "username": username,
            "email": f"{username}@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text
    login = await client.post("/auth/login", json={"username": username, "password": "ApexDesk!23"})
    assert login.status_code == 200, login.text
    otp = await client.post("/auth/otp/request", json={"username": username})
    verify = await client.post("/auth/otp/verify", json={"username": username, "code": otp.json()["code"]})
    assert verify.status_code == 200, verify.text
    refresh = _assert_refresh_cookie(verify)
    access = verify.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200, me.text
    return access, refresh, me.json()["id"]


def _expired_access(user_id: str, mode: str = "paper_funded") -> str:
    settings = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    return jwt.encode(
        {"sub": user_id, "typ": "access", "mode": mode, "iat": now - 120, "exp": now - 60},
        settings.app_secret_key,
        algorithm="HS256",
    )


def test_session_ttls_are_unchanged() -> None:
    assert Settings.model_fields["access_token_ttl_seconds"].default == 900
    assert Settings.model_fields["refresh_token_ttl_seconds"].default == 604800
    assert Settings.model_fields["cookie_secure"].default is True
    assert Settings.model_fields["cookie_samesite"].default == "strict"
    assert Settings.model_fields["access_token_refresh_skew_seconds"].default == 60


@pytest.mark.asyncio
async def test_two_hour_session_refreshes_without_logout(client: AsyncClient) -> None:
    _access, refresh, user_id = await _login(client, "session2h")
    _remember(client, refresh)
    assert REFRESH_SLICES == 8
    for slice_index in range(REFRESH_SLICES):
        expired = _expired_access(user_id)
        denied = await client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert denied.status_code == 401, denied.text
        assert denied.json()["detail"] == "Invalid access token"
        refreshed = await client.post("/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        access = refreshed.json()["access_token"]
        assert refreshed.json()["expires_in"] == ACCESS_TTL
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200, f"slice {slice_index} logged out: {me.text}"
        assert me.json()["id"] == user_id


@pytest.mark.asyncio
async def test_reload_restores_session_from_cookie_on_every_screen(client: AsyncClient) -> None:
    """A reload drops the in-memory access token. The cookie alone restores it."""
    _access, refresh, user_id = await _login(client, "sessionreload")
    _remember(client, refresh)
    # No Authorization header: this is the browser after a document reload.
    restored = await client.post("/auth/refresh")
    assert restored.status_code == 200, restored.text
    access = restored.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    screens = {
        "/app": "/auth/me",
        "/portfolio": "/api/portfolio",
        "/settings": "/auth/me",
        "/scan": "/scan/layers",
    }
    for screen, path in screens.items():
        res = await client.get(path, headers=headers)
        assert res.status_code == 200, f"{screen} {path} {res.text}"
    me = await client.get("/auth/me", headers=headers)
    assert me.json()["id"] == user_id


@pytest.mark.asyncio
async def test_expired_access_token_mid_scan_recovers(client: AsyncClient) -> None:
    _access, refresh, user_id = await _login(client, "sessionscan")
    _remember(client, refresh)
    snapshot = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "visible_from": "2026-01-01T00:00:00+00:00",
        "visible_to": datetime.now(timezone.utc).isoformat(),
        "studies": ["EMA_9"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    exps = await client.get("/market/expirations/AAPL")
    expiry = exps.json()["expirations"][1]["date"]
    denied = await client.post(
        "/scan",
        json={"snapshot": snapshot, "expiry": expiry},
        headers={"Authorization": f"Bearer {_expired_access(user_id)}"},
    )
    assert denied.status_code == 401, denied.text
    assert denied.json()["detail"] == "Invalid access token"
    refreshed = await client.post("/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    scan = await client.post(
        "/scan",
        json={"snapshot": snapshot, "expiry": expiry},
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_access_token_is_not_a_refresh_cookie(client: AsyncClient) -> None:
    access, _refresh, _user_id = await _login(client, "sessiontype")
    _remember(client, access)
    rejected = await client.post("/auth/refresh")
    assert rejected.status_code == 401, rejected.text


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_cookie(client: AsyncClient) -> None:
    access, refresh, _user_id = await _login(client, "sessionout")
    _remember(client, refresh)
    out = await client.post("/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert out.status_code == 200, out.text
    cleared = _cookie_jar(out)
    assert REFRESH_COOKIE in cleared
    assert cleared[REFRESH_COOKIE]["max-age"] == "0"
    again = await client.post("/auth/refresh")
    assert again.status_code == 401
