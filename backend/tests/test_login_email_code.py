"""Sign-in emails a one-time code to that account and does not return it."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest
import smtplib
from httpx import ASGITransport, AsyncClient
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import create_app
from app.models.user import User
from app.redis_client import get_redis, reset_redis_for_tests
from app.security import generate_otp, hash_otp
from app.services.otp import _key
from app.services.signup_email import (
    _deliver_login_code,
    _logo_path,
    login_code_body,
    login_code_html,
    mask_password,
)

_PASSWORD = "ApexDesk!23"


def _signup_body(username: str, email: str, full_name: str = "Ada Lovelace") -> dict:
    return {
        "full_name": full_name,
        "username": username,
        "email": email,
        "password": _PASSWORD,
        "confirm_password": _PASSWORD,
        "account_mode": "paper_funded",
        "starting_balance": 25000,
    }


async def _signup(client: AsyncClient, username: str, email: str, full_name: str = "Ada Lovelace") -> None:
    res = await client.post("/auth/signup", json=_signup_body(username, email, full_name))
    assert res.status_code == 201, res.text


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    async def _send(_settings: object, *, full_name: str, email: str, code: str) -> bool:
        sent.append({"full_name": full_name, "email": email, "code": code})
        return True

    monkeypatch.setattr("app.routers.auth.send_login_code", _send)
    return sent


@pytest.fixture
async def client_db():
    reset_redis_for_tests()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_db():
        async with Session() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, Session
    await engine.dispose()


@pytest.mark.asyncio
async def test_emailed_code_verifies_after_the_memory_store_is_cleared(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reload wipes the in-memory stand-in. The emailed code must still verify."""
    sent = _capture(monkeypatch)
    await _signup(client, "reloadotp", "reloadotp@example.com")
    login = await client.post("/auth/login", json={"username": "reloadotp", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    assert len(sent) == 1
    reset_redis_for_tests()
    verify = await client.post("/auth/otp/verify", json={"username": "reloadotp", "code": sent[0]["code"]})
    assert verify.status_code == 200, verify.text
    assert verify.json()["access_token"]
    assert sent[0]["code"] not in verify.text
    second = await client.post("/auth/otp/verify", json={"username": "reloadotp", "code": sent[0]["code"]})
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_shared_hash_wins_when_process_memory_has_a_different_code(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another worker's memory must not hide the code stored for the latest email."""
    sent = _capture(monkeypatch)
    await _signup(client, "shadowotp", "shadowotp@example.com")
    login = await client.post("/auth/login", json={"username": "shadowotp", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    code = sent[0]["code"]
    other = "000000" if code != "000000" else "111111"
    redis = await get_redis(get_settings())
    await redis.set(_key("shadowotp"), hash_otp(other), ex=600)
    spaced = f"{code[:3]} {code[3:]}"
    verify = await client.post("/auth/otp/verify", json={"username": "shadowotp", "code": spaced})
    assert verify.status_code == 200, verify.text
    assert code not in verify.text
    assert "access_token" in verify.json()


@pytest.mark.asyncio
async def test_memory_wipe_does_not_replace_a_fresh_shared_code(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "keepotp", "keepotp@example.com")
    first = await client.post("/auth/login", json={"username": "keepotp", "password": _PASSWORD})
    assert first.status_code == 200, first.text
    reset_redis_for_tests()
    second = await client.post("/auth/login", json={"username": "keepotp", "password": _PASSWORD})
    assert second.status_code == 200, second.text
    assert len(sent) == 1
    verify = await client.post("/auth/otp/verify", json={"username": "keepotp", "code": sent[0]["code"]})
    assert verify.status_code == 200, verify.text
    assert sent[0]["code"] not in verify.text


def test_new_process_verifies_the_code_the_letter_renders(tmp_path: Path) -> None:
    """The hash lives in SQLite, so a process that did not issue the code can verify it."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.database import Base
    from app.services.otp import issue_otp
    from app.services.signup_email import login_code_body, login_code_html

    db_file = tmp_path / "shared-otp.db"
    url = f"sqlite+aiosqlite:///{db_file}"

    async def _issue() -> str:
        engine = create_async_engine(url, connect_args={"check_same_thread": False})
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with Session() as db:
            issued = await issue_otp(get_settings(), "crossproc", ttl_seconds=600, db=db)
        await engine.dispose()
        return issued

    code = asyncio.run(_issue())
    plain = login_code_body(full_name="Ada Lovelace", code=code)
    html_body = login_code_html(full_name="Ada Lovelace", code=code)
    assert code in plain
    assert f"\n{code}\n" in html_body

    script = """
import asyncio, os, sys
os.environ["DATABASE_URL"] = sys.argv[1]
from app.config import get_settings
get_settings.cache_clear()
from app.redis_client import reset_redis_for_tests
reset_redis_for_tests()
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.services.otp import verify_otp

async def main():
    engine = create_async_engine(sys.argv[1])
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as db:
        ok = await verify_otp(get_settings(), "crossproc", sys.argv[2], db=db)
    await engine.dispose()
    print("accepted" if ok else "rejected")

asyncio.run(main())
"""
    proc = subprocess.run(
        [sys.executable, "-c", script, url, code],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "accepted"
    assert code not in proc.stdout
    assert code not in proc.stderr


@pytest.mark.asyncio
async def test_correct_code_completes_login_without_returning_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "mailin", "mailin@example.com", "Ada Lovelace")
    warnings: list[str] = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        login = await client.post("/auth/login", json={"username": "mailin", "password": _PASSWORD})
    finally:
        logger.remove(sink)
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["otp_required"] is True
    assert body["ttl_seconds"] == 600
    assert "code" not in body
    assert "access_token" not in body
    assert len(sent) == 1
    code = sent[0]["code"]
    assert len(code) == 6 and code.isdigit()
    assert code not in login.text
    assert code not in "\n".join(warnings)
    assert sent[0]["email"] == "mailin@example.com"
    assert sent[0]["full_name"] == "Ada Lovelace"

    redis = await get_redis(get_settings())
    stored = await redis.get(_key("mailin"))
    assert stored == hash_otp(code)
    assert stored != code
    _value, exp = redis._store[_key("mailin")]  # type: ignore[attr-defined]
    assert exp is not None
    remaining = exp - time.time()
    assert 540 <= remaining <= 600

    wrong = "000000" if code != "000000" else "111111"
    denied = await client.post("/auth/otp/verify", json={"username": "mailin", "code": wrong})
    assert denied.status_code == 401
    assert "access_token" not in denied.json()

    verify = await client.post("/auth/otp/verify", json={"username": "mailin", "code": code})
    assert verify.status_code == 200, verify.text
    token = verify.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "mailin"
    assert me.json()["email"] == "mailin@example.com"

    again = await client.post("/auth/otp/verify", json={"username": "mailin", "code": code})
    assert again.status_code == 401


@pytest.mark.asyncio
async def test_wrong_code_does_not_log_in(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "wrongcode", "wrongcode@example.com")
    login = await client.post("/auth/login", json={"username": "wrongcode", "password": _PASSWORD})
    assert login.status_code == 200, login.text
    code = sent[0]["code"]
    wrong = "000000" if code != "000000" else "111111"
    denied = await client.post("/auth/otp/verify", json={"username": "wrongcode", "code": wrong})
    assert denied.status_code == 401
    assert denied.json()["detail"] == "Invalid or expired code"
    me = await client.get("/auth/me")
    assert me.status_code == 401
    assert code not in login.text
    assert code not in denied.text


@pytest.mark.asyncio
async def test_each_login_emails_only_that_account(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "ada.mail", "ada.lovelace@company.com", "Ada Lovelace")
    await _signup(client, "grace.mail", "grace.hopper@laboratory.org", "Grace Hopper")

    ada = await client.post("/auth/login", json={"username": "ada.mail", "password": _PASSWORD})
    grace = await client.post("/auth/login", json={"username": "grace.mail", "password": _PASSWORD})
    assert ada.status_code == 200 and grace.status_code == 200
    assert [row["email"] for row in sent] == [
        "ada.lovelace@company.com",
        "grace.hopper@laboratory.org",
    ]
    ada_code = sent[0]["code"]
    grace_code = sent[1]["code"]
    assert ada_code not in ada.text
    assert grace_code not in grace.text
    assert ada_code not in grace.text
    assert grace_code not in ada.text

    crossed = await client.post("/auth/otp/verify", json={"username": "grace.mail", "code": ada_code})
    assert crossed.status_code == 401
    opened = await client.post("/auth/otp/verify", json={"username": "grace.mail", "code": grace_code})
    assert opened.status_code == 200
    assert opened.json()["access_token"]


@pytest.mark.asyncio
async def test_resend_emails_the_same_account_and_hides_the_code(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "resend1", "resend1@example.com", "Resend User")
    first = await client.post("/auth/login", json={"username": "resend1", "password": _PASSWORD})
    assert first.status_code == 200, first.text
    again = await client.post("/auth/login/code", json={"username": "resend1", "password": _PASSWORD})
    assert again.status_code == 200, again.text
    assert "code" not in again.json()
    assert again.json()["ttl_seconds"] == 600
    assert [row["email"] for row in sent] == ["resend1@example.com", "resend1@example.com"]
    assert sent[1]["code"] not in again.text
    stale = await client.post("/auth/otp/verify", json={"username": "resend1", "code": sent[0]["code"]})
    assert stale.status_code == 401
    fresh = await client.post("/auth/otp/verify", json={"username": "resend1", "code": sent[1]["code"]})
    assert fresh.status_code == 200


@pytest.mark.asyncio
async def test_wrong_password_does_not_email(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent = _capture(monkeypatch)
    await _signup(client, "badpass", "badpass@example.com")
    login = await client.post("/auth/login", json={"username": "badpass", "password": "not-the-password"})
    assert login.status_code == 401
    assert sent == []


@pytest.mark.asyncio
async def test_missing_email_does_not_log_in(client_db, monkeypatch: pytest.MonkeyPatch) -> None:
    client, Session = client_db
    sent = _capture(monkeypatch)
    await _signup(client, "noemail1", "noemail1@example.com", "No Email")
    async with Session() as session:
        user = await session.scalar(select(User).where(User.username == "noemail1"))
        assert user is not None
        user.email = ""
        await session.commit()
    login = await client.post("/auth/login", json={"username": "noemail1", "password": _PASSWORD})
    assert login.status_code == 400
    assert login.json()["detail"] == "This account has no email for a sign-in code."
    assert "access_token" not in login.json()
    assert sent == []
    verify = await client.post("/auth/otp/verify", json={"username": "noemail1", "code": "123456"})
    assert verify.status_code == 401


@pytest.mark.asyncio
async def test_smtp_failure_does_not_log_in(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    async def _fail(_settings: object, *, full_name: str, email: str, code: str) -> bool:
        sent.append(code)
        assert email == "smtpfail@example.com"
        assert full_name == "Smtp Fail"
        return False

    monkeypatch.setattr("app.routers.auth.send_login_code", _fail)
    await _signup(client, "smtpfail", "smtpfail@example.com", "Smtp Fail")
    warnings: list[str] = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        login = await client.post("/auth/login", json={"username": "smtpfail", "password": _PASSWORD})
    finally:
        logger.remove(sink)
    assert login.status_code == 503
    assert login.json()["detail"] == "The sign-in code could not be sent."
    assert "access_token" not in login.json()
    assert sent and sent[0] not in login.text
    assert sent[0] not in "\n".join(warnings)
    verify = await client.post("/auth/otp/verify", json={"username": "smtpfail", "code": sent[0]})
    assert verify.status_code == 401


def test_login_letter_is_addressed_to_the_given_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    code = generate_otp()
    delivered: list[tuple[str, str, str]] = []

    class _FakeSMTP:
        def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
            assert host == "127.0.0.1"
            assert port == 587

        def __enter__(self) -> "_FakeSMTP":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("login is unused when SMTP username is empty")

        def quit(self) -> None:
            return None

        def close(self) -> None:
            return None

        def send_message(self, message: object, from_addr: str | None = None, to_addrs: list[str] | None = None) -> None:
            assert from_addr == "desk@example.com"
            assert to_addrs == ["ada.lovelace@company.com"]
            delivered.append((str(message["To"]), str(message["Subject"]), str(message["From"])))  # type: ignore[index]
            assert message.get_content_type() == "multipart/related"  # type: ignore[attr-defined]
            walked = [part.get_content_type() for part in message.walk()]  # type: ignore[attr-defined]
            assert "multipart/alternative" in walked
            parts = list(message.walk())  # type: ignore[attr-defined]
            plain = next(part for part in parts if part.get_content_type() == "text/plain")
            html_part = next(part for part in parts if part.get_content_type() == "text/html")
            text = plain.get_content()
            html_body = html_part.get_content()
            header_text = "\n".join(f"{key}: {value}" for key, value in message.items())  # type: ignore[attr-defined]
            assert code not in header_text
            assert code in text
            assert code in html_body
            assert f"\n{code}\n" in html_body
            assert "Hello Ada Lovelace," in text
            assert "Hello Ada Lovelace," in html_body
            assert "This code expires in 10 minutes." in text
            assert "This code expires in 10 minutes." in html_body
            assert "If you did not request this, ignore this email." in text
            assert "If you did not request this, ignore this email." in html_body
            assert text.rstrip().endswith("Trading involves risk. Not financial advice.")
            assert html_body.lower().count("<table") == 1
            assert "max-width:600px" in html_body
            assert 'src="cid:apex-logo"' in html_body
            assert 'alt="APEX"' in html_body
            assert "<svg" not in html_body.lower()
            assert "<style" not in html_body.lower()
            assert "gradient" not in html_body.lower()
            raw = message.as_string()  # type: ignore[attr-defined]
            head = raw.split("\n\n", 1)[0]
            assert "MIME-Version: 1.0" in head
            assert 'type="multipart/alternative"' in head
            assert head.lower().count("mime-version:") == 1
            lowered = raw.lower()
            assert "multipart/related" in lowered
            assert "content-id:" in lowered
            assert "content-disposition: inline" in lowered
            assert "image/png" in lowered
            assert "content-disposition: attachment" not in lowered
            images = [part for part in message.walk() if part.get_content_maintype() == "image"]  # type: ignore[attr-defined]
            assert len(images) == 1
            image = images[0]
            assert str(image.get("Content-ID")).strip("<>") == "apex-logo"
            disposition = str(image.get("Content-Disposition") or "")
            assert disposition.lower().startswith("inline")
            assert "attachment" not in disposition.lower()
            assert image.get_content() == _logo_path().read_bytes()
            assert _PASSWORD not in text
            assert _PASSWORD not in html_body
            masked = mask_password(_PASSWORD)
            assert masked not in text
            assert masked not in html_body

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    ok = _deliver_login_code(
        Settings(smtp_host="127.0.0.1", smtp_port=587, smtp_from="desk@example.com", smtp_username=""),
        full_name="Ada Lovelace",
        email="ada.lovelace@company.com",
        code=code,
    )
    assert ok is True
    assert delivered == [("ada.lovelace@company.com", "Your APEX sign-in code", "desk@example.com")]
    body = login_code_body(full_name="Ada Lovelace", code=code)
    html_body = login_code_html(full_name="Ada Lovelace", code=code)
    assert body.startswith("Hello Ada Lovelace,\n")
    assert f"Your sign-in code is {code}." in body
    assert "This code expires in 10 minutes." in body
    assert "If you did not request this, ignore this email." in body
    assert body.rstrip().endswith("Trading involves risk. Not financial advice.")
    assert "Hello Ada Lovelace," in html_body
    assert f">{code}<" not in html_body
    assert f"\n{code}\n" in html_body
    assert 'src="cid:apex-logo"' in html_body
    assert "<svg" not in html_body.lower()
    assert "This code expires in 10 minutes." in html_body
    assert "If you did not request this, ignore this email." in html_body
    assert mask_password(_PASSWORD) not in body
    assert mask_password(_PASSWORD) not in html_body
    assert _PASSWORD not in body
    assert _PASSWORD not in html_body


def test_quit_failure_after_accepted_data_still_delivers(monkeypatch: pytest.MonkeyPatch) -> None:
    code = generate_otp()

    class _QuitFails:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.sock = None

        def ehlo(self) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, *_args: object, **_kwargs: object) -> None:
            return None

        def data(self, _payload: bytes) -> tuple[int, bytes]:
            return 250, b"queued"

        def send_message(self, *_args: object, **_kwargs: object) -> dict[str, tuple[int, bytes]]:
            return {}

        def quit(self) -> None:
            raise smtplib.SMTPResponseException(250, b"closing")

        def close(self) -> None:
            return None

    monkeypatch.setattr(smtplib, "SMTP", _QuitFails)
    ok = _deliver_login_code(
        Settings(smtp_host="127.0.0.1", smtp_port=587, smtp_from="desk@example.com", smtp_username=""),
        full_name="Ada Lovelace",
        email="ada@example.com",
        code=code,
    )
    assert ok is True


def test_unconfigured_smtp_does_not_log_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    code = generate_otp()

    def fail_smtp(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SMTP must not be opened when no host is configured")

    monkeypatch.setattr(smtplib, "SMTP", fail_smtp)
    warnings: list[str] = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        ok = _deliver_login_code(
            Settings(smtp_host="", smtp_from=""),
            full_name="Ada Lovelace",
            email="ada@example.com",
            code=code,
        )
    finally:
        logger.remove(sink)
    assert ok is False
    joined = "\n".join(warnings)
    assert code not in joined
    assert "Sign-in code email was not sent" in joined
