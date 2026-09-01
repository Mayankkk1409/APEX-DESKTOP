from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _signup_login_otp(client: AsyncClient, username: str = "trader1") -> str:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Paper Trader",
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
    assert login.status_code == 200
    otp = await client.post("/auth/otp/request", json={"username": username})
    assert otp.status_code == 200
    code = otp.json()["code"]
    assert code and len(code) == 6
    verify = await client.post("/auth/otp/verify", json={"username": username, "code": code})
    assert verify.status_code == 200, verify.text
    return verify.json()["access_token"]


@pytest.mark.asyncio
async def test_signup_login_2fa_connect_later_dashboard(client: AsyncClient) -> None:
    token = await _signup_login_otp(client)
    headers = {"Authorization": f"Bearer {token}"}
    later = await client.post("/auth/brokerage", json={"later": True}, headers=headers)
    assert later.status_code == 200
    body = later.json()
    assert body["brokerage_connected"] is False
    assert body["connect_later_banner"] is True
    dash = await client.get("/api/portfolio", headers=headers)
    assert dash.status_code == 200
    assert dash.json()["balance"] == 25000
    me = await client.get("/auth/me", headers=headers)
    assert me.json()["account_mode"] == "paper_funded"


@pytest.mark.asyncio
async def test_every_login_requires_new_otp_and_shows_connect_modal(client: AsyncClient) -> None:
    await client.post(
        "/auth/signup",
        json={
            "full_name": "Repeat Login",
            "username": "repeat1",
            "email": "repeat1@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 10000,
        },
    )
    await client.post("/auth/login", json={"username": "repeat1", "password": "ApexDesk!23"})
    first = await client.post("/auth/otp/request", json={"username": "repeat1"})
    a = first.json()["code"]
    v1 = await client.post("/auth/otp/verify", json={"username": "repeat1", "code": a})
    assert v1.status_code == 200
    assert v1.json()["show_connect_modal"] is True

    await client.post("/auth/login", json={"username": "repeat1", "password": "ApexDesk!23"})
    reuse = await client.post("/auth/otp/verify", json={"username": "repeat1", "code": a})
    assert reuse.status_code == 401

    second = await client.post("/auth/otp/request", json={"username": "repeat1"})
    b = second.json()["code"]
    assert b != a
    v2 = await client.post("/auth/otp/verify", json={"username": "repeat1", "code": b})
    assert v2.status_code == 200
    assert v2.json()["show_connect_modal"] is True


@pytest.mark.asyncio
async def test_signup_does_not_require_otp(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "No OTP",
            "username": "nootp",
            "email": "nootp@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 10000,
        },
    )
    assert res.status_code == 201, res.text
    assert "code" not in res.json()


@pytest.mark.asyncio
async def test_real_signup_api_rejects_starting_balance(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Live Trader",
            "username": "live1",
            "email": "live1@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "real_brokerage",
            "starting_balance": 10000,
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_real_signup_gets_default_paper_balance(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Live Trader",
            "username": "live2",
            "email": "live2@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "real_brokerage",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["account_mode"] == "real_brokerage"
    assert body["starting_balance"] == 100_000
    assert body["cash_balance"] == 100_000
    assert body["buying_power"] == 100_000
    assert body["portfolio_value"] == 100_000


@pytest.mark.asyncio
async def test_paper_signup_without_balance_defaults_to_100k(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Paper Default",
            "username": "paperdef",
            "email": "paperdef@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["account_mode"] == "paper_funded"
    assert body["starting_balance"] == 100_000
    assert body["cash_balance"] == 100_000


@pytest.mark.asyncio
async def test_paper_signup_with_explicit_balance(client: AsyncClient) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Paper Custom",
            "username": "papercust",
            "email": "papercust@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["starting_balance"] == 25_000
    assert body["cash_balance"] == 25_000


@pytest.mark.asyncio
async def test_otp_autofill_returned_for_paper_and_real(client: AsyncClient) -> None:
    paper = await client.post(
        "/auth/signup",
        json={
            "full_name": "Paper Autofill",
            "username": "paperaf",
            "email": "paperaf@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "paper_funded",
            "starting_balance": 10000,
        },
    )
    assert paper.status_code == 201, paper.text
    await client.post("/auth/login", json={"username": "paperaf", "password": "ApexDesk!23"})
    paper_otp = await client.post("/auth/otp/request", json={"username": "paperaf"})
    paper_body = paper_otp.json()
    assert paper_otp.status_code == 200
    assert paper_body["autofill"] is True
    assert paper_body["code"] and len(paper_body["code"]) == 6

    real = await client.post(
        "/auth/signup",
        json={
            "full_name": "Real Autofill",
            "username": "realaf",
            "email": "realaf@example.com",
            "password": "ApexDesk!23",
            "confirm_password": "ApexDesk!23",
            "account_mode": "real_brokerage",
        },
    )
    assert real.status_code == 201, real.text
    await client.post("/auth/login", json={"username": "realaf", "password": "ApexDesk!23"})
    real_otp = await client.post("/auth/otp/request", json={"username": "realaf"})
    real_body = real_otp.json()
    assert real_otp.status_code == 200
    assert real_body["autofill"] is True
    assert real_body["code"] and len(real_body["code"]) == 6
    assert real_body["code"] != paper_body["code"]
