from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user
from app.models.brokerage import AccountBalance, AuditLog, BrokerageAccount, BrokerageConnection
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.brokerage import (
    AccountBalanceOut,
    AccountsResponse,
    BrokerageAccountOut,
    EquityHistoryResponse,
    OrderOut,
    OrdersResponse,
    PortalUrlRequest,
    PortalUrlResponse,
    PositionsResponse,
    PositionOut,
    RegisterUserResponse,
    SyncResponse,
    WebhookResponse,
)
from app.services import snaptrade as st
from app.services.equity_history import brokerage_equity_history_points

router = APIRouter(prefix="/api/brokerage", tags=["brokerage"])

OAUTH_STATE_TTL = 600
OAUTH_STATE_PREFIX = "brokerage_oauth_state:"


def _require_configured() -> None:
    if not st.get_snaptrade_settings().configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SnapTrade is not configured")


def _brokerage_db_error(exc: Exception) -> HTTPException:
    logger.warning("Brokerage database error: {}", exc.__class__.__name__)
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Brokerage service is temporarily unavailable. Restart the backend to apply database updates.",
    )


def _snaptrade_upstream_error(context: str, exc: Exception) -> HTTPException:
    st.log_safe_error(context, exc)
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        "Unable to reach your brokerage right now. Try Refresh in a minute.",
    )


def _decrypt_connection_secret(connection: BrokerageConnection) -> str:
    try:
        return st.decrypt_user_secret(connection.snaptrade_user_secret_encrypted)
    except (ValueError, Exception) as exc:  # noqa: BLE001
        st.log_safe_error("decrypt_user_secret", exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Brokerage credentials could not be read. Disconnect and reconnect your brokerage.",
        ) from exc


async def _rollback_db(db: AsyncSession) -> None:
    try:
        await db.rollback()
    except Exception:  # noqa: BLE001
        pass


async def _audit(
    db: AsyncSession,
    *,
    user_id: str | None,
    action: str,
    result: str,
    request: Request | None = None,
) -> None:
    ip = request.client.host if request and request.client else None
    db.add(AuditLog(user_id=user_id, action=action, ip_address=ip, result=result))
    await db.flush()


async def _connection_for_user(db: AsyncSession, user_id: str) -> BrokerageConnection | None:
    return await db.scalar(
        select(BrokerageConnection)
        .where(BrokerageConnection.user_id == user_id, BrokerageConnection.provider == "snaptrade")
        .options(selectinload(BrokerageConnection.accounts))
    )


async def _account_for_user(db: AsyncSession, user_id: str, account_id: str) -> BrokerageAccount:
    account = await db.scalar(
        select(BrokerageAccount)
        .join(BrokerageConnection, BrokerageAccount.connection_id == BrokerageConnection.id)
        .where(BrokerageConnection.user_id == user_id, BrokerageAccount.account_id == account_id)
    )
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Brokerage account not found")
    return account


async def _latest_balance(db: AsyncSession, account_pk: str) -> AccountBalance | None:
    return await db.scalar(
        select(AccountBalance)
        .where(AccountBalance.account_id == account_pk)
        .order_by(AccountBalance.as_of_timestamp.desc())
        .limit(1)
    )


def _balance_out(row: AccountBalance) -> AccountBalanceOut:
    return AccountBalanceOut(
        cash_balance=row.cash_balance,
        buying_power=row.buying_power,
        total_equity=row.total_equity,
        day_pnl=row.day_pnl,
        currency=row.currency,
        as_of_timestamp=row.as_of_timestamp,
    )


