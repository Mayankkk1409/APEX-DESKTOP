"""Rebuild brokerage equity from positions, cash, activity, and session closes.

SnapTrade's account-value history is often disabled. When the activity list is
complete, holdings can be walked back to the first returned activity and marked
with real closing prices. A split's amount is the share value, not extra cash.
Deposits and withdrawals are kept out of P&L.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.daily_pnl import closes_by_session

_NY = ZoneInfo("America/New_York")
_SHARE = {"BUY", "SELL", "REI", "SPLIT"}
_CASH = {
    "BUY",
    "SELL",
    "REI",
    "DIVIDEND",
    "CONTRIBUTION",
    "DEPOSIT",
    "WITHDRAWAL",
    "ADJUSTMENT",
    "EXTERNAL_ASSET_TRANSFER_IN",
    "EXTERNAL_ASSET_TRANSFER_OUT",
}
_EXTERNAL = {
    "CONTRIBUTION",
    "DEPOSIT",
    "WITHDRAWAL",
    "EXTERNAL_ASSET_TRANSFER_IN",
    "EXTERNAL_ASSET_TRANSFER_OUT",
}
_DEPOSIT = {"CONTRIBUTION", "DEPOSIT", "EXTERNAL_ASSET_TRANSFER_IN"}


def activity_symbol(row: dict[str, Any]) -> str:
    raw = row.get("symbol")
    if isinstance(raw, dict):
        return str(raw.get("raw_symbol") or raw.get("symbol") or "").upper()
    if isinstance(raw, str):
        return raw.upper()
    return ""


def _day(value: Any) -> date | None:
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _kind(row: dict[str, Any]) -> str:
    return str(row.get("type") or "").upper()


def _amount(row: dict[str, Any]) -> float:
    try:
        return float(row.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0


def _units(row: dict[str, Any]) -> float:
    try:
        return float(row.get("units") or 0)
    except (TypeError, ValueError):
        return 0.0


def cash_delta(row: dict[str, Any]) -> float:
    """Cash impact. Split amounts are the value of the new shares, not cash."""
    if _kind(row) not in _CASH:
        return 0.0
    return _amount(row)


def share_delta(row: dict[str, Any]) -> tuple[str, float] | None:
    if _kind(row) not in _SHARE:
        return None
    symbol = activity_symbol(row)
    units = _units(row)
    if not symbol or units == 0.0:
        return None
    return symbol, units


def external_flow(row: dict[str, Any]) -> float:
    """Deposits positive, withdrawals negative. Everything else is not a cash flow."""
    kind = _kind(row)
    if kind not in _EXTERNAL:
        return 0.0
    amount = abs(_amount(row))
    if kind in _DEPOSIT:
        return amount
    return -amount


def opening_state(
    cash: float,
    positions: dict[str, float],
    activities: list[dict[str, Any]],
) -> tuple[float, dict[str, float]]:
    """Holdings and cash before the first activity, reversed from the broker's current book."""
    qty = {symbol: float(quantity) for symbol, quantity in positions.items()}
    balance = float(cash)
    ordered = sorted(activities, key=lambda row: str(row.get("trade_date") or ""), reverse=True)
    for row in ordered:
        share = share_delta(row)
        if share:
            symbol, units = share
            qty[symbol] = qty.get(symbol, 0.0) - units
        balance -= cash_delta(row)
    return balance, {symbol: quantity for symbol, quantity in qty.items() if abs(quantity) > 1e-8}


def _state_on(
    opening_cash: float,
    opening_qty: dict[str, float],
    activities: list[dict[str, Any]],
    day: date,
) -> tuple[float, dict[str, float]]:
    cash = opening_cash
    qty = dict(opening_qty)
    for row in activities:
        when = _day(row.get("trade_date"))
        if when is None or when > day:
            continue
        share = share_delta(row)
        if share:
            symbol, units = share
            qty[symbol] = qty.get(symbol, 0.0) + units
        cash += cash_delta(row)
    return cash, {symbol: quantity for symbol, quantity in qty.items() if abs(quantity) > 1e-8}


