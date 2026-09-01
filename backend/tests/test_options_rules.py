"""Rule-engine tests for Full Document §5 (options chain) and §9.1 (Rule 1 / Rule 2).

Boundaries are asserted on both sides of every documented threshold, because a gate that is
off by one tick is a gate that silently admits a trade the docs reject.
"""

from __future__ import annotations

import pytest

from app.analysis.options_rules import (
    ChainContext,
    DEFAULT_THRESHOLDS,
    RuleThresholds,
    build_uoa_reference,
    delta_theta_ratio,
    evaluate_chain,
    evaluate_contract,
    mid_price,
    spread_metrics,
)
from app.schemas.market import OptionContract


def contract(**kw) -> OptionContract:
    """A liquid, tight, gradeable call. Tests override only the field under test."""
    base = dict(
        symbol="TEST240920C00100000",
        strike=100.0,
        side="call",
        bid=0.95,
        ask=1.05,
        last=1.0,
        volume=500,
        open_interest=1000,
        iv=0.30,
        delta=0.60,
        gamma=0.02,
        theta=-0.05,
        vega=0.08,
        greeks_source="vendor",
        iv_source="vendor",
    )
    base.update(kw)
    return OptionContract(**base)


def ctx(**kw) -> ChainContext:
    base = dict(
        symbol="TEST",
        expiry="2026-09-20",
        dte=30,
        spot=100.0,
        atm_strike=100.0,
        uoa_reference={"call": 100.0, "put": 100.0},
        uoa_basis="test baseline",
        atm_iv=0.30,
        hv=0.28,
    )
    base.update(kw)
    return ChainContext(**base)


def gate(verdict, gate_id):
    return next(g for g in verdict.gates if g.id == gate_id)


# ── §5.5 bid/ask spread — the only hard reject ────────────────────────────────


def test_spread_exactly_at_cap_passes() -> None:
    v = evaluate_contract(contract(bid=0.95, ask=1.05), ctx())
    assert v.spread_pct_of_mid == pytest.approx(0.10)
    assert gate(v, "spread").status == "pass"
    assert v.hard_reject is False
    assert v.verdict != "rejected"


def test_spread_one_tick_over_cap_is_hard_rejected() -> None:
    v = evaluate_contract(contract(bid=0.9495, ask=1.0505), ctx())
    assert v.spread_pct_of_mid > 0.10
    assert gate(v, "spread").status == "fail"
    assert v.hard_reject is True
    assert v.verdict == "rejected"
    assert any("exceeds" in r for r in v.reasons)


def test_very_wide_spread_reports_the_computed_percentage() -> None:
    v = evaluate_contract(contract(bid=0.10, ask=2.00), ctx())
    assert v.spread_pct_of_mid == pytest.approx(1.90 / 1.05)
    assert v.verdict == "rejected"
    assert "%" in gate(v, "spread").observed


def test_spread_cap_is_configurable_and_clamped_to_the_documented_maximum() -> None:
    loose = DEFAULT_THRESHOLDS.with_spread_cap(0.15)
    assert loose.spread_max_pct_of_mid == 0.15
    # Anything above the documented 15% ceiling is clamped, not honoured.
    assert DEFAULT_THRESHOLDS.with_spread_cap(0.40).spread_max_pct_of_mid == 0.15
    assert DEFAULT_THRESHOLDS.with_spread_cap(0.0001).spread_max_pct_of_mid == 0.01
    assert DEFAULT_THRESHOLDS.with_spread_cap(None) is DEFAULT_THRESHOLDS

    wide = contract(bid=0.94, ask=1.06)  # 12% of mid
    assert evaluate_contract(wide, ctx()).verdict == "rejected"
    assert evaluate_contract(wide, ctx(thresholds=loose)).verdict != "rejected"


def test_zero_bid_and_zero_ask_is_no_market_not_a_free_option() -> None:
    v = evaluate_contract(contract(bid=0.0, ask=0.0), ctx())
    assert v.mid is None
    assert v.hard_reject is True
    assert v.verdict == "rejected"
    assert "no two-sided market" in " ".join(v.reasons)


def test_zero_bid_with_a_live_ask_is_a_real_one_sided_market() -> None:
    v = evaluate_contract(contract(bid=0.0, ask=0.05), ctx())
    assert v.mid == pytest.approx(0.025)
    assert v.spread_pct_of_mid == pytest.approx(2.0)
    assert v.verdict == "rejected"


def test_missing_quote_side_is_unknown_not_a_pass() -> None:
    for kw in ({"bid": None}, {"ask": None}, {"bid": None, "ask": None}):
        v = evaluate_contract(contract(**kw), ctx())
        assert gate(v, "spread").status == "unknown"
        assert v.hard_reject is False
        assert v.verdict == "insufficient_data"


