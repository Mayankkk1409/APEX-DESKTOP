from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base
from app.models.assistant import AssistantUsage
from app.models.user import User
from app.security import create_access_token, hash_password
from app.services.assistant_gate import classify_question, decide_access
from app.services.assistant_model import AssistantProviderError
from app.services.assistant_plans import PLANS, RESET_NOTE, RESET_TIMEZONE, SEPARATE_FROM_EVERY_PLAN
from app.services.assistant_usage import reserve_question


@pytest.fixture(autouse=True)
def _no_signup_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no(*_args: object, **_kwargs: object) -> bool:
        return False

    monkeypatch.setattr("app.routers.auth.send_signup_confirmation", _no)


async def _auth(client: AsyncClient, username: str) -> dict[str, str]:
    created = await client.post(
        "/auth/signup",
        json={
            "full_name": "Assistant Test",
            "username": username,
            "email": f"{username}@example.com",
            "password": "Testpass#2026",
            "confirm_password": "Testpass#2026",
            "account_mode": "paper_funded",
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]
    token = create_access_token(
        get_settings(),
        UUID(user_id),
        extra={"vfy": int(datetime.now(timezone.utc).timestamp())},
    )
    return {"Authorization": f"Bearer {token}"}


def test_plan_catalog_matches_the_proposed_prices() -> None:
    by_id = {plan["id"]: plan for plan in PLANS}
    assert by_id["free"]["monthly_price"] == "$0"
    assert by_id["free"]["annual_checkout"] == "$0"
    assert by_id["free"]["equivalent_monthly"] == "$0.00"
    assert by_id["free"]["twelve_monthly_total"] == "$0.00"
    assert by_id["free"]["daily_questions"] == 5
    assert by_id["free"]["assistant"] == "5 questions a day"
    assert by_id["equity"]["monthly_price"] == "$14.99"
    assert by_id["equity"]["annual_checkout"] == "$149.99"
    assert by_id["equity"]["equivalent_monthly"] == "$12.50"
    assert by_id["equity"]["twelve_monthly_total"] == "$179.88"
    assert by_id["equity"]["daily_questions"] == 50
    assert by_id["options"]["monthly_price"] == "$21.99"
    assert by_id["options"]["annual_checkout"] == "$219.99"
    assert by_id["options"]["equivalent_monthly"] == "$18.33"
    assert by_id["options"]["twelve_monthly_total"] == "$263.88"
    assert by_id["pro"]["name"] == "Pro Bundle"
    assert by_id["pro"]["subtitle"] == "For stocks and options"
    assert by_id["pro"]["monthly_price"] == "$34.99"
    assert by_id["pro"]["annual_checkout"] == "$349.99"
    assert by_id["pro"]["equivalent_monthly"] == "$29.17"
    assert by_id["pro"]["twelve_monthly_total"] == "$419.88"
    assert by_id["pro"]["daily_questions"] == 100
    assert by_id["elite"]["monthly_price"] == "$99.99"
    assert by_id["elite"]["annual_checkout"] == "$999.99"
    assert by_id["elite"]["equivalent_monthly"] == "$83.33"
    assert by_id["elite"]["twelve_monthly_total"] == "$1,199.88"
    assert by_id["elite"]["daily_questions"] is None
    assert by_id["elite"]["assistant"] == "Unlimited questions a day"
    assert RESET_TIMEZONE == "America/New_York"
    assert "New York" in RESET_NOTE
    assert "New_York" not in RESET_NOTE
    assert "not sold here" in SEPARATE_FROM_EVERY_PLAN
    assert "trial is not offered here" in SEPARATE_FROM_EVERY_PLAN
    assert "$9.99 once" in SEPARATE_FROM_EVERY_PLAN


def test_free_questions_split_basic_from_screen_and_research() -> None:
    assert classify_question("What is a call option?") == "basic"
    assert classify_question("What is P&L?") == "basic"
    assert classify_question("How do I open Portfolio?") == "basic"
    assert classify_question("explain this chart") == "screen"
    assert classify_question("what is on my screen") == "screen"
    assert classify_question("analyze NVDA") == "complex"
    assert classify_question("should I buy AAPL calls") == "complex"
    assert decide_access("free", "basic") == "allow"
    assert decide_access("free", "screen") == "upgrade"
    assert decide_access("free", "complex") == "upgrade"
    assert decide_access("equity", "complex") == "boundary"
    assert decide_access("elite", "screen") == "boundary"
    assert decide_access("pro", "basic") == "allow"


@pytest.mark.asyncio
async def test_parallel_reserves_stop_at_the_allowance() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        session.add(
            User(
                id="user-quota",
                full_name="Quota",
                username="quota-user",
                email="quota@example.com",
                password_hash=hash_password("Testpass#2026"),
                account_mode="paper_funded",
                cash_balance=0,
                buying_power=0,
                portfolio_value=0,
            )
        )
        await session.commit()

    async def once() -> bool:
        async with Session() as session:
            allowed, _used = await reserve_question(session, "user-quota", "2026-10-11", 1)
            return allowed

    first, second = await asyncio.gather(once(), once())
    assert sorted([first, second]) == [False, True]
    async with Session() as session:
        row = await session.get(AssistantUsage, ("user-quota", "2026-10-11"))
        assert row is not None
        assert row.question_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_free_screen_question_does_not_call_the_model_or_count(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _blocked(*_args: object, **_kwargs: object) -> str:
        called["n"] += 1
        return "should not run"

    monkeypatch.setattr("app.routers.assistant.complete_basic_answer", _blocked)
    headers = await _auth(client, "ai-free-screen")
    response = await client.post("/assistant/ask", json={"message": "explain this chart"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "upgrade"
    assert "Please upgrade your plan" in body["text"]
    assert body["used"] == 0
    assert body["checkout_available"] is False
    assert body["plan_id"] == "free"
    assert body["plans"][1]["annual_checkout"] == "$149.99"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_basic_answer_counts_and_failure_does_not(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = await _auth(client, "ai-free-basic")

    async def _answer(*_args: object, **_kwargs: object) -> str:
        return "A call option is the right to buy shares at a strike."

    monkeypatch.setattr("app.routers.assistant.complete_basic_answer", _answer)
    ok = await client.post("/assistant/ask", json={"message": "What is a call option?"}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["kind"] == "answer"
    assert ok.json()["used"] == 1

    async def _fail(*_args: object, **_kwargs: object) -> str:
        raise AssistantProviderError()

    monkeypatch.setattr("app.routers.assistant.complete_basic_answer", _fail)
    failed = await client.post("/assistant/ask", json={"message": "What is a put?"}, headers=headers)
    assert failed.status_code == 200
    assert failed.json()["kind"] == "error"
    assert failed.json()["used"] == 1
    assert failed.json()["text"] == "APEX AI is temporarily unavailable. Please try again."


@pytest.mark.asyncio
async def test_client_cannot_send_a_plan_or_screen(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _answer(*_args: object, **_kwargs: object) -> str:
        return "A stock is a share of a company."

    monkeypatch.setattr("app.routers.assistant.complete_basic_answer", _answer)
    headers = await _auth(client, "ai-free-key")
    rejected = await client.post(
        "/assistant/ask",
        json={"message": "What is a stock?", "plan": "elite", "screen": "positions"},
        headers=headers,
    )
    assert rejected.status_code == 422


@pytest.mark.asyncio
async def test_paid_plan_is_not_told_to_upgrade(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _blocked(*_args: object, **_kwargs: object) -> str:
        called["n"] += 1
        return "no"

    monkeypatch.setattr("app.routers.assistant.complete_basic_answer", _blocked)
    monkeypatch.setattr("app.routers.assistant.resolve_plan_id", lambda _user: "equity")
    headers = await _auth(client, "ai-equity")
    response = await client.post("/assistant/ask", json={"message": "analyze NVDA"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "boundary"
    assert body["plan_id"] == "equity"
    assert "upgrade" not in body["text"].lower()
    assert body["plans"] is None
    assert called["n"] == 0
