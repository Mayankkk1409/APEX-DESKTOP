"""Live ticker quotes and fundamentals.

Priority:
  1. Alpaca Market Data (alpaca-py) — latest trade/quote, snapshot, daily bars.
     52-week high/low and average volume are derived from historical daily bars.
     Keys come only from ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY.
  2. Public live feeds for anything Alpaca does not quote (indexes, most fundamentals):
     CNBC quote cache, NASDAQ public quote API, Yahoo Finance chart API.
     Sources are labeled on the payload so the UI never pretends Alpaca sent a P/E.

Never invent placeholder prices. If every live fetch fails, fields stay null
and status is "unavailable".
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

from app.config import Settings
from app.schemas.market import Fundamentals, Quote

# Display names for indexes we treat as indexes (not ETFs).
INDEX_FEEDS: dict[str, dict[str, str]] = {
    "SPX": {
        "name": "S&P 500 INDEX",
        "cnbc": ".SPX",
        "yahoo": "^GSPC",
        "asset_class": "index",
    },
    "DJI": {"name": "DOW JONES INDUSTRIAL AVERAGE", "cnbc": ".DJI", "yahoo": "^DJI", "asset_class": "index"},
    "DJIA": {"name": "DOW JONES INDUSTRIAL AVERAGE", "cnbc": ".DJI", "yahoo": "^DJI", "asset_class": "index"},
    "NDX": {"name": "NASDAQ-100 INDEX", "cnbc": ".NDX", "yahoo": "^NDX", "asset_class": "index"},
    "RUT": {"name": "RUSSELL 2000 INDEX", "cnbc": ".RUT", "yahoo": "^RUT", "asset_class": "index"},
    "VIX": {"name": "CBOE VOLATILITY INDEX", "cnbc": ".VIX", "yahoo": "^VIX", "asset_class": "index"},
    "COMP": {"name": "NASDAQ COMPOSITE", "cnbc": ".IXIC", "yahoo": "^IXIC", "asset_class": "index"},
    "IXIC": {"name": "NASDAQ COMPOSITE", "cnbc": ".IXIC", "yahoo": "^IXIC", "asset_class": "index"},
}

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

_CACHE_TTL_SECONDS = 8.0
_bundle_cache: dict[str, tuple[float, "_Bundle"]] = {}


@dataclass
class _Bundle:
    symbol: str
    name: str
    asset_class: str
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    avg_volume: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    div_yield: float | None = None
    expense_ratio: float | None = None
    beta_5y: float | None = None
    price_source: str | None = None
    fundamentals_source: str | None = None
    as_of: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.price is None:
            return "unavailable"
        core = (self.open, self.high, self.low, self.week_52_high, self.week_52_low)
        if any(v is None for v in core):
            return "partial"
        return "live"


def clear_quote_cache() -> None:
    _bundle_cache.clear()


def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "NA", "NONE", "NULL", "--", "—", "-"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("(", "").replace(")", "").replace(",", "").replace("$", "").replace("+", "").strip()
    multiplier = 1.0
    if text and text[-1] in "KMBTkmbt":
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1].upper()]
        text = text[:-1]
    text = text.replace("%", "").strip()
    try:
        number = float(text) * multiplier
    except ValueError:
        return None
    return -number if negative else number


def parse_percent_fraction(value: Any) -> float | None:
    """'0.35%' or 0.35 → 0.0035. Already-fraction values (< 0.2 with no %) stay as-is."""
    if value is None:
        return None
    raw = str(value)
    number = parse_number(value)
    if number is None:
        return None
    if "%" in raw or abs(number) > 0.2:
        return round(number / 100.0, 8)
    return round(number, 8)


def _first(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _index_meta(symbol: str) -> dict[str, str] | None:
    return INDEX_FEEDS.get(symbol.upper())


async def _http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 8.0) -> Any | None:
    merged = {**HTTP_HEADERS, **(headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            res = await client.get(url, headers=merged)
            if res.status_code >= 400:
                logger.warning("Live quote HTTP {} {} -> {}", url[:80], res.status_code, res.text[:160])
                return None
            ctype = res.headers.get("content-type", "")
            if "json" not in ctype and not res.text.lstrip().startswith("{") and not res.text.lstrip().startswith("["):
                return None
            return res.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live quote fetch failed {}: {}", url[:80], exc)
        return None


def _alpaca_stock_sync(symbol: str, settings: Settings) -> dict[str, Any] | None:
    """Blocking alpaca-py calls — run via asyncio.to_thread."""
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest, StockSnapshotRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.trading.client import TradingClient

    client = StockHistoricalDataClient(
        api_key=settings.alpaca_api_key_id,
        secret_key=settings.alpaca_api_secret_key,
    )
    snapshot = None
    last_error: Exception | None = None
    for feed in (DataFeed.IEX, DataFeed.DELAYED_SIP):
        try:
            snaps = client.get_stock_snapshot(StockSnapshotRequest(symbol_or_symbols=[symbol], feed=feed))
            snapshot = snaps.get(symbol) if isinstance(snaps, dict) else None
            if snapshot is None and hasattr(snaps, "__getitem__"):
                try:
                    snapshot = snaps[symbol]
                except Exception:  # noqa: BLE001
                    snapshot = None
            if snapshot is not None:
                break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            snapshot = None
    if snapshot is None:
        if last_error:
            logger.warning("Alpaca snapshot failed for {}: {}", symbol, last_error)
        return None

    latest_trade = getattr(snapshot, "latest_trade", None)
    latest_quote = getattr(snapshot, "latest_quote", None)
    daily = getattr(snapshot, "daily_bar", None)
    prev = getattr(snapshot, "previous_daily_bar", None)
    trade_px = getattr(latest_trade, "price", None)
    ask = getattr(latest_quote, "ask_price", None)
    bid = getattr(latest_quote, "bid_price", None)
    mid = None
    if ask and bid and ask > 0 and bid > 0:
        mid = (float(ask) + float(bid)) / 2.0
    price = _first(parse_number(trade_px), parse_number(mid), parse_number(getattr(daily, "close", None)))
    prev_close = parse_number(getattr(prev, "close", None))
    change = round(price - prev_close, 4) if price is not None and prev_close else None
    change_pct = round((change / prev_close) * 100, 4) if change is not None and prev_close else None
    trade_ts = getattr(latest_trade, "timestamp", None)

    week_high = week_low = avg_vol = None
    try:
        start = datetime.now(timezone.utc) - timedelta(days=400)
        bars_resp = client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=[symbol],
                timeframe=TimeFrame.Day,
                start=start.replace(tzinfo=None),
                limit=300,
                adjustment=Adjustment.RAW,
            )
        )
        bars = []
        if bars_resp is not None:
            try:
                bars = list(bars_resp[symbol])
            except Exception:  # noqa: BLE001
                data = getattr(bars_resp, "data", None) or {}
                bars = list(data.get(symbol) or [])
        if bars:
            highs = [float(b.high) for b in bars if getattr(b, "high", None) is not None]
            lows = [float(b.low) for b in bars if getattr(b, "low", None) is not None]
            vols = [float(b.volume) for b in bars if getattr(b, "volume", None) is not None]
            if highs:
                week_high = max(highs)
            if lows:
                week_low = min(lows)
            window = vols[-20:] if len(vols) >= 5 else vols
            if window:
                avg_vol = sum(window) / len(window)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alpaca bars failed for {}: {}", symbol, exc)

    name = None
    asset_class = "stock"
    try:
        trading = TradingClient(
            api_key=settings.alpaca_api_key_id,
            secret_key=settings.alpaca_api_secret_key,
            paper=settings.alpaca_trading_mode != "live",
        )
        asset = trading.get_asset(symbol)
        name = getattr(asset, "name", None)
        raw_class = str(getattr(asset, "asset_class", "") or "")
        if "etf" in raw_class.lower() or (name and "ETF" in str(name).upper()):
            asset_class = "etf"
    except Exception as exc:  # noqa: BLE001
        logger.debug("Alpaca asset lookup skipped for {}: {}", symbol, exc)

    as_of = None
    if trade_ts is not None:
        as_of = trade_ts.isoformat() if hasattr(trade_ts, "isoformat") else str(trade_ts)

    return {
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "open": parse_number(getattr(daily, "open", None)),
        "high": parse_number(getattr(daily, "high", None)),
        "low": parse_number(getattr(daily, "low", None)),
        "volume": parse_number(getattr(daily, "volume", None)),
        "avg_volume": avg_vol,
        "week_52_high": week_high,
        "week_52_low": week_low,
        "name": name,
        "asset_class": asset_class,
        "as_of": as_of,
        "source": "Alpaca",
    }


async def _alpaca_stock(symbol: str, settings: Settings) -> dict[str, Any] | None:
    if not settings.alpaca_keys_present:
        return None
    try:
        return await asyncio.to_thread(_alpaca_stock_sync, symbol, settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alpaca live quote thread failed for {}: {}", symbol, exc)
        return None


def _cnbc_row(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    rows = ((payload.get("FormattedQuoteResult") or {}).get("FormattedQuote")) or []
    if not rows:
        return None
    row = rows[0] if isinstance(rows, list) else rows
    if not isinstance(row, dict) or not row.get("last"):
        return None
    last = parse_number(row.get("last"))
    change = parse_number(row.get("change"))
    change_pct = parse_number(row.get("change_pct"))
    prev = parse_number(row.get("previous_day_closing"))
    if last is not None and (change is None or (prev is not None and abs(prev - last) < 1e-9)):
        # After the close CNBC often copies last into previous_day_closing.
        # Prefer the published change fields when they are present.
        pass
    return {
        "name": row.get("altName") or row.get("name") or row.get("onAirName"),
        "price": last,
        "change": change,
        "change_pct": change_pct,
        "open": parse_number(row.get("open")),
        "high": parse_number(row.get("high")),
        "low": parse_number(row.get("low")),
        "volume": parse_number(row.get("volume") or row.get("volume_alt")),
        "avg_volume": parse_number(row.get("tendayavgvol")),
        "week_52_high": parse_number(row.get("yrhiprice")),
        "week_52_low": parse_number(row.get("yrloprice")),
        "market_cap": parse_number(row.get("mktcapView")),
        "pe_ttm": parse_number(row.get("pe")),
        "div_yield": parse_percent_fraction(row.get("dividendyield")),
        "beta_5y": parse_number(row.get("beta")),
        "as_of": row.get("last_timedate") or row.get("last_time"),
        "type": row.get("type") or row.get("subType"),
        "source": "CNBC",
    }


async def _cnbc_quote(cnbc_symbol: str) -> dict[str, Any] | None:
    from urllib.parse import quote

    url = (
        "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
        f"?symbols={quote(cnbc_symbol, safe='.')}"
        "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1"
    )
    payload = await _http_json(
        url,
        headers={"Origin": "https://www.cnbc.com", "Referer": "https://www.cnbc.com/"},
    )
    return _cnbc_row(payload)


def _nasdaq_summary_map(summary: dict[str, Any]) -> dict[str, Any]:
    data = (summary or {}).get("data") or {}
    rows = data.get("summaryData") or {}
    out: dict[str, Any] = {}

    def val(*keys: str) -> Any:
        for key in keys:
            item = rows.get(key) or {}
            if item.get("value"):
                return item["value"]
        return None

    hi_lo = val("FiftTwoWeekHighLow", "FiftyTwoWeekHighLow")
    today_hl = val("TodayHighLow")
    out["volume"] = parse_number(val("ShareVolume"))
    out["avg_volume"] = parse_number(
        val("AverageVolume", "AvgDailyVol20Days", "FiftyDayAvgDailyVol", "AvgDailyVol65Days")
    )
    out["prev_close"] = parse_number(val("PreviousClose"))
    out["market_cap"] = parse_number(val("MarketCap"))
    out["div_yield"] = parse_percent_fraction(val("Yield"))
    out["expense_ratio"] = parse_percent_fraction(val("ExpenseRatio"))
    out["beta_5y"] = parse_number(val("Beta"))
    if isinstance(hi_lo, str) and "/" in hi_lo:
        left, right = hi_lo.split("/", 1)
        # "$344.5699/$223.7804" is high/low
        high, low = parse_number(left), parse_number(right)
        if high is not None and low is not None and high < low:
            high, low = low, high
        out["week_52_high"] = high
        out["week_52_low"] = low
    if isinstance(today_hl, str) and "/" in today_hl:
        left, right = today_hl.split("/", 1)
        high, low = parse_number(left), parse_number(right)
        if high is not None and "N/A" not in today_hl.upper():
            out["high"] = high
            out["low"] = low
    return out


async def _nasdaq_quote(symbol: str) -> dict[str, Any] | None:
    nasdaq_headers = {
        "Origin": "https://www.nasdaq.com",
        "Referer": f"https://www.nasdaq.com/market-activity/stocks/{symbol.lower()}",
    }
    info = summary = None
    asset_class = "stock"
    for ac in ("stocks", "etf"):
        info = await _http_json(
            f"https://api.nasdaq.com/api/quote/{symbol}/info?assetclass={ac}",
            headers=nasdaq_headers,
        )
        data = (info or {}).get("data") if isinstance(info, dict) else None
        if data:
            asset_class = "etf" if ac == "etf" else "stock"
            summary = await _http_json(
                f"https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass={ac}",
                headers=nasdaq_headers,
            )
            break
    if not isinstance(info, dict) or not info.get("data"):
        return None
    primary = (info["data"].get("primaryData") or {}) if info.get("data") else {}
    stats = _nasdaq_summary_map(summary if isinstance(summary, dict) else {})
    price = parse_number(primary.get("lastSalePrice"))
    change = parse_number(primary.get("netChange"))
    change_pct = parse_number(primary.get("percentageChange"))
    volume = parse_number(primary.get("volume")) or stats.get("volume")
    return {
        "name": (info.get("data") or {}).get("companyName"),
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "open": None,
        "high": stats.get("high"),
        "low": stats.get("low"),
        "volume": volume,
        "avg_volume": stats.get("avg_volume"),
        "week_52_high": stats.get("week_52_high"),
        "week_52_low": stats.get("week_52_low"),
        "market_cap": stats.get("market_cap"),
        "div_yield": stats.get("div_yield"),
        "expense_ratio": stats.get("expense_ratio"),
        "beta_5y": stats.get("beta_5y"),
        "as_of": primary.get("lastTradeTimestamp"),
        "asset_class": asset_class,
        "source": "NASDAQ",
    }


async def _yahoo_chart(yahoo_symbol: str) -> dict[str, Any] | None:
    from urllib.parse import quote

    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_symbol, safe='^')}"
        "?interval=1d&range=1y&includePrePost=false"
    )
    payload = await _http_json(url)
    if not isinstance(payload, dict):
        return None
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    indicators = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    highs = [h for h in (indicators.get("high") or []) if h is not None]
    lows = [low for low in (indicators.get("low") or []) if low is not None]
    vols = [v for v in (indicators.get("volume") or []) if v is not None]
    closes = [c for c in (indicators.get("close") or []) if c is not None]
    opens = [o for o in (indicators.get("open") or []) if o is not None]
    price = parse_number(meta.get("regularMarketPrice") or (closes[-1] if closes else None))
    prev = parse_number(meta.get("chartPreviousClose") or meta.get("previousClose"))
    change = round(price - prev, 4) if price is not None and prev else None
    change_pct = round((change / prev) * 100, 4) if change is not None and prev else None
    avg_vol = (sum(vols[-20:]) / len(vols[-20:])) if len(vols) >= 5 else (sum(vols) / len(vols) if vols else None)
    return {
        "name": meta.get("shortName") or meta.get("longName"),
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "open": parse_number(meta.get("regularMarketOpen") or (opens[-1] if opens else None)),
        "high": parse_number(meta.get("regularMarketDayHigh") or (highs[-1] if highs else None)),
        "low": parse_number(meta.get("regularMarketDayLow") or (lows[-1] if lows else None)),
        "volume": parse_number(meta.get("regularMarketVolume") or (vols[-1] if vols else None)),
        "avg_volume": avg_vol,
        "week_52_high": max(highs) if highs else parse_number(meta.get("fiftyTwoWeekHigh")),
        "week_52_low": min(lows) if lows else parse_number(meta.get("fiftyTwoWeekLow")),
        "as_of": str(meta.get("regularMarketTime") or ""),
        "source": "Yahoo Finance",
    }


_YAHOO_BAR_RANGE: dict[str, tuple[str, str]] = {
    "1m": ("1m", "7d"),
    "5m": ("5m", "1mo"),
    "15m": ("15m", "1mo"),
    "30m": ("30m", "1mo"),
    "1H": ("60m", "3mo"),
    "4H": ("60m", "6mo"),
    "1D": ("1d", "2y"),
    "1W": ("1wk", "5y"),
}


async def yahoo_ohlc_bars(symbol: str, timeframe: str, limit: int = 400) -> list[dict]:
    """Index OHLC when Alpaca has no index bars (SPX/DJI/…). Same Yahoo chart used for quotes."""
    from urllib.parse import quote

    meta = _index_meta(symbol)
    yahoo_symbol = meta["yahoo"] if meta else symbol
    interval, span = _YAHOO_BAR_RANGE.get(timeframe, ("1d", "2y"))
    path = f"/v8/finance/chart/{quote(yahoo_symbol, safe='^')}?interval={interval}&range={span}&includePrePost=false"
    payload = None
    for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
        payload = await _http_json(host + path, timeout=12.0)
        if isinstance(payload, dict):
            break
    if not isinstance(payload, dict):
        return []
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return []
    timestamps = result.get("timestamp") or []
    quote_row = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote_row.get("open") or []
    highs = quote_row.get("high") or []
    lows = quote_row.get("low") or []
    closes = quote_row.get("close") or []
    vols = quote_row.get("volume") or []
    bars: list[dict] = []
    for i, ts in enumerate(timestamps):
        try:
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        except IndexError:
            continue
        if None in (o, h, l, c):
            continue
        v = 0.0
        try:
            v = float(vols[i] or 0)
        except (IndexError, TypeError):
            v = 0.0
        iso = datetime.fromtimestamp(int(ts), timezone.utc).isoformat()
        bars.append({"t": iso, "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": v})
    if timeframe == "4H":
        bars = _resample_ohlc(bars, 4)
    return bars[-limit:]


def _resample_ohlc(bars: list[dict], group: int) -> list[dict]:
    if group <= 1 or not bars:
        return bars
    out: list[dict] = []
    for i in range(0, len(bars), group):
        chunk = bars[i : i + group]
        out.append(
            {
                "t": chunk[0]["t"],
                "o": chunk[0]["o"],
                "h": max(b["h"] for b in chunk),
                "l": min(b["l"] for b in chunk),
                "c": chunk[-1]["c"],
                "v": sum(b["v"] for b in chunk),
            }
        )
    return out


def _apply(dst: _Bundle, src: dict[str, Any] | None, *, price: bool, fundamentals: bool) -> None:
    if not src:
        return
    if price:
        if dst.price is None and src.get("price") is not None:
            dst.price = src["price"]
            dst.price_source = src.get("source")
        dst.change = _first(dst.change, src.get("change"))
        dst.change_pct = _first(dst.change_pct, src.get("change_pct"))
        dst.open = _first(dst.open, src.get("open"))
        dst.high = _first(dst.high, src.get("high"))
        dst.low = _first(dst.low, src.get("low"))
        dst.volume = _first(dst.volume, src.get("volume"))
        dst.week_52_high = _first(dst.week_52_high, src.get("week_52_high"))
        dst.week_52_low = _first(dst.week_52_low, src.get("week_52_low"))
        dst.as_of = dst.as_of or src.get("as_of")
        if src.get("name") and dst.name == dst.symbol:
            dst.name = src["name"]
    if fundamentals:
        before = (dst.market_cap, dst.pe_ttm, dst.div_yield, dst.expense_ratio, dst.beta_5y, dst.avg_volume)
        dst.avg_volume = _first(dst.avg_volume, src.get("avg_volume"))
        dst.market_cap = _first(dst.market_cap, src.get("market_cap"))
        dst.pe_ttm = _first(dst.pe_ttm, src.get("pe_ttm"))
        dst.div_yield = _first(dst.div_yield, src.get("div_yield"))
        dst.expense_ratio = _first(dst.expense_ratio, src.get("expense_ratio"))
        dst.beta_5y = _first(dst.beta_5y, src.get("beta_5y"))
        after = (dst.market_cap, dst.pe_ttm, dst.div_yield, dst.expense_ratio, dst.beta_5y, dst.avg_volume)
        if after != before and src.get("source"):
            if dst.fundamentals_source and src["source"] not in dst.fundamentals_source:
                dst.fundamentals_source = f"{dst.fundamentals_source} / {src['source']}"
            elif not dst.fundamentals_source:
                dst.fundamentals_source = src["source"]


async def _load_bundle(symbol: str, settings: Settings) -> _Bundle:
    symbol = symbol.strip().upper()
    now = time.monotonic()
    cached = _bundle_cache.get(symbol)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    meta = _index_meta(symbol)
    bundle = _Bundle(
        symbol=symbol,
        name=(meta["name"] if meta else symbol),
        asset_class=(meta["asset_class"] if meta else "stock"),
    )

    cnbc_symbol = meta["cnbc"] if meta else symbol
    alpaca_task = (
        asyncio.create_task(_alpaca_stock(symbol, settings))
        if meta is None and settings.alpaca_keys_present
        else None
    )
    cnbc_task = asyncio.create_task(_cnbc_quote(cnbc_symbol))
    nasdaq_task = asyncio.create_task(_nasdaq_quote(symbol)) if meta is None else None

    alpaca = await alpaca_task if alpaca_task else None
    cnbc = await cnbc_task
    nasdaq = await nasdaq_task if nasdaq_task else None

    _apply(bundle, alpaca, price=True, fundamentals=True)
    if alpaca and alpaca.get("name"):
        bundle.name = alpaca["name"]
    if alpaca and alpaca.get("asset_class"):
        bundle.asset_class = alpaca["asset_class"]

    _apply(bundle, cnbc, price=True, fundamentals=True)
    if meta:
        bundle.name = meta["name"]
        bundle.asset_class = "index"
        bundle.notes.append("S&P 500 INDEX feed" if symbol == "SPX" else f"{bundle.name} feed")
        if bundle.price_source:
            bundle.notes.append(f"Alpaca does not quote {symbol}; using {bundle.price_source} ({cnbc_symbol})")

    _apply(bundle, nasdaq, price=True, fundamentals=True)
    if nasdaq and nasdaq.get("asset_class") == "etf":
        bundle.asset_class = "etf"

    if bundle.price is None:
        yahoo_symbol = meta["yahoo"] if meta else symbol
        yahoo = await _yahoo_chart(yahoo_symbol)
        _apply(bundle, yahoo, price=True, fundamentals=True)
        if meta and yahoo and yahoo.get("source"):
            bundle.notes.append(f"Yahoo Finance {yahoo_symbol} index chart")

    if nasdaq:
        if nasdaq.get("market_cap") is not None:
            bundle.market_cap = nasdaq["market_cap"]
        if nasdaq.get("avg_volume") is not None:
            bundle.avg_volume = nasdaq["avg_volume"]
        if nasdaq.get("expense_ratio") is not None:
            bundle.expense_ratio = nasdaq["expense_ratio"]
        if nasdaq.get("source"):
            if bundle.fundamentals_source and nasdaq["source"] not in bundle.fundamentals_source:
                bundle.fundamentals_source = f"{bundle.fundamentals_source} / {nasdaq['source']}"
            elif not bundle.fundamentals_source:
                bundle.fundamentals_source = nasdaq["source"]

    # Indexes / common stocks do not have an expense ratio — leave null (UI shows —).
    if bundle.asset_class in {"stock", "index"}:
        bundle.expense_ratio = None
    if bundle.asset_class == "index":
        bundle.market_cap = None  # not a single issuer market cap

    _bundle_cache[symbol] = (now, bundle)
    return bundle


def _quote_from_bundle(bundle: _Bundle) -> Quote:
    source = bundle.price_source or "unavailable"
    secondary = None
    if bundle.fundamentals_source:
        secondary = f"Fundamentals · {bundle.fundamentals_source}"
    if bundle.asset_class == "index" and bundle.price_source:
        extra = f"{bundle.name} · {bundle.price_source}"
        if bundle.symbol == "SPX":
            extra = f"S&P 500 INDEX · {bundle.price_source} (.SPX) — not SPY"
        secondary = extra if not secondary else f"{extra} · {secondary}"
    return Quote(
        symbol=bundle.symbol,
        name=bundle.name,
        price=bundle.price,
        change=bundle.change,
        change_pct=bundle.change_pct,
        open=bundle.open,
        high=bundle.high,
        low=bundle.low,
        volume=bundle.volume,
        avg_volume=bundle.avg_volume,
        week_52_high=bundle.week_52_high,
        week_52_low=bundle.week_52_low,
        market_cap=bundle.market_cap,
        pe_ttm=bundle.pe_ttm,
        div_yield=bundle.div_yield,
        expense_ratio=bundle.expense_ratio,
        beta_5y=bundle.beta_5y,
        source=source,
        secondary_source=secondary,
        status=bundle.status,  # type: ignore[arg-type]
        as_of=bundle.as_of or None,
        asset_class=bundle.asset_class,
    )


def _fundamentals_from_bundle(bundle: _Bundle) -> Fundamentals:
    has_any = any(
        v is not None
        for v in (
            bundle.market_cap,
            bundle.pe_ttm,
            bundle.div_yield,
            bundle.expense_ratio,
            bundle.beta_5y,
            bundle.avg_volume,
        )
    )
    status = "unavailable" if not has_any else ("live" if bundle.price is not None else "partial")
    return Fundamentals(
        symbol=bundle.symbol,
        name=bundle.name,
        market_cap=bundle.market_cap,
        pe_ttm=bundle.pe_ttm,
        div_yield=bundle.div_yield,
        expense_ratio=bundle.expense_ratio,
        beta_5y=bundle.beta_5y,
        avg_volume=bundle.avg_volume,
        source=bundle.fundamentals_source or "unavailable",
        status=status,  # type: ignore[arg-type]
        as_of=bundle.as_of or None,
        asset_class=bundle.asset_class,
    )


async def get_live_quote(symbol: str, settings: Settings) -> Quote:
    bundle = await _load_bundle(symbol, settings)
    return _quote_from_bundle(bundle)


async def get_live_fundamentals(symbol: str, settings: Settings) -> Fundamentals:
    bundle = await _load_bundle(symbol, settings)
    return _fundamentals_from_bundle(bundle)
