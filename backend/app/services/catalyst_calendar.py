"""Catalyst / event calendar from live public + Alpaca sources only.

Sources (each event is labeled with ``source`` + ``as_of`` / event time):
  * NASDAQ Earnings Calendar — ticker matches + broader market
  * NASDAQ Economic Events — United States macro prints / Fed speakers
  * Alpaca Corporate Actions — dividends, splits, mergers for the ticker

Never fabricates dates. Empty lists are honest "no live events returned".
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.config import Settings
from app.services.live_quotes import _http_json

NASDAQ_HEADERS = {
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

_CACHE_TTL = 900.0
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

_US_COUNTRIES = {"united states", "usa", "us", "u.s.", "u.s.a."}
#: Macro names that matter for equity options vol (keep the board readable).
_MACRO_KEEP = re.compile(
    r"FOMC|Fed |CPI|PCE|Nonfarm|NFP|Unemployment|GDP|ISM|PPI|Retail Sales|"
    r"Jobless|Treasury|Jackson Hole|Interest Rate|Core CPI|Core PCE|"
    r"Initial Claims|ADP|Beige Book|Consumer Confidence|Durable Goods",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_html(text: str | None) -> str:
    if not text:
        return ""
    t = re.sub(r"<[^>]+>", " ", text)
    t = t.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&#039;", "'")
    return re.sub(r"\s+", " ", t).strip()


def _parse_nasdaq_time(raw: str | None) -> str:
    if not raw:
        return "unspecified"
    mapping = {
        "time-pre-market": "pre-market",
        "time-after-hours": "after-hours",
        "time-not-supplied": "unspecified",
    }
    return mapping.get(raw, raw.replace("time-", "").replace("-", " "))


async def _nasdaq_earnings_day(day: date) -> list[dict[str, Any]]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/calendar/earnings?date={day.isoformat()}",
        headers=NASDAQ_HEADERS,
        timeout=10.0,
    )
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    out: list[dict[str, Any]] = []
    fetched = _now_iso()
    for row in rows:
        sym = (row.get("symbol") or "").upper()
        if not sym:
            continue
        out.append(
            {
                "id": f"earn-{sym}-{day.isoformat()}",
                "scope": "ticker",
                "kind": "earnings",
                "symbol": sym,
                "title": f"{sym} earnings",
                "detail": (
                    f"{row.get('name') or sym} · fiscal {row.get('fiscalQuarterEnding') or '—'} · "
                    f"EPS est. {row.get('epsForecast') or '—'}"
                ),
                "event_date": day.isoformat(),
                "event_time": _parse_nasdaq_time(row.get("time")),
                "source": "NASDAQ Earnings Calendar",
                "as_of": fetched,
            }
        )
    return out


async def _nasdaq_econ_day(day: date) -> list[dict[str, Any]]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/calendar/economicevents?date={day.isoformat()}",
        headers=NASDAQ_HEADERS,
        timeout=10.0,
    )
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    fetched = _now_iso()
    out: list[dict[str, Any]] = []
    for row in rows:
        country = (row.get("country") or "").strip()
        if country.lower() not in _US_COUNTRIES:
            continue
        name = _clean_html(row.get("eventName"))
        if not name or not _MACRO_KEEP.search(name):
            continue
        consensus = _clean_html(row.get("consensus")) or "—"
        previous = _clean_html(row.get("previous")) or "—"
        gmt = (row.get("gmt") or "").strip() or "—"
        out.append(
            {
                "id": f"macro-{day.isoformat()}-{gmt}-{name}",
                "scope": "market",
                "kind": "macro",
                "symbol": None,
                "title": name,
                "detail": f"Consensus {consensus} · prior {previous}",
                "event_date": day.isoformat(),
                "event_time": f"{gmt} GMT" if gmt != "—" else "unspecified",
                "source": "NASDAQ Economic Calendar",
                "as_of": fetched,
            }
        )
    return out


async def _alpaca_corporate_actions(symbol: str, settings: Settings, *, start: date, end: date) -> list[dict[str, Any]]:
    if not settings.alpaca_keys_present:
        return []
    import httpx

    url = f"{settings.resolved_data_base_url}/v1/corporate-actions"
    params = {
        "symbols": symbol.upper(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": 100,
    }
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key_id,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(url, headers=headers, params=params)
            if res.status_code >= 400:
                logger.warning("Alpaca corporate-actions {} -> {}", res.status_code, res.text[:160])
                return []
            payload = res.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alpaca corporate-actions failed: {}", exc)
        return []

    actions = (payload or {}).get("corporate_actions") or {}
    fetched = _now_iso()
    out: list[dict[str, Any]] = []

    def add(kind: str, rows: list[dict], date_key: str, title_fn) -> None:
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ed = row.get(date_key) or row.get("ex_date") or row.get("effective_date")
            if not ed:
                continue
            out.append(
                {
                    "id": f"ca-{kind}-{row.get('id') or ed}-{symbol}",
                    "scope": "ticker",
                    "kind": kind,
                    "symbol": symbol.upper(),
                    "title": title_fn(row),
                    "detail": title_fn(row),
                    "event_date": str(ed)[:10],
                    "event_time": "session",
                    "source": "Alpaca Corporate Actions",
                    "as_of": fetched,
                }
            )

    add(
        "dividend",
        actions.get("cash_dividends") or [],
        "ex_date",
        lambda r: f"Ex-dividend ${r.get('rate')} (payable {r.get('payable_date') or '—'})",
    )
    add(
        "split",
        actions.get("forward_splits") or actions.get("reverse_splits") or [],
        "ex_date",
        lambda r: f"Split {r.get('old_rate')}:{r.get('new_rate')}" if r.get("old_rate") else "Stock split",
    )
    add(
        "merger",
        actions.get("mergers") or [],
        "effective_date",
        lambda r: f"Merger / corporate action ({r.get('id') or 'listed'})",
    )
    return out


async def fetch_catalyst_calendar(
    symbol: str,
    settings: Settings,
    *,
    earnings_days: int = 21,
    macro_days: int = 7,
) -> dict[str, Any]:
    """Live catalyst board for ``symbol`` + broader US market.

    Cached briefly so Deep Scan re-renders do not hammer NASDAQ.
    """
    symbol = symbol.upper()
    cache_key = f"{symbol}:{earnings_days}:{macro_days}"
    hit = _cache.get(cache_key)
    now = datetime.now(timezone.utc).timestamp()
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    today = datetime.now(timezone.utc).date()
    earn_dates = [today + timedelta(days=i) for i in range(0, max(earnings_days, 1)) if (today + timedelta(days=i)).weekday() < 5]
    # Cap weekday fan-out so we stay polite to NASDAQ.
    earn_dates = earn_dates[:15]
    macro_dates = [today + timedelta(days=i) for i in range(0, max(macro_days, 1))]

    earn_lists, macro_lists, corp = await asyncio.gather(
        asyncio.gather(*[_nasdaq_earnings_day(d) for d in earn_dates]),
        asyncio.gather(*[_nasdaq_econ_day(d) for d in macro_dates]),
        _alpaca_corporate_actions(symbol, settings, start=today - timedelta(days=7), end=today + timedelta(days=90)),
    )

    all_earnings = [e for batch in earn_lists for e in batch]
    ticker_earnings = [e for e in all_earnings if e["symbol"] == symbol]
    # Broader market: largest names by simply taking a sample of the day's prints (already real).
    market_earnings = [e for e in all_earnings if e["symbol"] != symbol][:40]
    for e in market_earnings:
        e["scope"] = "market"

    macro = [e for batch in macro_lists for e in batch]

    ticker_events = sorted(ticker_earnings + list(corp), key=lambda e: (e["event_date"], e["title"]))
    market_events = sorted(macro + market_earnings, key=lambda e: (e["event_date"], e["title"]))

    notes: list[str] = []
    if not ticker_events:
        notes.append(
            f"No live corporate actions returned for {symbol} in the next {earnings_days} calendar days."
        )
    if not market_events:
        notes.append("No live US macro / market earnings events returned for the look-ahead window.")

    payload = {
        "symbol": symbol,
        "ticker_events": ticker_events,
        "market_events": market_events,
        "sources": [
            "NASDAQ Earnings Calendar",
            "NASDAQ Economic Calendar",
            "Alpaca Corporate Actions",
        ],
        "as_of": _now_iso(),
        "notes": notes,
    }
    _cache[cache_key] = (now, payload)
    return payload
