"""Transactional mail.

The browser does not post this to FormSubmit. Signup and sign-in routes send
through SMTP to the address on that account. An empty SMTP_HOST or SMTP_FROM
skips delivery and reports that the message was not sent.

Both letters share one sober HTML table. The wordmark is the site PNG, attached
once as an inline CID image. The root is multipart/related so the image stays
inside the letter. It is not an SVG and not a separate download.
"""

from __future__ import annotations

import asyncio
import html
import re
import smtplib
import tempfile
from email.message import EmailMessage
from email.utils import formatdate, parseaddr
from pathlib import Path

from loguru import logger

from app.config import Settings

_NOT_SENT = "Signup confirmation email was not sent"
_LOGIN_NOT_SENT = "Sign-in code email was not sent"
_DISCLAIMER = "Trading involves risk. Not financial advice."
_CONFIRMATION = "Your APEX account is confirmed."
_SUPPORT = "If you did not create this account, reply to this message."
_LOGIN_EXPIRES = "This code expires in 10 minutes."
_LOGIN_IGNORE = "If you did not request this, ignore this email."
_NEXT_STEPS = (
    "Sign in with your username and password.",
    "Enter the sign-in code sent to this address.",
    "Keep this summary for your records.",
)

_FONT = "Georgia, 'Times New Roman', Times, serif"
_MONO = "Consolas, 'Courier New', monospace"
_LOGO_CID = "apex-logo"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOSTED_LOGO = _REPO_ROOT / "frontend" / "public" / "brand" / "apex-logo.png"
_SOURCE_LOGO = Path(
    "/Users/Mayank/.cursor/projects/Users-Mayank-Desktop-APEX-DESKTOP/assets/"
    "APEX_TRADING-3-8d716276-f40f-4e7f-a9c9-9acd3d50c1c7.png"
)

_ACCOUNT_MODE_LABELS = {
    "paper_funded": "Paper funded",
    "real_brokerage": "Real brokerage",
}


def mask_password(password: str) -> str:
    """Show the last three characters. Each earlier character is one asterisk."""
    if len(password) <= 3:
        return password
    hidden = len(password) - 3
    return ("*" * hidden) + password[-3:]


def _plain_money(amount: float) -> str:
    if amount == int(amount):
        return f"${int(amount):,}"
    return f"${amount:,.2f}"


def _account_rows(
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    account_mode: str,
    starting_balance: float | None,
) -> list[tuple[str, str]]:
    mode = _ACCOUNT_MODE_LABELS.get(account_mode, account_mode)
    rows = [
        ("Full name", full_name),
        ("Username", username),
        ("Email", email),
        ("Account mode", mode),
    ]
    if starting_balance is not None:
        rows.append(("Starting balance", _plain_money(starting_balance)))
    rows.append(("Password", mask_password(password)))
    return rows


def _plain_footer() -> list[str]:
    return ["", "APEX", _DISCLAIMER]


def _logo_path() -> Path:
    """Prefer the file the site hosts. Fall back to the source PNG."""
    if _HOSTED_LOGO.is_file():
        return _HOSTED_LOGO
    return _SOURCE_LOGO


def _logo_bytes() -> bytes | None:
    path = _logo_path()
    if not path.is_file():
        logger.warning("APEX logo file is missing")
        return None
    return path.read_bytes()


def _text_row(content: str, *, padding: str) -> str:
    return (
        '<tr><td colspan="2" style="padding:'
        + padding
        + f";font-family:{_FONT};font-size:16px;line-height:1.55;color:#1c1c1c;text-align:left;\">"
        + content
        + "</td></tr>"
    )


def _pair_row(label: str, value: str) -> str:
    family = _MONO if label == "Password" else _FONT
    return (
        "<tr>"
        f'<td style="padding:10px 16px 10px 32px;border-top:1px solid #e3dfd6;width:42%;'
        f"vertical-align:top;font-family:{_FONT};font-size:14px;line-height:1.4;color:#5e584f;\">"
        f"{html.escape(label)}</td>"
        f'<td style="padding:10px 32px 10px 0;border-top:1px solid #e3dfd6;vertical-align:top;'
        f"font-family:{family};font-size:14px;line-height:1.4;color:#1c1c1c;\">"
        f"{html.escape(value)}</td>"
        "</tr>"
    )


