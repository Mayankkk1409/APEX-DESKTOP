"""First-login platform tour flag on OTP verify."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_otp_verify_flags_platform_tour_until_complete(client: AsyncClient) -> None:
    signup = await client.post(
        "/auth/signup",
        json={
            "full_name": "Tour User",
            "username": "touruser",
            "email": "touruser@example.com",
            "password": "TourPass#2026",
            "confirm_password": "TourPass#2026",
            "account_mode": "paper_funded",
            "starting_balance": 100_000,
        },
    )
    assert signup.status_code == 201, signup.text
    login = await client.post(
        "/auth/login",
        json={"username": "touruser", "password": "TourPass#2026"},
    )
    assert login.status_code == 200, login.text
    otp = await client.post("/auth/otp/request", json={"username": "touruser"})
    assert otp.status_code == 200, otp.text
    code = otp.json()["code"]
    verify = await client.post("/auth/otp/verify", json={"username": "touruser", "code": code})
    assert verify.status_code == 200, verify.text
    body = verify.json()
    assert body.get("platform_tour") is True
    token = body["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json().get("platform_tour_seen") is False
    done = await client.post("/auth/platform-tour/complete", headers=headers, json={})
    assert done.status_code == 200, done.text
    assert done.json().get("platform_tour_seen") is True
    login2 = await client.post(
        "/auth/login",
        json={"username": "touruser", "password": "TourPass#2026"},
    )
    assert login2.status_code == 200
    otp2 = await client.post("/auth/otp/request", json={"username": "touruser"})
    verify2 = await client.post(
        "/auth/otp/verify",
        json={"username": "touruser", "code": otp2.json()["code"]},
    )
    assert verify2.status_code == 200
    assert verify2.json().get("platform_tour") is False
