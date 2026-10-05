"""Change 9 Part B — strategy selection follows the matrix, not a name quota.

Each scenario is one outlook × IV-versus-HV band × DTE bucket × risk profile.
DTE is not a score input. Buckets 0–7 and 8–21 mean no later expiration.
Buckets 22–60 and 61–180 mean a back month is available, which is the only
DTE fact the selector reads (`back_month_available`).

Expected labels are the §9.1 bonuses in ``_rank_candidates``, then the risk-profile
reorder. They are not fitted by changing weights.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.apex_strategy import ApexStrategyInput
from app.services.strategy_engine import build_strategy_layer, strategy_decision
from app.services.strategy_recommendation import real_strategy_count
from app.strategies.registry import STRATEGY_REGISTRY, get_strategy_spec

VETO_LABELS = (
    "NO TRADE",
    "Wait for IV Crush",
    "Stand aside",
)

# Outlook → direction, technical score, RSI.
# Strong means tech score above the debit-vertical gate (80) and RSI outside 40–60,
# so a range-bound iron condor is not also eligible. Mild keeps RSI inside 40–60
# and tech score at or below 80, so the debit vertical gate stays closed.
OUTLOOKS: dict[str, dict[str, float | str]] = {
    "strong_bull": {"direction": "bullish", "tech_score": 90.0, "rsi": 72.0},
    "mild_bull": {"direction": "bullish", "tech_score": 65.0, "rsi": 52.0},
    "neutral": {"direction": "neutral", "tech_score": 60.0, "rsi": 50.0},
    "mild_bear": {"direction": "bearish", "tech_score": 65.0, "rsi": 48.0},
    "strong_bear": {"direction": "bearish", "tech_score": 90.0, "rsi": 28.0},
}

# Cheap: HV − IV > 0.10 and the vol signal is not sell_premium (that flag alone marks IV rich).
# Near: IV equals HV. Rich: IV − HV > 0.10.
IV_BANDS: dict[str, dict[str, float | str]] = {
    "cheap": {"iv": 0.18, "hv": 0.32, "vol_signal": "buy_premium"},
    "near": {"iv": 0.25, "hv": 0.25, "vol_signal": "fair"},
    "rich": {"iv": 0.40, "hv": 0.22, "vol_signal": "sell_premium"},
}

# Numeric DTE does not change the rank. Only whether a second expiration exists does.
DTE_BUCKETS: dict[str, bool] = {
    "0-7": False,
    "8-21": False,
    "22-60": True,
    "61-180": True,
}

PROFILES = ("conservative", "moderate", "aggressive")

# (outlook, iv band, back month, profile) → Best Match from the current matrix.
# Bonuses: iron condor +5 when IV is rich and RSI is 40–60; bull call / bear put +6
# when IV is cheap and tech > 80; credit vertical +4 when IV is rich and directional;
# long straddle +4 when IV is cheap and neutral; married put +2 on any bullish tape;
# diagonal +2 and calendar +1 only when a back month exists.
# Conservative moves its preferred defined-risk names in front. Aggressive pulls a
# later directional name in front of the first neutral-income name. An empty
# candidate list falls back to Bear Put / Long Straddle / Bull Call by direction.
EXPECTED: dict[tuple[str, str, bool, str], str] = {
    ("mild_bear", "cheap", False, "aggressive"): "Bear Put Spread",
    ("mild_bear", "cheap", False, "conservative"): "Bear Put Spread",
    ("mild_bear", "cheap", False, "moderate"): "Bear Put Spread",
    ("mild_bear", "cheap", True, "aggressive"): "Diagonal Spread (bearish)",
    ("mild_bear", "cheap", True, "conservative"): "Diagonal Spread (bearish)",
    ("mild_bear", "cheap", True, "moderate"): "Diagonal Spread (bearish)",
    ("mild_bear", "near", False, "aggressive"): "Bear Put Spread",
    ("mild_bear", "near", False, "conservative"): "Bear Put Spread",
    ("mild_bear", "near", False, "moderate"): "Bear Put Spread",
    ("mild_bear", "near", True, "aggressive"): "Diagonal Spread (bearish)",
    ("mild_bear", "near", True, "conservative"): "Diagonal Spread (bearish)",
    ("mild_bear", "near", True, "moderate"): "Diagonal Spread (bearish)",
    ("mild_bear", "rich", False, "aggressive"): "Short Iron Condor",
    ("mild_bear", "rich", False, "conservative"): "Short Iron Condor",
    ("mild_bear", "rich", False, "moderate"): "Short Iron Condor",
    ("mild_bear", "rich", True, "aggressive"): "Diagonal Spread (bearish)",
    ("mild_bear", "rich", True, "conservative"): "Short Iron Condor",
    ("mild_bear", "rich", True, "moderate"): "Short Iron Condor",
    ("mild_bull", "cheap", False, "aggressive"): "Married Put",
    ("mild_bull", "cheap", False, "conservative"): "Married Put",
    ("mild_bull", "cheap", False, "moderate"): "Married Put",
    ("mild_bull", "cheap", True, "aggressive"): "Married Put",
    ("mild_bull", "cheap", True, "conservative"): "Married Put",
    ("mild_bull", "cheap", True, "moderate"): "Married Put",
    ("mild_bull", "near", False, "aggressive"): "Married Put",
    ("mild_bull", "near", False, "conservative"): "Married Put",
    ("mild_bull", "near", False, "moderate"): "Married Put",
    ("mild_bull", "near", True, "aggressive"): "Married Put",
    ("mild_bull", "near", True, "conservative"): "Married Put",
    ("mild_bull", "near", True, "moderate"): "Married Put",
    ("mild_bull", "rich", False, "aggressive"): "Short Iron Condor",
    ("mild_bull", "rich", False, "conservative"): "Short Iron Condor",
    ("mild_bull", "rich", False, "moderate"): "Short Iron Condor",
    ("mild_bull", "rich", True, "aggressive"): "Diagonal Spread (bullish)",
    ("mild_bull", "rich", True, "conservative"): "Short Iron Condor",
    ("mild_bull", "rich", True, "moderate"): "Short Iron Condor",
    ("neutral", "cheap", False, "aggressive"): "Long Straddle",
    ("neutral", "cheap", False, "conservative"): "Long Straddle",
    ("neutral", "cheap", False, "moderate"): "Long Straddle",
    ("neutral", "cheap", True, "aggressive"): "Long Straddle",
    ("neutral", "cheap", True, "conservative"): "Calendar Spread",
    ("neutral", "cheap", True, "moderate"): "Long Straddle",
    ("neutral", "near", False, "aggressive"): "Long Straddle",
    ("neutral", "near", False, "conservative"): "Long Straddle",
    ("neutral", "near", False, "moderate"): "Long Straddle",
    ("neutral", "near", True, "aggressive"): "Calendar Spread",
    ("neutral", "near", True, "conservative"): "Calendar Spread",
    ("neutral", "near", True, "moderate"): "Calendar Spread",
    ("neutral", "rich", False, "aggressive"): "Short Iron Condor",
    ("neutral", "rich", False, "conservative"): "Short Iron Condor",
    ("neutral", "rich", False, "moderate"): "Short Iron Condor",
    ("neutral", "rich", True, "aggressive"): "Short Iron Condor",
    ("neutral", "rich", True, "conservative"): "Short Iron Condor",
    ("neutral", "rich", True, "moderate"): "Short Iron Condor",
    ("strong_bear", "cheap", False, "aggressive"): "Bear Put Spread",
    ("strong_bear", "cheap", False, "conservative"): "Bear Put Spread",
    ("strong_bear", "cheap", False, "moderate"): "Bear Put Spread",
    ("strong_bear", "cheap", True, "aggressive"): "Bear Put Spread",
    ("strong_bear", "cheap", True, "conservative"): "Diagonal Spread (bearish)",
    ("strong_bear", "cheap", True, "moderate"): "Bear Put Spread",
    ("strong_bear", "near", False, "aggressive"): "Bear Put Spread",
    ("strong_bear", "near", False, "conservative"): "Bear Put Spread",
    ("strong_bear", "near", False, "moderate"): "Bear Put Spread",
    ("strong_bear", "near", True, "aggressive"): "Diagonal Spread (bearish)",
    ("strong_bear", "near", True, "conservative"): "Diagonal Spread (bearish)",
    ("strong_bear", "near", True, "moderate"): "Diagonal Spread (bearish)",
    ("strong_bear", "rich", False, "aggressive"): "Bear Call Spread (credit)",
    ("strong_bear", "rich", False, "conservative"): "Bear Call Spread (credit)",
    ("strong_bear", "rich", False, "moderate"): "Bear Call Spread (credit)",
    ("strong_bear", "rich", True, "aggressive"): "Bear Call Spread (credit)",
    ("strong_bear", "rich", True, "conservative"): "Bear Call Spread (credit)",
    ("strong_bear", "rich", True, "moderate"): "Bear Call Spread (credit)",
    ("strong_bull", "cheap", False, "aggressive"): "Bull Call Spread",
    ("strong_bull", "cheap", False, "conservative"): "Married Put",
    ("strong_bull", "cheap", False, "moderate"): "Bull Call Spread",
    ("strong_bull", "cheap", True, "aggressive"): "Bull Call Spread",
    ("strong_bull", "cheap", True, "conservative"): "Married Put",
    ("strong_bull", "cheap", True, "moderate"): "Bull Call Spread",
    ("strong_bull", "near", False, "aggressive"): "Married Put",
    ("strong_bull", "near", False, "conservative"): "Married Put",
    ("strong_bull", "near", False, "moderate"): "Married Put",
    ("strong_bull", "near", True, "aggressive"): "Married Put",
    ("strong_bull", "near", True, "conservative"): "Married Put",
    ("strong_bull", "near", True, "moderate"): "Married Put",
    ("strong_bull", "rich", False, "aggressive"): "Bull Put Spread (credit)",
    ("strong_bull", "rich", False, "conservative"): "Bull Put Spread (credit)",
    ("strong_bull", "rich", False, "moderate"): "Bull Put Spread (credit)",
    ("strong_bull", "rich", True, "aggressive"): "Bull Put Spread (credit)",
    ("strong_bull", "rich", True, "conservative"): "Bull Put Spread (credit)",
    ("strong_bull", "rich", True, "moderate"): "Bull Put Spread (credit)",
}


def _eligible_apex() -> ApexStrategyInput:
    return ApexStrategyInput(
        catalyst_days=7,
        term_structure_inverted=True,
        front_iv=0.45,
        back_iv=0.35,
        front_ivr=75.0,
        four_leg_structure=True,
        legs_same_strikes=True,
        call_delta=0.20,
        put_delta=0.20,
        front_premium_offset_pct=0.55,
        adv=6_000_000,
        open_interest=2000,
        spread_pct=5.0,
        earnings_date_confirmed=True,
        earnings_history_hits=6,
        earnings_history_count=8,
        front_expiry_listed=True,
        back_expiry_listed=True,
    )


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    outlook: str
    iv_band: str
    dte_bucket: str
    risk_profile: str
    expected: str
    delta_theta_ratio: float | None = None
    sentiment_score: float | None = None
    catalyst: bool = False

    def inputs(self) -> dict:
        outlook = OUTLOOKS[self.outlook]
        band = IV_BANDS[self.iv_band]
        payload: dict = {
            "composite": 78.0,
            "direction": outlook["direction"],
            "vol_signal": band["vol_signal"],
            "rsi": outlook["rsi"],
            "iv": band["iv"],
            "hv": band["hv"],
            "tech_score": outlook["tech_score"],
            "confirmed_pattern_count": 1,
            "data_fresh": True,
            "back_month_available": DTE_BUCKETS[self.dte_bucket],
            "risk_profile": self.risk_profile,
            "symbol": "FIX",
            "delta_theta_ratio": self.delta_theta_ratio,
            "sentiment_score": self.sentiment_score,
            "catalyst_active": self.catalyst,
        }
        if self.catalyst:
            payload["apex_input"] = _eligible_apex()
        return payload


def _grid() -> list[Scenario]:
    rows: list[Scenario] = []
    for outlook in OUTLOOKS:
        for iv_band in IV_BANDS:
            for dte_bucket, back_month in DTE_BUCKETS.items():
                for profile in PROFILES:
                    expected = EXPECTED[(outlook, iv_band, back_month, profile)]
                    rows.append(
                        Scenario(
                            scenario_id=f"{outlook}-{iv_band}-{dte_bucket}-{profile}",
                            outlook=outlook,
                            iv_band=iv_band,
                            dte_bucket=dte_bucket,
                            risk_profile=profile,
                            expected=expected,
                        )
                    )
    return rows


def _branches() -> list[Scenario]:
    """Gates the four-factor grid does not turn on. Same matrix, extra inputs."""
    rows: list[Scenario] = []
    for profile, expected in (
        ("moderate", "Bull Call Spread"),
        ("aggressive", "Bull Call Spread"),
        ("conservative", "Married Put"),
    ):
        rows.append(
            Scenario(
                scenario_id=f"branch-dtheta-{profile}",
                outlook="strong_bull",
                iv_band="cheap",
                dte_bucket="22-60",
                risk_profile=profile,
                expected=expected,
                delta_theta_ratio=12.0,
            )
        )
    rows.append(
        Scenario(
            scenario_id="branch-sentiment-mild-bull-near",
            outlook="mild_bull",
            iv_band="near",
            dte_bucket="0-7",
            risk_profile="moderate",
            expected="Married Put",
            sentiment_score=70.0,
        )
    )
    for profile in PROFILES:
        rows.append(
            Scenario(
                scenario_id=f"branch-apex-{profile}",
                outlook="neutral",
                iv_band="rich",
                dte_bucket="22-60",
                risk_profile=profile,
                expected="Gamma Trampoline™",
                catalyst=True,
            )
        )
    rows.append(
        Scenario(
            scenario_id="branch-apex-outranks-benchmark",
            outlook="strong_bull",
            iv_band="cheap",
            dte_bucket="22-60",
            risk_profile="moderate",
            expected="Gamma Trampoline™",
            delta_theta_ratio=12.0,
            catalyst=True,
        )
    )
    return rows


GRID = _grid()
BRANCHES = _branches()
SCENARIOS = GRID + BRANCHES


def real_executable_names() -> frozenset[str]:
    """Registry display names with legs. Advisory stand-ins are not executable."""
    return frozenset(
        spec.display_name
        for spec in STRATEGY_REGISTRY.values()
        if spec.risk_type != "advisory" and spec.leg_count > 0
    )


def test_real_executable_names_omit_advisory_stand_ins() -> None:
    names = real_executable_names()
    assert "NO TRADE — Insufficient Conviction" not in names
    assert "NO TRADE — Wait for IV Crush" not in names
    assert len(names) == real_strategy_count()
    assert len(names) == len(STRATEGY_REGISTRY) - 2


def test_fixture_has_at_least_fifty_distinct_scenarios() -> None:
    assert len(SCENARIOS) >= 50
    assert len({scenario.scenario_id for scenario in SCENARIOS}) == len(SCENARIOS)
    assert len({scenario.expected for scenario in GRID}) >= 8


def test_same_back_month_flag_does_not_rotate_by_dte_number() -> None:
    """0–7 matches 8–21, and 22–60 matches 61–180. DTE does not spin the label."""
    by_key: dict[tuple[str, str, bool, str], set[str]] = {}
    for scenario in GRID:
        key = (scenario.outlook, scenario.iv_band, DTE_BUCKETS[scenario.dte_bucket], scenario.risk_profile)
        by_key.setdefault(key, set()).add(scenario.expected)
    assert all(len(names) == 1 for names in by_key.values())


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.scenario_id)
def test_scenario_selects_the_matrix_strategy(scenario: Scenario) -> None:
    decision = strategy_decision(**scenario.inputs())
    label = decision.best_match
    spec = get_strategy_spec(label)
    assert spec is not None
    assert spec.risk_type != "advisory"
    assert spec.leg_count > 0
    assert spec.tradeable
    for veto in VETO_LABELS:
        assert veto not in label
    assert label in real_executable_names() or label == "Gamma Trampoline™"
    assert label == scenario.expected
    assert decision.strategies_evaluated == real_strategy_count()
    eligible = [candidate.name for candidate in decision.candidates if candidate.eligible and candidate.defined_risk]
    assert label == eligible[0]


def test_shared_one_leg_shape_does_not_replace_the_matrix_name() -> None:
    """Married Put is one long put plus stock already held. That shape is also Long Put.

    The leg label must not replace the matrix winner. The same collision turns
    APEX Benchmark Greeks Strategy into Long Call.
    """
    contracts = [
        {"side": "put", "strike": 95.0, "bid": 1.9, "ask": 2.1, "delta": -0.30, "expiry": "2026-11-20", "symbol": "XYZ261120P00095000"},
        {"side": "call", "strike": 100.0, "bid": 3.8, "ask": 4.0, "delta": 0.55, "expiry": "2026-11-20", "symbol": "XYZ261120C00100000"},
    ]
    chain = {
        "symbol": "XYZ",
        "spot": 100.0,
        "expiry": "2026-11-20",
        "recommendedContract": {"strike": 95.0, "side": "put", "expiry": "2026-11-20"},
        "contracts": contracts,
    }
    common = {
        "composite": 78.0,
        "direction": "bullish",
        "vol_signal": "fair",
        "vol_layer": {"iv": 0.25, "hv": 0.25},
        "sentiment_layer": {},
        "fundamentals_layer": {"score": 60},
        "tech_score": 65.0,
        "ticker": "XYZ",
    }
    married = build_strategy_layer(strategy_name="Married Put", chain_analysis=chain, **common)
    assert married["selected_strategy"] == "Married Put"
    assert "Long Put" not in married["selected_strategy"]
    benchmark = build_strategy_layer(
        strategy_name="APEX Benchmark Greeks Strategy",
        chain_analysis={
            **chain,
            "recommendedContract": {"strike": 100.0, "side": "call", "expiry": "2026-11-20"},
        },
        **common,
    )
    assert benchmark["selected_strategy"] == "APEX Benchmark Greeks Strategy"
    assert benchmark["selected_strategy"] != "Long Call"
