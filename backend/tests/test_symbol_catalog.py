from __future__ import annotations

import pytest

from app.adapters.alpaca import AlpacaAdapter
from app.adapters.demo import DemoAdapter
from app.config import Settings
from app.services.symbol_catalog import (
    ALLOWED_ASSET_CLASSES,
    CATALOG,
    Instrument,
    filter_symbol_hits,
    search_instruments,
)


def test_catalog_is_allowed_types_without_duplicate_symbols() -> None:
    symbols = [row.symbol for row in CATALOG]
    assert len(symbols) == len(set(symbols))
    assert {row.asset_class for row in CATALOG} <= ALLOWED_ASSET_CLASSES
    assert {"us_equity", "us_etf", "us_index", "commodity", "forex"} <= {row.asset_class for row in CATALOG}


def test_empty_query_is_alphabetical_by_name_then_ticker() -> None:
    hits = search_instruments("")
    ordered = [(hit.name.casefold(), hit.symbol.casefold()) for hit in hits]
    assert ordered == sorted(ordered)
    assert len(hits) == len(CATALOG)

    tied = filter_symbol_hits(
        "",
        [
            Instrument("ZZZ", "Alpha Co", "us_equity"),
            Instrument("AAA", "Alpha Co", "stock"),
            Instrument("MMM", "Beta Co", "us_equity"),
        ],
    )
    assert [hit.symbol for hit in tied] == ["AAA", "ZZZ", "MMM"]


def test_ticker_match_is_case_insensitive() -> None:
    hits = search_instruments("aapl")
    assert [hit.symbol for hit in hits] == ["AAPL"]
    assert search_instruments("AAPL")[0].name == "Apple Inc."


def test_name_match_finds_apple() -> None:
    hits = search_instruments("Apple")
    assert [hit.symbol for hit in hits] == ["AAPL"]
    assert search_instruments("apple")[0].symbol == "AAPL"
    assert search_instruments("pple") == []


def test_disallowed_types_never_appear() -> None:
    mixed = [
        Instrument("AAPL", "Apple Inc.", "stock"),
        Instrument("AAPL", "Apple Inc.", "individual_equity"),
        Instrument("BTC", "Bitcoin", "crypto"),
        Instrument("ETH", "Ethereum", "cryptocurrency"),
        Instrument("VTSAX", "Vanguard Total Stock Market Index Fund", "mutual_fund"),
        Instrument("FXAIX", "Fidelity 500 Index Fund", "mutual fund"),
        Instrument("AAPL260116C00150000", "AAPL Jan 2026 150 Call", "us_option"),
        Instrument("SPX260116P05000000", "SPX Put", "us_equity"),
        Instrument("PRIVATE", "Private Credit Note", "bond"),
    ]
    empty = filter_symbol_hits("", mixed)
    assert [hit.symbol for hit in empty] == ["AAPL"]
    assert empty[0].asset_class == "us_equity"

    blocked = {"BTC", "ETH", "VTSAX", "FXAIX", "AAPL260116C00150000", "SPX260116P05000000", "PRIVATE"}
    for query in ("BTC", "Bitcoin", "VTSAX", "mutual", "AAPL260116C00150000", "PRIVATE", "bond"):
        assert blocked.isdisjoint(hit.symbol for hit in filter_symbol_hits(query, mixed))

    catalog_symbols = {hit.symbol for hit in search_instruments("bitcoin")}
    assert "BTC" not in catalog_symbols
    assert all(hit.asset_class in ALLOWED_ASSET_CLASSES for hit in search_instruments("btc"))


def test_typing_narrows_the_list() -> None:
    full = search_instruments("")
    letter = search_instruments("a")
    narrower = search_instruments("app")
    pinpoint = search_instruments("apple")
    assert {hit.symbol for hit in pinpoint} <= {hit.symbol for hit in narrower}
    assert {hit.symbol for hit in narrower} <= {hit.symbol for hit in letter}
    assert {hit.symbol for hit in letter} <= {hit.symbol for hit in full}
    assert len(pinpoint) < len(narrower) < len(letter) < len(full)
    assert [hit.symbol for hit in pinpoint] == ["AAPL"]
    assert {hit.symbol for hit in narrower} >= {"AAPL", "AMAT"}


def test_broker_extras_cannot_add_disallowed_types() -> None:
    hits = search_instruments(
        "btc",
        extras=[Instrument("BTC", "Bitcoin", "crypto"), Instrument("BTCUSD", "Bitcoin", "crypto")],
    )
    assert hits == []
    gold = search_instruments("gold")
    assert {hit.symbol for hit in gold} >= {"GC", "GLD"}


def test_search_route_empty_ticker_and_name() -> None:
    from starlette.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        empty = client.get("/market/search", params={"q": ""})
        assert empty.status_code == 200
        hits = empty.json()["hits"]
        ordered = [(hit["name"].casefold(), hit["symbol"].casefold()) for hit in hits]
        assert ordered == sorted(ordered)
        assert [hit["symbol"] for hit in client.get("/market/search", params={"q": "AAPL"}).json()["hits"]] == ["AAPL"]
        assert [hit["symbol"] for hit in client.get("/market/search", params={"q": "Apple"}).json()["hits"]] == ["AAPL"]
        assert client.get("/market/search", params={"q": "BTC"}).json()["hits"] == []
        letter = {hit["symbol"] for hit in client.get("/market/search", params={"q": "app"}).json()["hits"]}
        assert "AAPL" in letter and "AMAT" in letter
        assert letter < {hit["symbol"] for hit in hits}


@pytest.mark.asyncio
async def test_demo_search_uses_shared_catalog() -> None:
    hits = await DemoAdapter().search("")
    assert [hit.symbol for hit in hits] == [hit.symbol for hit in search_instruments("")]
    assert [hit.symbol for hit in await DemoAdapter().search("Apple")] == ["AAPL"]
    assert await DemoAdapter().search("BTC") == []


@pytest.mark.asyncio
async def test_alpaca_search_uses_shared_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = AlpacaAdapter(Settings())
    fetched: list[str] = []

    async def _get(self, base: str, path: str, params: dict | None = None):
        fetched.append(path)
        return [
            {"symbol": "BTC/USD", "name": "Bitcoin", "class": "crypto"},
            {"symbol": "VTSAX", "name": "Vanguard Total Stock Market Index Fund", "class": "mutual_fund"},
            {"symbol": "AAPL260116C00150000", "name": "AAPL Jan 2026 150 Call", "class": "us_option"},
            {"symbol": "ZZZZ", "name": "Zebra Medical", "class": "us_equity"},
        ]

    monkeypatch.setattr(AlpacaAdapter, "_get", _get)
    empty = await adapter.search("")
    assert fetched == []
    assert [(hit.name.casefold(), hit.symbol.casefold()) for hit in empty] == sorted(
        (hit.name.casefold(), hit.symbol.casefold()) for hit in empty
    )
    zebra = await adapter.search("zebra")
    assert [hit.symbol for hit in zebra] == ["ZZZZ"]
    blocked = {hit.symbol for hit in await adapter.search("bitcoin")}
    blocked |= {hit.symbol for hit in await adapter.search("VTSAX")}
    blocked |= {hit.symbol for hit in await adapter.search("AAPL260116C00150000")}
    assert blocked.isdisjoint({"BTC/USD", "VTSAX", "AAPL260116C00150000"})
