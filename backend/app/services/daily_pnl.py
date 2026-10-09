"""Day-by-day P&L for open positions from real session marks.

A session is marked only when this session and the prior session both have a
price. Entry day uses the fill. Later days are close to close. A weekday with
no price stays unavailable for that position. The book still sums every
position that does have a mark.
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from app.models.trading import Position
from app.services.occ_symbol import parse_occ

_NY = ZoneInfo("America/New_York")
_CENT = Decimal("0.01")
# Daily closes do not tick. A short process cache keeps a desk refresh from
# repeating the Yahoo/Alpaca history round trip for every position.
_CLOSE_TTL_SECONDS = 60.0
_close_cache: dict[str, tuple[float, dict[date, float]]] = {}
_close_inflight: dict[str, asyncio.Task[dict[date, float]]] = {}


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
    avg_cost: float | None,
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
            prior = avg_cost if avg_cost is not None and avg_cost > 0 else None
        else:
            prior = closes.get(_previous_weekday(day))
        if mark is None or prior is None:
            rows.append({"date": day.isoformat(), "pnl": None, "status": "unavailable"})
            continue
        pnl = _money((_dec(mark) - _dec(prior)) * _dec(qty) * Decimal(multiplier))
        rows.append({"date": day.isoformat(), "pnl": pnl, "status": "marked"})
    return rows


def book_daily_pnl(series: list[list[dict]]) -> list[dict]:
    """Sum marked position days. A date is unavailable only when none of them have a price."""
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
        marked = [v for v in by_date[key] if v is not None]
        if not marked:
            book.append({"date": key, "pnl": None, "status": "unavailable"})
            continue
        total = sum((Decimal(str(v)) for v in marked), Decimal(0))
        book.append({"date": key, "pnl": _money(total), "status": "marked"})
    return book


def bars_from_option_snapshot(payload: Any, symbol: str) -> list[dict]:
    """Session closes from one Alpaca option snapshot.

    Indicative snapshots publish ``prevDailyBar`` and ``dailyBar`` when the
    OPRA history feed does not. A latest trade or quote fills today only when
    those bars are absent. Empty when the payload has no positive price.
    """
    if not isinstance(payload, dict):
        return []
    snaps = payload.get("snapshots")
    if not isinstance(snaps, dict):
        return []
    wanted = symbol.upper()
    row = snaps.get(wanted) or snaps.get(symbol)
    if not isinstance(row, dict) and len(snaps) == 1:
        row = next(iter(snaps.values()))
    if not isinstance(row, dict):
        return []
    out: list[dict] = []
    sessions: set[date] = set()
    for key in ("prevDailyBar", "dailyBar"):
        bar = row.get(key)
        if not isinstance(bar, dict):
            continue
        px = _positive_price(bar.get("c"))
        ts = bar.get("t")
        session = session_date(ts)
        if px is None or session is None:
            continue
        out.append({"t": ts, "c": px})
        sessions.add(session)
    trade = row.get("latestTrade") if isinstance(row.get("latestTrade"), dict) else {}
    quote = row.get("latestQuote") if isinstance(row.get("latestQuote"), dict) else {}
    px = _positive_price(trade.get("p"))
    ts = trade.get("t")
    if px is None:
        bid = _positive_price(quote.get("bp"))
        ask = _positive_price(quote.get("ap"))
        if bid is not None and ask is not None:
            px = (bid + ask) / 2.0
        else:
            px = bid if bid is not None else ask
        ts = quote.get("t")
    session = session_date(ts)
    if px is not None and session is not None and session not in sessions:
        out.append({"t": ts, "c": px})
    return out


def _positive_price(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return price


def _synthetic_option_mark(symbol: str, price: float, when: datetime | None = None) -> bool:
    """True when a stored option price is the internal demo generator, not a fill or quote."""
    if parse_occ(symbol) is None:
        return False
    from app.adapters.demo import _price_at

    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    synthetic = float(_price_at(symbol.upper(), moment.astimezone(timezone.utc)))
    # Fills land on the demo bid or ask, about 0.1% off the generator mid.
    return abs(price - synthetic) <= max(0.05, abs(synthetic) * 0.002)


def entry_basis(pos: Position) -> float | None:
    """Fill used as the entry-day baseline. A demo generator fill is not a price."""
    price = _positive_price(getattr(pos, "avg_cost", None))
    if price is None or _synthetic_option_mark(pos.symbol, price, getattr(pos, "created_at", None)):
        return None
    return price


def position_stored_mark(pos: Position) -> float | None:
    """Last quote already on the position. Demo generator prices are not a mark."""
    price = _positive_price(getattr(pos, "current_price", None))
    if price is None:
        try:
            qty = float(pos.qty)
            mult = int(getattr(pos, "multiplier", 1) or 1)
        except (TypeError, ValueError):
            qty, mult = 0.0, 1
        market_value = getattr(pos, "market_value", None)
        if qty != 0 and mult and market_value is not None:
            try:
                derived = float(market_value) / (qty * mult)
            except (TypeError, ValueError, ZeroDivisionError):
                derived = None
            if derived is not None and derived > 0:
                price = derived
    if price is None or _synthetic_option_mark(pos.symbol, price):
        return None
    return price


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
    return _positive_price(getattr(quote, "price", None))


def _quote_previous_close(price: float, quote: Any) -> float | None:
    """Previous close published on the quote. Not derived from a fill."""
    explicit = getattr(quote, "prev_close", None)
    if explicit is None:
        explicit = getattr(quote, "previous_close", None)
    prev = _positive_price(explicit)
    if prev is not None:
        return prev
    change = getattr(quote, "change", None)
    if change is None:
        return None
    try:
        prev = price - float(change)
    except (TypeError, ValueError):
        return None
    return prev if prev > 0 else None


async def _vendor_bars(adapter: Any, symbol: str, start: date, end: date) -> list[dict]:
    fn = getattr(adapter, "vendor_daily_bars", None)
    if not callable(fn):
        return []
    try:
        rows = await fn(symbol, start=start.isoformat(), end=end.isoformat())
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


async def _prefetch_option_bars(adapter: Any, symbols: list[str]) -> dict[str, list[dict]]:
    """One options-snapshot read for the book. Missing method means per-symbol bars."""
    fn = getattr(adapter, "option_snapshot_bars", None)
    if not callable(fn) or not symbols:
        return {}
    try:
        rows = await fn(symbols)
    except Exception:
        return {}
    if not isinstance(rows, dict):
        return {}
    out: dict[str, list[dict]] = {}
    for key, bars in rows.items():
        if isinstance(bars, list) and bars:
            out[str(key).upper()] = bars
    return out


async def _live_quote(adapter: Any, symbol: str) -> Any:
    """Equity quote only. An OCC symbol is not a stock snapshot."""
    if parse_occ(symbol) is not None:
        return None
    quote_fn = getattr(adapter, "quote", None)
    if not callable(quote_fn):
        return None
    try:
        return await quote_fn(symbol)
    except Exception:
        return None


def _fill_gaps(closes: dict[date, float], *, today: date, price: float | None, previous: float | None) -> None:
    """Write a known mark only into a session that has none."""
    if previous is not None:
        closes.setdefault(_previous_weekday(today), previous)
    if price is not None:
        closes.setdefault(today, price)


def _carry_last_close(closes: dict[date, float], today: date) -> None:
    """After the close, a session with no new print stays at the prior session's close."""
    if closes.get(today) is not None:
        return
    prev = _previous_weekday(today)
    last = closes.get(prev)
    if last is not None:
        closes[today] = last


