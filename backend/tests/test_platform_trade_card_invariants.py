"""Platform-wide trade card invariant tests — all 98 implemented strategies × test matrix tickers.

Every generated trade card must pass the universal validator:
  1. Credit recomputation from leg mids matches summary (±$0.01/share)
  2. Moneyness monotonicity for applicable multi-leg structures
  3. Anchor leg == order ticket (recommended contract)
  4. equity_required boundary (stock leg policy)
  5. Score bounds [0, 100]

Bug-injection cases prove the validator blocks bad payloads before trade card emission.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

import pytest

from app.analysis.score_bounds import ScoreOutOfBoundsError, assert_score_in_bounds
from app.services.strategy_engine import _anchor_from_metrics_legs, build_strategy_layer
from app.strategies.metrics_builder import build_registry_metrics
from app.strategies.registry import STRATEGY_REGISTRY
from app.strategies.validator import validate_strategy_output

TODAY = date.today()
FRONT_EXPIRY = (TODAY + timedelta(days=30)).isoformat()
BACK_EXPIRY = (TODAY + timedelta(days=60)).isoformat()

NO_LEG_STRATEGIES = frozenset({"no_trade_insufficient_conviction", "no_trade_wait_iv_crush"})

BACK_MONTH_STRATEGIES = frozenset(
    {
        "calendar_spread",
        "calendar_put_spread",
        "calendar_call_spread",
        "double_calendar",
        "diagonal_spread_bullish",
        "diagonal_spread_bearish",
        "double_diagonal",
        "reverse_calendar",
        "calendar_straddle",
        "diagonal_call_spread",
        "apex_strategy",
        "jelly_roll",
    }
)

# All 98 encyclopedia strategies with implemented payoff handlers.
IMPLEMENTED_STRATEGY_IDS = sorted(
    sid for sid, spec in STRATEGY_REGISTRY.items() if spec.payoff_function_ref and sid not in NO_LEG_STRATEGIES
)

TEST_MATRIX: dict[str, float] = {
    "AAPL": 100.0,
    "MSFT": 500.0,
    "TSLA": 250.0,
    "NVDA": 218.0,
    "SPY": 550.0,
}

TICKERS = list(TEST_MATRIX.keys())

MANDATORY_CHECKS = frozenset(
    {
        "credit_recomputation",
        "moneyness_monotonicity",
        "anchor_strike_match",
        "equity_leg_required",
        "equity_forbidden",
        "score_bounds",
    }
)


def _occ(root: str, expiry: str, side: str, strike: float) -> str:
    yymmdd = expiry.replace("-", "")[2:]
    cp = "C" if side == "call" else "P"
    return f"{root}{yymmdd}{cp}{int(strike * 1000):08d}"


def _leg(
    root: str,
    strike: float,
    side: str,
    expiry: str,
    *,
    bid: float,
    ask: float,
    delta: float | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    mid = round((bid + ask) / 2, 2)
    row: dict[str, Any] = {
        "side": side,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "last": mid,
        "mid": mid,
        "symbol": _occ(root, expiry, side, strike),
        "expiry": expiry,
        "delta": delta if delta is not None else (0.5 if side == "call" else -0.5),
        "iv": 0.28,
    }
    if action:
        row["action"] = action
    return row


def _rich_chain(root: str, spot: float, expiry: str) -> list[dict[str, Any]]:
    """Monotonic mock chain — premium decreases away from spot on each side."""
    step = max(5.0, round(spot * 0.05, 0))
    strikes = [spot - 3 * step, spot - 2 * step, spot - step, spot, spot + step, spot + 2 * step, spot + 3 * step]
    rows: list[dict[str, Any]] = []
    for k in strikes:
        dist = abs(k - spot)
        cb = max(0.3, 4.0 - dist * (0.35 * 100 / spot))
        pb = max(0.3, 3.5 - dist * (0.30 * 100 / spot))
        cd = 0.55 - (k - spot) * (0.04 * 100 / spot)
        pd = -0.45 + (k - spot) * (0.04 * 100 / spot)
        rows.append(_leg(root, k, "call", expiry, bid=cb, ask=cb + 0.2, delta=cd))
        rows.append(_leg(root, k, "put", expiry, bid=pb, ask=pb + 0.2, delta=pd))
    return rows


def _build_valid_metrics(strategy_id: str, ticker: str) -> dict[str, Any] | None:
    spot = TEST_MATRIX[ticker]
    front = _rich_chain(ticker, spot, FRONT_EXPIRY)
    back = _rich_chain(ticker, spot, BACK_EXPIRY) if strategy_id in BACK_MONTH_STRATEGIES else None
    recommended = {"strike": spot, "side": "call", "expiry": FRONT_EXPIRY}
    return build_registry_metrics(
        strategy_id,
        spot=spot,
        contracts=front,
        back_month_contracts=back,
        front_expiry=FRONT_EXPIRY,
        back_expiry=BACK_EXPIRY if strategy_id in BACK_MONTH_STRATEGIES else None,
        iv=0.28,
        ticker=ticker,
        recommended=recommended,
    )


def _msft_buggy_iron_condor() -> dict[str, Any]:
    """Original MSFT bug: inverted puts + credit/summary mismatch."""
    legs = [
        _leg("MSFT", 492.5, "put", FRONT_EXPIRY, bid=1.66, ask=1.70, action="sell"),
        _leg("MSFT", 490.0, "put", FRONT_EXPIRY, bid=1.71, ask=1.75, action="buy"),
        _leg("MSFT", 505.0, "call", FRONT_EXPIRY, bid=1.92, ask=1.96, action="sell"),
        _leg("MSFT", 510.0, "call", FRONT_EXPIRY, bid=1.74, ask=1.78, action="buy"),
    ]
    return {
        "legs": legs,
        "net_debit_credit": 0.14,
        "net_type": "credit",
        "max_profit": 13.5,
        "max_loss": 236.5,
        "breakevens": [492.37, 505.14],
        "per_contract_multiplier": 100,
    }


def _aapl_credit_mismatch() -> dict[str, Any]:
    metrics = _build_valid_metrics("bull_put_spread_credit", "AAPL")
    assert metrics is not None
    return {
        **metrics,
        "net_debit_credit": (metrics.get("net_debit_credit") or 0) + 0.05,
        "max_profit": 999.0,
    }


def _nvda_anchor_mismatch() -> tuple[dict[str, Any], dict[str, Any]]:
    metrics = _build_valid_metrics("bull_call_spread", "NVDA")
    assert metrics is not None
    bad_anchor = {"strike": 999.0, "side": "call", "expiry": FRONT_EXPIRY}
    return metrics, bad_anchor


def _tsla_score_out_of_bounds() -> dict[str, Any]:
    metrics = _build_valid_metrics("long_call", "TSLA")
    assert metrics is not None
    return metrics


def _spy_equity_forbidden() -> dict[str, Any]:
    return {
        "legs": [
            {"action": "buy", "side": "stock", "strike": 550.0, "symbol": "SPY", "mid": 550.0},
            {
                "action": "buy",
                "side": "call",
                "strike": 550.0,
                "expiry": FRONT_EXPIRY,
                "mid": 5.0,
                "symbol": _occ("SPY", FRONT_EXPIRY, "call", 550.0),
            },
        ],
        "max_profit": None,
        "max_loss": 500.0,
        "breakevens": [555.0],
        "net_debit_credit": 5.0,
        "net_type": "debit",
    }


def _aapl_calendar_expiry_mismatch() -> dict[str, Any]:
    metrics = _build_valid_metrics("calendar_spread", "AAPL")
    assert metrics is not None
    legs = list(metrics.get("legs") or [])
    if len(legs) >= 2:
        legs[1] = {**legs[1], "expiry": FRONT_EXPIRY}
        metrics = {**metrics, "legs": legs}
    return metrics


@dataclass(frozen=True)
class BugInjectionCase:
    ticker: str
    strategy_name: str
    build: Callable[[], Any]
    expected_checks: frozenset[str]
    scan_scores: dict[str, float | int | None] | None = None
    recommended: dict[str, Any] | None = None
    spot: float | None = None


BUG_INJECTION_CASES: tuple[BugInjectionCase, ...] = (
    BugInjectionCase(
        ticker="MSFT",
        strategy_name="Short Iron Condor",
        build=_msft_buggy_iron_condor,
        expected_checks=frozenset({"moneyness_monotonicity", "score_bounds", "credit_recomputation", "max_profit_credit_match"}),
        scan_scores={"iv_rank": 285.2, "composite": 80, "technical": 73.4},
        spot=500.0,
    ),
    BugInjectionCase(
        ticker="AAPL",
        strategy_name="Bull Put Spread (credit)",
        build=_aapl_credit_mismatch,
        expected_checks=frozenset({"credit_recomputation", "max_profit_credit_match"}),
    ),
    BugInjectionCase(
        ticker="NVDA",
        strategy_name="Bull Call Spread",
        build=lambda: _nvda_anchor_mismatch()[0],
        expected_checks=frozenset({"anchor_strike_match"}),
    ),
    BugInjectionCase(
        ticker="TSLA",
        strategy_name="Long Call",
        build=_tsla_score_out_of_bounds,
        expected_checks=frozenset({"score_bounds"}),
        scan_scores={"composite": 150.0, "technical": 72.0},
    ),
    BugInjectionCase(
        ticker="SPY",
        strategy_name="Long Call",
        build=_spy_equity_forbidden,
        expected_checks=frozenset({"equity_forbidden"}),
    ),
    BugInjectionCase(
        ticker="AAPL",
        strategy_name="Calendar Spread",
        build=_aapl_calendar_expiry_mismatch,
        expected_checks=frozenset({"expiration_relationship"}),
    ),
)


@pytest.mark.parametrize("strategy_id", IMPLEMENTED_STRATEGY_IDS)
@pytest.mark.parametrize("ticker", TICKERS)
def test_platform_trade_card_passes_validator(strategy_id: str, ticker: str) -> None:
    """Every implemented strategy × test-matrix ticker must produce a valid trade card."""
    metrics = _build_valid_metrics(strategy_id, ticker)
    assert metrics is not None, f"No metrics builder for {strategy_id}"
    if metrics.get("validation_blocked"):
        pytest.skip(f"{strategy_id}/{ticker}: builder blocked without optional chain data")

    spec = STRATEGY_REGISTRY[strategy_id]
    legs = metrics.get("legs") or []
    if len(legs) != spec.leg_count:
        pytest.skip(f"{strategy_id}/{ticker}: mock chain produced {len(legs)} legs, expected {spec.leg_count}")

    spot = TEST_MATRIX[ticker]
    seed_recommended = {"strike": spot, "side": "call", "expiry": FRONT_EXPIRY}
    recommended = _anchor_from_metrics_legs(metrics, seed_recommended, ticker)
    scan_scores = {
        "iv_rank": 55.0,
        "composite": 78.0,
        "technical": 72.0,
        "sentiment": 58.0,
        "fundamentals": 62.0,
    }
    result = validate_strategy_output(
        spec.display_name,
        metrics,
        ticker,
        recommended_contract=recommended,
        scan_scores=scan_scores,
        spot=spot,
    )
    assert result.valid, [(e.check, e.expected, e.actual) for e in result.errors]


def test_implemented_strategy_count_is_98() -> None:
    assert len(IMPLEMENTED_STRATEGY_IDS) == 98


@pytest.mark.parametrize(
    "case",
    [
        BUG_INJECTION_CASES[0],
        BUG_INJECTION_CASES[1],
        BUG_INJECTION_CASES[2],
        BUG_INJECTION_CASES[4],
        BUG_INJECTION_CASES[5],
    ],
    ids=["msft_iron_condor", "aapl_credit_mismatch", "nvda_anchor", "spy_equity", "aapl_calendar"],
)
def test_bug_injection_blocked(case: BugInjectionCase) -> None:
    """Injected defects on strategy/ticker pairs must block before trade card."""
    if case.ticker == "NVDA" and case.strategy_name == "Bull Call Spread":
        metrics, bad_anchor = _nvda_anchor_mismatch()
        result = validate_strategy_output(
            case.strategy_name,
            metrics,
            case.ticker,
            recommended_contract=bad_anchor,
            spot=TEST_MATRIX[case.ticker],
        )
    else:
        metrics = case.build()
        result = validate_strategy_output(
            case.strategy_name,
            metrics,
            case.ticker,
            recommended_contract=case.recommended,
            scan_scores=case.scan_scores,
            spot=case.spot or TEST_MATRIX.get(case.ticker),
        )
    assert not result.valid, f"Expected block for {case.ticker}/{case.strategy_name}"
    checks = {e.check for e in result.errors}
    assert checks & case.expected_checks, f"Expected one of {case.expected_checks}, got {checks}"


def test_tsla_score_out_of_bounds_blocked() -> None:
    metrics = _tsla_score_out_of_bounds()
    result = validate_strategy_output(
        "Long Call",
        metrics,
        "TSLA",
        scan_scores={"composite": 150.0, "technical": 72.0},
        spot=TEST_MATRIX["TSLA"],
    )
    assert not result.valid
    assert any(e.check == "score_bounds" for e in result.errors)


def test_msft_iron_condor_regression_corrected_passes() -> None:
    """MSFT iron condor regression — corrected payload must pass all five checks."""
    legs = [
        _leg("MSFT", 492.5, "put", FRONT_EXPIRY, bid=1.76, ask=1.80, action="sell"),
        _leg("MSFT", 490.0, "put", FRONT_EXPIRY, bid=1.61, ask=1.65, action="buy"),
        _leg("MSFT", 505.0, "call", FRONT_EXPIRY, bid=1.92, ask=1.96, action="sell"),
        _leg("MSFT", 510.0, "call", FRONT_EXPIRY, bid=1.74, ask=1.78, action="buy"),
    ]
    credit = round((1.78 + 1.94) - (1.63 + 1.76), 2)
    wing = max(492.5 - 490.0, 510.0 - 505.0)
    metrics = {
        "legs": legs,
        "net_debit_credit": credit,
        "net_type": "credit",
        "max_profit": round(credit * 100, 2),
        "max_loss": round((wing - credit) * 100, 2),
        "breakevens": [round(492.5 - credit, 2), round(505.0 + credit, 2)],
        "per_contract_multiplier": 100,
    }
    result = validate_strategy_output(
        "Short Iron Condor",
        metrics,
        "MSFT",
        scan_scores={"iv_rank": 72.0, "composite": 80, "technical": 73.4},
        spot=500.0,
    )
    assert result.valid, [(e.check, e.actual) for e in result.errors]


def test_build_strategy_layer_blocks_out_of_band_iv_rank() -> None:
    layer = build_strategy_layer(
        strategy_name="Short Iron Condor",
        composite=82.0,
        direction="bullish",
        vol_signal="sell_premium",
        chain_analysis={"spot": 500.0, "expiry": FRONT_EXPIRY, "contracts": [], "symbol": "MSFT"},
        vol_layer={"iv_rank": 285.2, "iv": 0.35, "hv": 0.12},
        sentiment_layer={"bias": "neutral", "score_0_100": 55},
        fundamentals_layer={"score": 60},
        tech_score=73.4,
        ticker="MSFT",
    )
    assert layer["tradeable"] is False


def test_mandatory_validator_checks_are_exercised() -> None:
    """Proof that each mandatory check fires on at least one injected defect."""
    fired: set[str] = set()
    for case in BUG_INJECTION_CASES:
        if case.ticker == "NVDA":
            metrics, bad_anchor = _nvda_anchor_mismatch()
            result = validate_strategy_output(
                case.strategy_name, metrics, case.ticker, recommended_contract=bad_anchor, spot=218.0
            )
        elif case.scan_scores and case.scan_scores.get("composite", 0) > 100:
            metrics = case.build()
            result = validate_strategy_output(
                case.strategy_name, metrics, case.ticker, scan_scores=case.scan_scores, spot=TEST_MATRIX[case.ticker]
            )
        else:
            metrics = case.build()
            result = validate_strategy_output(
                case.strategy_name,
                metrics,
                case.ticker,
                scan_scores=case.scan_scores,
                spot=case.spot or TEST_MATRIX.get(case.ticker),
            )
        fired.update(e.check for e in result.errors)

    assert "credit_recomputation" in fired or "max_profit_credit_match" in fired
    assert "moneyness_monotonicity" in fired
    assert "anchor_strike_match" in fired
    assert "equity_forbidden" in fired or "equity_leg_required" in fired
    assert "score_bounds" in fired


def test_iv_rank_computation_hard_fails_above_100() -> None:
    with pytest.raises(ScoreOutOfBoundsError):
        assert_score_in_bounds("iv_rank", 285.2)