def render_transactional_email(*, title: str, preheader: str, rows_html: str) -> str:
    """One sober table, max-width 600px, inline CSS only."""
    safe_title = html.escape(title)
    safe_preheader = html.escape(preheader)
    logo = (
        f'<img src="cid:{_LOGO_CID}" alt="APEX" width="96" height="96" '
        'style="display:block;width:96px;height:96px;margin:0 auto;border:0;'
        'outline:none;text-decoration:none;">'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{safe_preheader}">
<title>{safe_title}</title>
</head>
<body style="margin:0;padding:24px 12px;background:#f4f2ee;">
<table role="presentation" align="center" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;border-collapse:collapse;background:#ffffff;border:1px solid #e3dfd6;">
<tr>
<td colspan="2" align="center" style="padding:28px 32px;background:#111111;text-align:center;">{logo}</td>
</tr>
{rows_html}
<tr>
<td colspan="2" style="padding:18px 32px 22px;border-top:1px solid #e3dfd6;font-family:{_FONT};text-align:left;">
<p style="margin:0 0 4px;font-family:{_FONT};font-size:12px;letter-spacing:0.16em;color:#5e584f;">APEX</p>
<p style="margin:0;font-family:{_FONT};font-size:12px;line-height:1.5;color:#5e584f;">{html.escape(_DISCLAIMER)}</p>
</td>
</tr>
</table>
</body>
</html>
"""


def signup_confirmation_body(
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    account_mode: str,
    starting_balance: float | None,
) -> str:
    lines = [
        f"Hello {full_name},",
        "",
        _CONFIRMATION,
        "",
    ]
    lines.extend(
        f"{label}: {value}"
        for label, value in _account_rows(
            full_name=full_name,
            username=username,
            email=email,
            password=password,
            account_mode=account_mode,
            starting_balance=starting_balance,
        )
    )
    lines.append("")
    lines.extend(_NEXT_STEPS)
    lines.extend(["", _SUPPORT])
    lines.extend(_plain_footer())
    return "\n".join(lines) + "\n"


def signup_confirmation_html(
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    account_mode: str,
    starting_balance: float | None,
) -> str:
    rows = _account_rows(
        full_name=full_name,
        username=username,
        email=email,
        password=password,
        account_mode=account_mode,
        starting_balance=starting_balance,
    )
    greeting = html.escape(f"Hello {full_name},")
    steps = "".join(
        f'<p style="margin:0 0 8px;font-family:{_FONT};font-size:15px;line-height:1.5;color:#1c1c1c;">'
        f"{html.escape(step)}</p>"
        for step in _NEXT_STEPS
    )
    rows_html = (
        _text_row(greeting, padding="28px 32px 12px")
        + _text_row(html.escape(_CONFIRMATION), padding="0 32px 16px")
        + "".join(_pair_row(label, value) for label, value in rows)
        + _text_row(steps, padding="22px 32px 8px")
        + _text_row(
            f'<p style="margin:0;font-family:{_FONT};font-size:14px;line-height:1.5;color:#5e584f;">'
            f"{html.escape(_SUPPORT)}</p>",
            padding="8px 32px 22px",
        )
    )
    return render_transactional_email(
        title="Your APEX account",
        preheader=_CONFIRMATION,
        rows_html=rows_html,
    )


def _smtp_ready(settings: Settings) -> bool:
    return bool(settings.smtp_host.strip() and settings.smtp_from.strip())


def _envelope_sender(settings: Settings) -> str:
    """Gmail drops mail unless the envelope sender is the authenticated From address."""
    raw = settings.smtp_from.strip()
    _display, address = parseaddr(raw)
    sender = (address or raw).strip()
    if not sender:
        sender = settings.smtp_username.strip()
    return sender


def _address_message(message: EmailMessage, settings: Settings, recipient: str) -> str:
    if "From" in message:
        del message["From"]
    if "To" in message:
        del message["To"]
    message["From"] = settings.smtp_from.strip()
    message["To"] = recipient
    return _envelope_sender(settings)


_SIX_DIGITS = re.compile(r"\b\d{6}\b")


def _log_smtp_failure(label: str, exc: BaseException, recipient: str, settings: Settings) -> None:
    detail = _SIX_DIGITS.sub("[code]", str(exc))
    secret = settings.smtp_password
    if secret:
        detail = detail.replace(secret, "[redacted]")
    code = getattr(exc, "smtp_code", None)
    if code is None and isinstance(exc, smtplib.SMTPRecipientsRefused):
        first = next(iter(exc.recipients.values()), None)
        if isinstance(first, tuple) and first:
            code = first[0]
    logger.warning(
        "{} class={} smtp_code={} recipient={} detail={}",
        label,
        type(exc).__name__,
        code,
        recipient,
        detail[:300],
    )


def _transmit(settings: Settings, message: EmailMessage, recipient: str, *, label: str) -> int:
    """Send one message. Envelope recipient is the account address, never SMTP_FROM."""
    recipient = recipient.strip()
    if not recipient or not _smtp_ready(settings):
        logger.warning(label)
        return 0
    sender = _address_message(message, settings, recipient)
    try:
        smtp = smtplib.SMTP(settings.smtp_host.strip(), settings.smtp_port, timeout=20)
    except Exception as exc:
        _log_smtp_failure(label, exc, recipient, settings)
        return 0
    try:
        smtp.ehlo()
        if settings.smtp_starttls:
            smtp.starttls()
            smtp.ehlo()
        sock = getattr(smtp, "sock", None)
        if sock is not None:
            sock.settimeout(20)
        smtp_username = settings.smtp_username.strip()
        smtp_password = "".join(settings.smtp_password.split())
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        data_code: dict[str, int | None] = {"code": None}
        if callable(getattr(smtp, "data", None)):
            original_data = smtp.data

            def _data(payload: bytes) -> tuple[int, bytes]:
                code, reply = original_data(payload)
                data_code["code"] = code
                return code, reply

            smtp.data = _data  # type: ignore[method-assign]
        refused = smtp.send_message(message, from_addr=sender, to_addrs=[recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
        code = data_code["code"]
        if code is None:
            code = 250
        if code != 250:
            raise smtplib.SMTPDataError(code, b"DATA rejected")
    except Exception as exc:
        _log_smtp_failure(label, exc, recipient, settings)
        return 0
    finally:
        # QUIT is not delivery. A non-221 close after DATA 250 must not erase the code.
        try:
            smtp.quit()
        except Exception:
            try:
                smtp.close()
            except Exception:
                pass
    logger.info("SMTP accepted code={} recipient={}", code, recipient)
    return code


def _attach_inline_logo(message: EmailMessage) -> None:
    """Add the PNG to a multipart/related root. Disposition stays inline."""
    logo = _logo_bytes()
    if logo is None:
        return
    message.add_related(
        logo,
        "image",
        "png",
        cid=f"<{_LOGO_CID}>",
        disposition="inline",
    )


def _compose(subject: str, recipient: str, settings: Settings, plain: str, html_body: str) -> EmailMessage:
    """Related root, alternative inside it, logo inline on that related part.

    Nesting the image under the HTML alternative makes some clients offer the
    PNG as a download and skip the HTML, so the sign-in code never appears.
    """
    alternative = EmailMessage()
    alternative.set_content(plain, cte=_transfer_encoding(plain))
    alternative.add_alternative(html_body, subtype="html", cte=_transfer_encoding(html_body))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from.strip()
    message["To"] = recipient
    message["Date"] = formatdate(localtime=False)
    message.make_related()
    message.attach(alternative)
    try:
        _attach_inline_logo(message)
    except Exception as exc:
        logger.warning("logo attach skipped class={}", type(exc).__name__)
    return message


def _deliver_signup_confirmation(
    settings: Settings,
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    account_mode: str,
    starting_balance: float | None,
) -> bool:
    recipient = email.strip()
    details = {
        "full_name": full_name,
        "username": username,
        "email": recipient,
        "password": password,
        "account_mode": account_mode,
        "starting_balance": starting_balance,
    }
    plain = signup_confirmation_body(**details)
    html_body = signup_confirmation_html(**details)
    if not _smtp_ready(settings):
        logger.warning(_NOT_SENT)
        return False
    message = _compose("Your APEX account", recipient, settings, plain, html_body)
    try:
        with smtplib.SMTP(settings.smtp_host.strip(), settings.smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            smtp_username = settings.smtp_username.strip()
            smtp_password = "".join(settings.smtp_password.split())
            if smtp_username:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return True
    except Exception:
        logger.warning(_NOT_SENT)
        return False


async def send_signup_confirmation(
    settings: Settings,
    *,
    full_name: str,
    username: str,
    email: str,
    password: str,
    account_mode: str,
    starting_balance: float | None,
) -> bool:
    try:
        return await asyncio.to_thread(
            _deliver_signup_confirmation,
            settings,
            full_name=full_name,
            username=username,
            email=email,
            password=password,
            account_mode=account_mode,
            starting_balance=starting_balance,
        )
    except Exception:
        logger.warning(_NOT_SENT)
        return False


def login_code_body(*, full_name: str, code: str) -> str:
    name = full_name.strip()
    greeting = f"Hello {name}," if name else "Hello,"
    lines = [
        greeting,
        "",
        f"Your sign-in code is {code}.",
        "",
        _LOGIN_EXPIRES,
        "",
        _LOGIN_IGNORE,
    ]
    lines.extend(_plain_footer())
    return "\n".join(lines) + "\n"


def _transfer_encoding(payload: str) -> str:
    """7bit when the letter is ASCII so a soft break cannot land on the code."""
    try:
        payload.encode("ascii")
    except UnicodeEncodeError:
        return "8bit"
    return "7bit"


def login_code_html(*, full_name: str, code: str) -> str:
    name = full_name.strip()
    greeting = html.escape(f"Hello {name}," if name else "Hello,")
    visible = html.escape(code)
    # Digits are the cell text, on their own line. A nested <p> is dropped by
    # some clients, and a quoted-printable break after the digits hides them.
    code_row = (
        '<tr><td colspan="2" style="padding:8px 32px 16px;background-color:#ffffff;'
        f"font-family:{_MONO};font-size:28px;line-height:1.4;letter-spacing:0.18em;"
        'color:#111111;text-align:left;">\n'
        f"{visible}\n"
        "</td></tr>"
    )
    rows_html = (
        _text_row(greeting, padding="28px 32px 12px")
        + _text_row("Your sign-in code is", padding="0 32px 8px")
        + code_row
        + _text_row(html.escape(_LOGIN_EXPIRES), padding="0 32px 12px")
        + _text_row(html.escape(_LOGIN_IGNORE), padding="0 32px 22px")
    )
    return render_transactional_email(
        title="Your APEX sign-in code",
        preheader=f"Your sign-in code is {visible}.",
        rows_html=rows_html,
    )


def _deliver_login_code(settings: Settings, *, full_name: str, email: str, code: str) -> bool:
    recipient = email.strip()
    if not recipient or not _smtp_ready(settings):
        logger.warning(_LOGIN_NOT_SENT)
        return False
    message = _compose(
        "Your APEX sign-in code",
        recipient,
        settings,
        login_code_body(full_name=full_name, code=code),
        login_code_html(full_name=full_name, code=code),
    )
    return _transmit(settings, message, recipient, label=_LOGIN_NOT_SENT) == 250


async def send_login_code(settings: Settings, *, full_name: str, email: str, code: str) -> bool:
    """Email a sign-in code with the same SMTP settings as the signup letter."""
    try:
        return await asyncio.to_thread(
            _deliver_login_code,
            settings,
            full_name=full_name,
            email=email,
            code=code,
        )
    except Exception:
        logger.warning(_LOGIN_NOT_SENT)
        return False


def write_email_preview(html_body: str, *, name: str = "apex-email") -> str:
    """Write one HTML letter to a temp file for local viewing. Does not send mail."""
    directory = Path(tempfile.mkdtemp(prefix="apex-email-"))
    path = directory / f"{name}.html"
    path.write_text(html_body, encoding="utf-8")
    return str(path)
