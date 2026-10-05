"""Searchable symbol backlog.

Every ticker search (demo adapter, Alpaca adapter, ``/market/search``) goes
through :func:`search_instruments`. The backlog only contains:

- individual equity stocks (``stock`` and ``individual_equity`` are one class)
- ETFs
- market indexes
- commodities and futures
- currencies (forex)

Crypto, mutual funds, option contracts, and any other asset class are dropped.
The same symbol is returned once.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Sequence

from app.schemas.market import SearchHit

# Canonical classes stored on search hits.
EQUITY = "us_equity"
ETF = "us_etf"
INDEX = "us_index"
COMMODITY = "commodity"
FOREX = "forex"

ALLOWED_ASSET_CLASSES = frozenset({EQUITY, ETF, INDEX, COMMODITY, FOREX})

_CANONICAL = {
    "stock": EQUITY,
    "stocks": EQUITY,
    "equity": EQUITY,
    "equities": EQUITY,
    "us_equity": EQUITY,
    "individual_equity": EQUITY,
    "individual_equity_stock": EQUITY,
    "individual_stock": EQUITY,
    "common_stock": EQUITY,
    "etf": ETF,
    "etfs": ETF,
    "us_etf": ETF,
    "exchange_traded_fund": ETF,
    "index": INDEX,
    "indexes": INDEX,
    "indices": INDEX,
    "us_index": INDEX,
    "market_index": INDEX,
    "commodity": COMMODITY,
    "commodities": COMMODITY,
    "future": COMMODITY,
    "futures": COMMODITY,
    "commodity_future": COMMODITY,
    "commodity_futures": COMMODITY,
    "forex": FOREX,
    "fx": FOREX,
    "currency": FOREX,
    "currencies": FOREX,
}

# OCC-style option contract: ROOT + yymmdd + C/P + strike*1000.
_OPTION_CONTRACT = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")
_WORD = re.compile(r"[a-z0-9]+")
_CLASS_KEY = re.compile(r"[\s-]+")


class Instrument(NamedTuple):
    symbol: str
    name: str
    asset_class: str


def _class_key(raw: str) -> str:
    return _CLASS_KEY.sub("_", (raw or "").strip().casefold())


def canonical_asset_class(raw: str) -> str | None:
    """Map aliases onto an allowed class. Anything else is not searchable."""
    return _CANONICAL.get(_class_key(raw))


def _is_option_contract(symbol: str) -> bool:
    return bool(_OPTION_CONTRACT.match(symbol.strip().upper().replace(" ", "")))


def matches_query(symbol: str, name: str, query: str) -> bool:
    """Case-insensitive pinpoint match on ticker or full name.

    A ticker matches when it equals the query or starts with it.
    A name matches when it equals the query, starts with it, or any word in
    the name starts with it. ``AAPL`` and ``Apple`` both match Apple Inc.
    """
    q = query.strip().casefold()
    if not q:
        return True
    sym = symbol.casefold()
    if sym == q or sym.startswith(q):
        return True
    nm = name.casefold()
    if nm == q or nm.startswith(q):
        return True
    return any(word.startswith(q) for word in _WORD.findall(nm))


def filter_symbol_hits(query: str, rows: Sequence[Instrument]) -> list[SearchHit]:
    """Drop disallowed types, collapse duplicate symbols, then sort A–Z.

    Sort key is the full name, then the ticker. ``stock`` and
    ``individual_equity`` share one equity class, so a symbol listed under
    both is a single row (the first allowed name wins).
    """
    blocked: set[str] = set()
    chosen: dict[str, SearchHit] = {}
    for row in rows:
        symbol = row.symbol.strip().upper()
        if not symbol or symbol in blocked or symbol in chosen:
            continue
        if _is_option_contract(symbol):
            blocked.add(symbol)
            continue
        asset = canonical_asset_class(row.asset_class)
        if asset is None:
            continue
        name = row.name.strip() or symbol
        chosen[symbol] = SearchHit(symbol=symbol, name=name, asset_class=asset)
    hits = [hit for hit in chosen.values() if matches_query(hit.symbol, hit.name, query)]
    hits.sort(key=lambda hit: (hit.name.casefold(), hit.symbol.casefold()))
    return hits


# Curated desk backlog. Equities, ETFs, indexes, commodities/futures, forex.
# One row per symbol. Do not add crypto, mutual funds, or option contracts.
CATALOG: tuple[Instrument, ...] = (
    Instrument("AAPL", "Apple Inc.", EQUITY),
    Instrument("MSFT", "Microsoft Corporation", EQUITY),
    Instrument("NVDA", "NVIDIA Corporation", EQUITY),
    Instrument("AMZN", "Amazon.com, Inc.", EQUITY),
    Instrument("META", "Meta Platforms, Inc.", EQUITY),
    Instrument("GOOGL", "Alphabet Inc. Class A", EQUITY),
    Instrument("GOOG", "Alphabet Inc. Class C", EQUITY),
    Instrument("TSLA", "Tesla, Inc.", EQUITY),
    Instrument("AMD", "Advanced Micro Devices, Inc.", EQUITY),
    Instrument("NFLX", "Netflix, Inc.", EQUITY),
    Instrument("INTC", "Intel Corporation", EQUITY),
    Instrument("AVGO", "Broadcom Inc.", EQUITY),
    Instrument("COST", "Costco Wholesale Corporation", EQUITY),
    Instrument("PEP", "PepsiCo, Inc.", EQUITY),
    Instrument("CSCO", "Cisco Systems, Inc.", EQUITY),
    Instrument("QCOM", "QUALCOMM Incorporated", EQUITY),
    Instrument("AMAT", "Applied Materials, Inc.", EQUITY),
    Instrument("ADBE", "Adobe Inc.", EQUITY),
    Instrument("PYPL", "PayPal Holdings, Inc.", EQUITY),
    Instrument("JPM", "JPMorgan Chase & Co.", EQUITY),
    Instrument("BAC", "Bank of America Corporation", EQUITY),
    Instrument("WFC", "Wells Fargo & Company", EQUITY),
    Instrument("C", "Citigroup Inc.", EQUITY),
    Instrument("GS", "The Goldman Sachs Group, Inc.", EQUITY),
    Instrument("V", "Visa Inc.", EQUITY),
    Instrument("MA", "Mastercard Incorporated", EQUITY),
    Instrument("WMT", "Walmart Inc.", EQUITY),
    Instrument("JNJ", "Johnson & Johnson", EQUITY),
    Instrument("XOM", "Exxon Mobil Corporation", EQUITY),
    Instrument("CVX", "Chevron Corporation", EQUITY),
    Instrument("UNH", "UnitedHealth Group Incorporated", EQUITY),
    Instrument("PG", "The Procter & Gamble Company", EQUITY),
    Instrument("HD", "The Home Depot, Inc.", EQUITY),
    Instrument("KO", "The Coca-Cola Company", EQUITY),
    Instrument("DIS", "The Walt Disney Company", EQUITY),
    Instrument("IBM", "International Business Machines Corporation", EQUITY),
    Instrument("GE", "GE Aerospace", EQUITY),
    Instrument("CAT", "Caterpillar Inc.", EQUITY),
    Instrument("BA", "The Boeing Company", EQUITY),
    Instrument("MMM", "3M Company", EQUITY),
    Instrument("MRK", "Merck & Co., Inc.", EQUITY),
    Instrument("PFE", "Pfizer Inc.", EQUITY),
    Instrument("NKE", "NIKE, Inc.", EQUITY),
    Instrument("MCD", "McDonald's Corporation", EQUITY),
    Instrument("VZ", "Verizon Communications Inc.", EQUITY),
    Instrument("T", "AT&T Inc.", EQUITY),
    Instrument("BRK.B", "Berkshire Hathaway Inc. Class B", EQUITY),
    Instrument("BRK.A", "Berkshire Hathaway Inc. Class A", EQUITY),
    Instrument("SPY", "SPDR S&P 500 ETF Trust", ETF),
    Instrument("QQQ", "Invesco QQQ Trust", ETF),
    Instrument("IWM", "iShares Russell 2000 ETF", ETF),
    Instrument("DIA", "SPDR Dow Jones Industrial Average ETF Trust", ETF),
    Instrument("GLD", "SPDR Gold Shares", ETF),
    Instrument("SLV", "iShares Silver Trust", ETF),
    Instrument("TLT", "iShares 20+ Year Treasury Bond ETF", ETF),
    Instrument("HYG", "iShares iBoxx $ High Yield Corporate Bond ETF", ETF),
    Instrument("EEM", "iShares MSCI Emerging Markets ETF", ETF),
    Instrument("EFA", "iShares MSCI EAFE ETF", ETF),
    Instrument("XLF", "Financial Select Sector SPDR Fund", ETF),
    Instrument("XLE", "Energy Select Sector SPDR Fund", ETF),
    Instrument("XLK", "Technology Select Sector SPDR Fund", ETF),
    Instrument("XLV", "Health Care Select Sector SPDR Fund", ETF),
    Instrument("XLI", "Industrial Select Sector SPDR Fund", ETF),
    Instrument("XLP", "Consumer Staples Select Sector SPDR Fund", ETF),
    Instrument("XLY", "Consumer Discretionary Select Sector SPDR Fund", ETF),
    Instrument("XLU", "Utilities Select Sector SPDR Fund", ETF),
    Instrument("XLB", "Materials Select Sector SPDR Fund", ETF),
    Instrument("SPYG", "SPDR Portfolio S&P 500 Growth ETF", ETF),
    Instrument("SPYV", "SPDR Portfolio S&P 500 Value ETF", ETF),
    Instrument("TQQQ", "ProShares UltraPro QQQ", ETF),
    Instrument("SQQQ", "ProShares UltraPro Short QQQ", ETF),
    Instrument("SPX", "S&P 500 Index", INDEX),
    Instrument("DJI", "Dow Jones Industrial Average", INDEX),
    Instrument("NDX", "Nasdaq-100 Index", INDEX),
    Instrument("RUT", "Russell 2000 Index", INDEX),
    Instrument("VIX", "CBOE Volatility Index", INDEX),
    Instrument("IXIC", "Nasdaq Composite", INDEX),
    Instrument("CL", "WTI Crude Oil", COMMODITY),
    Instrument("GC", "Gold", COMMODITY),
    Instrument("SI", "Silver", COMMODITY),
    Instrument("NG", "Henry Hub Natural Gas", COMMODITY),
    Instrument("HG", "Copper", COMMODITY),
    Instrument("ZC", "Corn", COMMODITY),
    Instrument("ZW", "Chicago Wheat", COMMODITY),
    Instrument("KC", "Coffee", COMMODITY),
    Instrument("CT", "Cotton", COMMODITY),
    Instrument("ZB", "US Treasury Bond Future", COMMODITY),
    Instrument("EURUSD", "Euro / US Dollar", FOREX),
    Instrument("GBPUSD", "British Pound / US Dollar", FOREX),
    Instrument("USDJPY", "US Dollar / Japanese Yen", FOREX),
    Instrument("USDCHF", "US Dollar / Swiss Franc", FOREX),
    Instrument("AUDUSD", "Australian Dollar / US Dollar", FOREX),
    Instrument("USDCAD", "US Dollar / Canadian Dollar", FOREX),
    Instrument("NZDUSD", "New Zealand Dollar / US Dollar", FOREX),
    Instrument("EURGBP", "Euro / British Pound", FOREX),
    Instrument("EURJPY", "Euro / Japanese Yen", FOREX),
    Instrument("GBPJPY", "British Pound / Japanese Yen", FOREX),
)


# Broker dumps can contain thousands of prefix matches. Catalog hits are always
# kept; only this many additional allowed symbols are merged in.
_EXTRA_MATCH_LIMIT = 25


def search_instruments(query: str, extras: Sequence[Instrument] | None = None) -> list[SearchHit]:
    """Filter and sort the backlog. Empty query returns every allowed symbol.

    ``extras`` are additional rows (for example a broker asset dump). They pass
    through the same type filter. An empty query does not merge extras — the
    focused, empty search shows the backlog itself.
    """
    if not query.strip():
        return filter_symbol_hits("", CATALOG)
    catalog_hits = filter_symbol_hits(query, CATALOG)
    if not extras:
        return catalog_hits
    seen = {hit.symbol for hit in catalog_hits}
    merged = list(catalog_hits)
    added = 0
    for hit in filter_symbol_hits(query, extras):
        if hit.symbol in seen:
            continue
        merged.append(hit)
        seen.add(hit.symbol)
        added += 1
        if added >= _EXTRA_MATCH_LIMIT:
            break
    merged.sort(key=lambda hit: (hit.name.casefold(), hit.symbol.casefold()))
    return merged
