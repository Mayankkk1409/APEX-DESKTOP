from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

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
    host: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.consumer_key and self.encryption_key)


def get_snaptrade_settings() -> SnapTradeSettings:
    """Read SnapTrade config from application settings (the `.env` file).

    Partner credentials are not taken from a separate process environment lookup,
    so a server started without ``source .env`` still sees the same values Alpaca uses.
    """
    from app.config import get_settings

    settings = get_settings()
    frontend = settings.frontend_base_url.strip().rstrip("/")
    if not frontend:
        frontend = settings.cors_origin_list[0] if settings.cors_origin_list else "http://localhost:5173"
    api_base = settings.api_public_base_url.strip().rstrip("/") or "http://localhost:8000"
    return SnapTradeSettings(
        client_id=settings.snaptrade_client_id.strip(),
        consumer_key=settings.snaptrade_consumer_key.strip(),
        env=settings.snaptrade_env.strip() or "sandbox",
        encryption_key=settings.encryption_key.strip(),
        api_base_url=api_base,
        frontend_origin=frontend,
        host=settings.resolved_snaptrade_host,
    )


@lru_cache(maxsize=4)
def _cached_client(client_id: str, consumer_key: str, host: str) -> SnapTrade:
    return SnapTrade(
        auth=SnapTradeAuth.commercial_api_key(
            consumer_key=consumer_key,
            client_id=client_id,
        ),
        host=host,
    )


def _client() -> SnapTrade:
    settings = get_snaptrade_settings()
    return _cached_client(settings.client_id, settings.consumer_key, settings.host)


_PROBE_TTL_SECONDS = 30.0
_probe_cache: tuple[float, dict[str, Any]] | None = None


def clear_probe_cache() -> None:
    global _probe_cache
    _probe_cache = None


def _missing_snaptrade_env(settings: SnapTradeSettings) -> list[str]:
    missing: list[str] = []
    if not settings.client_id:
        missing.append("SNAPTRADE_CLIENT_ID")
    if not settings.consumer_key:
        missing.append("SNAPTRADE_CONSUMER_KEY")
    if not settings.encryption_key:
        missing.append("ENCRYPTION_KEY")
    return missing


async def _probe_upstream_once() -> dict[str, Any]:
    settings = get_snaptrade_settings()
    missing = _missing_snaptrade_env(settings)
    if missing:
        return {
            "upstream": "not_configured",
            "http_status": None,
            "host": settings.host,
            "missing": missing,
        }
    try:
        response = await _call("api_status.check")
        code = int(getattr(response, "status", None) or 200)
        return {
            "upstream": "up" if 200 <= code < 300 else "down",
            "http_status": code,
            "host": settings.host,
            "missing": [],
        }
    except ApiException as exc:
        code = getattr(exc, "status", None)
        log_safe_error("api_status", exc)
        return {
            "upstream": "down",
            "http_status": int(code) if isinstance(code, int) else None,
            "host": settings.host,
            "missing": [],
        }
    except Exception as exc:  # noqa: BLE001
        log_safe_error("api_status", exc)
        return {
            "upstream": "down",
            "http_status": None,
            "host": settings.host,
            "missing": [],
        }


async def probe_upstream() -> dict[str, Any]:
    """Live SnapTrade API status. Never reports up unless the status call succeeds."""
    global _probe_cache
    now = time.monotonic()
    if _probe_cache is not None and now - _probe_cache[0] < _PROBE_TTL_SECONDS:
        return _probe_cache[1]
    result = await _probe_upstream_once()
    _probe_cache = (now, result)
    return result


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


def is_existing_snaptrade_user(exc: Exception) -> bool:
    """True when SnapTrade already has this user id (code 1010).

    The stored user secret cannot be recovered, so callers delete and register again.
    """
    status_code = getattr(exc, "status", None)
    if status_code not in (400, 409):
        return False
    code, detail = _error_code_and_detail(getattr(exc, "body", None))
    if code == "1010":
        return True
    return "already exist" in detail.lower()


def _error_code_and_detail(body: Any) -> tuple[str, str]:
    if isinstance(body, (bytes, str)):
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            return "", text
    if isinstance(body, dict):
        return str(body.get("code") or ""), str(body.get("detail") or body.get("message") or "")
    return "", ""