def test_crossed_market_yields_no_mid() -> None:
    assert mid_price(1.20, 1.00) is None
    assert spread_metrics(1.20, 1.00) == (None, None, None)


# ── §5.6 open interest and volume gates ───────────────────────────────────────


def test_open_interest_floor_boundary() -> None:
    assert gate(evaluate_contract(contract(open_interest=500, volume=200), ctx()), "open_interest").status == "pass"
    below = evaluate_contract(contract(open_interest=499, volume=200), ctx())
    assert gate(below, "open_interest").status == "fail"
    assert below.verdict == "screened_out"
    assert below.hard_reject is False


def test_missing_open_interest_is_unknown() -> None:
    v = evaluate_contract(contract(open_interest=None), ctx())
    assert gate(v, "open_interest").status == "unknown"
    assert v.verdict == "insufficient_data"


def test_volume_must_exceed_25_percent_of_open_interest() -> None:
    at_threshold = evaluate_contract(contract(open_interest=1000, volume=250), ctx())
    assert at_threshold.volume_oi_ratio == pytest.approx(0.25)
    assert gate(at_threshold, "volume_oi").status == "fail"
    assert at_threshold.verdict == "screened_out"

    over = evaluate_contract(contract(open_interest=1000, volume=251), ctx())
    assert gate(over, "volume_oi").status == "pass"
    assert over.verdict != "screened_out"


def test_zero_open_interest_expiry_fails_the_turnover_gate_without_dividing_by_zero() -> None:
    v = evaluate_contract(contract(open_interest=0, volume=10), ctx())
    assert gate(v, "open_interest").status == "fail"
    assert gate(v, "volume_oi").status == "fail"
    assert v.volume_oi_ratio is None
    assert v.verdict == "screened_out"


def test_unusual_options_activity_at_three_times_the_baseline() -> None:
    flagged = evaluate_contract(contract(volume=300), ctx(uoa_reference={"call": 100.0}))
    assert "uoa" in flagged.flags
    assert gate(flagged, "uoa").status == "warn"
    assert "UNUSUAL ACTIVITY" in gate(flagged, "uoa").detail

    quiet = evaluate_contract(contract(volume=299), ctx(uoa_reference={"call": 100.0}))
    assert "uoa" not in quiet.flags
    assert gate(quiet, "uoa").status == "pass"


def test_uoa_is_unknown_without_a_baseline_and_states_the_basis() -> None:
    v = evaluate_contract(contract(), ctx(uoa_reference={}, uoa_basis="no baseline in this test"))
    assert gate(v, "uoa").status == "unknown"
    assert "no baseline in this test" in gate(v, "uoa").detail


def test_uoa_baseline_is_built_per_side_and_names_its_basis() -> None:
    ref, basis = build_uoa_reference([contract(volume=100), contract(side="put", volume=300, strike=95.0)])
    assert ref == {"call": 100.0, "put": 300.0}
    assert "20-day ADV is not published" in basis

    empty_ref, empty_basis = build_uoa_reference([contract(volume=None)])
    assert empty_ref == {}
    assert "no UOA baseline exists" in empty_basis


# ── §5.1 Delta filtering ──────────────────────────────────────────────────────


def test_buy_delta_floor_boundary() -> None:
    at = evaluate_contract(contract(delta=0.50, theta=-0.01), ctx())
    assert at.verdict == "buy_candidate"
    below = evaluate_contract(contract(delta=0.49, theta=-0.01), ctx())
    assert below.verdict == "tradeable"
    assert gate(below, "delta").status == "warn"


def test_short_leg_delta_ceiling_boundary() -> None:
    at = evaluate_contract(contract(delta=0.25, theta=-0.10), ctx())
    assert at.verdict == "sell_candidate"
    above = evaluate_contract(contract(delta=0.26, theta=-0.10), ctx())
    assert above.verdict == "tradeable"


def test_delta_is_reported_as_a_probability_proxy() -> None:
    v = evaluate_contract(contract(delta=0.25, theta=-0.10), ctx())
    assert v.itm_probability_proxy == pytest.approx(0.25)
    assert "25%" in gate(v, "delta").detail


def test_put_delta_is_graded_on_magnitude() -> None:
    v = evaluate_contract(contract(side="put", delta=-0.22, theta=-0.10, strike=95.0), ctx())
    assert v.itm_probability_proxy == pytest.approx(0.22)
    assert v.verdict == "sell_candidate"


def test_missing_delta_cannot_be_graded() -> None:
    v = evaluate_contract(contract(delta=None), ctx())
    assert gate(v, "delta").status == "unknown"
    assert v.verdict == "insufficient_data"
    assert "Delta unavailable" in v.reasons


# ── §5.2 APEX Delta/Theta ratio ───────────────────────────────────────────────


