"""Deep Scan fundamentals layer — Full Document §7.2.

Sources (labeled on every field group):
  - Quote / market-cap / 52w / P/E: existing live_quotes stack (Alpaca + CNBC + NASDAQ)
  - EPS surprises, analyst targets, income statement, sector: NASDAQ public APIs
  - Sector rotation: Yahoo Finance daily charts for sector ETF vs SPY (1-week)

Missing values stay ``None`` / ``"—"`` in the UI — never fabricated.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.config import Settings
from app.schemas.market import Quote
from app.services.catalyst_calendar import _nasdaq_earnings_day
from app.services.live_quotes import HTTP_HEADERS, get_live_fundamentals, parse_number

#: Docs §7.2 sector rotation — map NASDAQ sector labels to Select Sector SPDRs.
SECTOR_ETFS: dict[str, str] = {
    "technology": "XLK",
    "information technology": "XLK",
    "health care": "XLV",
    "healthcare": "XLV",
    "financials": "XLF",
    "financial": "XLF",
    "energy": "XLE",
    "consumer discretionary": "XLY",
    "consumer cyclical": "XLY",
    "consumer staples": "XLP",
    "consumer defensive": "XLP",
    "industrials": "XLI",
    "materials": "XLB",
    "basic materials": "XLB",
    "utilities": "XLU",
    "real estate": "XLRE",
    "communication services": "XLC",
    "telecommunications": "XLC",
}


async def _http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 12.0) -> Any | None:
    import httpx

    merged = {**HTTP_HEADERS, **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=merged)
            if res.status_code >= 400:
                logger.warning("Fundamentals HTTP {} {} -> {}", url[:90], res.status_code, res.text[:140])
                return None
            return res.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fundamentals fetch failed {}: {}", url[:90], exc)
        return None


def _nasdaq_headers(symbol: str) -> dict[str, str]:
    return {
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}",
    }


def _pct_change(newer: float | None, older: float | None) -> float | None:
    if newer is None or older is None or older == 0:
        return None
    return round((newer - older) / abs(older) * 100.0, 2)


def _parse_table_money(row: dict[str, Any] | None, col: str = "value2") -> float | None:
    if not row:
        return None
    return parse_number(row.get(col))


async def _earnings_surprise(symbol: str) -> dict[str, Any]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/company/{symbol}/earnings-surprise",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"status": "unavailable", "source": None, "history": [], "consecutive_beats": None, "latest": None}
    table = data.get("earningsSurpriseTable") or {}
    rows = table.get("rows") or []
    history: list[dict[str, Any]] = []
    for row in rows[:8]:
        history.append(
            {
                "fiscal_quarter": row.get("fiscalQtrEnd"),
                "date_reported": row.get("dateReported"),
                "eps": parse_number(row.get("eps")),
                "consensus": parse_number(row.get("consensusForecast")),
                "surprise_pct": parse_number(row.get("percentageSurprise")),
            }
        )
    beats = 0
    for item in history:
        sp = item.get("surprise_pct")
        if sp is None:
            break
        if sp > 0:
            beats += 1
        else:
            break
    latest = history[0] if history else None
    return {
        "status": "live" if history else "unavailable",
        "source": "NASDAQ",
        "history": history,
        "consecutive_beats": beats if history else None,
        "latest": latest,
        "trend": (
            "consecutive_beats"
            if beats >= 2
            else "mixed"
            if history
            else "unavailable"
        ),
    }


async def _analyst_targets(symbol: str) -> dict[str, Any]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/analyst/{symbol}/targetprice",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"status": "unavailable", "source": None}
    overview = data.get("consensusOverview") or {}
    buy = parse_number(overview.get("buy"))
    hold = parse_number(overview.get("hold"))
    sell = parse_number(overview.get("sell"))
    target = parse_number(overview.get("priceTarget"))
    coverage = None
    if buy is not None or hold is not None or sell is not None:
        coverage = int((buy or 0) + (hold or 0) + (sell or 0))
    return {
        "status": "live" if target is not None or coverage else "unavailable",
        "source": "NASDAQ",
        "price_target": target,
        "low_target": parse_number(overview.get("lowPriceTarget")),
        "high_target": parse_number(overview.get("highPriceTarget")),
        "buy": int(buy) if buy is not None else None,
        "hold": int(hold) if hold is not None else None,
        "sell": int(sell) if sell is not None else None,
        "coverage": coverage,
        "consensus_label": (
            "Buy"
            if (buy or 0) > (hold or 0) and (buy or 0) > (sell or 0)
            else "Sell"
            if (sell or 0) > (buy or 0) and (sell or 0) > (hold or 0)
            else "Hold"
            if coverage
            else None
        ),
    }


async def _earnings_forecast(symbol: str) -> dict[str, Any]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/analyst/{symbol}/earnings-forecast",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"status": "unavailable", "source": None, "next_quarter": None}
    q_rows = ((data.get("quarterlyForecast") or {}).get("rows")) or []
    next_q = None
    if q_rows:
        row = q_rows[0]
        next_q = {
            "fiscal_end": row.get("fiscalEnd"),
            "consensus_eps": parse_number(row.get("consensusEPSForecast")),
            "high_eps": parse_number(row.get("highEPSForecast")),
            "low_eps": parse_number(row.get("lowEPSForecast")),
            "estimates": parse_number(row.get("noOfEstimates")),
            "revisions_up": parse_number(row.get("up")),
            "revisions_down": parse_number(row.get("down")),
        }
    return {"status": "live" if next_q else "unavailable", "source": "NASDAQ", "next_quarter": next_q}


async def _income_annual(symbol: str) -> dict[str, Any]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/company/{symbol}/financials?frequency=1",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"status": "unavailable", "source": None}
    table = data.get("incomeStatementTable") or {}
    headers = table.get("headers") or {}
    rows = table.get("rows") or []

    def find(*needles: str) -> dict[str, Any] | None:
        for row in rows:
            label = (row.get("value1") or "").lower()
            if any(n in label for n in needles):
                return row
        return None

    rev = find("total revenue")
    ni = find("net income")
    # Prefer continuing ops / attributable if present
    if ni is None:
        ni = find("net income-cont", "net income")

    rev_now = _parse_table_money(rev, "value2")
    rev_prior = _parse_table_money(rev, "value3")
    ni_now = _parse_table_money(ni, "value2")
    ni_prior = _parse_table_money(ni, "value3")
    rev_yoy = _pct_change(rev_now, rev_prior)
    signal = None
    if rev_yoy is not None:
        signal = "strong" if rev_yoy > 15 else "caution" if rev_yoy < 5 else "moderate"
    return {
        "status": "live" if rev_now is not None or ni_now is not None else "unavailable",
        "source": "NASDAQ",
        "period_current": headers.get("value2"),
        "period_prior": headers.get("value3"),
        "revenue": rev_now,
        "revenue_prior": rev_prior,
        "revenue_yoy_pct": rev_yoy,
        "revenue_signal": signal,
        "net_income": ni_now,
        "net_income_prior": ni_prior,
        "net_income_yoy_pct": _pct_change(ni_now, ni_prior),
        # NASDAQ income statement figures are reported in thousands.
        "units": "USD thousands (as published by NASDAQ financials table)",
    }


async def _company_profile(symbol: str) -> dict[str, Any]:
    payload = await _http_json(
        f"https://api.nasdaq.com/api/company/{symbol}/company-profile",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {"status": "unavailable", "source": None, "sector": None, "industry": None}

    def val(key: str) -> str | None:
        node = data.get(key) or {}
        if isinstance(node, dict):
            v = node.get("value")
            return str(v) if v else None
        return None

    return {
        "status": "live",
        "source": "NASDAQ",
        "company_name": val("CompanyName"),
        "sector": val("Sector"),
        "industry": val("Industry"),
        "description": val("CompanyDescription"),
    }


def _humanize_label(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return ""
    text = str(value).replace("_", " ")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return " ".join(part.capitalize() for part in text.split())


def _fmt_pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.1f}%"


def _fmt_money(value: float | None, *, thousands: bool = False) -> str:
    if value is None:
        return "—"
    amount = value * 1000 if thousands else value
    sign = "-" if amount < 0 else ""
    abs_amt = abs(amount)
    if abs_amt >= 1e12:
        return f"{sign}${abs_amt / 1e12:.2f}T"
    if abs_amt >= 1e9:
        return f"{sign}${abs_amt / 1e9:.2f}B"
    if abs_amt >= 1e6:
        return f"{sign}${abs_amt / 1e6:.2f}M"
    if abs_amt >= 1e3:
        return f"{sign}${abs_amt / 1e3:.1f}K"
    return f"{sign}${abs_amt:.2f}"


def _week_return_from_bars(bars: list[dict]) -> float | None:
    closes = [float(b["c"]) for b in bars if b.get("c") is not None]
    if len(closes) < 6:
        return None
    older, newer = closes[-6], closes[-1]
    if older == 0:
        return None
    return round((newer - older) / abs(older) * 100.0, 2)


async def _alpaca_week_return(ticker: str, settings: Settings) -> float | None:
    from app.adapters.alpaca import AlpacaAdapter

    try:
        adapter = AlpacaAdapter(settings)
        bars = await adapter.bars(ticker.upper(), "1D", 12)
        return _week_return_from_bars(bars)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alpaca week return failed {}: {}", ticker, exc)
        return None


async def _yahoo_week_return(ticker: str) -> float | None:
    payload = None
    for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        payload = await _http_json(
            f"{host}/v8/finance/chart/{ticker}?interval=1d&range=1mo&includePrePost=false"
        )
        if isinstance(payload, dict):
            break
    if not isinstance(payload, dict):
        return None
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    closes = [c for c in (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
    if len(closes) < 6:
        return None
    older, newer = closes[-6], closes[-1]
    if older == 0:
        return None
    return round((newer - older) / abs(older) * 100.0, 2)


async def _sector_rotation(sector: str | None, settings: Settings | None = None) -> dict[str, Any]:
    if not sector:
        return {
            "status": "unavailable",
            "source": None,
            "caveat": "Sector label unavailable — rotation not scored.",
        }
    etf = SECTOR_ETFS.get(sector.strip().lower())
    if not etf:
        return {
            "status": "unavailable",
            "source": None,
            "sector": sector,
            "caveat": f"No Select Sector SPDR mapping for '{sector}'.",
        }
    sector_ret, spy_ret = await asyncio.gather(_yahoo_week_return(etf), _yahoo_week_return("SPY"))
    source = "Yahoo Finance"
    used_alpaca = False
    if settings is not None and (sector_ret is None or spy_ret is None):
        if sector_ret is None:
            sector_ret = await _alpaca_week_return(etf, settings)
            used_alpaca = used_alpaca or sector_ret is not None
        if spy_ret is None:
            spy_ret = await _alpaca_week_return("SPY", settings)
            used_alpaca = used_alpaca or spy_ret is not None
        if used_alpaca:
            source = "Alpaca + Yahoo Finance" if source == "Yahoo Finance" and (sector_ret is not None or spy_ret is not None) else "Alpaca"
    if sector_ret is None and spy_ret is None:
        return {
            "status": "unavailable",
            "source": source,
            "sector": sector,
            "etf": etf,
            "benchmark": "SPY",
            "caveat": "Could not load 1-week returns for sector ETF / SPY.",
        }
    if sector_ret is None or spy_ret is None:
        return {
            "status": "partial",
            "source": source,
            "sector": sector,
            "etf": etf,
            "benchmark": "SPY",
            "window": "approx_5_trading_days",
            "sector_return_pct": sector_ret,
            "spy_return_pct": spy_ret,
            "relative_pct": None,
            "flow": None,
            "reading": (
                f"{etf} returned {_fmt_pct(sector_ret, signed=True)} over the last ~5 sessions"
                if sector_ret is not None
                else f"SPY returned {_fmt_pct(spy_ret, signed=True)} over the last ~5 sessions"
            ),
            "caveat": "Only one leg of the sector-vs-SPY pair loaded — relative rotation not scored.",
        }
    relative = round(sector_ret - spy_ret, 2)
    flow = "into" if relative > 0.35 else "out_of" if relative < -0.35 else "inline"
    return {
        "status": "live",
        "source": source,
        "sector": sector,
        "etf": etf,
        "benchmark": "SPY",
        "window": "approx_5_trading_days",
        "sector_return_pct": sector_ret,
        "spy_return_pct": spy_ret,
        "relative_pct": relative,
        "flow": flow,
        "reading": (
            f"Capital leaning into {sector} ({etf} {sector_ret:+.2f}% vs SPY {spy_ret:+.2f}%)"
            if flow == "into"
            else f"Capital leaning out of {sector} ({etf} {sector_ret:+.2f}% vs SPY {spy_ret:+.2f}%)"
            if flow == "out_of"
            else f"{sector} roughly in line with SPY this week ({etf} {sector_ret:+.2f}% vs SPY {spy_ret:+.2f}%)"
        ),
    }


def _parse_us_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def announcement_date(announcement: str | None) -> date | None:
    """Date printed in a NASDAQ earnings-date ``announcement`` string, or None."""
    if not isinstance(announcement, str) or ":" not in announcement:
        return None
    return _parse_us_date(announcement.split(":")[-1].strip())


async def _scan_nasdaq_earnings_calendar(symbol: str, *, horizon_days: int = 90) -> dict[str, Any] | None:
    """Walk the NASDAQ earnings calendar for the next ``horizon_days`` and return the nearest future print."""
    today = date.today()
    dates = [
        today + timedelta(days=i)
        for i in range(horizon_days)
        if (today + timedelta(days=i)).weekday() < 5
    ][:45]
    if not dates:
        return None
    batches = await asyncio.gather(*[_nasdaq_earnings_day(d) for d in dates])
    sym = symbol.upper()
    matches = sorted(
        (e for batch in batches for e in batch if e.get("symbol") == sym),
        key=lambda e: str(e.get("event_date") or ""),
    )
    for ev in matches:
        raw = str(ev.get("event_date") or "")[:10]
        parsed = _parse_us_date(raw) or (date.fromisoformat(raw) if raw else None)
        if parsed is None:
            continue
        dte = (parsed - today).days
        if dte < 0:
            continue
        return {
            "next_date": parsed.isoformat(),
            "dte": dte,
            "time": ev.get("event_time"),
            "source": "NASDAQ Earnings Calendar",
        }
    return None


async def _earnings_calendar(symbol: str, surprise: dict[str, Any]) -> dict[str, Any]:
    """Resolve earnings timing without inventing a date.

    Order: NASDAQ analyst earnings-date → NASDAQ earnings calendar scan → last reported only.
    """
    today = date.today()
    last = None
    latest = (surprise or {}).get("latest") or {}
    if latest.get("date_reported"):
        last = latest["date_reported"]

    payload = await _http_json(
        f"https://api.nasdaq.com/api/analyst/{symbol}/earnings-date",
        headers=_nasdaq_headers(symbol),
    )
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    announcement = (data or {}).get("announcement") if isinstance(data, dict) else None
    report_text = (data or {}).get("reportText") if isinstance(data, dict) else None
    vendor_note = None
    if isinstance(report_text, str) and report_text.strip():
        parts = [part.strip() for part in report_text.strip().split(". ") if part.strip()]
        vendor_note = ". ".join(parts[:2])
        if vendor_note and not vendor_note.endswith("."):
            vendor_note += "."

    next_date = None
    dte = None
    source = None
    event_time = None
    parsed = announcement_date(announcement if isinstance(announcement, str) else None)
    if parsed is not None:
        next_date = parsed.isoformat()
        dte = (parsed - today).days
        source = "NASDAQ earnings-date"

    if next_date is None:
        scanned = await _scan_nasdaq_earnings_calendar(symbol)
        if scanned:
            next_date = scanned.get("next_date")
            dte = scanned.get("dte")
            source = scanned.get("source")
            event_time = scanned.get("time")

    if next_date is not None:
        return {
            "status": "live",
            "next_date": next_date,
            "dte": dte,
            "time": event_time,
            "eps_forecast": latest.get("consensus"),
            "last_reported": last,
            "source": source,
            "vendor_note": vendor_note,
        }

    return {
        "status": "partial" if last else "unavailable",
        "next_date": None,
        "dte": None,
        "time": None,
        "eps_forecast": None,
        "last_reported": last,
        "source": "NASDAQ" if last else None,
        "vendor_note": vendor_note,
    }


def _fund_score(
    *,
    rev_yoy: float | None,
    consecutive_beats: int | None,
    target: float | None,
    spot: float | None,
    pe: float | None,
) -> float:
    score = 55.0
    if rev_yoy is not None:
        if rev_yoy > 15:
            score += 12
        elif rev_yoy < 5:
            score -= 10
        else:
            score += 4
    if consecutive_beats is not None:
        score += min(12.0, consecutive_beats * 4.0)
    if target is not None and spot is not None and spot > 0:
        upside = (target - spot) / spot
        score += max(-10.0, min(12.0, upside * 40.0))
    if pe is not None:
        if 8 < pe < 40:
            score += 4
        elif pe >= 60:
            score -= 6
    return round(max(5.0, min(95.0, score)), 1)


async def build_fundamentals_layer(symbol: str, quote: Quote, settings: Settings) -> dict[str, Any]:
    sym = symbol.upper()
    base, surprise, analyst, forecast, income, profile = await asyncio.gather(
        get_live_fundamentals(sym, settings),
        _earnings_surprise(sym),
        _analyst_targets(sym),
        _earnings_forecast(sym),
        _income_annual(sym),
        _company_profile(sym),
    )
    rotation, calendar = await asyncio.gather(
        _sector_rotation(profile.get("sector"), settings),
        _earnings_calendar(sym, surprise),
    )

    pe = quote.pe_ttm if quote.pe_ttm is not None else base.pe_ttm
    mcap = quote.market_cap if quote.market_cap is not None else base.market_cap
    w52h = quote.week_52_high
    w52l = quote.week_52_low
    spot = quote.price

    target = analyst.get("price_target")
    upside = None
    if target is not None and spot is not None and spot > 0:
        upside = round((target - spot) / spot * 100.0, 2)

    score = _fund_score(
        rev_yoy=income.get("revenue_yoy_pct"),
        consecutive_beats=surprise.get("consecutive_beats"),
        target=target if isinstance(target, (int, float)) else None,
        spot=spot,
        pe=pe,
    )

    health = {
        "eps_latest": (surprise.get("latest") or {}).get("eps"),
        "eps_consensus_last": (surprise.get("latest") or {}).get("consensus"),
        "eps_surprise_pct": (surprise.get("latest") or {}).get("surprise_pct"),
        "revenue": income.get("revenue"),
        "revenue_yoy_pct": income.get("revenue_yoy_pct"),
        "net_income": income.get("net_income"),
        "net_income_yoy_pct": income.get("net_income_yoy_pct"),
        "pe_ttm": pe,
        "market_cap": mcap,
        "week_52_high": w52h,
        "week_52_low": w52l,
        "avg_volume": quote.avg_volume if quote.avg_volume is not None else base.avg_volume,
        "div_yield": quote.div_yield if quote.div_yield is not None else base.div_yield,
        "beta_5y": quote.beta_5y if quote.beta_5y is not None else base.beta_5y,
        "analyst_target": target,
        "analyst_upside_pct": upside,
        "analyst_coverage": analyst.get("coverage"),
        "spot": spot,
    }

    sources = sorted(
        {
            s
            for s, st in (
                (base.source, base.status),
                (quote.source, quote.status),
                (surprise.get("source"), surprise.get("status")),
                (analyst.get("source"), analyst.get("status")),
                (income.get("source"), income.get("status")),
                (profile.get("source"), profile.get("status")),
                (rotation.get("source"), rotation.get("status")),
                (calendar.get("source"), calendar.get("status")),
            )
            if s and s != "unavailable" and st not in (None, "unavailable")
        }
    )

    factor_cards = _build_factor_cards(
        sym,
        profile=profile,
        rotation=rotation,
        health=health,
        income=income,
        surprise=surprise,
        analyst=analyst,
        calendar=calendar,
        forecast=forecast,
        pe=pe,
        spot=spot,
        target=target,
        upside=upside,
    )

    return {
        "title": "Fundamentals — EPS · revenue · calendar · consensus · sector",
        "symbol": sym,
        "name": profile.get("company_name") or quote.name or base.name,
        "score": score,
        "quote_source": quote.source,
        "fundamentals_source": base.source,
        "sources": sources,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "eps_trend": surprise,
        "revenue": {
            "status": income.get("status"),
            "source": income.get("source"),
            "yoy_pct": income.get("revenue_yoy_pct"),
            "signal": income.get("revenue_signal"),
            "current": income.get("revenue"),
            "prior": income.get("revenue_prior"),
            "period_current": income.get("period_current"),
            "period_prior": income.get("period_prior"),
            "units": income.get("units"),
            "rule": ">15% strong; <5% caution",
        },
        "net_income": {
            "current": income.get("net_income"),
            "prior": income.get("net_income_prior"),
            "yoy_pct": income.get("net_income_yoy_pct"),
            "source": income.get("source"),
        },
        "earnings_calendar": calendar,
        "analyst": analyst,
        "forecast": forecast,
        "sector_rotation": rotation,
        "factor_cards": factor_cards,
        "profile": profile,
        "company_health": health,
        "base_fundamentals": base.model_dump(),
    }


def _build_factor_cards(
    sym: str,
    *,
    profile: dict[str, Any],
    rotation: dict[str, Any],
    health: dict[str, Any],
    income: dict[str, Any],
    surprise: dict[str, Any],
    analyst: dict[str, Any],
    calendar: dict[str, Any],
    forecast: dict[str, Any],
    pe: float | None,
    spot: float | None,
    target: float | None,
    upside: float | None,
) -> list[dict[str, str]]:
    sector = profile.get("sector") or "—"
    industry = profile.get("industry")
    etf = rotation.get("etf") or SECTOR_ETFS.get(str(sector).strip().lower(), "—")
    rev_yoy = income.get("revenue_yoy_pct")
    rev_sig = _humanize_label(income.get("revenue_signal") or "unavailable")
    beats = surprise.get("consecutive_beats")
    trend = _humanize_label(surprise.get("trend") or "unavailable")
    label = _humanize_label(analyst.get("consensus_label") or "—")
    flow = _humanize_label(rotation.get("flow") or "")

    # --- Sector positioning ---
    if rotation.get("status") == "live":
        s_ret = rotation.get("sector_return_pct")
        spy_ret = rotation.get("spy_return_pct")
        rel = rotation.get("relative_pct")
        sector_body = (
            f"{sym} is classified in {sector}"
            + (f" ({industry})" if industry else "")
            + f", tracked against the {etf} sector ETF versus the {rotation.get('benchmark') or 'SPY'} benchmark "
            f"over roughly five trading days. {etf} returned {_fmt_pct(s_ret, signed=True)} while "
            f"{rotation.get('benchmark') or 'SPY'} returned {_fmt_pct(spy_ret, signed=True)}, "
            f"a {_fmt_pct(rel, signed=True)} relative spread that indicates capital is rotating "
            f"{flow.lower() or 'inline with'} the group. "
            f"When a sector outperforms the broad market, names inside the group often carry a supportive "
            f"tailwind for relative strength; underperformance can compress multiples even when company-level "
            f"fundamentals are stable. "
            + (
                f"That backdrop aligns with the {_fmt_pct(rev_yoy, signed=True)} revenue trend on {sym}, "
                f"suggesting the tape is rewarding the group while the issuer is participating."
                if rev_yoy is not None and rel is not None and rel > 0 and rev_yoy > 5
                else f"Pair this sector read with the issuer's {_fmt_pct(rev_yoy, signed=True)} revenue YoY "
                f"and {trend.lower()} EPS pattern when sizing directional risk."
                if rev_yoy is not None
                else f"Cross-check this sector read against the issuer's EPS trend ({trend.lower()}) "
                f"and valuation before leaning on beta alone."
            )
        )
    elif rotation.get("status") == "partial":
        sector_body = (
            f"{sym} maps to {sector}"
            + (f" / {industry}" if industry else "")
            + f" via the {etf} proxy. "
            f"{rotation.get('reading') or ''} "
            f"Use the partial print as context only — full sector-vs-market rotation requires both legs."
        )
    elif rotation.get("sector") and rotation.get("etf"):
        sector_body = (
            f"{sym} sits in {sector}"
            + (f" ({industry})" if industry else "")
            + f", benchmarked to {rotation.get('etf')} versus SPY. "
            f"Live one-week relative returns were not available from Yahoo Finance or Alpaca on this request; "
            f"the sector classification still frames how macro rotation and factor crowding may affect the name."
        )
    else:
        sector_body = (
            f"Sector positioning for {sym} could not be mapped to a Select Sector SPDR — "
            f"verify the NASDAQ profile feed for an updated sector label."
        )

    # --- Valuation ---
    hi = health.get("week_52_high")
    lo = health.get("week_52_low")
    mcap = health.get("market_cap")
    div_y = health.get("div_yield")
    beta = health.get("beta_5y")
    val_parts: list[str] = []
    if pe is not None and spot is not None:
        pe_read = (
            "a premium multiple that prices in above-average growth or quality"
            if pe >= 35
            else "a discounted multiple that may reflect slower growth, cyclicality, or risk premium"
            if pe <= 12
            else "a mid-range multiple relative to large-cap norms"
        )
        val_parts.append(
            f"Trailing P/E of {pe:.1f} at a spot price of ${spot:.2f} implies {pe_read}."
        )
    elif pe is not None:
        val_parts.append(f"Trailing P/E reads {pe:.1f}.")
    if spot is not None and hi is not None and lo is not None and hi > lo:
        span = hi - lo
        pos = round((spot - lo) / span * 100, 0)
        range_read = (
            "near the upper bound of its annual range, where upside may need fresh catalysts"
            if pos >= 75
            else "closer to the lower bound, where mean-reversion setups often emerge if fundamentals hold"
            if pos <= 25
            else "mid-range within the annual band, leaving room for movement in either direction"
        )
        val_parts.append(
            f"Price sits near the {pos:.0f}th percentile of the 52-week range "
            f"(${lo:.2f}–${hi:.2f}), {range_read}."
        )
    if mcap is not None:
        val_parts.append(f"Market capitalization is {_fmt_money(mcap)}.")
    if div_y is not None:
        val_parts.append(f"Dividend yield is {_fmt_pct(div_y, signed=False)}.")
    if beta is not None:
        val_parts.append(
            f"Five-year beta of {beta:.2f} "
            f"{'amplifies' if beta > 1.1 else 'dampens' if beta < 0.9 else 'tracks'} "
            f"broad-market swings — relevant when sector rotation is active."
        )
    if upside is not None and target is not None and spot is not None:
        val_parts.append(
            f"Street targets imply {_fmt_pct(upside, signed=True)} from spot (${target:.2f} mean target), "
            f"which should be weighed against the P/E and range position above."
        )
    val_body = " ".join(val_parts) if val_parts else "Valuation multiples and range context were not available from live quote feeds."

    # --- Growth ---
    ni_yoy = income.get("net_income_yoy_pct")
    period_now = income.get("period_current")
    period_prior = income.get("period_prior")
    rev_now = income.get("revenue")
    rev_prior = income.get("revenue_prior")
    latest = surprise.get("latest") or {}
    history = surprise.get("history") or []
    growth_parts: list[str] = []
    if rev_yoy is not None:
        growth_parts.append(
            f"Revenue grew {_fmt_pct(rev_yoy, signed=True)} year-over-year"
            + (
                f" from {_fmt_money(rev_prior, thousands=True)} ({period_prior}) "
                f"to {_fmt_money(rev_now, thousands=True)} ({period_now})"
                if rev_now is not None and rev_prior is not None and period_now and period_prior
                else ""
            )
            + f", tagged as a {rev_sig.lower()} growth signal (>15% strong, <5% caution)."
        )
    if ni_yoy is not None:
        growth_parts.append(f"Net income moved {_fmt_pct(ni_yoy, signed=True)} YoY on the same annual filings.")
    if beats and beats >= 2:
        growth_parts.append(
            f"EPS delivery shows {beats} consecutive quarters beating consensus — a {trend.lower()} pattern "
            f"that often supports premium multiples when revenue keeps pace."
        )
    elif history:
        last = history[0]
        sp = last.get("surprise_pct")
        fq = last.get("fiscal_quarter") or "the latest quarter"
        if sp is not None:
            growth_parts.append(
                f"Most recent print ({fq}) reported EPS {last.get('eps')} vs consensus {last.get('consensus')} "
                f"({_fmt_pct(sp, signed=True)} surprise), contributing to a {trend.lower()} EPS trend."
            )
        else:
            growth_parts.append(f"EPS trend is {trend.lower()} based on NASDAQ surprise history.")
    elif trend:
        growth_parts.append(f"EPS trend reads {trend.lower()} from NASDAQ surprise data.")
    if rev_yoy is not None and rotation.get("relative_pct") is not None:
        growth_parts.append(
            "Strong revenue alongside a sector that is outperforming SPY is a constructive confluence; "
            "weak revenue into a lagging sector often signals relative weakness."
            if rev_yoy > 10 and (rotation.get("relative_pct") or 0) > 0
            else "If revenue decelerates while the sector is already lagging SPY, expect relative pressure "
            "even on in-line EPS prints."
            if rev_yoy < 5 and (rotation.get("relative_pct") or 0) < 0
            else "Align revenue trajectory with the sector rotation read when judging whether growth is "
            "idiosyncratic or group-driven."
        )
    growth_body = " ".join(growth_parts) if growth_parts else (
        f"Revenue and EPS growth details were sparse; EPS trend is {trend.lower()} from available NASDAQ history."
    )

    # --- Analyst view ---
    buy = analyst.get("buy")
    hold = analyst.get("hold")
    sell = analyst.get("sell")
    coverage = analyst.get("coverage")
    low_t = analyst.get("low_target")
    high_t = analyst.get("high_target")
    analyst_parts: list[str] = []
    if label:
        analyst_parts.append(f"Consensus skew is {label}")
        if buy is not None or hold is not None or sell is not None:
            analyst_parts.append(
                f"with {int(buy or 0)} Buy / {int(hold or 0)} Hold / {int(sell or 0)} Sell ratings"
                + (f" across {coverage} analysts" if coverage else "")
                + "."
            )
    if target is not None and spot is not None and upside is not None:
        analyst_parts.append(
            f"Mean price target is ${target:.2f} versus spot ${spot:.2f} "
            f"({_fmt_pct(upside, signed=True)} implied upside)."
        )
    if low_t is not None and high_t is not None:
        spread = high_t - low_t
        analyst_parts.append(
            f"The published range spans ${low_t:.0f}–${high_t:.0f}"
            + (f" (${spread:.0f} wide), reflecting dispersion in forward assumptions." if spread else ".")
        )
    if upside is not None:
        analyst_parts.append(
            "Upside skew supports long-bias positioning when paired with stable EPS delivery."
            if upside > 8
            else "Limited implied upside suggests the name may be fairly valued versus the Street — "
            "upgrades or estimate revisions would be needed to re-rate."
            if upside < 3
            else "Target gap is moderate; monitor estimate revisions into the next earnings window."
        )
    if rev_yoy is not None:
        analyst_parts.append(
            f"Cross-check the {_fmt_pct(rev_yoy, signed=True)} revenue trend against this target gap — "
            f"targets tend to stick when growth validates the narrative."
        )
    analyst_body = " ".join(analyst_parts) if analyst_parts else "Analyst consensus and price targets were not available from NASDAQ on this request."

    # --- Earnings timing ---
    nd = calendar.get("next_date")
    dte = calendar.get("dte")
    last = calendar.get("last_reported")
    event_time = calendar.get("time")
    next_q = (forecast or {}).get("next_quarter") or {}
    earn_parts: list[str] = []
    if nd:
        earn_parts.append(
            f"Next earnings date is {nd}"
            + (f" ({dte} days out)" if dte is not None else "")
            + (f", expected {event_time}" if event_time else "")
            + f" per {calendar.get('source') or 'NASDAQ'}."
        )
        note = calendar.get("vendor_note")
        if isinstance(note, str) and note.strip():
            earn_parts.append(note.strip())
    if next_q.get("consensus_eps") is not None:
        earn_parts.append(
            f"Forward-quarter consensus EPS is {next_q['consensus_eps']:.2f}"
            + (
                f" (range {next_q.get('low_eps')}–{next_q.get('high_eps')}, "
                f"{int(next_q.get('estimates') or 0)} estimates"
                + (
                    f", {int(next_q.get('revisions_up') or 0)} up / "
                    f"{int(next_q.get('revisions_down') or 0)} down revisions"
                )
                + ")."
                if next_q.get("low_eps") is not None
                else ")."
            )
        )
    if last:
        earn_parts.append(f"Last reported on {last}.")
        if latest.get("surprise_pct") is not None:
            earn_parts.append(
                f"The prior print carried a {_fmt_pct(latest.get('surprise_pct'), signed=True)} EPS surprise "
                f"({latest.get('eps')} vs {latest.get('consensus')} consensus)."
            )
    if dte is not None:
        earn_parts.append(
            "With the event inside two weeks, implied volatility and estimate drift typically dominate price action."
            if dte <= 14
            else "The calendar is far enough out that sector rotation and multiple expansion can matter more "
            "than the binary print itself."
            if dte > 45
            else "Use the intervening weeks to track pre-announcement estimate revisions and peer pre-announcements."
        )
    if not nd and last:
        earn_parts.append("A forward date has not been published yet — watch NASDAQ earnings-date for an update.")
    earn_body = " ".join(earn_parts) if earn_parts else "Earnings timing was not available from NASDAQ calendar feeds."

    return [
        {"id": "sector", "title": "Sector positioning", "body": sector_body},
        {"id": "valuation", "title": "Valuation", "body": val_body},
        {"id": "growth", "title": "Growth", "body": growth_body},
        {"id": "analyst", "title": "Analyst view", "body": analyst_body},
        {"id": "earnings", "title": "Earnings timing", "body": earn_body},
    ]