async def sync_connection(
    db: AsyncSession,
    connection: BrokerageConnection,
    *,
    user_secret: str,
) -> None:
    accounts = await st.list_accounts(connection.snaptrade_user_id, user_secret)
    seen: set[str] = set()
    for row in accounts:
        if not isinstance(row, dict):
            continue
        snap_id = str(row.get("id") or "")
        if not snap_id:
            continue
        seen.add(snap_id)
        account = await db.scalar(
            select(BrokerageAccount).where(
                BrokerageAccount.connection_id == connection.id,
                BrokerageAccount.account_id == snap_id,
            )
        )
        if not account:
            account = BrokerageAccount(
                id=str(uuid4()),
                connection_id=connection.id,
                account_id=snap_id,
            )
            db.add(account)
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        account.account_name = str(row.get("name") or row.get("account_name") or "Brokerage account")
        account.account_type = str(
            row.get("raw_type") or meta.get("type") or row.get("account_type") or row.get("type") or "—"
        )
        institution = row.get("institution_name") or row.get("brokerage") or {}
        if isinstance(institution, dict):
            account.broker_name = str(institution.get("name") or institution.get("slug") or "—")
        else:
            account.broker_name = str(institution or "—")
        account.account_number_masked = st.mask_account_number(
            str(row.get("number") or row.get("account_number") or "")
        )
        account.sync_status = "synced"
        balance = await st.fetch_balance(
            connection.snaptrade_user_id,
            user_secret,
            snap_id,
            account_row=row,
        )
        day_pnl = await st.fetch_day_pnl(
            connection.snaptrade_user_id,
            user_secret,
            snap_id,
            balance["total_equity"],
        )
        db.add(
            AccountBalance(
                id=str(uuid4()),
                account_id=account.id,
                cash_balance=balance["cash_balance"],
                buying_power=balance["buying_power"],
                total_equity=balance["total_equity"],
                day_pnl=day_pnl,
                currency=balance["currency"],
                as_of_timestamp=datetime.now(timezone.utc),
            )
        )
    for account in connection.accounts:
        if account.account_id not in seen:
            account.sync_status = "stale"
    connection.connection_status = "connected" if seen else connection.connection_status
    connection.last_synced_at = datetime.now(timezone.utc)
    await db.commit()


def _accounts_response(connection: BrokerageConnection) -> AccountsResponse:
    rows: list[BrokerageAccountOut] = []
    for account in connection.accounts:
        rows.append(
            BrokerageAccountOut(
                id=account.account_id,
                account_name=account.account_name,
                account_type=account.account_type,
                broker_name=account.broker_name,
                account_number_masked=account.account_number_masked,
                sync_status=account.sync_status,
                last_synced_at=connection.last_synced_at,
            )
        )
    return AccountsResponse(connection_status=connection.connection_status, accounts=rows)


async def _maybe_sync_connection(
    db: AsyncSession,
    connection: BrokerageConnection,
) -> BrokerageConnection:
    if connection.accounts and connection.connection_status == "connected":
        return connection
    _require_configured()
    secret = _decrypt_connection_secret(connection)
    try:
        await sync_connection(db, connection, user_secret=secret)
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        raise _brokerage_db_error(exc) from exc
    refreshed = await _connection_for_user(db, connection.user_id)
    return refreshed or connection


async def _account_count(db: AsyncSession, connection_id: str) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(BrokerageAccount)
        .where(BrokerageAccount.connection_id == connection_id)
    )
    return int(count or 0)


