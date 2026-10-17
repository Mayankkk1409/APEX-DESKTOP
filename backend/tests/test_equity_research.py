"""Equity plans follow the masterbook scorecard and do not invent missing inputs."""

from app.services.equity_research import assemble_equity_research, parse_analyst_ratings, score_equity


def _facts(**overrides):
    base = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "as_of": "2026-10-14",
        "price": 100.0,
        "atr": 2.0,
        "support": 96.0,
        "resistance": 110.0,
        "trend": "up",
        "volume_ratio": 1.4,
        "technical_score": 72.0,
        "sentiment_score": 40.0,
        "news_count": 3,
        "fundamental_score": 70.0,
        "fundamental_trend": "improving",
        "is_etf": False,
        "earnings_date": None,
        "earnings_confirmed": False,
        "spread_pct": 0.001,
        "bars": 80,
        "shares_held": 0,
        "risk_profile": "moderate",
        "analysts": [],
    }
    base.update(overrides)
    return base


def test_bullish_setup_is_a_buy_with_one_target() -> None:
    plan = score_equity(_facts())
    assert plan["action"] == "Buy"
    assert plan["direction"] == "long"
    assert "upside case is the one that fits" in plan["fit"]
    assert plan["levels"]["entry"] == 100.0
    assert plan["levels"]["stop"] < plan["levels"]["entry"]
    assert plan["levels"]["take_profit"] == plan["levels"]["exit_target"]
    assert plan["levels"]["take_profit"] > plan["levels"]["entry"]
    assert plan["horizon"]["label"] == "Standard swing"
    assert plan["order_action"] is None
    assert "options_chain_greeks" not in plan["slides"]


def test_bearish_holding_is_a_sale_not_a_short() -> None:
    plan = score_equity(
        _facts(
            trend="down",
            sentiment_score=-40,
            fundamental_trend="deteriorating",
            shares_held=10,
            support=80,
            resistance=104,
        )
    )
    assert plan["action"] == "Sell"
    assert plan["action"] != "Short Sell"
    assert plan["short_available"] is False
    assert plan["direction"] == "down"
    assert plan["levels"]["stop"] > plan["levels"]["entry"]
    assert plan["levels"]["take_profit"] < plan["levels"]["entry"]
    assert "downside case is the one that fits" in plan["fit"]
    assert "above the entry" in plan["fit"]
    assert "sale of those shares" in plan["fit"]


def test_bearish_without_shares_does_not_invent_a_short() -> None:
    plan = score_equity(
        _facts(trend="down", sentiment_score=-40, fundamental_trend="deteriorating", support=80, resistance=104)
    )
    assert plan["action"] == "Avoid"
    assert "borrow" in plan["why"].lower() or "short" in plan["why"].lower()


def test_conflicting_evidence_holds_an_existing_position() -> None:
    plan = score_equity(
        _facts(trend="flat", volume_ratio=1.0, sentiment_score=0, fundamental_trend="neutral", shares_held=4)
    )
    assert plan["action"] == "Hold"
    assert plan["levels"]["stop"] < plan["levels"]["entry"]
    assert plan["levels"]["take_profit"] > plan["levels"]["entry"]


def test_earnings_inside_the_window_blocks_the_trade() -> None:
    plan = score_equity(_facts(timeframe="5m", earnings_date="2026-10-14", earnings_confirmed=True, earnings_source="NASDAQ"))
    assert plan["action"] == "Avoid"
    assert plan["earnings"]["inside_holding_window"] is True
    later = score_equity(_facts(earnings_date="2026-10-20", earnings_confirmed=True, earnings_source="NASDAQ"))
    assert later["earnings"]["inside_holding_window"] is False


def test_missing_news_is_not_scored_as_neutral() -> None:
    plan = score_equity(_facts(sentiment_score=None, news_count=0))
    assert plan["scores"]["sentiment"] is None
    assert "sentiment" in plan["scores"]["reweighted"]
    assert "sentiment" in plan["scorecard"]["bull"]["missing"]


def test_intraday_horizon_and_conservative_reward_gate() -> None:
    intraday = score_equity(_facts(timeframe="5m"))
    assert intraday["horizon"]["label"] == "Active intraday"
    hour = score_equity(_facts(timeframe="1H"))
    assert hour["horizon"]["label"] == "Swing confirmation"
    assert "same-session" in hour["horizon"]["detail"]
    tight = score_equity(_facts(risk_profile="conservative", atr=10, resistance=115))
    assert tight["action"] == "Avoid"
    assert "conservative" in tight["why"].lower()


def test_analyst_rows_keep_five_newest_named_ratings() -> None:
    payload = {
        "data": {
            "rows": [
                {"analyst": "A", "firm": "One", "rating": "Buy", "priceTarget": 10, "date": "2026-01-01"},
                {"analyst": "B", "firm": "Two", "rating": "Hold", "priceTarget": 11, "date": "2026-06-01"},
                {"firm": "Three", "rating": "Sell", "priceTarget": 9, "date": "2026-05-01"},
                {"analyst": "D", "firm": "Four", "rating": "Buy", "priceTarget": 12, "date": "2026-04-01"},
                {"analyst": "E", "firm": "Five", "rating": "Hold", "priceTarget": 8, "date": "2026-03-01"},
                {"analyst": "F", "firm": "Six", "rating": "Buy", "priceTarget": 13, "date": "2026-02-01"},
                {"rating": "Buy", "priceTarget": 99},
            ]
        }
    }
    rows = parse_analyst_ratings(payload)
    assert len(rows) == 5
    assert rows[0]["analyst"] == "B"
    assert rows[0]["source"] == "NASDAQ"
    assert all(row["rating"] for row in rows)


def test_options_flow_does_not_become_the_equity_sentiment_score() -> None:
    plan = assemble_equity_research(
        symbol="AAPL",
        timeframe="1D",
        as_of="2026-10-14",
        quote=type("Q", (), {"price": 100.0, "bid": 99.9, "ask": 100.1, "status": "live"})(),
        bars=[{"h": 101, "l": 99, "c": 100}] * 40,
        technical={"pattern_analysis": {"direction": "bullish", "score": 70, "patterns": []}},
        volume={"ratio": 1.3, "regime": "above"},
        fundamentals={"score": 60, "earnings_calendar": {}},
        sentiment={
            "score_0_100": 90,
            "components": {
                "news": {"score": None, "articles": [], "status": "empty"},
                "options_flow": {"score": 95},
            },
        },
        risk_profile="moderate",
        shares_held=0,
    )
    assert plan["scores"]["sentiment"] is None
    assert plan["research_mode"] == "equity"
    assert plan["order_action"] is None


def test_empty_analyst_feed_does_not_invent_names() -> None:
    assert parse_analyst_ratings({"data": {}}) == []
    plan = score_equity(_facts())
    assert plan["analysts"] == []
    assert "not on the feed" in plan["analyst_note"]
