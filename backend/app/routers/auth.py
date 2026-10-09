from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user
from app.models.otp_device import OtpDevice
from app.models.trading import WatchlistItem
from app.models.user import LoginAudit, RefreshToken, User
from app.schemas.auth import (
    ConnectBrokerageRequest,
    DEFAULT_PAPER_BALANCE,
    ForgotPasswordRequest,
    ForgotPasswordVerifyRequest,
    LoginRequest,
    OtpRequest,
    OtpVerifyRequest,
    PasswordStrengthRequest,
    SignupOut,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_strength,
    verify_password,
)
from app.services.market_session import getLastMarketOpen
from app.services.otp import claim_login_code, invalidate_login_code, issue_otp, verify_otp
from app.services.password_reset import consume_pending_reset, store_pending_reset
from app.services.signup_email import send_login_code, send_signup_confirmation

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "apex_refresh"
DEVICE_COOKIE = "apex_device"
DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 400
LOGIN_CODE_TTL_SECONDS = 600
NO_SIGNIN_EMAIL = "This account has no email for a sign-in code."
SIGNIN_CODE_NOT_SENT = "The sign-in code could not be sent."


def _set_refresh(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
    )


def _clear_refresh(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _sign_device(settings: Settings, device_id: str) -> str:
    mac = hmac.new(settings.app_secret_key.encode("utf-8"), device_id.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{device_id}.{mac}"


def _read_device_cookie(settings: Settings, raw: str | None) -> str | None:
    if not raw or raw.count(".") != 1:
        return None
    device_id, mac = raw.split(".", 1)
    if len(device_id) != 32 or any(char not in "0123456789abcdef" for char in device_id):
        return None
    expected = hmac.new(
        settings.app_secret_key.encode("utf-8"), device_id.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return None
    return device_id


def _bind_device(request: Request, response: Response, settings: Settings) -> str:
    """Return this browser's device id, setting a signed httpOnly cookie when it has none."""
    device_id = _read_device_cookie(settings, request.cookies.get(DEVICE_COOKIE))
    if device_id:
        return device_id
    device_id = secrets.token_hex(16)
    response.set_cookie(
        DEVICE_COOKIE,
        _sign_device(settings, device_id),
        httponly=True,
        samesite=settings.cookie_samesite,
        secure=settings.cookie_secure,
        max_age=DEVICE_COOKIE_MAX_AGE,
        path="/",
    )
    return device_id


async def _verified_since_open(db: AsyncSession, user_id: str, device_id: str, now: datetime) -> bool:
    row = await db.scalar(select(OtpDevice).where(OtpDevice.user_id == user_id, OtpDevice.device_id == device_id))
    if row is None or row.otp_verified_at is None:
        return False
    return _aware(row.otp_verified_at) >= getLastMarketOpen(now)


async def _remember_otp_verification(db: AsyncSession, user_id: str, device_id: str, now: datetime) -> None:
    row = await db.scalar(select(OtpDevice).where(OtpDevice.user_id == user_id, OtpDevice.device_id == device_id))
    if row is None:
        db.add(OtpDevice(user_id=user_id, device_id=device_id, otp_verified_at=now))
    else:
        row.otp_verified_at = now


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _token_response(user: User, access: str, settings: Settings, *, show_connect_modal: bool) -> TokenResponse:
    ttl = int(settings.access_token_ttl_seconds)
    skew = max(0, int(settings.access_token_refresh_skew_seconds))
    return TokenResponse(
        access_token=access,
        expires_in=ttl,
        refresh_in=max(0, ttl - skew),
        brokerage_connected=user.brokerage_connected,
        first_login=not user.first_login_completed,
        account_mode=user.account_mode,  # type: ignore[arg-type]
        show_connect_modal=show_connect_modal,
    )


async def _resolve_user(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip()
    if not ident:
        return None
    user = await db.scalar(select(User).where(User.username == ident))
    if user:
        return user
    return await db.scalar(select(User).where(User.email == ident.lower()))


async def _email_login_code(user: User, settings: Settings, *, force_new: bool = False) -> None:
    """Mail one sign-in code to this account. No session is created.

    A pending code issued in the last 45 seconds is reused and not mailed again.
    ``force_new`` is the explicit resend: it replaces that code and sends once.
    """
    email = (user.email or "").strip()
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, NO_SIGNIN_EMAIL)
    claim = await claim_login_code(
        settings,
        user.username,
        ttl_seconds=LOGIN_CODE_TTL_SECONDS,
        force_new=force_new,
    )
    if claim.code is None:
        logger.info("Sign-in code already pending; email not sent again")
        return
    sent = await send_login_code(
        settings,
        full_name=user.full_name or "",
        email=email,
        code=claim.code,
    )
    if not sent:
        await invalidate_login_code(settings, user.username)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, SIGNIN_CODE_NOT_SENT)


async def _issue_session(
    user: User,
    response: Response,
    db: AsyncSession,
    settings: Settings,
) -> TokenResponse:
    jti = secrets.token_hex(16)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl_seconds)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires))
    await db.commit()
    access = create_access_token(settings, UUID(user.id), {"mode": user.account_mode})
    refresh = create_refresh_token(settings, UUID(user.id), jti)
    _set_refresh(response, refresh, settings)
    return _token_response(user, access, settings, show_connect_modal=True)


def _otp_request_payload(settings: Settings, code: str | None = None) -> dict:
    payload: dict = {"ok": True, "ttl_seconds": settings.otp_ttl_seconds, "autofill": False, "code": None}
    if code and settings.autofill_2fa and settings.app_env != "production":
        payload["autofill"] = True
        payload["code"] = code
    return payload


