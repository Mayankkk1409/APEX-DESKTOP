from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user
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
from app.services.otp import invalidate_otp, issue_otp, verify_otp
from app.services.password_reset import consume_pending_reset, store_pending_reset

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "apex_refresh"


def _set_refresh(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env == "production",
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
    )


async def _resolve_user(db: AsyncSession, identifier: str) -> User | None:
    ident = identifier.strip()
    if not ident:
        return None
    user = await db.scalar(select(User).where(User.username == ident))
    if user:
        return user
    return await db.scalar(select(User).where(User.email == ident.lower()))


async def _issue_session(
    user: User,
    response: Response,
    db: AsyncSession,
    settings: Settings,
) -> TokenResponse:
    first = not user.first_login_completed
    jti = secrets.token_hex(16)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl_seconds)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires))
    await db.commit()
    access = create_access_token(settings, UUID(user.id), {"mode": user.account_mode})
    refresh = create_refresh_token(settings, UUID(user.id), jti)
    _set_refresh(response, refresh, settings)
    return TokenResponse(
        access_token=access,
        brokerage_connected=user.brokerage_connected,
        first_login=first,
        account_mode=user.account_mode,  # type: ignore[arg-type]
        show_connect_modal=True,
    )


def _otp_request_payload(settings: Settings, code: str | None = None) -> dict:
    payload: dict = {"ok": True, "ttl_seconds": settings.otp_ttl_seconds, "autofill": False, "code": None}
    if code and settings.autofill_2fa and settings.app_env != "production":
        payload["autofill"] = True
        payload["code"] = code
    return payload


@router.post("/signup", response_model=UserOut, status_code=201)
async def signup(body: SignupRequest, db: AsyncSession = Depends(get_db)) -> User:
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
    return user


@router.post("/password-strength")
async def strength(body: PasswordStrengthRequest) -> dict:
    return password_strength(body.password)


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
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
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    settings = get_settings()
    await invalidate_otp(settings, user.username)
    return {"ok": True, "username": user.username, "account_mode": user.account_mode, "otp_required": True}


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
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown username")
    if not await verify_otp(settings, user.username, body.code):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired code")
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
        payload = decode_token(settings, raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh") from exc
    row = await db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti"), RefreshToken.revoked.is_(False)))
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh revoked")
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    access = create_access_token(settings, UUID(user.id), {"mode": user.account_mode})
    return TokenResponse(
        access_token=access,
        brokerage_connected=user.brokerage_connected,
        first_login=not user.first_login_completed,
        account_mode=user.account_mode,  # type: ignore[arg-type]
        show_connect_modal=not user.first_login_completed,
    )


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
    response.delete_cookie(REFRESH_COOKIE, path="/")
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
