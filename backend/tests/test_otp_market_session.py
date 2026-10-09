"""Sign-in OTP is required once per NYSE session, per user and device.

Holiday used below: Thanksgiving Day, Thursday 2026-11-26 (NYSE full close).
Christmas Day, Friday 2026-12-25, covers a Saturday whose Friday is closed.
"""

from __future__ import annotations

import http.cookies
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import create_app
from app.models.otp_device import OtpDevice
from app.redis_client import reset_redis_for_tests
from app.routers.auth import DEVICE_COOKIE
from app.services.market_session import NYSE_HOLIDAYS, getLastMarketOpen

_PASSWORD = "ApexDesk!23"
_NY = ZoneInfo("America/New_York")


def _at(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_NY)


def test_same_trading_day_shares_one_open() -> None:
    morning = getLastMarketOpen(_at(2026, 10, 7, 11, 0))
    evening = getLastMarketOpen(_at(2026, 10, 7, 18, 0))
    assert morning == evening == _at(2026, 10, 7, 9, 30)


def test_next_trading_day_open_is_new_and_preopen_is_not() -> None:
    wednesday = getLastMarketOpen(_at(2026, 10, 7, 11, 0))
    assert getLastMarketOpen(_at(2026, 10, 8, 9, 0)) == wednesday
    assert getLastMarketOpen(_at(2026, 10, 8, 9, 30)) == _at(2026, 10, 8, 9, 30)
    assert getLastMarketOpen(_at(2026, 10, 8, 9, 31)) == _at(2026, 10, 8, 9, 30)


def test_saturday_uses_friday_open() -> None:
    assert getLastMarketOpen(_at(2026, 10, 10, 12, 0)) == _at(2026, 10, 9, 9, 30)


def test_saturday_uses_thursday_when_friday_is_christmas() -> None:
    """Christmas Day 2026 is Friday, December 25, a NYSE full-day holiday."""
    assert date(2026, 12, 25) in NYSE_HOLIDAYS
    assert getLastMarketOpen(_at(2026, 12, 25, 12, 0)) == _at(2026, 12, 24, 9, 30)
    assert getLastMarketOpen(_at(2026, 12, 26, 12, 0)) == _at(2026, 12, 24, 9, 30)


def test_monday_before_open_keeps_previous_session() -> None:
    friday = _at(2026, 10, 9, 9, 30)
    assert getLastMarketOpen(_at(2026, 10, 12, 9, 29)) == friday
    assert getLastMarketOpen(_at(2026, 10, 12, 9, 31)) == _at(2026, 10, 12, 9, 30)


def test_thanksgiving_2026_uses_the_previous_regular_open() -> None:
    """Thanksgiving Day, Thursday 2026-11-26, is a NYSE full-day holiday."""
    assert date(2026, 11, 26) in NYSE_HOLIDAYS
    wednesday_open = _at(2026, 11, 25, 9, 30)
    assert getLastMarketOpen(_at(2026, 11, 26, 9, 30)) == wednesday_open
    assert getLastMarketOpen(_at(2026, 11, 26, 15, 0)) == wednesday_open
    # The Friday after Thanksgiving is an early close, and it still opens at 09:30.
    assert getLastMarketOpen(_at(2026, 11, 27, 9, 0)) == wednesday_open
    assert getLastMarketOpen(_at(2026, 11, 27, 9, 31)) == _at(2026, 11, 27, 9, 30)


def test_dst_spring_forward_stays_930_new_york() -> None:
    # Monday 2026-03-09 is the first session after DST starts (2026-03-08). 09:30 EDT is UTC-4.
    opened = getLastMarketOpen(datetime(2026, 3, 9, 15, 0, tzinfo=timezone.utc))
    assert opened == _at(2026, 3, 9, 9, 30)
    assert opened.utcoffset() == timedelta(hours=-4)
    assert opened.astimezone(timezone.utc) == datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc)
    before = getLastMarketOpen(datetime(2026, 3, 9, 13, 0, tzinfo=timezone.utc))
    assert before == _at(2026, 3, 6, 9, 30)
    assert before.utcoffset() == timedelta(hours=-5)


def test_dst_fall_back_stays_930_new_york() -> None:
    # Monday 2026-11-02 is the first session after DST ends (2026-11-01). 09:30 EST is UTC-5.
    opened = getLastMarketOpen(datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc))
    assert opened == _at(2026, 11, 2, 9, 30)
    assert opened.utcoffset() == timedelta(hours=-5)
    assert opened.astimezone(timezone.utc) == datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)


def test_naive_clock_is_rejected() -> None:
    with pytest.raises(ValueError):
        getLastMarketOpen(datetime(2026, 10, 7, 11, 0))


