"""Signup confirmation: masked password in the mail body, raw password nowhere in it."""

from __future__ import annotations

import smtplib
from pathlib import Path

import pytest
from httpx import AsyncClient
from loguru import logger

from app.config import Settings, get_settings
from app.services.signup_email import (
    _SOURCE_LOGO,
    _deliver_signup_confirmation,
    _logo_path,
    mask_password,
    signup_confirmation_body,
    signup_confirmation_html,
    write_email_preview,
)

_FAKE_PASSWORD = "test-abc"


def test_mask_shows_only_the_last_three_characters() -> None:
    masked = mask_password(_FAKE_PASSWORD)
    assert masked == "*****abc"
    assert len(masked) == len(_FAKE_PASSWORD)
    assert masked.endswith(_FAKE_PASSWORD[-3:])
    assert set(masked[:-3]) == {"*"}

    longer = mask_password("aaaaaaaxyz")
    assert longer == "*******xyz"
    assert "aaaaaaa" not in longer


def test_short_passwords_do_not_reveal_more_than_the_last_three() -> None:
    assert mask_password("wxyz") == "*xyz"
    assert "w" not in mask_password("wxyz")
    assert mask_password("abc") == "abc"
    assert mask_password("ab") == "ab"
    assert len(mask_password("ab")) == 2
    assert mask_password("q") == "q"


def _message_parts(message: object) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():  # type: ignore[attr-defined]
        content_type = part.get_content_type()
        if content_type == "text/plain":
            plain_parts.append(part.get_content())
        elif content_type == "text/html":
            html_parts.append(part.get_content())
    return "\n".join(plain_parts), "\n".join(html_parts)


def _assert_inline_logo(html_body: str) -> None:
    lowered = html_body.lower()
    assert lowered.count("<table") == 1
    assert "max-width:600px" in lowered
    assert 'src="cid:apex-logo"' in html_body
    assert 'alt="APEX"' in html_body
    assert "<svg" not in lowered
    assert "<style" not in lowered
    assert "gradient" not in lowered
    assert ">APEX</p>" in html_body


def _assert_inline_png(message: object) -> None:
    raw = message.as_string().lower()  # type: ignore[attr-defined]
    assert "multipart/related" in raw
    assert "content-id:" in raw
    assert "content-disposition: inline" in raw
    assert "image/png" in raw
    assert "content-disposition: attachment" not in raw
    assert "<svg" not in raw
    assert message.get_content_type() == "multipart/alternative"  # type: ignore[attr-defined]
    images = [part for part in message.walk() if part.get_content_maintype() == "image"]  # type: ignore[attr-defined]
    assert len(images) == 1
    image = images[0]
    assert image.get_content_type() == "image/png"
    assert str(image.get("Content-ID")).strip("<>") == "apex-logo"
    disposition = str(image.get("Content-Disposition") or "")
    assert disposition.lower().startswith("inline")
    assert "attachment" not in disposition.lower()
    assert image.get_content() == _logo_path().read_bytes()


def test_confirmation_body_includes_name_and_username_and_hides_password() -> None:
    body = signup_confirmation_body(
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password=_FAKE_PASSWORD,
        account_mode="paper_funded",
        starting_balance=25000,
    )
    assert body.startswith("Hello Ada Lovelace,\n")
    assert "Your APEX account is confirmed." in body
    assert "Full name: Ada Lovelace" in body
    assert "Username: ada.lovelace" in body
    assert "Email: ada@example.com" in body
    assert "Account mode: Paper funded" in body
    assert "Starting balance: $25,000" in body
    assert f"Password: {mask_password(_FAKE_PASSWORD)}" in body
    assert "Sign in with your username and password." in body
    assert "Enter the sign-in code sent to this address." in body
    assert "Keep this summary for your records." in body
    assert "If you did not create this account, reply to this message." in body
    assert "APEX\n" in body
    assert body.rstrip().endswith("Trading involves risk. Not financial advice.")
    assert _FAKE_PASSWORD not in body
    assert "!" not in body


def test_confirmation_html_has_greeting_logo_and_masked_password() -> None:
    html_body = signup_confirmation_html(
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password=_FAKE_PASSWORD,
        account_mode="paper_funded",
        starting_balance=25000,
    )
    assert "Hello Ada Lovelace," in html_body
    assert "Your APEX account is confirmed." in html_body
    _assert_inline_logo(html_body)
    assert "max-width:600px" in html_body
    assert "ada.lovelace" in html_body
    assert mask_password(_FAKE_PASSWORD) in html_body
    assert _FAKE_PASSWORD not in html_body
    assert "Trading involves risk. Not financial advice." in html_body
    assert "If you did not create this account, reply to this message." in html_body


def test_preview_file_keeps_the_inline_logo_and_masked_password() -> None:
    html_body = signup_confirmation_html(
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password=_FAKE_PASSWORD,
        account_mode="paper_funded",
        starting_balance=25000,
    )
    written = Path(write_email_preview(html_body, name="apex-signup")).read_text(encoding="utf-8")
    assert written == html_body
    _assert_inline_logo(written)
    assert "Hello Ada Lovelace," in written
    assert mask_password(_FAKE_PASSWORD) in written
    assert _FAKE_PASSWORD not in written


def test_real_brokerage_body_omits_starting_balance() -> None:
    body = signup_confirmation_body(
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password=_FAKE_PASSWORD,
        account_mode="real_brokerage",
        starting_balance=None,
    )
    assert "Account mode: Real brokerage" in body
    assert "Starting balance" not in body
    assert _FAKE_PASSWORD not in body


