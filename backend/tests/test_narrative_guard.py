"""Narrative numbers, dates, tickers, and qualitative claims must come from the ledger."""

from __future__ import annotations

import pytest
from loguru import logger

from app.services.evidence_ledger import record_card_value, reset_ledger
from app.services.narrative_guard import check_narrative, rejections, reset_rejections

_META = {
    "source": "alpaca",
    "feed": "indicative",
    "timestamp": "2026-10-05T14:00:00Z",
    "fn": "card_field",
}


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_ledger()
    reset_rejections()
    yield
    reset_ledger()
    reset_rejections()


def _seed() -> None:
    record_card_value(
        "scan-1",
        "symbol",
        "AAPL",
        inputs={"symbol": "AAPL"},
        **_META,
    )
    record_card_value(
        "scan-1",
        "composite",
        62.9,
        inputs={"technicals": 18.4, "volatility": 15.0},
        **_META,
    )
    record_card_value(
        "scan-1",
        "expiry",
        "2026-10-16",
        inputs={"expiry": "2026-10-16"},
        **_META,
    )
    record_card_value(
        "scan-1",
        "iv",
        30.31,
        inputs={"atm_iv": 30.31},
        **_META,
    )
    record_card_value(
        "scan-1",
        "open_interest",
        1500,
        inputs={"contracts": 12},
        **_META,
    )


def test_hallucinated_percent_is_rejected_and_logged() -> None:
    _seed()
    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(message.record["message"]), level="WARNING")
    try:
        result = check_narrative(
            "AAPL composite is 62.9 and the probability is 99.9 percent.",
            scan_id="scan-1",
            strategy_id="bull_put_spread_credit",
        )
    finally:
        logger.remove(sink)
    assert result.accepted is False
    assert result.used_fallback is True
    assert any("99.9" in item for item in result.unmatched)
    assert "99.9" not in result.text
    again = check_narrative(result.text, scan_id="scan-1", strategy_id="bull_put_spread_credit")
    assert again.accepted is True
    assert again.used_fallback is False
    logged = rejections("scan-1")
    assert logged and logged[0]["unmatched"]
    assert any("narrative rejected" in line and "99.9" in line for line in lines)


def test_narrative_whose_figures_are_on_the_ledger_passes() -> None:
    _seed()
    text = "AAPL composite is 62.9 as of Oct 16, 2026 and IV is 30.3. Open interest is 1,500."
    result = check_narrative(text, scan_id="scan-1", strategy_id="bull_put_spread_credit")
    assert result.accepted is True
    assert result.unmatched == ()
    assert result.text == text
    assert rejections("scan-1") == []


def test_display_rounding_accepts_one_decimal_and_rejects_the_other_way() -> None:
    _seed()
    assert check_narrative("IV is 30.3.", scan_id="scan-1", strategy_id="bull_put_spread_credit").accepted is True
    rounded = check_narrative("IV is 30.4.", scan_id="scan-1", strategy_id="bull_put_spread_credit")
    assert rounded.accepted is False
    assert any("30.4" in item for item in rounded.unmatched)
    record_card_value(
        "scan-width",
        "width",
        30.35,
        inputs={"width": 30.35},
        **_META,
    )
    assert check_narrative("Width is 30.4.", scan_id="scan-width", strategy_id="bull_put_spread_credit").accepted is True
    assert check_narrative("Width is 30.3.", scan_id="scan-width", strategy_id="bull_put_spread_credit").accepted is False


@pytest.mark.parametrize("word", ["high", "low", "rich", "cheap"])
def test_qualitative_claim_cites_ledger_value_and_threshold(word: str) -> None:
    record_card_value(
        "scan-1",
        "iv",
        {"measured": 30.31, "threshold": 20.38, "verdict": word},
        inputs={"measured": 30.31, "threshold": 20.38, "hv": 20.38},
        **_META,
    )
    bare = check_narrative(f"Volatility is {word}.", scan_id="scan-1", strategy_id="bull_put_spread_credit")
    assert bare.accepted is False
    assert word in bare.qualitative
    value_only = check_narrative(
        f"Volatility is {word} at 30.31.",
        scan_id="scan-1",
        strategy_id="bull_put_spread_credit",
    )
    assert value_only.accepted is False
    cited = check_narrative(
        f"Volatility is {word} at 30.31 versus threshold 20.38.",
        scan_id="scan-1",
        strategy_id="bull_put_spread_credit",
    )
    assert cited.accepted is True
    split = check_narrative(
        f"Volatility is {word}. IV is 30.31 versus threshold 20.38.",
        scan_id="scan-1",
        strategy_id="bull_put_spread_credit",
    )
    assert split.accepted is False
    assert word in split.qualitative


def test_unknown_ticker_is_rejected() -> None:
    _seed()
    result = check_narrative("ZZZZ composite is 62.9.", scan_id="scan-1", strategy_id="bull_put_spread_credit")
    assert result.accepted is False
    assert "ZZZZ" in result.unmatched
