"""Coverage of production Best Match across outlook, IV versus HV, and risk profile.

Calls ``strategy_decision`` — the selector ``scan_engine`` uses, which delegates
to ``recommend_strategy``. Ranking is not reimplemented here.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.strategy_engine import strategy_decision

# Phrases that are not an executable structure.
_BLOCKED = ("NO TRADE", "Wait for IV Crush", "Stand aside")

# Held constant so only outlook, IV versus HV, and risk profile move the selector.
_FIXED = dict(
    composite=82.0,
    vol_signal="fair",
    rsi=50.0,
    tech_score=85.0,
    sentiment_score=None,
    catalyst_active=False,
    delta_theta_ratio=None,
    symbol="AAPL",
    spot=100.0,
    spread_pct=2.0,
    data_fresh=True,
    confirmed_pattern_count=1,
    back_month_available=False,
    catalyst_days=None,
    apex_input=None,
    structure_limits=None,
)

_OUTLOOKS = ("bullish", "bearish", "neutral")
_PROFILES = ("conservative", "moderate", "aggressive", "custom")
# (label, iv, hv) — gaps are absolute fractions after alignment inside the selector.
_IV_HV = (
    ("cheap", 0.18, 0.40),
    ("rich", 0.52, 0.40),
    ("extreme", 0.55, 0.30),
    ("matched", 0.25, 0.25),
    ("mild_cheap", 0.22, 0.28),
    ("mild_rich", 0.28, 0.22),
)


@dataclass(frozen=True)
class CoverageCase:
    outlook: str
    iv_hv: str
    iv: float
    hv: float
    risk_profile: str

    @property
    def case_id(self) -> str:
        return f"{self.outlook}-{self.iv_hv}-{self.risk_profile}"


def coverage_cases() -> list[CoverageCase]:
    cases: list[CoverageCase] = []
    for outlook in _OUTLOOKS:
        for iv_hv, iv, hv in _IV_HV:
            for profile in _PROFILES:
                cases.append(
                    CoverageCase(
                        outlook=outlook,
                        iv_hv=iv_hv,
                        iv=iv,
                        hv=hv,
                        risk_profile=profile,
                    )
                )
    return cases


CASES = coverage_cases()


def selected_label(case: CoverageCase) -> str:
    """Production Best Match for one deterministic condition set."""
    decision = strategy_decision(
        direction=case.outlook,
        iv=case.iv,
        hv=case.hv,
        risk_profile=case.risk_profile,
        **_FIXED,
    )
    return decision.best_match


def test_at_least_thirty_conditions() -> None:
    assert len(CASES) >= 30


@pytest.mark.parametrize("case", CASES, ids=[case.case_id for case in CASES])
def test_condition_selects_executable_strategy(case: CoverageCase) -> None:
    label = selected_label(case)
    for phrase in _BLOCKED:
        assert phrase not in label
    assert label.strip()