def test_delta_theta_ratio_arithmetic_and_missing_inputs() -> None:
    assert delta_theta_ratio(0.60, -0.05) == pytest.approx(12.0)
    assert delta_theta_ratio(-0.40, 0.02) == pytest.approx(20.0)
    assert delta_theta_ratio(0.60, 0.0) is None
    assert delta_theta_ratio(None, -0.05) is None
    assert delta_theta_ratio(0.60, None) is None


def test_ratio_above_ten_is_exceptional_buying_value() -> None:
    v = evaluate_contract(contract(delta=0.60, theta=-0.05), ctx())
    assert v.delta_theta_ratio == pytest.approx(12.0)
    assert v.verdict == "buy_candidate"
    assert "exceptional buying value" in gate(v, "delta_theta").detail


def test_ratio_exactly_ten_is_not_exceptional() -> None:
    v = evaluate_contract(contract(delta=0.60, theta=-0.06), ctx())
    assert v.delta_theta_ratio == pytest.approx(10.0)
    assert v.verdict == "tradeable"
    assert gate(v, "delta_theta").status == "warn"


def test_ratio_below_three_is_an_efficient_selling_candidate() -> None:
    v = evaluate_contract(contract(delta=0.20, theta=-0.10), ctx())
    assert v.delta_theta_ratio == pytest.approx(2.0)
    assert v.verdict == "sell_candidate"
    assert "efficient selling candidate" in gate(v, "delta_theta").detail


def test_ratio_exactly_three_is_not_an_efficient_sell() -> None:
    v = evaluate_contract(contract(delta=0.24, theta=-0.08), ctx())
    assert v.delta_theta_ratio == pytest.approx(3.0)
    assert v.verdict == "tradeable"


def test_zero_theta_yields_no_ratio_rather_than_infinity() -> None:
    v = evaluate_contract(contract(theta=0.0), ctx())
    assert v.delta_theta_ratio is None
    assert gate(v, "delta_theta").status == "unknown"
    assert v.verdict == "insufficient_data"


def test_rule1_and_rule2_proprietary_filters() -> None:
    rule1 = evaluate_contract(contract(delta=0.55, theta=-0.049), ctx())
    assert "rule1_buy" in rule1.flags
    assert "Rule 1" in rule1.reasoning

    # Delta clears 0.55 but daily Theta is at the 0.05 limit, so Rule 1 does not fire.
    assert "rule1_buy" not in evaluate_contract(contract(delta=0.55, theta=-0.05), ctx()).flags

    rule2 = evaluate_contract(contract(delta=0.20, theta=-0.10), ctx())
    assert "rule2_sell" in rule2.flags
    assert "rule2_sell" not in evaluate_contract(contract(delta=0.21, theta=-0.10), ctx()).flags


# ── §5.3 Vega cap ─────────────────────────────────────────────────────────────


def test_vega_cap_is_inactive_outside_a_catalyst_environment() -> None:
    v = evaluate_contract(contract(), ctx(catalyst_environment=False))
    assert gate(v, "vega_cap").status == "pass"
    assert "vega_cap_blocked" not in v.flags


def test_vega_cap_blocks_long_premium_in_a_catalyst_environment() -> None:
    v = evaluate_contract(
        contract(delta=0.60, theta=-0.05),
        ctx(catalyst_environment=True, catalyst_reason="IV 12 points over realised"),
    )
    assert gate(v, "vega_cap").status == "fail"
    assert "vega_cap_blocked" in v.flags
    # Would otherwise be a buy candidate on Delta and ratio alone.
    assert v.verdict == "tradeable"
    assert "IV 12 points over realised" in gate(v, "vega_cap").detail


def test_explicit_override_satisfies_the_vega_cap() -> None:
    v = evaluate_contract(contract(delta=0.60, theta=-0.05), ctx(catalyst_environment=True, vega_cap_override=True))
    assert gate(v, "vega_cap").status == "pass"
    assert v.verdict == "buy_candidate"


def test_apex_strategy_structure_satisfies_the_vega_cap() -> None:
    v = evaluate_contract(
        contract(delta=0.60, theta=-0.05), ctx(catalyst_environment=True, structure_absorbs_gamma=True)
    )
    assert gate(v, "vega_cap").status == "pass"
    assert v.verdict == "buy_candidate"


def test_missing_vega_is_unknown_not_a_silent_pass() -> None:
    v = evaluate_contract(contract(vega=None), ctx(catalyst_environment=True))
    assert gate(v, "vega_cap").status == "unknown"


# ── §5.4 Gamma awareness ──────────────────────────────────────────────────────


def test_gamma_flag_boundary_at_seven_dte() -> None:
    flagged = evaluate_contract(contract(), ctx(dte=7))
    assert "gamma_risk_7dte" in flagged.flags
    assert gate(flagged, "gamma_dte").status == "warn"

    clear = evaluate_contract(contract(), ctx(dte=8))
    assert "gamma_risk_7dte" not in clear.flags
    assert gate(clear, "gamma_dte").status == "pass"