def _cookie_jar(response) -> http.cookies.SimpleCookie:
    jar: http.cookies.SimpleCookie = http.cookies.SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        jar.load(header)
    return jar


def _pin_device(client: AsyncClient, response) -> str:
    jar = _cookie_jar(response)
    assert DEVICE_COOKIE in jar
    morsel = jar[DEVICE_COOKIE]
    assert morsel["httponly"]
    assert morsel["secure"]
    assert str(morsel["samesite"]).lower() == "strict"
    client.cookies.clear()
    client.cookies.set(DEVICE_COOKIE, morsel.value)
    return morsel.value.split(".", 1)[0]


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def _send(_settings: object, *, full_name: str, email: str, code: str) -> bool:
        sent.append({"full_name": full_name, "email": email, "code": code})
        return True

    monkeypatch.setattr("app.routers.auth.send_login_code", _send)
    return sent


async def _signup(client: AsyncClient, username: str, email: str) -> None:
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Ada Lovelace",
            "username": username,
            "email": email,
            "password": _PASSWORD,
            "confirm_password": _PASSWORD,
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text


@pytest.fixture
async def api() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    reset_redis_for_tests()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_verified_device_skips_otp_until_the_next_open(
    api: tuple[AsyncClient, async_sessionmaker[AsyncSession]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, session_factory = api
    sent = _capture(monkeypatch)
    await _signup(client, "session1", "session1@example.com")
    login = await client.post("/auth/login", json={"username": "session1", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["otp_required"] is True
    assert "access_token" not in login.json()
    assert len(sent) == 1
    device_id = _pin_device(client, login)

    verify = await client.post("/auth/otp/verify", json={"username": "session1", "code": sent[0]["code"]})
    assert verify.status_code == 200, verify.text
    assert verify.json()["access_token"]

    again = await client.post("/auth/login", json={"username": "session1", "password": _PASSWORD})
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["otp_required"] is False
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0
    assert body["refresh_in"] >= 0
    assert body["account_mode"] == "paper_funded"
    assert "brokerage_connected" in body
    assert "first_login" in body
    assert "show_connect_modal" in body
    assert "code" not in body
    assert len(sent) == 1
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "session1"

    last_open = getLastMarketOpen(datetime.now(timezone.utc))
    async with session_factory() as session:
        row = await session.scalar(select(OtpDevice).where(OtpDevice.device_id == device_id))
        assert row is not None and row.otp_verified_at is not None
        row.otp_verified_at = last_open.astimezone(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    required = await client.post("/auth/login", json={"username": "session1", "password": _PASSWORD})
    assert required.status_code == 200, required.text
    assert required.json()["otp_required"] is True
    assert "access_token" not in required.json()
    assert len(sent) == 2

    async with session_factory() as session:
        row = await session.scalar(select(OtpDevice).where(OtpDevice.device_id == device_id))
        assert row is not None
        row.otp_verified_at = last_open.astimezone(timezone.utc)
        await session.commit()
    skipped = await client.post("/auth/login", json={"username": "session1", "password": _PASSWORD})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["otp_required"] is False
    assert skipped.json()["access_token"]
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_other_device_user_and_forged_cookie_still_require_otp(
    api: tuple[AsyncClient, async_sessionmaker[AsyncSession]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _session_factory = api
    sent = _capture(monkeypatch)
    await _signup(client, "devicea", "devicea@example.com")
    await _signup(client, "deviceb", "deviceb@example.com")
    login = await client.post("/auth/login", json={"username": "devicea", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    _pin_device(client, login)
    verify = await client.post("/auth/otp/verify", json={"username": "devicea", "code": sent[0]["code"]})
    assert verify.status_code == 200, verify.text

    other_user = await client.post("/auth/login", json={"username": "deviceb", "password": _PASSWORD})
    assert other_user.status_code == 200, other_user.text
    assert other_user.json()["otp_required"] is True
    assert "access_token" not in other_user.json()
    assert len(sent) == 2
    assert sent[1]["email"] == "deviceb@example.com"

    client.cookies.clear()
    other_device = await client.post("/auth/login", json={"username": "devicea", "password": _PASSWORD})
    assert other_device.json()["otp_required"] is True
    assert len(sent) == 3

    forged = "0" * 32 + "." + "ab" * 32
    client.cookies.clear()
    client.cookies.set(DEVICE_COOKIE, forged)
    tampered = await client.post(
        "/auth/login",
        json={"username": "devicea", "password": _PASSWORD, "now": "2099-01-01T15:00:00Z"},
    )
    assert tampered.status_code == 200, tampered.text
    assert tampered.json()["otp_required"] is True
    assert "access_token" not in tampered.json()