def clear_daily_mark_cache() -> None:
    """Drop in-process session closes. Tests use this so one case cannot feed the next."""
    _close_cache.clear()
    _close_inflight.clear()


def _cache_key(symbol: str, today: date) -> str:
    return f"{symbol.upper()}|{today.isoformat()}"


def _cached_closes(symbol: str, today: date) -> dict[date, float] | None:
    key = _cache_key(symbol, today)
    hit = _close_cache.get(key)
    if hit is None:
        return None
    stored_at, closes = hit
    if time.monotonic() - stored_at > _CLOSE_TTL_SECONDS:
        _close_cache.pop(key, None)
        return None
    return dict(closes)


def _remember_closes(symbol: str, today: date, closes: dict[date, float]) -> None:
    if not closes:
        return
    _close_cache[_cache_key(symbol, today)] = (time.monotonic(), dict(closes))


def cached_mark(symbol: str, *, as_of: date | None = None) -> float | None:
    """Today's cached session close, when a recent daily P&L build stored one."""
    today = as_of or datetime.now(_NY).date()
    closes = _cached_closes(symbol, today)
    if not closes:
        return None
    price = closes.get(today)
    if price is None or price <= 0:
        return None
    return price


def _cached_quote(symbol: str, price: float) -> SimpleNamespace:
    option = parse_occ(symbol) is not None
    return SimpleNamespace(
        price=price,
        change=None,
        change_pct=None,
        status="live",
        source="session close",
        asset_class="us_option" if option else "us_equity",
    )


