from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from loguru import logger
from snaptrade_client import ApiException, SnapTrade, SnapTradeAuth

from app.services.encryption import decrypt_secret, encrypt_secret


@dataclass(frozen=True)
class SnapTradeSettings:
    client_id: str
    consumer_key: str
    env: str
    encryption_key: str
    api_base_url: str
    frontend_origin: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.consumer_key and self.encryption_key)


def get_snaptrade_settings() -> SnapTradeSettings:
    cors = os.environ.get(
        "APP_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    frontend = cors.split(",")[0].strip() or "http://localhost:5173"
    api_base = os.environ.get("VITE_API_BASE_URL", "http://localhost:8000").rstrip("/")
    return SnapTradeSettings(
        client_id=os.environ.get("SNAPTRADE_CLIENT_ID", "").strip(),
        consumer_key=os.environ.get("SNAPTRADE_CONSUMER_KEY", "").strip(),
        env=os.environ.get("SNAPTRADE_ENV", "sandbox").strip() or "sandbox",
        encryption_key=os.environ.get("ENCRYPTION_KEY", "").strip(),
        api_base_url=api_base,
        frontend_origin=frontend,
    )


@lru_cache
def _client() -> SnapTrade:
    settings = get_snaptrade_settings()
    return SnapTrade(
        auth=SnapTradeAuth.commercial_api_key(
            consumer_key=settings.consumer_key,
            client_id=settings.client_id,
        )
    )


def encrypt_user_secret(secret: str) -> str:
    return encrypt_secret(secret, get_snaptrade_settings().encryption_key)


def decrypt_user_secret(secret_encrypted: str) -> str:
    return decrypt_secret(secret_encrypted, get_snaptrade_settings().encryption_key)


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return False
    sig_content = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    key = get_snaptrade_settings().consumer_key.encode("utf-8")
    digest = hmac.new(key, sig_content.encode("utf-8"), hashlib.sha256).digest()
    calculated = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(calculated, signature.strip())


OAUTH_STATE_TTL_SECONDS = 600


def _oauth_state_key() -> bytes:
    return get_snaptrade_settings().encryption_key.encode("utf-8")


def _sign_oauth_payload(payload: str) -> str:
    digest = hmac.new(_oauth_state_key(), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def new_oauth_state(user_id: str) -> str:
    ts = int(datetime.now(timezone.utc).timestamp())
    payload = f"{user_id}|{ts}"
    token = f"{payload}|{_sign_oauth_payload(payload)}"
    return base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")


def verify_oauth_state(state: str, ttl_seconds: int = OAUTH_STATE_TTL_SECONDS) -> str | None:
    try:
        padded = state + "=" * (-len(state) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        user_id, ts_str, sig = raw.rsplit("|", 2)
        payload = f"{user_id}|{ts_str}"
        if not hmac.compare_digest(_sign_oauth_payload(payload), sig):
            return None
        if int(datetime.now(timezone.utc).timestamp()) - int(ts_str) > ttl_seconds:
            return None
        return user_id
    except (TypeError, ValueError):
        return None


def callback_url(state: str) -> str:
    settings = get_snaptrade_settings()
    return f"{settings.api_base_url}/api/brokerage/callback?state={state}"


def dashboard_redirect(success: bool) -> str:
    settings = get_snaptrade_settings()
    flag = "true" if success else "false"
    return f"{settings.frontend_origin}/app?connected={flag}"


async def _call(method: str, **kwargs: Any) -> Any:
    client = _client()
    parts = method.split(".")
    obj = client
    for part in parts[:-1]:
        obj = getattr(obj, part)
    name = parts[-1]
    async_fn = getattr(obj, f"a{name}", None)
    if async_fn is not None:
        return await async_fn(**kwargs)
    sync_fn = getattr(obj, name)
    return await asyncio.to_thread(sync_fn, **kwargs)


async def register_snaptrade_user(user_id: str) -> dict[str, str]:
    response = await _call("authentication.register_snap_trade_user", user_id=user_id)
    body = response.body or {}
    return {
        "userId": body.get("userId") or user_id,
        "userSecret": body["userSecret"],
    }


async def connection_portal_url(
    *,
    user_id: str,
    user_secret: str,
    state: str,
    broker: str | None = None,
) -> str:
    kwargs: dict[str, Any] = {
        "user_id": user_id,
        "user_secret": user_secret,
        "connection_type": "read",
        "immediate_redirect": True,
        "custom_redirect": callback_url(state),
        "dark_mode": True,
        "connection_portal_version": "v4",
    }
    if broker:
        kwargs["broker"] = broker
    response = await _call("authentication.login_snap_trade_user", **kwargs)
    body = response.body or {}
    url = body.get("redirectURI") or body.get("redirectUri") or body.get("loginLink")
    if not url:
        raise RuntimeError("SnapTrade did not return a connection portal URL")
    return str(url)


async def list_accounts(user_id: str, user_secret: str) -> list[dict[str, Any]]:
    response = await _call(
        "account_information.list_user_accounts",
        user_id=user_id,
        user_secret=user_secret,
    )
    body = response.body
    if isinstance(body, list):
        return body
    return []


async def fetch_balance(
    user_id: str,
    user_secret: str,
    account_id: str,
    *,
    account_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await _call(
        "account_information.get_user_account_balance",
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret,
    )
    total_equity = _total_equity_from_account(account_row) if account_row else None
    if total_equity is None:
        accounts = await list_accounts(user_id, user_secret)
        for row in accounts:
            if isinstance(row, dict) and str(row.get("id") or "") == account_id:
                total_equity = _total_equity_from_account(row)
                break
    return _normalize_balance(response.body, total_equity=total_equity)


async def fetch_orders(user_id: str, user_secret: str, account_id: str, *, days: int = 90) -> list[dict[str, Any]]:
    response = await _call(
        "account_information.get_user_account_orders",
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret,
        days=days,
    )
    body = response.body or {}
    rows: Any = body
    if isinstance(body, dict):
        rows = body.get("orders") or body.get("data") or body.get("results") or []
    if not isinstance(rows, list):
        return []
    return [_normalize_order(row) for row in rows if isinstance(row, dict)]


async def fetch_positions(user_id: str, user_secret: str, account_id: str) -> list[dict[str, Any]]:
    response = await _call(
        "account_information.get_all_account_positions",
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret,
    )
    body = response.body or {}
    rows = body.get("results") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return []
    return [_normalize_position(row) for row in rows]


async def fetch_day_pnl(user_id: str, user_secret: str, account_id: str, total_equity: float) -> float | None:
    try:
        response = await _call(
            "account_information.get_user_account_return_rates",
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
            timeframes="1D",
        )
    except ApiException:
        return None
    body = response.body or {}
    rates = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rates, list):
        return None
    for row in rates:
        if not isinstance(row, dict):
            continue
        timeframe = str(row.get("timeframe") or row.get("period") or "").upper()
        if timeframe != "1D":
            continue
        pct = (
            row.get("return_percent")
            or row.get("returnPercent")
            or row.get("rate_of_return")
            or row.get("rateOfReturn")
        )
        if pct is None:
            return None
        return float(total_equity) * (float(pct) / 100.0)
    return None


async def delete_authorization(user_id: str, user_secret: str, authorization_id: str) -> None:
    await _call(
        "connections.delete_connection",
        authorization_id=authorization_id,
        user_id=user_id,
        user_secret=user_secret,
    )


def _currency_code(value: Any, default: str = "USD") -> str:
    if isinstance(value, dict):
        return str(value.get("code") or value.get("name") or default)
    if value:
        return str(value)
    return default


def _money_amount(value: Any) -> float:
    if isinstance(value, dict):
        return _num(value.get("amount") or value.get("value"))
    return _num(value)


def _total_equity_from_account(account_row: dict[str, Any] | None) -> float | None:
    if not account_row:
        return None
    balance = account_row.get("balance")
    if not isinstance(balance, dict):
        return None
    total = balance.get("total")
    if total is None:
        return None
    return _money_amount(total)


def _normalize_balance(body: Any, *, total_equity: float | None = None) -> dict[str, Any]:
    rows = body if isinstance(body, list) else [body] if isinstance(body, dict) else []
    cash = buying_power = 0.0
    currency = "USD"
    for row in rows:
        if not isinstance(row, dict):
            continue
        currency = _currency_code(row.get("currency") or row.get("currency_code"), currency)
        cash += _num(row.get("cash") or row.get("cash_balance"))
        buying_power += _num(row.get("buying_power") or row.get("buyingPower"))
    equity = total_equity if total_equity is not None else 0.0
    if buying_power == 0.0:
        buying_power = cash
    return {
        "cash_balance": cash,
        "buying_power": buying_power,
        "total_equity": equity,
        "currency": currency,
        "as_of_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _position_symbol(row: dict[str, Any]) -> str:
    instrument = row.get("instrument") or row.get("symbol") or {}
    if not isinstance(instrument, dict):
        return str(instrument or "—")
    symbol = instrument.get("symbol")
    if isinstance(symbol, dict):
        return str(symbol.get("symbol") or symbol.get("raw_symbol") or symbol.get("ticker") or "—")
    if symbol:
        return str(symbol)
    return str(
        instrument.get("raw_symbol")
        or instrument.get("ticker")
        or instrument.get("description")
        or "—"
    )


def _normalize_position(row: dict[str, Any]) -> dict[str, Any]:
    quantity = _num(
        _first_present(row, "units", "quantity", "open_quantity", "fractional_units")
    )
    current_price = _num(_first_present(row, "price", "current_price", "currentPrice"))
    average_cost = _num(
        _first_present(
            row,
            "cost_basis",
            "costBasis",
            "average_purchase_price",
            "averagePurchasePrice",
        )
    )
    market_value = _num(_first_present(row, "market_value", "marketValue"))
    if market_value == 0.0 and quantity != 0.0 and current_price != 0.0:
        market_value = quantity * current_price

    open_pnl_raw = _first_present(row, "open_pnl", "openPnl", "unrealized_pnl", "unrealizedPnl")
    if open_pnl_raw is not None:
        unrealized_pnl = _num(open_pnl_raw)
    elif average_cost != 0.0 and quantity != 0.0 and current_price != 0.0:
        unrealized_pnl = (current_price - average_cost) * quantity
    else:
        unrealized_pnl = 0.0

    return {
        "symbol": _position_symbol(row),
        "quantity": quantity,
        "average_cost": average_cost,
        "current_price": current_price,
        "market_value": market_value,
        "unrealized_pnl": unrealized_pnl,
        "currency": _currency_code(row.get("currency"), "USD"),
    }


def _normalize_order(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "")
    universal = row.get("universal_symbol")
    if isinstance(universal, dict):
        symbol = str(universal.get("symbol") or universal.get("raw_symbol") or symbol)
    option = row.get("option_symbol")
    if isinstance(option, dict):
        symbol = str(option.get("ticker") or option.get("symbol") or symbol)

    action = str(row.get("action") or "").lower()
    side = "sell" if "sell" in action else "buy"

    qty = _num(row.get("filled_quantity") or row.get("total_quantity"))
    fill_price_raw = row.get("execution_price") or row.get("limit_price")
    fill_price = _num(fill_price_raw) if fill_price_raw is not None else None

    status_raw = row.get("status")
    if isinstance(status_raw, dict):
        status = str(status_raw.get("raw") or status_raw.get("description") or "unknown")
    else:
        status = str(status_raw or "unknown")

    order_id = str(row.get("brokerage_order_id") or row.get("id") or "")

    def _fmt_dt(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    time_placed = row.get("time_placed")
    time_executed = row.get("time_executed") or time_placed

    return {
        "id": order_id or f"order-{symbol}-{time_placed}",
        "symbol": symbol or "—",
        "side": side,
        "qty": qty,
        "order_type": str(row.get("order_type") or "market").lower(),
        "fill_price": fill_price,
        "status": status,
        "asset_class": "us_option" if option else "us_equity",
        "created_at": _fmt_dt(time_placed),
        "filled_at": _fmt_dt(time_executed),
    }


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def mask_account_number(raw: str | None) -> str:
    if not raw:
        return "—"
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 4:
        return f"****{digits[-4:]}"
    return "****"


def log_safe_error(context: str, exc: Exception) -> None:
    logger.warning("SnapTrade {} failed: {}", context, exc.__class__.__name__)
