from __future__ import annotations

import pytest

from app.analysis.news_nlp import score_articles, score_text
from app.config import Settings
from app.schemas.market import OptionChain, OptionContract, Quote
from app.services import fundamentals_layer as fl
from app.services import sentiment_layer as sl


def test_news_nlp_bullish_and_bearish() -> None:
    assert score_text("Apple beats estimates on strong growth") is not None
    assert (score_text("Apple beats estimates on strong growth") or 0) > 0
    assert (score_text("Shares plunge after downgrade and lawsuit") or 0) < 0
    assert score_text("") is None
    assert score_text(None) is None


def test_score_articles_mean() -> None:
    mean, rows = score_articles(
        [
            {"headline": "Upgrade lifts rally", "summary": "Bullish outlook", "source": "benzinga", "created_at": "2026-01-01"},
            {"headline": "Quiet session", "summary": "Tape mixed", "source": "benzinga", "created_at": "2026-01-02"},
        ]
    )
    assert mean is not None
    assert len(rows) == 2
    assert rows[0]["nlp_method"] == "lexicon_v1"


def test_pc_signal_thresholds() -> None:
    fear_s, fear_l = sl._pc_signal(1.5)
    bull_s, bull_l = sl._pc_signal(0.5)
    mid_s, mid_l = sl._pc_signal(0.95)
    assert fear_l == "fear" and (fear_s or 0) < 0
    assert bull_l == "aggressive_bullish" and (bull_s or 0) > 0
    assert mid_l == "neutral"
    assert mid_s is not None
    assert sl._pc_signal(None)[0] is None


def test_flow_never_invents_notional_without_quotes() -> None:
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-09-18",
        feed="indicative",
        contracts=[
            OptionContract(symbol="AAPL260918C00200000", strike=200, side="call", volume=100, bid=None, ask=None),
            OptionContract(symbol="AAPL260918P00200000", strike=200, side="put", volume=40, bid=None, ask=None),
        ],
        source="test",
    )
    flow = sl._flow_from_chain(chain, None)
    assert flow["call_volume"] == 100
    assert flow["put_volume"] == 40
    assert flow["put_call_volume_ratio"] == pytest.approx(0.4)
    assert flow["call_notional_proxy"] is None
    assert flow["put_notional_proxy"] is None
    assert flow["score"] is not None  # falls back to P/C


def test_synthesis_cites_numbers() -> None:
    text = sl._synthesis_paragraph(
        "AAPL",
        band="Bullish",
        score_0_100=69.0,
        composite=38.0,
        news_score=25.0,
        news_count=5,
        constructive=3,
        negative=1,
        neutral=1,
        sample_headlines=["Analyst upgrade sparks rally", "Services growth beats estimates"],
        flow_score=40.0,
        flow_label="bullish",
        call_vol=12000,
        put_vol=8000,
        avg_equity_vol=50_000_000,
        pc_ratio=0.67,
        pc_label="aggressive_bullish",
        pc_score=38.0,
        volume_context=None,
        notional_skew="call-heavy notional skew",
        renorm={"news": 0.45, "options_flow": 0.35, "put_call": 0.20},
        parts={"news": 25.0, "options_flow": 40.0, "put_call": 38.0},
        earnings_message=None,
    )
    assert "5 articles" in text or "5-article" in text or "5 recent" in text
    assert "constructive" in text.lower()
    assert "12,000 call contracts" in text
    assert "put/call ratio at 0.67" in text.lower()
    assert "bullish read" in text.lower()
    assert "×" not in text
    assert "lexicon" not in text.lower()
    assert "Score 69" not in text
    assert "3 constructive" not in text