async def quotes_for_positions(positions: list[Any], adapter: Any) -> list[Any]:
    """One quote per position. A fresh cached close skips another vendor round trip.

    Symbols without a cached close are requested together.
    """
    if not positions:
        return []
    needed: list[tuple[int, Any]] = []
    out: list[Any] = [None] * len(positions)
    for index, pos in enumerate(positions):
        mark = cached_mark(getattr(pos, "symbol", ""))
        if mark is not None:
            out[index] = _cached_quote(str(pos.symbol), mark)
        else:
            needed.append((index, pos))
    if needed:
        live = await asyncio.gather(*(adapter.quote(pos.symbol) for _, pos in needed))
        for (index, _), quote in zip(needed, live):
            out[index] = quote
    return out


async def _fetch_closes(
    *,
    symbol: str,
    opened: date,
    today: date,
    stored_mark: float | None,
    adapter: Any,
    prefetched: dict[str, list[dict]],
) -> dict[date, float]:
    bars = prefetched.get(symbol)
    if not bars:
        bars = await _vendor_bars(adapter, symbol, opened, today)
    closes = closes_by_session(bars)
    need_today = closes.get(today) is None
    need_prior = opened < today and _previous_weekday(today) not in closes
    if need_today or need_prior:
        quote = await _live_quote(adapter, symbol)
        live = _usable_live_mark(symbol, quote)
        previous = _quote_previous_close(live, quote) if live is not None and quote is not None else None
        _fill_gaps(closes, today=today, price=live, previous=previous if need_prior else None)
    if closes.get(today) is None:
        _fill_gaps(closes, today=today, price=stored_mark, previous=None)
    if opened < today:
        _carry_last_close(closes, today)
    if closes:
        _remember_closes(symbol, today, closes)
    return closes


async def _closes_for_symbol(
    *,
    symbol: str,
    opened: date,
    today: date,
    stored_mark: float | None,
    adapter: Any,
    prefetched: dict[str, list[dict]],
) -> dict[date, float]:
    key = _cache_key(symbol, today)
    cached = _cached_closes(symbol, today)
    if cached is not None:
        return cached
    inflight = _close_inflight.get(key)
    if inflight is not None:
        return dict(await inflight)
    task = asyncio.create_task(
        _fetch_closes(
            symbol=symbol,
            opened=opened,
            today=today,
            stored_mark=stored_mark,
            adapter=adapter,
            prefetched=prefetched,
        )
    )
    _close_inflight[key] = task
    try:
        return dict(await task)
    finally:
        if _close_inflight.get(key) is task:
            _close_inflight.pop(key, None)


async def assemble_daily_pnl(
    positions: list[Position],
    adapter: Any,
    *,
    as_of: date | None = None,
) -> dict:
    """Daily series for each open position and the book. No synthetic prices."""
    today = as_of or datetime.now(_NY).date()
    open_positions = [pos for pos in positions if pos.qty != 0]
    prepared = [
        {
            "id": pos.id,
            "symbol": pos.symbol,
            "key": pos.symbol.upper(),
            "opened": _opened_session(pos.created_at, today),
            "qty": float(pos.qty),
            "multiplier": int(pos.multiplier),
            "avg_cost": entry_basis(pos),
            "stored": position_stored_mark(pos),
            "option": parse_occ(pos.symbol) is not None,
        }
        for pos in open_positions
    ]
    missing_options = [
        item["symbol"] for item in prepared if item["option"] and _cached_closes(item["key"], today) is None
    ]
    prefetch = asyncio.create_task(_prefetch_option_bars(adapter, missing_options)) if missing_options else None

    async def one(item: dict) -> dict[date, float]:
        if _cached_closes(item["key"], today) is not None:
            snaps: dict[str, list[dict]] = {}
        else:
            snaps = await prefetch if prefetch is not None and item["option"] else {}
        return await _closes_for_symbol(
            symbol=item["key"],
            opened=item["opened"],
            today=today,
            stored_mark=item["stored"],
            adapter=adapter,
            prefetched=snaps,
        )

    closes_list = await asyncio.gather(*(one(item) for item in prepared))
    rows: list[dict] = []
    for item, closes in zip(prepared, closes_list):
        days = position_daily_pnl(
            opened_on=item["opened"],
            as_of=today,
            avg_cost=item["avg_cost"],
            qty=item["qty"],
            multiplier=item["multiplier"],
            closes=closes,
        )
        rows.append({"id": item["id"], "symbol": item["symbol"], "days": days})
    return {"positions": rows, "book": book_daily_pnl([row["days"] for row in rows])}
