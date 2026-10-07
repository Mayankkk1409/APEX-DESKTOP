"""Day-by-day P&L for open positions from real session marks.

A session is marked only when this session and the prior session both have a
price. A weekday with no feed price stays in the series as unavailable.
Nothing here fills a gap with a made-up close.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.models.trading import Position
from app.services.occ_symbol import parse_occ

_NY = ZoneInfo("America/New_York")
_CENT = Decimal("0.01")


def _money(amount: Decimal) -> float:
    return float(amount.quantize(_CENT, rounding=ROUND_HALF_UP))


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


def session_date(raw: object) -> date | None:
    """Session date for a vendor bar timestamp. Date-only strings stay as written."""
    if raw is None:
        return None
    text = str(raw).strip()
    if len(text) < 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        if "T" not in text and " " not in text:
            return date.fromisoformat(text[:10])
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_NY).date()


def closes_by_session(bars: list[dict]) -> dict[date, float]:
    """Last positive close per session. Bars without a close are skipped."""
    out: dict[date, float] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        session = session_date(bar.get("t"))
        raw = bar.get("c")
        if session is None or raw is None:
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out[session] = price
    return out


def _roll_to_weekday(day: date, *, end: date) -> date:
    cursor = day
    while cursor.weekday() >= 5 and cursor <= end:
        cursor += timedelta(days=1)
    return cursor


def _sessions(start: date, end: date) -> list[date]:
    cursor = _roll_to_weekday(start, end=end)
    days: list[date] = []
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _previous_weekday(day: date) -> date:
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def _opened_session(created_at: datetime | None, as_of: date) -> date:
    if created_at is None:
        return as_of
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    opened = created_at.astimezone(_NY).date()
    if opened > as_of:
        return as_of
    return opened


def position_daily_pnl(
    *,
    opened_on: date,
    as_of: date,
    avg_cost: float,
    qty: float,
    multiplier: int,
    closes: dict[date, float],
    live_mark: float | None = None,
) -> list[dict]:
    """One row per weekday from the open session through ``as_of``.

    Entry session P&L is mark minus the fill (``avg_cost``). Later sessions
    need that session's mark and the previous weekday's close. A missing
    price leaves ``pnl`` null and ``status`` ``unavailable``.
    """
    start = opened_on if opened_on <= as_of else as_of
    days = _sessions(start, as_of)
    if not days:
        return []
    entry = days[0]
    rows: list[dict] = []
    for day in days:
        mark = live_mark if day == as_of and live_mark is not None else closes.get(day)
        if day == entry:
            prior = avg_cost
        else:
            prior = closes.get(_previous_weekday(day))
        if mark is None or prior is None:
            rows.append({"date": day.isoformat(), "pnl": None, "status": "unavailable"})
            continue
        pnl = _money((_dec(mark) - _dec(prior)) * _dec(qty) * Decimal(multiplier))
        rows.append({"date": day.isoformat(), "pnl": pnl, "status": "marked"})
    return rows


def book_daily_pnl(series: list[list[dict]]) -> list[dict]:
    """Sum position days. A date is unavailable when any open position lacks a mark."""
    by_date: dict[str, list[float | None]] = {}
    for days in series:
        for row in days:
            key = str(row.get("date") or "")
            if not key:
                continue
            pnl = row.get("pnl")
            status = row.get("status")
            if status != "marked" or pnl is None:
                by_date.setdefault(key, []).append(None)
            else:
                by_date.setdefault(key, []).append(float(pnl))
    book: list[dict] = []
    for key in sorted(by_date):
        vals = by_date[key]
        if any(v is None for v in vals):
            book.append({"date": key, "pnl": None, "status": "unavailable"})
            continue
        total = sum((Decimal(str(v)) for v in vals if v is not None), Decimal(0))
        book.append({"date": key, "pnl": _money(total), "status": "marked"})
    return book


def _usable_live_mark(symbol: str, quote: Any) -> float | None:
    """A live mark only. Demo and unavailable quotes are not a price."""
    if quote is None:
        return None
    status = str(getattr(quote, "status", "") or "").lower()
    source = str(getattr(quote, "source", "") or "").lower()
    if status == "unavailable" or source in {"demo", "unavailable"} or "demo" in source:
        return None
    if parse_occ(symbol) is not None:
        asset = str(getattr(quote, "asset_class", "") or "").lower()
        if asset not in {"us_option", "option"}:
            return None
    raw = getattr(quote, "price", None)
    if raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


async def _vendor_bars(adapter: Any, symbol: str, start: date, end: date) -> list[dict]:
    fn = getattr(adapter, "vendor_daily_bars", None)
    if not callable(fn):
        return []
    try:
        rows = await fn(symbol, start=start.isoformat(), end=end.isoformat())
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


async def _live_mark(adapter: Any, symbol: str) -> float | None:
    quote_fn = getattr(adapter, "quote", None)
    if not callable(quote_fn):
        return None
    try:
        quote = await quote_fn(symbol)
    except Exception:
        return None
    return _usable_live_mark(symbol, quote)


async def assemble_daily_pnl(
    positions: list[Position],
    adapter: Any,
    *,
    as_of: date | None = None,
) -> dict:
    """Daily series for each open position and the book. No synthetic prices."""
    today = as_of or datetime.now(_NY).date()
    rows: list[dict] = []
    for pos in positions:
        if pos.qty == 0:
            continue
        opened = _opened_session(pos.created_at, today)
        bars = await _vendor_bars(adapter, pos.symbol, opened, today)
        closes = closes_by_session(bars)
        live = await _live_mark(adapter, pos.symbol)
        days = position_daily_pnl(
            opened_on=opened,
            as_of=today,
            avg_cost=float(pos.avg_cost),
            qty=float(pos.qty),
            multiplier=int(pos.multiplier),
            closes=closes,
            live_mark=live,
        )
        rows.append({"id": pos.id, "symbol": pos.symbol, "days": days})
    return {"positions": rows, "book": book_daily_pnl([row["days"] for row in rows])}