@pytest.mark.asyncio
async def test_sentiment_drops_social_and_uses_news(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_news(symbol: str, settings: Settings, *, limit: int = 20):
        return (
            [
                {
                    "headline": "Analyst upgrade sparks rally",
                    "summary": "Strong growth outlook",
                    "source": "benzinga",
                    "created_at": "2026-08-24T12:00:00Z",
                    "url": "https://example.com/a",
                    "symbols": ["AAPL"],
                }
            ],
            None,
        )

    monkeypatch.setattr(sl, "_fetch_alpaca_news", fake_news)
    settings = Settings(alpaca_api_key_id="x", alpaca_api_secret_key="y")
    out = await sl.build_sentiment_layer("AAPL", settings, chain=None, fundamentals=None)
    assert out["components"]["social"]["status"] == "unavailable"
    assert out["components"]["social"]["score"] is None
    assert out["components"]["news"]["count"] == 1
    assert out["score"] is not None
    assert -100 <= out["score"] <= 100
    assert out.get("band")
    assert "article" in out["narrative"].lower()
    assert "×" not in out["narrative"]


@pytest.mark.asyncio
async def test_fundamentals_missing_fields_stay_none(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(*_a, **_k):
        return {"status": "unavailable", "source": None}

    async def empty_profile(*_a, **_k):
        return {"status": "unavailable", "source": None, "sector": None, "industry": None, "company_name": None}

    async def empty_surprise(*_a, **_k):
        return {"status": "unavailable", "source": None, "history": [], "consecutive_beats": None, "latest": None, "trend": "unavailable"}

    async def empty_analyst(*_a, **_k):
        return {"status": "unavailable", "source": None, "price_target": None, "buy": None, "hold": None, "sell": None, "coverage": None, "consensus_label": None}

    async def empty_income(*_a, **_k):
        return {"status": "unavailable", "source": None, "revenue": None, "revenue_prior": None, "revenue_yoy_pct": None, "revenue_signal": None, "net_income": None, "net_income_prior": None, "net_income_yoy_pct": None}

    async def empty_cal(symbol, surprise, asset_class=None):
        return {"status": "unavailable", "next_date": None, "dte": None, "last_reported": None, "source": None, "caveat": "missing"}

    async def empty_rot(sector, settings=None):
        return {"status": "unavailable", "source": None, "caveat": "no sector"}

    class FakeFund:
        def model_dump(self):
            return {"symbol": "ZZZ", "source": "unavailable", "pe_ttm": None, "market_cap": None}

        symbol = "ZZZ"
        name = "ZZZ"
        source = "unavailable"
        pe_ttm = None
        market_cap = None
        div_yield = None
        beta_5y = None
        avg_volume = None
        expense_ratio = None
        status = "unavailable"
        as_of = None
        asset_class = None

    async def fake_base(*_a, **_k):
        return FakeFund()

    monkeypatch.setattr(fl, "get_live_fundamentals", fake_base)
    monkeypatch.setattr(fl, "_earnings_surprise", empty_surprise)
    monkeypatch.setattr(fl, "_analyst_targets", empty_analyst)
    monkeypatch.setattr(fl, "_earnings_forecast", empty)
    monkeypatch.setattr(fl, "_income_annual", empty_income)
    monkeypatch.setattr(fl, "_company_profile", empty_profile)
    monkeypatch.setattr(fl, "_sector_rotation", empty_rot)
    monkeypatch.setattr(fl, "_earnings_calendar", empty_cal)

    quote = Quote(symbol="ZZZ", name="ZZZ", source="unavailable", status="unavailable")
    out = await fl.build_fundamentals_layer("ZZZ", quote, Settings())
    assert out["company_health"]["pe_ttm"] is None
    assert out["company_health"]["revenue"] is None
    assert out["earnings_calendar"]["next_date"] is None
    assert out["analyst"]["price_target"] is None
    assert len(out.get("factor_cards") or []) == 5


def test_humanize_label() -> None:
    assert fl._humanize_label("consecutive_beats") == "Consecutive Beats"
    assert fl._humanize_label("out_of") == "Out Of"
    assert fl._humanize_label("") == ""


def test_build_factor_cards_verbose_no_copout() -> None:
    cards = fl._build_factor_cards(
        "AAPL",
        profile={"sector": "Technology", "industry": "Consumer Electronics"},
        rotation={
            "status": "live",
            "sector": "Technology",
            "etf": "XLK",
            "benchmark": "SPY",
            "sector_return_pct": 1.25,
            "spy_return_pct": 0.4,
            "relative_pct": 0.85,
            "flow": "into",
        },
        health={
            "week_52_high": 200.0,
            "week_52_low": 150.0,
            "market_cap": 3e12,
            "div_yield": 0.5,
            "beta_5y": 1.2,
        },
        income={
            "revenue_yoy_pct": 8.5,
            "revenue_signal": "moderate",
            "revenue": 400_000,
            "revenue_prior": 368_000,
            "period_current": "2024",
            "period_prior": "2023",
            "net_income_yoy_pct": 10.0,
        },
        surprise={
            "consecutive_beats": 3,
            "trend": "consecutive_beats",
            "latest": {"eps": 1.5, "consensus": 1.4, "surprise_pct": 7.1, "fiscal_quarter": "Q2 2024"},
            "history": [{"eps": 1.5, "consensus": 1.4, "surprise_pct": 7.1, "fiscal_quarter": "Q2 2024"}],
        },
        analyst={
            "consensus_label": "Buy",
            "price_target": 210.0,
            "low_target": 180.0,
            "high_target": 240.0,
            "buy": 25,
            "hold": 5,
            "sell": 1,
            "coverage": 31,
        },
        calendar={
            "next_date": "2026-10-30",
            "dte": 66,
            "last_reported": "2026-07-25",
            "source": "NASDAQ earnings-date",
            "time": "after market close",
        },
        forecast={
            "next_quarter": {
                "consensus_eps": 1.55,
                "low_eps": 1.4,
                "high_eps": 1.7,
                "estimates": 28,
                "revisions_up": 4,
                "revisions_down": 1,
            }
        },
        pe=28.5,
        spot=185.0,
        target=210.0,
        upside=13.51,
    )
    assert len(cards) == 5
    sector = cards[0]["body"]
    assert "limited on this pass" not in sector.lower()
    assert "XLK" in sector
    assert "SPY" in sector
    assert len(sector) > 120
    assert "Consecutive Beats" in cards[2]["body"] or "consecutive" in cards[2]["body"].lower()
    assert "Buy" in cards[3]["body"]
    assert "2026-10-30" in cards[4]["body"]


def test_googl_earnings_date_is_estimated_not_confirmed() -> None:
    from app.services.fundamentals_layer import attach_event_risk, resolve_earnings_info

    info = resolve_earnings_info("GOOGL", asset_class="stock")
    assert info["date"] == "2026-10-28"
    assert info["status"] == "estimated"
    assert info["display"] == "2026-10-28 est."
    assert any("MarketBeat" in source for source in info["sources"])
    assert info["date"] != "none"
    assert "none" not in {str(info["date"]).lower(), str(info["status"]).lower()}
    flagged = attach_event_risk(dict(info), "2026-10-30")
    assert flagged["event_risk"] is False


def test_spy_and_qqq_skip_the_unconfirmed_earnings_check() -> None:
    from app.services.fundamentals_layer import earnings_unconfirmed_applies, resolve_earnings_info

    for symbol in ("SPY", "QQQ"):
        info = resolve_earnings_info(symbol, asset_class="etf")
        assert info["securityType"] == "etf"
        assert info["earnings_applicable"] is False
        assert info["date"] is None
        assert info["status"] == "unknown"
        assert earnings_unconfirmed_applies(info) is False
        assert info["date"] != "none"
    from_catalog = resolve_earnings_info("QQQ")
    assert from_catalog["securityType"] == "etf"
    assert earnings_unconfirmed_applies(from_catalog) is False


def test_confirmed_ir_date_is_kept_and_a_conflict_is_unknown() -> None:
    from app.services.fundamentals_layer import attach_event_risk, resolve_earnings_info

    agreed = resolve_earnings_info("JPM", provider_dates=[("2026-10-13", "NASDAQ earnings-date")])
    assert agreed["date"] == "2026-10-13"
    assert agreed["status"] == "confirmed"
    assert any("jpmorganchase.com" in source for source in agreed["sources"])
    for symbol in ("GS", "C", "JNJ", "UNH"):
        confirmed = resolve_earnings_info(symbol, provider_dates=[("2026-10-13", "NASDAQ earnings-date")])
        assert confirmed["date"] == "2026-10-13"
        assert confirmed["status"] == "confirmed"
    clash = resolve_earnings_info("JPM", provider_dates=[("2026-10-14", "NASDAQ earnings-date")])
    assert clash["date"] is None
    assert clash["status"] == "unknown"
    assert clash["unverified"] is True
    assert clash["display"] is None
    missing = resolve_earnings_info("NVDA", asset_class="us_equity")
    assert missing["date"] is None
    assert missing["status"] == "unknown"
    assert missing["date"] != "none"
    risky = attach_event_risk(dict(missing), "2026-10-30")
    assert risky["event_risk"] is True
    later = attach_event_risk(dict(missing), "2026-12-18")
    assert later["event_risk"] is False