@router.post("/register-user", response_model=RegisterUserResponse)
async def register_user(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> RegisterUserResponse:
    _require_configured()
    try:
        existing = await _connection_for_user(db, user.id)
    except (OperationalError, SQLAlchemyError) as exc:
        raise _brokerage_db_error(exc) from exc
    if existing:
        await _audit(db, user_id=user.id, action="brokerage.register_user", result="exists", request=request)
        return RegisterUserResponse(connection_status=existing.connection_status)
    snap_user_id = f"apex-{user.id}"
    try:
        registered = await st.register_snaptrade_user(snap_user_id)
    except Exception as exc:  # noqa: BLE001
        st.log_safe_error("register_user", exc)
        await _audit(db, user_id=user.id, action="brokerage.register_user", result="error", request=request)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to register SnapTrade user") from exc
    connection = BrokerageConnection(
        id=str(uuid4()),
        user_id=user.id,
        provider="snaptrade",
        snaptrade_user_id=registered["userId"],
        snaptrade_user_secret_encrypted=st.encrypt_user_secret(registered["userSecret"]),
        connection_status="pending",
    )
    db.add(connection)
    await _audit(db, user_id=user.id, action="brokerage.register_user", result="ok", request=request)
    await db.commit()
    return RegisterUserResponse(connection_status=connection.connection_status)


@router.post("/connection-portal-url", response_model=PortalUrlResponse)
async def connection_portal_url(
    body: PortalUrlRequest,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PortalUrlResponse:
    _require_configured()
    connection = await _connection_for_user(db, user.id)
    if not connection:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Register SnapTrade user first")
    state = st.new_oauth_state(user.id)
    redis = await get_redis(settings)
    await redis.set(f"{OAUTH_STATE_PREFIX}{state}", user.id, ex=OAUTH_STATE_TTL)
    secret = _decrypt_connection_secret(connection)
    try:
        url = await st.connection_portal_url(
            user_id=connection.snaptrade_user_id,
            user_secret=secret,
            state=state,
            broker=body.broker,
        )
    except Exception as exc:  # noqa: BLE001
        st.log_safe_error("connection_portal_url", exc)
        await _audit(db, user_id=user.id, action="brokerage.portal_url", result="error", request=request)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to create connection portal URL") from exc
    await _audit(db, user_id=user.id, action="brokerage.portal_url", result="ok", request=request)
    return PortalUrlResponse(url=url)


@router.get("/callback")
async def oauth_callback(
    request: Request,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    _require_configured()
    if not state:
        return RedirectResponse(st.dashboard_redirect(False), status_code=status.HTTP_302_FOUND)
    user_id = st.verify_oauth_state(state)
    redis = await get_redis(settings)
    if not user_id:
        user_id = await redis.get(f"{OAUTH_STATE_PREFIX}{state}")
    if not user_id:
        return RedirectResponse(st.dashboard_redirect(False), status_code=status.HTTP_302_FOUND)
    await redis.delete(f"{OAUTH_STATE_PREFIX}{state}")
    connection = await _connection_for_user(db, user_id)
    if not connection:
        return RedirectResponse(st.dashboard_redirect(False), status_code=status.HTTP_302_FOUND)
    secret = _decrypt_connection_secret(connection)
    try:
        await sync_connection(db, connection, user_secret=secret)
        await _audit(db, user_id=user_id, action="brokerage.oauth_callback", result="ok", request=request)
        return RedirectResponse(st.dashboard_redirect(True), status_code=status.HTTP_302_FOUND)
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        st.log_safe_error("oauth_callback_db", exc)
        await _audit(db, user_id=user_id, action="brokerage.oauth_callback", result="error", request=request)
        return RedirectResponse(st.dashboard_redirect(False), status_code=status.HTTP_302_FOUND)
    except Exception as exc:  # noqa: BLE001
        await _rollback_db(db)
        st.log_safe_error("oauth_callback", exc)
        await _audit(db, user_id=user_id, action="brokerage.oauth_callback", result="error", request=request)
        return RedirectResponse(st.dashboard_redirect(False), status_code=status.HTTP_302_FOUND)


@router.post("/webhook", response_model=WebhookResponse)
async def webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> WebhookResponse:
    _require_configured()
    body = await request.body()
    signature = request.headers.get("Signature") or request.headers.get("signature")
    if not st.verify_webhook_signature(body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")
    try:
        payload: dict[str, Any] = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid JSON payload") from exc
    event_ts = payload.get("eventTimestamp") or payload.get("event_timestamp")
    if event_ts:
        try:
            ts = datetime.fromisoformat(str(event_ts).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - ts).total_seconds() > 300:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Stale webhook event")
        except ValueError:
            pass
    user_id = payload.get("userId") or payload.get("user_id")
    if user_id:
        connection = await db.scalar(
            select(BrokerageConnection).where(BrokerageConnection.snaptrade_user_id == str(user_id))
        )
        if connection:
            secret = _decrypt_connection_secret(connection)
            try:
                await sync_connection(db, connection, user_secret=secret)
            except (OperationalError, SQLAlchemyError) as exc:
                await _rollback_db(db)
                st.log_safe_error("webhook_sync_db", exc)
            except Exception as exc:  # noqa: BLE001
                await _rollback_db(db)
                st.log_safe_error("webhook_sync", exc)
    await _audit(db, user_id=None, action="brokerage.webhook", result="ok", request=request)
    await db.commit()
    return WebhookResponse()


@router.post("/sync", response_model=SyncResponse)
async def sync_accounts(
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> SyncResponse:
    user_id = user.id
    _require_configured()
    connection = await _connection_for_user(db, user_id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brokerage connection")
    try:
        connection = await _maybe_sync_connection(db, connection)
        await _audit(db, user_id=user_id, action="brokerage.sync", result="ok", request=request)
        return SyncResponse(
            connection_status=connection.connection_status,
            account_count=await _account_count(db, connection.id),
        )
    except HTTPException:
        await _rollback_db(db)
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        await _audit(db, user_id=user_id, action="brokerage.sync", result="error", request=request)
        raise _brokerage_db_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        await _rollback_db(db)
        st.log_safe_error("sync_accounts", exc)
        await _audit(db, user_id=user_id, action="brokerage.sync", result="error", request=request)
        raise _snaptrade_upstream_error("sync_accounts", exc) from exc


@router.get("/accounts", response_model=AccountsResponse)
async def list_accounts(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountsResponse:
    try:
        connection = await _connection_for_user(db, user.id)
    except (OperationalError, SQLAlchemyError) as exc:
        raise _brokerage_db_error(exc) from exc
    if not connection:
        return AccountsResponse(connection_status=None, accounts=[])
    if not connection.accounts or connection.connection_status != "connected":
        try:
            await _maybe_sync_connection(db, connection)
            connection = await _connection_for_user(db, user.id) or connection
        except HTTPException:
            await _rollback_db(db)
            if connection.accounts:
                logger.warning("Returning cached brokerage accounts after sync failure")
                return _accounts_response(connection)
            raise
        except (OperationalError, SQLAlchemyError) as exc:
            await _rollback_db(db)
            if connection.accounts:
                logger.warning("Returning cached brokerage accounts after database error during sync")
                return _accounts_response(connection)
            raise _brokerage_db_error(exc) from exc
        except Exception as exc:  # noqa: BLE001
            await _rollback_db(db)
            st.log_safe_error("accounts_auto_sync", exc)
            if connection.accounts:
                return _accounts_response(connection)
    return _accounts_response(connection)


@router.get("/accounts/{account_id}/balance", response_model=AccountBalanceOut)
async def account_balance(
    account_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> AccountBalanceOut:
    user_id = user.id
    _require_configured()
    connection = await _connection_for_user(db, user_id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brokerage connection")
    account = await _account_for_user(db, user_id, account_id)
    account_pk = account.id
    secret = _decrypt_connection_secret(connection)
    try:
        balance = await st.fetch_balance(connection.snaptrade_user_id, secret, account_id)
        day_pnl = await st.fetch_day_pnl(
            connection.snaptrade_user_id,
            secret,
            account_id,
            balance["total_equity"],
        )
        row = AccountBalance(
            id=str(uuid4()),
            account_id=account_pk,
            cash_balance=balance["cash_balance"],
            buying_power=balance["buying_power"],
            total_equity=balance["total_equity"],
            day_pnl=day_pnl,
            currency=balance["currency"],
            as_of_timestamp=datetime.now(timezone.utc),
        )
        db.add(row)
        connection.last_synced_at = datetime.now(timezone.utc)
        await db.commit()
        await _audit(db, user_id=user_id, action="brokerage.balance_refresh", result="ok", request=request)
        return _balance_out(row)
    except HTTPException:
        await _rollback_db(db)
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        cached = await _latest_balance(db, account_pk)
        if cached:
            await _audit(db, user_id=user_id, action="brokerage.balance_refresh", result="cached_db", request=request)
            return _balance_out(cached)
        await _audit(db, user_id=user_id, action="brokerage.balance_refresh", result="error", request=request)
        raise _brokerage_db_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        await _rollback_db(db)
        st.log_safe_error("account_balance", exc)
        cached = await _latest_balance(db, account_pk)
        if cached:
            await _audit(db, user_id=user_id, action="brokerage.balance_refresh", result="cached_upstream", request=request)
            return _balance_out(cached)
        await _audit(db, user_id=user_id, action="brokerage.balance_refresh", result="error", request=request)
        raise _snaptrade_upstream_error("account_balance", exc) from exc


@router.get("/accounts/{account_id}/positions", response_model=PositionsResponse)
async def account_positions(
    account_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> PositionsResponse:
    user_id = user.id
    _require_configured()
    connection = await _connection_for_user(db, user_id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brokerage connection")
    await _account_for_user(db, user_id, account_id)
    secret = _decrypt_connection_secret(connection)
    try:
        rows = await st.fetch_positions(connection.snaptrade_user_id, secret, account_id)
        connection.last_synced_at = datetime.now(timezone.utc)
        await db.commit()
        await _audit(db, user_id=user_id, action="brokerage.positions_refresh", result="ok", request=request)
        return PositionsResponse(positions=[PositionOut(**row) for row in rows])
    except HTTPException:
        await _rollback_db(db)
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        await _audit(db, user_id=user_id, action="brokerage.positions_refresh", result="error", request=request)
        raise _brokerage_db_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        await _rollback_db(db)
        st.log_safe_error("account_positions", exc)
        await _audit(db, user_id=user_id, action="brokerage.positions_refresh", result="error", request=request)
        raise _snaptrade_upstream_error("account_positions", exc) from exc


@router.get("/accounts/{account_id}/equity-history", response_model=EquityHistoryResponse)
async def account_equity_history(
    account_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> EquityHistoryResponse:
    account = await _account_for_user(db, user.id, account_id)
    starting, points = await brokerage_equity_history_points(db, account.id)
    return EquityHistoryResponse(starting_balance=starting, account_mode="real_brokerage", points=points)


@router.get("/accounts/{account_id}/orders", response_model=OrdersResponse)
async def account_orders(
    account_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> OrdersResponse:
    user_id = user.id
    _require_configured()
    connection = await _connection_for_user(db, user_id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brokerage connection")
    await _account_for_user(db, user_id, account_id)
    secret = _decrypt_connection_secret(connection)
    try:
        rows = await st.fetch_orders(connection.snaptrade_user_id, secret, account_id)
        connection.last_synced_at = datetime.now(timezone.utc)
        await db.commit()
        await _audit(db, user_id=user_id, action="brokerage.orders_refresh", result="ok", request=request)
        return OrdersResponse(orders=[OrderOut(**row) for row in rows])
    except HTTPException:
        await _rollback_db(db)
        raise
    except (OperationalError, SQLAlchemyError) as exc:
        await _rollback_db(db)
        await _audit(db, user_id=user_id, action="brokerage.orders_refresh", result="error", request=request)
        raise _brokerage_db_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        await _rollback_db(db)
        st.log_safe_error("account_orders", exc)
        await _audit(db, user_id=user_id, action="brokerage.orders_refresh", result="error", request=request)
        raise _snaptrade_upstream_error("account_orders", exc) from exc


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_account(
    account_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _require_configured()
    connection = await _connection_for_user(db, user.id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No brokerage connection")
    account = await _account_for_user(db, user.id, account_id)
    secret = _decrypt_connection_secret(connection)
    authorization_id = None
    try:
        accounts = await st.list_accounts(connection.snaptrade_user_id, secret)
        for row in accounts:
            if isinstance(row, dict) and str(row.get("id")) == account_id:
                authorization_id = row.get("brokerage_authorization") or row.get("brokerageAuthorization")
                if isinstance(authorization_id, dict):
                    authorization_id = authorization_id.get("id")
                break
        if authorization_id:
            await st.delete_authorization(connection.snaptrade_user_id, secret, str(authorization_id))
    except Exception as exc:  # noqa: BLE001
        st.log_safe_error("disconnect_account", exc)
        await _audit(db, user_id=user.id, action="brokerage.disconnect", result="error", request=request)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to disconnect brokerage account") from exc
    balances = await db.scalars(select(AccountBalance).where(AccountBalance.account_id == account.id))
    for row in balances:
        await db.delete(row)
    await db.delete(account)
    remaining = await db.scalar(
        select(BrokerageAccount.id).where(BrokerageAccount.connection_id == connection.id).limit(1)
    )
    if not remaining:
        connection.connection_status = "disconnected"
    connection.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    await _audit(db, user_id=user.id, action="brokerage.disconnect", result="ok", request=request)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