async def register_snaptrade_user(user_id: str) -> dict[str, str]:
    response = await _call("authentication.register_snap_trade_user", user_id=user_id)
    body = _mapping(response.body)
    secret = body.get("userSecret")
    if not isinstance(secret, str) or not secret:
        raise RuntimeError("SnapTrade did not return a user secret")
    user = body.get("userId")
    return {
        "userId": user if isinstance(user, str) and user else user_id,
        "userSecret": secret,
    }


async def delete_snaptrade_user(user_id: str) -> None:
    await _call("authentication.delete_snap_trade_user", user_id=user_id)


def _mapping(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        return body
    if isinstance(body, (bytes, str)):
        text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    if body is None:
        return {}
    mapped: dict[str, Any] = {}
    for key in ("redirectURI", "redirectUri", "loginLink", "userId", "userSecret"):
        value = getattr(body, key, None)
        if value is None and hasattr(body, "get"):
            try:
                value = body.get(key)
            except Exception:  # noqa: BLE001
                value = None
        if isinstance(value, str):
            mapped[key] = value
    return mapped


def portal_redirect_uri(body: Any) -> str | None:
    mapped = _mapping(body)
    for key in ("redirectURI", "redirectUri", "loginLink"):
        value = mapped.get(key)
        if isinstance(value, str) and _is_snaptrade_portal_url(value):
            return value
    return None


def _is_snaptrade_portal_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"https", "http"} and "snaptrade" in host


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
    url = portal_redirect_uri(getattr(response, "body", None))
    if not url:
        raise RuntimeError("SnapTrade did not return a connection portal URL")
    return url


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


ORDER_HISTORY_NOTE = (
    "Broker order records cover the last 90 days, which is the longest range this connection provides. "
    "Older buy and sell rows are account activity, not a second order ticket. Times are stored in UTC."
)


def order_history_note(rows: list[dict[str, Any]]) -> str:
    sources = {str(row.get("source") or "") for row in rows}
    dates = sorted(str(row.get("created_at") or "")[:10] for row in rows if row.get("created_at"))
    span = f" from {dates[0]} through {dates[-1]}" if dates else ""
    if rows and sources == {"activity"}:
        return (
            "The broker’s order endpoint returned no orders for the last 90 days. "
            f"These buy and sell rows are account activity{span}. "
            "A row is not marked filled; the price is the activity price when the broker sent one. "
            "Times are stored in UTC and shown in your local timezone."
        )
    if "activity" in sources:
        return ORDER_HISTORY_NOTE + span + "."
    if not rows:
        return (
            "The broker’s order endpoint returned no orders for the last 90 days, "
            "and account activity had no buy or sell rows."
        )
    return ORDER_HISTORY_NOTE


async def fetch_orders(user_id: str, user_secret: str, account_id: str, *, days: int = 90) -> list[dict[str, Any]]:
    """Read-only orders. SnapTrade's order endpoint accepts at most 90 days."""
    lookback = min(max(int(days), 1), 90)
    response = await _call(
        "account_information.get_user_account_orders",
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret,
        days=lookback,
    )
    orders = [_normalize_order(row) for row in _order_rows(getattr(response, "body", None))]
    activities, _complete = await _paged_activities(user_id, user_secret, account_id)
    return _merge_order_rows(orders, activities)


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


class BrokerHistoryDisabled(Exception):
    """SnapTrade refused account-value history because the add-on is not enabled."""


async def fetch_account_value_history(
    user_id: str, user_secret: str, account_id: str
) -> tuple[float, list[dict[str, Any]], str] | None:
    """Read-only SnapTrade account-value history. None when the broker does not provide it."""
    from app.services.equity_history import broker_value_points

    try:
        response = await _call(
            "account_information.get_account_balance_history",
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
        )
    except ApiException as exc:
        if getattr(exc, "status", None) == 403:
            raise BrokerHistoryDisabled() from exc
        return None
    except Exception:
        return None
    history = _history_rows(getattr(response, "body", None))
    if not history:
        return None
    flows, complete = await _cash_flows(user_id, user_secret, account_id)
    return broker_value_points(history, flows, flows_complete=complete)


