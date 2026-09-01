from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _signup(client: AsyncClient, username: str) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Forgot User",
            "username": username,
            "email": f"{username}@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text


RESET_PAYLOAD = {
    "password": "NewApexDesk!45",
    "confirm_password": "NewApexDesk!45",
}


@pytest.mark.asyncio
async def test_forgot_password_resets_password_and_logs_in(client: AsyncClient) -> None:
    username = "forgot1"
    await _signup(client, username)

    req = await client.post("/auth/forgot-password", json={"username": username, **RESET_PAYLOAD})
    assert req.status_code == 200
    body = req.json()
    assert body["ok"] is True
    assert body["ttl_seconds"] == 90
    assert body["autofill"] is True
    code = body["code"]
    assert code and len(code) == 6

    verify = await client.post("/auth/forgot-password/verify", json={"username": username, "code": code})
    assert verify.status_code == 200, verify.text
    token = verify.json()["access_token"]
    assert token

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == username

    old_login = await client.post("/auth/login", json={"username": username, "password": "ApexDesk!23"})
    assert old_login.status_code == 401

    new_login = await client.post("/auth/login", json={"username": username, "password": RESET_PAYLOAD["password"]})
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_forgot_password_accepts_email_identifier(client: AsyncClient) -> None:
    username = "forgotemail"
    await _signup(client, username)
    email = f"{username}@example.com"

    req = await client.post("/auth/forgot-password", json={"username": email, **RESET_PAYLOAD})
    assert req.status_code == 200
    code = req.json()["code"]
    assert code and len(code) == 6

    verify = await client.post("/auth/forgot-password/verify", json={"username": email, "code": code})
    assert verify.status_code == 200, verify.text


@pytest.mark.asyncio
async def test_forgot_password_unknown_user_returns_ok_without_code(client: AsyncClient) -> None:
    res = await client.post("/auth/forgot-password", json={"username": "nobody-here", **RESET_PAYLOAD})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["code"] is None
    assert body["autofill"] is False


@pytest.mark.asyncio
async def test_forgot_password_rejects_mismatched_passwords(client: AsyncClient) -> None:
    username = "forgotmismatch"
    await _signup(client, username)

    res = await client.post(
        "/auth/forgot-password",
        json={"username": username, "password": "NewApexDesk!45", "confirm_password": "Different!99"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_forgot_password_verify_rejects_invalid_code(client: AsyncClient) -> None:
    username = "forgotbad"
    await _signup(client, username)
    await client.post("/auth/forgot-password", json={"username": username, **RESET_PAYLOAD})

    verify = await client.post("/auth/forgot-password/verify", json={"username": username, "code": "000000"})
    assert verify.status_code == 401
    assert verify.json()["detail"] == "Invalid or expired code"


@pytest.mark.asyncio
async def test_forgot_password_code_is_single_use(client: AsyncClient) -> None:
    username = "forgotonce"
    await _signup(client, username)
    req = await client.post("/auth/forgot-password", json={"username": username, **RESET_PAYLOAD})
    code = req.json()["code"]

    first = await client.post("/auth/forgot-password/verify", json={"username": username, "code": code})
    assert first.status_code == 200

    second = await client.post("/auth/forgot-password/verify", json={"username": username, "code": code})
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_verify_requires_pending_reset(client: AsyncClient) -> None:
    from app.config import get_settings
    from app.services.otp import issue_otp

    username = "forgotpending"
    await _signup(client, username)
    settings = get_settings()
    code = await issue_otp(settings, username)

    verify = await client.post("/auth/forgot-password/verify", json={"username": username, "code": code})
    assert verify.status_code == 401
    assert verify.json()["detail"] == "Password reset expired — request a new code"