def trade_marks(activities: list[dict[str, Any]]) -> dict[str, dict[date, float]]:
    """Prices the broker recorded on buys, sells, and reinvestments."""
    marks: dict[str, dict[date, float]] = {}
    for row in activities:
        if _kind(row) not in {"BUY", "SELL", "REI"}:
            continue
        symbol = activity_symbol(row)
        day = _day(row.get("trade_date"))
        try:
            price = float(row.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if not symbol or day is None or price <= 0:
            continue
        marks.setdefault(symbol, {})[day] = price
    return marks


def _price(
    closes: dict[str, dict[date, float]],
    trades: dict[str, dict[date, float]],
    symbol: str,
    day: date,
) -> tuple[float | None, bool]:
    """Return a price and whether it came from a trade instead of a daily close."""
    series = closes.get(symbol) or {}
    if day in series:
        return series[day], False
    prior = [stamp for stamp in series if stamp < day and (day - stamp).days <= 10]
    if prior:
        return series[max(prior)], False
    booked = trades.get(symbol) or {}
    if day in booked:
        return booked[day], True
    earlier = [stamp for stamp in booked if stamp < day]
    if earlier:
        return booked[max(earlier)], True
    return None, False


def _sessions(closes: dict[str, dict[date, float]], start: date, end: date) -> list[date]:
    found: set[date] = set()
    for series in closes.values():
        for stamp in series:
            if start <= stamp <= end and stamp.weekday() < 5:
                found.add(stamp)
    return sorted(found)


def rebuild_equity_points(
    *,
    cash: float,
    equity: float,
    positions: dict[str, float],
    activities: list[dict[str, Any]],
    closes: dict[str, dict[date, float]],
    as_of: date,
    trades: dict[str, dict[date, float]] | None = None,
) -> tuple[float, list[dict[str, Any]], str, float | None, float | None]:
    """Return starting value, points, note, daily P&L, and daily percent.

    Daily P&L is the latest session's account-value change after deposits and
    withdrawals that session. Overall P&L on each point uses the same exclusion
    since the first plotted session.
    """
    dated = [row for row in activities if _day(row.get("trade_date"))]
    if not dated:
        return 0.0, [], "No brokerage activity was available to build a history.", None, None
    first_activity = min(_day(row.get("trade_date")) for row in dated if _day(row.get("trade_date")))
    opening_cash, opening_qty = opening_state(cash, positions, dated)
    booked = trades if trades is not None else trade_marks(dated)
    extra_days = {
        day
        for by_symbol in booked.values()
        for day in by_symbol
        if first_activity <= day <= as_of and day.weekday() < 5
    }
    sessions = sorted(set(_sessions(closes, first_activity, as_of)) | extra_days)
    points: list[dict[str, Any]] = []
    skipped = 0
    used_trade_price = False
    for session in sessions:
        balance, qty = _state_on(opening_cash, opening_qty, dated, session)
        value = balance
        missing = False
        for symbol, quantity in qty.items():
            price, from_trade = _price(closes, booked, symbol, session)
            if price is None:
                missing = True
                break
            if from_trade:
                used_trade_price = True
            value += quantity * price
        if missing:
            skipped += 1
            continue
        points.append(
            {
                "t": datetime(session.year, session.month, session.day, 16, 0, tzinfo=_NY).isoformat(),
                "portfolio_value": round(value, 2),
                "balance": round(balance, 2),
                "cumulative_pl": None,
                "_day": session,
            }
        )
    if not points:
        return 0.0, [], "Closing prices were not available for the holdings in this account.", None, None

    first_day: date = points[0]["_day"]
    first_value = float(points[0]["portfolio_value"])
    for point in points:
        session = point.pop("_day")
        flows = _flows_between(dated, first_day, session)
        point["cumulative_pl"] = round(float(point["portfolio_value"]) - first_value - flows, 2)

    # When the last plotted session is the current one, its value is the broker's equity.
    # Cash moved after that close is not profit. An older last session is left as marked.
    last_session = date.fromisoformat(str(points[-1]["t"])[:10])
    pinned = False
    if (as_of - last_session).days <= 5:
        pinned = True
        flows_since_close = _flows_between(dated, last_session, as_of)
        delta = float(equity) - float(points[-1]["portfolio_value"])
        points[-1]["portfolio_value"] = round(float(equity), 2)
        points[-1]["cumulative_pl"] = round(float(points[-1]["cumulative_pl"]) + delta - flows_since_close, 2)

    day_pnl = None
    day_pct = None
    if len(points) >= 2:
        prior = float(points[-2]["portfolio_value"])
        latest = float(points[-1]["portfolio_value"])
        prior_day = date.fromisoformat(str(points[-2]["t"])[:10])
        day_pnl = round(latest - prior - _flows_between(dated, prior_day, as_of), 2)
        if prior:
            day_pct = round(day_pnl / prior * 100.0, 4)

    start = str(points[0]["t"])[:10]
    end = last_session.isoformat()
    note = (
        f"Account value from {start} through {end}, rebuilt from this account’s positions, cash, "
        "and activity, marked at each session close. "
        f"The broker’s activity begins {first_activity.isoformat()}, so this is not an account-opening history. "
        "P&L excludes deposits and withdrawals."
    )
    if pinned:
        note += " The latest point is the broker’s current equity."
    if skipped:
        note += f" {skipped} sessions were left out because a holding had no closing price."
    if used_trade_price:
        note += " Where a daily close was missing, the last brokerage trade price was used."
    return round(first_value, 2), points, note, day_pnl, day_pct


def _flows_between(activities: list[dict[str, Any]], after: date, through: date) -> float:
    """External cash after `after` and through `through`. The baseline day is excluded."""
    total = 0.0
    for row in activities:
        when = _day(row.get("trade_date"))
        if when is None or when <= after or when > through:
            continue
        total += external_flow(row)
    return total


_SERIES_TTL_SECONDS = 180.0
_series_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


async def cached_activity_series(
    adapter: Any,
    *,
    user_id: str,
    user_secret: str,
    account_id: str,
) -> dict[str, Any] | None:
    """Equity curve, overall P&L, and daily P&L for one brokerage account."""
    now = time.monotonic()
    cached = _series_cache.get(account_id)
    if cached and now - cached[0] < _SERIES_TTL_SECONDS:
        return cached[1]
    built = await _activity_series(adapter, user_id=user_id, user_secret=user_secret, account_id=account_id)
    _series_cache[account_id] = (now, built)
    return built


async def _activity_series(
    adapter: Any,
    *,
    user_id: str,
    user_secret: str,
    account_id: str,
) -> dict[str, Any] | None:
    from app.services import snaptrade as st

    balance = await st.fetch_balance(user_id, user_secret, account_id)
    positions = await st.fetch_positions(user_id, user_secret, account_id)
    activities, complete = await st._paged_activities(user_id, user_secret, account_id)
    if not complete or not activities:
        return None
    held: dict[str, float] = {}
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        held[symbol] = held.get(symbol, 0.0) + float(row.get("quantity") or 0)
    symbols = set(held)
    for row in activities:
        symbol = activity_symbol(row)
        if symbol:
            symbols.add(symbol)
    days = [_day(row.get("trade_date")) for row in activities]
    dated = [day for day in days if day is not None]
    if not dated:
        return None
    as_of = datetime.now(_NY).date()
    closes = await load_closes(adapter, sorted(symbols), min(dated), as_of)
    starting, points, note, day_pnl, day_pct = rebuild_equity_points(
        cash=float(balance.get("cash_balance") or 0),
        equity=float(balance.get("total_equity") or 0),
        positions=held,
        activities=activities,
        closes=closes,
        as_of=as_of,
    )
    if not points:
        return None
    return {
        "starting": starting,
        "points": points,
        "note": note,
        "day_pnl": day_pnl,
        "day_pnl_percent": day_pct,
        "overall_pnl": points[-1].get("cumulative_pl"),
    }


async def load_closes(adapter: Any, symbols: list[str], start: date, end: date) -> dict[str, dict[date, float]]:
    async def one(symbol: str) -> tuple[str, list]:
        fn = getattr(adapter, "vendor_daily_bars", None)
        if fn is None:
            return symbol, []
        try:
            bars = await fn(symbol, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
        except Exception:
            return symbol, []
        return symbol, bars if isinstance(bars, list) else []

    rows = await asyncio.gather(*(one(symbol) for symbol in symbols))
    out: dict[str, dict[date, float]] = {}
    missing: list[str] = []
    for symbol, bars in rows:
        series = closes_by_session(bars)
        out[symbol] = series
        if not series:
            missing.append(symbol)
    if missing:
        from app.services.live_quotes import yahoo_ohlc_bars

        for symbol in missing:
            await asyncio.sleep(0.4)
            try:
                bars = await yahoo_ohlc_bars(symbol, "1D", 1000)
            except Exception:
                bars = []
            out[symbol] = closes_by_session(bars if isinstance(bars, list) else [])
    return out