def _plain(value: Any) -> Any:
    """Turn SnapTrade model objects into JSON-like values. Unset fields become None."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    type_name = type(value).__name__
    if "Unset" in type_name:
        return None
    if hasattr(value, "keys") and callable(value.keys):
        out: dict[str, Any] = {}
        for key in list(value.keys()):
            try:
                item = value[key]
            except Exception:
                continue
            out[str(key)] = _plain(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
        try:
            return [_plain(item) for item in value]
        except TypeError:
            return str(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _history_rows(body: Any) -> list[dict[str, Any]]:
    raw = _plain(body)
    rows = raw.get("history") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def _paged_activities(
    user_id: str, user_secret: str, account_id: str
) -> tuple[list[dict[str, Any]], bool]:
    """All activity pages the broker returns. The flag is false when a page could not be read."""
    rows_out: list[dict[str, Any]] = []
    offset = 0
    for _page in range(20):
        try:
            response = await _call(
                "account_information.get_account_activities",
                account_id=account_id,
                user_id=user_id,
                user_secret=user_secret,
                offset=offset,
                limit=1000,
            )
        except Exception:
            return rows_out, False
        rows = _activity_rows(getattr(response, "body", None))
        if not rows:
            return rows_out, True
        rows_out.extend(rows)
        if len(rows) < 1000:
            return rows_out, True
        offset += len(rows)
    return rows_out, False


async def _cash_flows(user_id: str, user_secret: str, account_id: str) -> tuple[list[dict[str, Any]], bool]:
    """Contributions and withdrawals. The second flag is false when a page could not be read."""
    rows, complete = await _paged_activities(user_id, user_secret, account_id)
    flows: list[dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("type") or "").upper()
        if kind not in {"CONTRIBUTION", "DEPOSIT", "WITHDRAWAL", "EXTERNAL_ASSET_TRANSFER_IN", "EXTERNAL_ASSET_TRANSFER_OUT"}:
            continue
        flows.append({"t": str(row.get("trade_date") or ""), "type": kind, "amount": row.get("amount")})
    return flows, complete


def _activity_rows(body: Any) -> list[dict[str, Any]]:
    raw = _plain(body)
    if isinstance(raw, dict):
        rows = raw.get("data") or raw.get("activities") or raw.get("results") or []
    else:
        rows = raw
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _order_rows(body: Any) -> list[dict[str, Any]]:
    raw = _plain(body)
    rows: Any = raw
    if isinstance(raw, dict):
        rows = raw.get("orders") or raw.get("data") or raw.get("results") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


DAY_PNL_DISABLED = (
    "Daily P&L is unavailable. The broker’s 1-day return is not enabled on this connection, "
    "and there is no earlier recorded equity to use as a prior close."
)


async def fetch_day_pnl(user_id: str, user_secret: str, account_id: str, total_equity: float) -> tuple[float | None, str | None]:
    try:
        response = await _call(
            "account_information.get_user_account_return_rates",
            account_id=account_id,
            user_id=user_id,
            user_secret=user_secret,
            timeframes="1D",
        )
    except ApiException as exc:
        if getattr(exc, "status", None) == 403:
            return None, DAY_PNL_DISABLED
        return None, "Daily P&L is unavailable from the broker right now."
    except Exception:
        return None, "Daily P&L is unavailable from the broker right now."
    body = _plain(getattr(response, "body", None)) or {}
    rates = body.get("data") if isinstance(body, dict) else body
    if not isinstance(rates, list):
        return None, "Daily P&L is unavailable. The broker did not return a 1-day figure."
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
            return None, "Daily P&L is unavailable. The broker did not return a 1-day percent."
        return float(total_equity) * (float(pct) / 100.0), None
    return None, "Daily P&L is unavailable. The broker did not return a 1-day figure."


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


def _position_expiry(row: dict[str, Any]) -> str | None:
    from app.services.occ_symbol import expiry_iso_from_text

    raw_values: list[Any] = []
    option = row.get("option_symbol")
    if isinstance(option, dict):
        raw_values.extend(
            [
                option.get("expiration_date"),
                option.get("expiry_date"),
                option.get("expiration"),
                option.get("ticker"),
                option.get("symbol"),
            ]
        )
    instrument = row.get("instrument")
    if isinstance(instrument, dict):
        raw_values.append(instrument.get("expiration_date"))
    raw_values.append(_position_symbol(row))
    for raw in raw_values:
        iso = expiry_iso_from_text(raw)
        if iso:
            return iso
    return None


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
        "expiry": _position_expiry(row),
    }


def _optional_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    total_qty = _optional_num(row.get("total_quantity"))
    filled_qty = _optional_num(row.get("filled_quantity"))
    qty = total_qty if total_qty is not None else (filled_qty if filled_qty is not None else 0.0)
    # A limit is not an execution. Leave the fill blank until the broker reports one.
    fill_price = _optional_num(row.get("execution_price"))
    limit_price = _optional_num(row.get("limit_price"))

    status_raw = row.get("status")
    if isinstance(status_raw, dict):
        status = str(status_raw.get("raw") or status_raw.get("description") or "unknown")
    else:
        status = str(status_raw or "unknown")

    order_id = str(row.get("brokerage_order_id") or row.get("id") or "")
    group = row.get("brokerage_group_order_id")
    group_id = str(group) if group else None

    def _fmt_dt(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    time_placed = row.get("time_placed")
    time_executed = row.get("time_executed")

    return {
        "id": order_id or f"order-{symbol}-{time_placed}",
        "symbol": symbol or "—",
        "side": side,
        "qty": qty,
        "filled_qty": filled_qty,
        "order_type": str(row.get("order_type") or "market").lower(),
        "fill_price": fill_price,
        "limit_price": limit_price,
        "status": status,
        "asset_class": "us_option" if option else "us_equity",
        "created_at": _fmt_dt(time_placed),
        "filled_at": _fmt_dt(time_executed),
        "group_id": group_id,
        "source": "order",
    }


def _activity_as_order(row: dict[str, Any]) -> dict[str, Any] | None:
    row = _plain(row)
    if not isinstance(row, dict):
        return None
    kind = str(row.get("type") or "").upper()
    if "BUY" not in kind and "SELL" not in kind:
        return None
    symbol = ""
    universal = row.get("symbol")
    if isinstance(universal, dict):
        symbol = str(universal.get("symbol") or universal.get("raw_symbol") or "")
    elif isinstance(universal, str):
        symbol = universal
    option = row.get("option_symbol")
    if isinstance(option, dict):
        symbol = str(option.get("ticker") or option.get("symbol") or symbol)
    price = _optional_num(row.get("price"))
    units = _optional_num(row.get("units"))
    qty = abs(units) if units is not None else 0.0
    activity_id = str(row.get("id") or row.get("external_reference_id") or "")
    when = row.get("trade_date")
    when_s = when.isoformat() if isinstance(when, datetime) else (str(when) if when else None)
    return {
        "id": activity_id or f"activity-{symbol}-{when_s}",
        "symbol": symbol or "—",
        "side": "sell" if "SELL" in kind else "buy",
        "qty": qty,
        "filled_qty": qty if price is not None else None,
        "order_type": "activity",
        "fill_price": price,
        "limit_price": None,
        "status": kind,
        "asset_class": "us_option" if isinstance(option, dict) else "us_equity",
        "created_at": when_s,
        "filled_at": when_s if price is not None else None,
        "group_id": None,
        "source": "activity",
        "external_reference_id": str(row.get("external_reference_id") or ""),
    }


def _merge_order_rows(orders: list[dict[str, Any]], activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep broker orders, then older activity trades that are not the same ticket."""
    seen = {str(row.get("id") or "") for row in orders}
    merged = list(orders)
    for raw in activities:
        mapped = _activity_as_order(raw)
        if mapped is None:
            continue
        ref = str(mapped.pop("external_reference_id", "") or "")
        if mapped["id"] in seen or (ref and ref in seen):
            continue
        if any(_same_trade(mapped, existing) for existing in orders):
            continue
        seen.add(mapped["id"])
        merged.append(mapped)
    merged.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return merged


def _same_trade(activity: dict[str, Any], order: dict[str, Any]) -> bool:
    if activity.get("symbol") != order.get("symbol") or activity.get("side") != order.get("side"):
        return False
    if activity.get("qty") != order.get("qty"):
        return False
    left = str(activity.get("created_at") or "")[:10]
    right = str(order.get("created_at") or order.get("filled_at") or "")[:10]
    return bool(left) and left == right


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