@router.post("/signup", response_model=SignupOut, status_code=201)
async def signup(
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SignupOut:
    exists = await db.scalar(select(User).where((User.username == body.username) | (User.email == body.email)))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already registered")
    if body.account_mode == "real_brokerage" and body.starting_balance is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "starting_balance is not accepted for real_brokerage")
    if body.account_mode == "paper_funded" and body.starting_balance is not None:
        cash = float(body.starting_balance)
    else:
        cash = DEFAULT_PAPER_BALANCE
    user = User(
        full_name=body.full_name,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        account_mode=body.account_mode,
        starting_balance=cash,
        cash_balance=cash,
        buying_power=cash,
        portfolio_value=cash,
    )
    db.add(user)
    await db.flush()
    for sym in ("SPX", "AAPL", "NVDA", "MSFT"):
        db.add(WatchlistItem(user_id=user.id, symbol=sym))
    await db.commit()
    await db.refresh(user)
    entered_balance = (
        float(body.starting_balance)
        if body.account_mode == "paper_funded" and body.starting_balance is not None
        else None
    )
    confirmation_sent = await send_signup_confirmation(
        settings,
        full_name=body.full_name,
        username=body.username,
        email=str(body.email),
        password=body.password,
        account_mode=body.account_mode,
        starting_balance=entered_balance,
    )
    account = UserOut.model_validate(user)
    return SignupOut(**account.model_dump(), confirmation_sent=confirmation_sent)


@router.post("/password-strength")
async def strength(body: PasswordStrengthRequest) -> dict:
    return password_strength(body.password)


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.scalar(select(User).where(User.username == body.username))
    ok = bool(user and verify_password(body.password, user.password_hash))
    db.add(
        LoginAudit(
            user_id=user.id if user else None,
            username=body.username,
            success=ok,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await db.commit()
    if not ok or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    settings = get_settings()
    now = datetime.now(timezone.utc)
    device_id = _bind_device(request, response, settings)
    if await _verified_since_open(db, user.id, device_id, now):
        token = await _issue_session(user, response, db, settings)
        payload = token.model_dump()
        payload["otp_required"] = False
        return payload
    await _email_login_code(user, settings)
    return {
        "ok": True,
        "username": user.username,
        "account_mode": user.account_mode,
        "otp_required": True,
        "ttl_seconds": LOGIN_CODE_TTL_SECONDS,
    }


@router.post("/login/code")
async def resend_login_code(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    await _email_login_code(user, settings, force_new=True)
    return {"ok": True, "ttl_seconds": LOGIN_CODE_TTL_SECONDS}


@router.post("/otp/request")
async def otp_request(
    body: OtpRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown username")
    code = await issue_otp(settings, user.username)
    return _otp_request_payload(settings, code)


@router.post("/otp/verify", response_model=TokenResponse)
async def otp_verify(
    body: OtpVerifyRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown username")
    if not await verify_otp(settings, user.username, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code")
    now = datetime.now(timezone.utc)
    device_id = _bind_device(request, response, settings)
    await _remember_otp_verification(db, user.id, device_id, now)
    return await _issue_session(user, response, db, settings)


# TODO(security): Replace with production password reset via email link + new password.
@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    user = await _resolve_user(db, body.username)
    if not user:
        return _otp_request_payload(settings)
    await store_pending_reset(settings, user.username, hash_password(body.password))
    code = await issue_otp(settings, user.username)
    return _otp_request_payload(settings, code)


# TODO(security): Replace with production password reset via email link + new password.
@router.post("/forgot-password/verify", response_model=TokenResponse)
async def forgot_password_verify(
    body: ForgotPasswordVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await _resolve_user(db, body.username)
    if not user or not await verify_otp(settings, user.username, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code")
    pending_hash = await consume_pending_reset(settings, user.username)
    if not pending_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Password reset expired — request a new code")
    user.password_hash = pending_hash
    await db.commit()
    await db.refresh(user)
    return await _issue_session(user, response, db, settings)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh cookie")
    try:
        payload = decode_token(settings, raw, expected_type="refresh")
    except Exception as exc:  # noqa: BLE001
        _clear_refresh(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh") from exc
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti or not payload.get("sub"):
        _clear_refresh(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh")
    row = await db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    if not row or row.revoked or row.user_id != payload["sub"] or _aware(row.expires_at) <= datetime.now(timezone.utc):
        _clear_refresh(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh revoked")
    user = await db.get(User, payload["sub"])
    if not user:
        _clear_refresh(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    # Keep this refresh cookie until logout or its own exp. Rotating it on every
    # silent refresh lets a second in-flight call present the old cookie, get
    # 401, and clear the cookie the first call just set — a forced logout.
    access = create_access_token(settings, UUID(user.id), {"mode": user.account_mode})
    return _token_response(user, access, settings, show_connect_modal=not user.first_login_completed)


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        try:
            payload = decode_token(settings, raw)
            row = await db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti")))
            if row:
                row.revoked = True
                await db.commit()
        except Exception:
            pass
    _clear_refresh(response, settings)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/brokerage", response_model=UserOut)
async def brokerage(body: ConnectBrokerageRequest, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> User:
    user.first_login_completed = True
    if body.later:
        user.brokerage_connected = False
        user.connect_later_banner = True
    else:
        user.brokerage_connected = True
        user.connect_later_banner = False
        if user.account_mode == "real_brokerage" and user.starting_balance is None:
            user.starting_balance = user.cash_balance
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/brokerage/banner/dismiss", response_model=UserOut)
async def dismiss_banner(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> User:
    user.connect_later_banner = False
    await db.commit()
    await db.refresh(user)
    return user