def test_unconfigured_smtp_logs_one_warning_and_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_smtp(*_args, **_kwargs):
        raise AssertionError("SMTP must not be opened when no host is configured")

    monkeypatch.setattr(smtplib, "SMTP", fail_smtp)
    warnings: list[str] = []
    sink = logger.add(lambda message: warnings.append(str(message)), level="WARNING")
    try:
        _deliver_signup_confirmation(
            Settings(smtp_host="", smtp_from=""),
            full_name="Ada Lovelace",
            username="ada.lovelace",
            email="ada@example.com",
            password=_FAKE_PASSWORD,
            account_mode="paper_funded",
            starting_balance=10000,
        )
    finally:
        logger.remove(sink)
    sent = [line for line in warnings if "confirmation email was not sent" in line]
    assert len(sent) == 1
    assert _FAKE_PASSWORD not in "\n".join(warnings)


def test_configured_smtp_sends_masked_body(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

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

        def send_message(self, message: object) -> None:
            assert message["Subject"] == "Your APEX account"  # type: ignore[index]
            assert message["From"] == "desk@example.com"  # type: ignore[index]
            assert message["To"] == "ada@example.com"  # type: ignore[index]
            plain, html_body = _message_parts(message)
            assert plain.strip()
            assert html_body.strip()
            sent.append(plain + "\n" + html_body)
            _assert_inline_png(message)
            _assert_inline_logo(html_body)

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _deliver_signup_confirmation(
        Settings(smtp_host="127.0.0.1", smtp_port=587, smtp_from="desk@example.com", smtp_username=""),
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password=_FAKE_PASSWORD,
        account_mode="paper_funded",
        starting_balance=25000,
    )
    assert len(sent) == 1
    assert "Hello Ada Lovelace," in sent[0]
    assert 'src="cid:apex-logo"' in sent[0]
    assert "<svg" not in sent[0].lower()
    assert "Full name: Ada Lovelace" in sent[0]
    assert "Username: ada.lovelace" in sent[0]
    assert mask_password(_FAKE_PASSWORD) in sent[0]
    assert "*****abc" in sent[0]
    assert _FAKE_PASSWORD not in sent[0]


@pytest.mark.asyncio
async def test_signup_without_smtp_still_creates_the_account(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_smtp(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("SMTP must not be opened when no host is configured")

    monkeypatch.setattr(smtplib, "SMTP", fail_smtp)
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from", "")
    res = await client.post(
        "/auth/signup",
        json={
            "full_name": "Ada Lovelace",
            "username": "ada.lovelace",
            "email": "ada@example.com",
            "password": _FAKE_PASSWORD,
            "confirm_password": _FAKE_PASSWORD,
            "account_mode": "paper_funded",
            "starting_balance": 25000,
        },
    )
    assert res.status_code == 201, res.text
    payload = res.json()
    assert payload["confirmation_sent"] is False
    assert payload["email"] == "ada@example.com"
    assert payload["full_name"] == "Ada Lovelace"
    assert "password" not in payload
    assert _FAKE_PASSWORD not in res.text


@pytest.mark.asyncio
async def test_two_signups_email_only_their_own_addresses(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    delivered: list[tuple[str, str]] = []

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

        def send_message(self, message: object) -> None:
            recipient = message["To"]  # type: ignore[index]
            plain, html_body = _message_parts(message)
            _assert_inline_png(message)
            _assert_inline_logo(html_body)
            delivered.append((str(recipient), plain + "\n" + html_body))

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_from", "desk@example.com")
    monkeypatch.setattr(settings, "smtp_username", "")

    people = (
        {
            "full_name": "Ada Lovelace",
            "username": "ada.two",
            "email": "ada.lovelace@company.com",
            "password": "test-abc",
        },
        {
            "full_name": "Grace Hopper",
            "username": "grace.two",
            "email": "grace.hopper@laboratory.org",
            "password": "test-xyz",
        },
    )
    for person in people:
        res = await client.post(
            "/auth/signup",
            json={
                "full_name": person["full_name"],
                "username": person["username"],
                "email": person["email"],
                "password": person["password"],
                "confirm_password": person["password"],
                "account_mode": "paper_funded",
                "starting_balance": 25000,
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["confirmation_sent"] is True
        assert res.json()["email"] == person["email"]
        assert person["password"] not in res.text

    assert [item[0] for item in delivered] == [
        "ada.lovelace@company.com",
        "grace.hopper@laboratory.org",
    ]
    first_body, second_body = delivered[0][1], delivered[1][1]
    assert "Full name: Ada Lovelace" in first_body
    assert "Username: ada.two" in first_body
    assert "Email: ada.lovelace@company.com" in first_body
    assert "*****abc" in first_body
    assert "test-abc" not in first_body
    assert "grace.hopper@laboratory.org" not in first_body
    assert "Grace Hopper" not in first_body
    assert "test-xyz" not in first_body
    assert "Full name: Grace Hopper" in second_body
    assert "Username: grace.two" in second_body
    assert "Email: grace.hopper@laboratory.org" in second_body
    assert "*****xyz" in second_body
    assert "test-xyz" not in second_body
    assert "ada.lovelace@company.com" not in second_body
    assert "Ada Lovelace" not in second_body
    assert "test-abc" not in second_body


def test_logo_path_prefers_the_hosted_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    hosted = tmp_path / "apex-logo.png"
    hosted.write_bytes(b"\x89PNG\r\n\x1a\nhosted")
    monkeypatch.setattr("app.services.signup_email._HOSTED_LOGO", hosted)
    assert _logo_path() == hosted
    assert _logo_path() != _SOURCE_LOGO


def test_logo_path_falls_back_when_the_hosted_file_is_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.services.signup_email._HOSTED_LOGO", tmp_path / "apex-logo.png")
    assert _logo_path() == _SOURCE_LOGO
