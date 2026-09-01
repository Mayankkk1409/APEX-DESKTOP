from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.alpaca import AlpacaAdapter
from app.config import Settings, get_settings
from app.database import get_db
from app.models.user import User
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)


async def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = creds.credentials if creds else None
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing access token")
    try:
        payload = decode_token(settings, token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token") from exc
    if payload.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = await db.get(User, payload["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


def get_adapter(settings: Settings = Depends(get_settings)):
    # Always AlpacaAdapter: live quotes even without keys (CNBC/NASDAQ/Yahoo fallback).
    # Options/orders still fall back to the demo adapter internally when Alpaca is dark.
    return AlpacaAdapter(settings)