def test_apex_strategy_absorbs_the_seven_dte_flag() -> None:
    v = evaluate_contract(contract(), ctx(dte=3, structure_absorbs_gamma=True))
    assert "gamma_risk_7dte" not in v.flags
    assert gate(v, "gamma_dte").status == "pass"
    assert "APEX Strategy" in gate(v, "gamma_dte").detail


def test_gamma_delta_shift_is_quantified_per_one_percent_move() -> None:
    v = evaluate_contract(contract(gamma=0.02), ctx(dte=5, spot=100.0))
    assert v.gamma_delta_shift_1pct == pytest.approx(0.02 * 100.0 * 0.01)


def test_zero_dte_still_grades_without_exploding() -> None:
    v = evaluate_contract(contract(), ctx(dte=0))
    assert v.dte == 0
    assert "gamma_risk_7dte" in v.flags


# ── derived metrics and reasoning ─────────────────────────────────────────────


def test_derived_percentages_and_breakeven() -> None:
    v = evaluate_contract(contract(bid=0.95, ask=1.05, theta=-0.05, vega=0.08), ctx())
    assert v.mid == pytest.approx(1.0)
    assert v.theta_pct_of_mid == pytest.approx(0.05)
    assert v.vega_pct_of_mid == pytest.approx(0.08)
    assert v.breakeven == pytest.approx(101.0)
    put = evaluate_contract(contract(side="put", strike=100.0), ctx())
    assert put.breakeven == pytest.approx(99.0)


def test_moneyness_classification_and_unknown_spot() -> None:
    assert evaluate_contract(contract(strike=90.0), ctx(atm_strike=100.0)).moneyness == "itm"
    assert evaluate_contract(contract(strike=110.0), ctx(atm_strike=100.0)).moneyness == "otm"
    assert evaluate_contract(contract(strike=100.0), ctx(atm_strike=100.0)).moneyness == "atm"
    assert evaluate_contract(contract(side="put", strike=110.0), ctx(atm_strike=100.0)).moneyness == "itm"
    assert evaluate_contract(contract(), ctx(spot=None, atm_strike=None)).moneyness == "unknown"


def test_reasoning_names_the_contract_the_verdict_and_the_greek_provenance() -> None:
    v = evaluate_contract(contract(greeks_source="model"), ctx())
    assert "TEST240920C00100000" in v.reasoning
    assert "locally computed Black-Scholes" in v.reasoning
    assert "2026-09-20" in v.reasoning

    rejected = evaluate_contract(contract(bid=0.5, ask=1.5), ctx())
    assert "HARD REJECT" in rejected.reasoning


def test_scores_rank_within_bucket_and_are_none_without_inputs() -> None:
    strong = evaluate_contract(contract(delta=0.80, theta=-0.02, bid=0.99, ask=1.01), ctx())
    weak = evaluate_contract(contract(delta=0.50, theta=-0.05, bid=0.95, ask=1.05), ctx())
    assert strong.buy_score is not None and weak.buy_score is not None
    assert strong.buy_score > weak.buy_score
    assert evaluate_contract(contract(delta=None), ctx()).buy_score is None


def test_scores_are_penalised_by_catalyst_vega_and_near_expiry_gamma() -> None:
    calm = evaluate_contract(contract(), ctx())
    hot = evaluate_contract(contract(), ctx(catalyst_environment=True, vega_cap_override=True))
    near = evaluate_contract(contract(), ctx(dte=3))
    assert (calm.buy_score or 0) > (hot.buy_score or 0)
    assert (calm.buy_score or 0) > (near.buy_score or 0)


def test_evaluate_chain_grades_every_contract() -> None:
    contracts = [contract(strike=95.0), contract(strike=100.0), contract(side="put", strike=105.0)]
    verdicts = evaluate_chain(contracts, ctx())
    assert len(verdicts) == 3
    assert {v.strike for v in verdicts} == {95.0, 100.0, 105.0}


def test_empty_chain_yields_no_verdicts() -> None:
    assert evaluate_chain([], ctx()) == []


def test_thresholds_match_the_documented_numbers() -> None:
    t = RuleThresholds()
    assert (t.buy_delta_min, t.sell_delta_max) == (0.50, 0.25)
    assert (t.rule1_delta_min, t.rule1_theta_max, t.rule2_delta_max) == (0.55, 0.05, 0.20)
    assert (t.delta_theta_buy_min, t.delta_theta_sell_max) == (10.0, 3.0)
    assert (t.spread_max_pct_of_mid, t.spread_max_pct_illiquid) == (0.10, 0.15)
    assert (t.min_open_interest, t.volume_oi_min_ratio, t.uoa_volume_multiple) == (500, 0.25, 3.0)
    assert t.gamma_dte_flag == 7
