from __future__ import annotations

import pytest

from app.config import Settings
from app.services import live_quotes as lq
from app.services.live_quotes import parse_number, parse_percent_fraction


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    lq.clear_quote_cache()


def test_parse_number_money_and_suffixes() -> None:
    assert parse_number("$309.35") == 309.35
    assert parse_number("7,674.37") == 7674.37
    assert parse_number("+33.21") == 33.21
    assert parse_number("-1.95") == -1.95
    assert parse_number("4.515T") == pytest.approx(4.515e12)
    assert parse_number("41.00M") == pytest.approx(41e6)
    assert parse_number("N/A") is None
    assert parse_number(None) is None


def test_parse_percent_fraction() -> None:
    assert parse_percent_fraction("0.35%") == pytest.approx(0.0035)
    assert parse_percent_fraction("0.09%") == pytest.approx(0.0009)
    assert parse_percent_fraction("-0.63%") == pytest.approx(-0.0063)


@pytest.mark.asyncio
async def test_aapl_from_cnbc_and_nasdaq(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_cnbc(sym: str):
        assert sym == "AAPL"
        return {
            "name": "Apple Inc.",
            "price": 309.35,
            "change": -1.95,
            "change_pct": -0.63,
            "open": 312.05,
            "high": 312.38,
            "low": 307.01,
            "volume": 39_519_444,
            "avg_volume": 41_000_000,
            "week_52_high": 344.57,
            "week_52_low": 224.69,
            "market_cap": 4.515e12,
            "pe_ttm": 35.60,
            "div_yield": 0.0035,
            "beta_5y": 1.08,
            "as_of": "08/21/26 EDT",
            "source": "CNBC",
        }

    async def fake_nasdaq(sym: str):
        assert sym == "AAPL"
        return {
            "name": "Apple Inc. Common Stock",
            "price": 309.35,
            "change": -1.95,
            "change_pct": -0.63,
            "volume": 46_876_985,
            "avg_volume": 56_243_543,
            "week_52_high": 344.5699,
            "week_52_low": 223.7804,
            "market_cap": 4_514_709_583_000,
            "div_yield": 0.0035,
            "expense_ratio": None,
            "as_of": "Aug 21, 2026",
            "asset_class": "stock",
            "source": "NASDAQ",
        }

    monkeypatch.setattr(lq, "_alpaca_stock", lambda *a, **k: _none())
    monkeypatch.setattr(lq, "_cnbc_quote", fake_cnbc)
    monkeypatch.setattr(lq, "_nasdaq_quote", fake_nasdaq)
    monkeypatch.setattr(lq, "_yahoo_chart", lambda *a, **k: _none())

    settings = Settings(alpaca_api_key_id="", alpaca_api_secret_key="")
    quote = await lq.get_live_quote("AAPL", settings)
    fund = await lq.get_live_fundamentals("AAPL", settings)
    assert quote.status == "live"
    assert quote.price == 309.35
    assert quote.name == "Apple Inc."
    assert quote.pe_ttm == 35.60
    assert quote.expense_ratio is None
    assert quote.source == "CNBC"
    assert fund.market_cap == 4.515e12 or fund.market_cap == 4_514_709_583_000
    assert fund.avg_volume == 41_000_000 or fund.avg_volume == 56_243_543
    assert "demo" not in (quote.source or "").lower()


@pytest.mark.asyncio
async def test_spx_is_index_not_spy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_cnbc(sym: str):
        assert sym == ".SPX"
        return {
            "name": "S&P 500 INDEX",
            "price": 7674.37,
            "change": 33.21,
            "change_pct": 0.43,
            "open": 7665.68,
            "high": 7697.11,
            "low": 7660.06,
            "week_52_high": 7816.70,
            "week_52_low": 6316.91,
            "as_of": "08/21/26 EDT",
            "source": "CNBC",
        }

    async def fail_nasdaq(sym: str):
        raise AssertionError("NASDAQ must not be queried for SPX as if it were a stock")

    monkeypatch.setattr(lq, "_alpaca_stock", lambda *a, **k: _none())
    monkeypatch.setattr(lq, "_cnbc_quote", fake_cnbc)
    monkeypatch.setattr(lq, "_nasdaq_quote", fail_nasdaq)
    monkeypatch.setattr(lq, "_yahoo_chart", lambda *a, **k: _none())

    settings = Settings(alpaca_api_key_id="", alpaca_api_secret_key="")
    quote = await lq.get_live_quote("SPX", settings)
    fund = await lq.get_live_fundamentals("SPX", settings)
    assert quote.symbol == "SPX"
    assert quote.name == "S&P 500 INDEX"
    assert quote.price == 7674.37
    assert quote.price != pytest.approx(765.72, rel=0.02)  # not SPY
    assert quote.expense_ratio is None
    assert quote.market_cap is None
    assert "not SPY" in (quote.secondary_source or "")
    assert "CNBC" in (quote.source or "")
    assert fund.expense_ratio is None


@pytest.mark.asyncio
async def test_alpaca_price_wins_over_secondary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_alpaca(sym: str, settings):
        assert settings.alpaca_keys_present
        return {
            "price": 310.01,
            "change": 0.66,
            "change_pct": 0.21,
            "open": 309.10,
            "high": 311.20,
            "low": 308.00,
            "volume": 12_000_000,
            "avg_volume": 50_000_000,
            "week_52_high": 350.0,
            "week_52_low": 210.0,
            "name": "Apple Inc.",
            "asset_class": "stock",
            "as_of": "2026-08-21T20:00:00+00:00",
            "source": "Alpaca",
        }

    async def fake_cnbc(sym: str):
        return {"name": "Apple Inc.", "price": 1.0, "change": 0, "change_pct": 0, "pe_ttm": 35.6, "beta_5y": 1.08, "div_yield": 0.0035, "source": "CNBC"}

    async def fake_nasdaq(sym: str):
        return {"market_cap": 4_514_709_583_000, "avg_volume": 56_243_543, "source": "NASDAQ", "asset_class": "stock"}

    monkeypatch.setattr(lq, "_alpaca_stock", fake_alpaca)
    monkeypatch.setattr(lq, "_cnbc_quote", fake_cnbc)
    monkeypatch.setattr(lq, "_nasdaq_quote", fake_nasdaq)
    monkeypatch.setattr(lq, "_yahoo_chart", lambda *a, **k: _none())

    settings = Settings(alpaca_api_key_id="PKTESTNOTREAL", alpaca_api_secret_key="secret-not-real")
    quote = await lq.get_live_quote("AAPL", settings)
    assert quote.price == 310.01
    assert quote.source == "Alpaca"
    assert quote.pe_ttm == 35.6
    assert quote.market_cap == 4_514_709_583_000
    assert quote.expense_ratio is None


@pytest.mark.asyncio
async def test_unavailable_does_not_invent_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lq, "_alpaca_stock", lambda *a, **k: _none())
    monkeypatch.setattr(lq, "_cnbc_quote", lambda *a, **k: _none())
    monkeypatch.setattr(lq, "_nasdaq_quote", lambda *a, **k: _none())
    monkeypatch.setattr(lq, "_yahoo_chart", lambda *a, **k: _none())
    settings = Settings(alpaca_api_key_id="", alpaca_api_secret_key="")
    quote = await lq.get_live_quote("AAPL", settings)
    assert quote.status == "unavailable"
    assert quote.price is None
    assert quote.open is None
    assert quote.pe_ttm is None
    assert quote.week_52_high is None
    assert quote.source == "unavailable"


async def _none(*_a, **_k):
    return None
