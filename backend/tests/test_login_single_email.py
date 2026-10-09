"""One sign-in attempt sends one email, including a concurrent double submit."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.redis_client import reset_redis_for_tests
from app.routers.auth import _email_login_code

_PASSWORD = "ApexDesk!23"


def _capture(monkeypatch: pytest.MonkeyPatch, *, delay: float = 0) -> list[str]:
    sent: list[str] = []

    async def _send(_settings: object, *, full_name: str, email: str, code: str) -> bool:
        sent.append(code)
        if delay:
            await asyncio.sleep(delay)
        return True

    monkeypatch.setattr("app.routers.auth.send_login_code", _send)
    return sent


async def _signup(client: AsyncClient, username: str) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Ada Lovelace",
            "username": username,
            "email": f"{username}@example.com",
            "password": _PASSWORD,
            "confirm_password": _PASSWORD,
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_one_login_attempt_emails_once(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "once-mail")
    login = await client.post("/auth/login", json={"username": "once-mail", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["otp_required"] is True
    assert "access_token" not in body
    assert "code" not in body
    assert len(sent) == 1
    assert sent[0] not in login.text
    verify = await client.post("/auth/otp/verify", json={"username": "once-mail", "code": sent[0]})
    assert verify.status_code == 200, verify.text


@pytest.mark.asyncio
async def test_second_login_inside_reuse_window_does_not_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "reuse-mail")
    first = await client.post("/auth/login", json={"username": "reuse-mail", "password": _PASSWORD})
    second = await client.post("/auth/login", json={"username": "reuse-mail", "password": _PASSWORD})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["otp_required"] is True
    assert second.json()["otp_required"] is True
    assert "access_token" not in second.json()
    assert len(sent) == 1
    assert sent[0] not in second.text
    verify = await client.post("/auth/otp/verify", json={"username": "reuse-mail", "code": sent[0]})
    assert verify.status_code == 200, verify.text


@pytest.mark.asyncio
async def test_concurrent_login_emails_once(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_redis_for_tests()
    sent = _capture(monkeypatch, delay=0.05)
    user = SimpleNamespace(username="race-mail", email="race-mail@example.com", full_name="Ada Lovelace")
    settings = get_settings()
    await asyncio.gather(
        _email_login_code(user, settings, None),
        _email_login_code(user, settings, None),
    )
    assert len(sent) == 1
