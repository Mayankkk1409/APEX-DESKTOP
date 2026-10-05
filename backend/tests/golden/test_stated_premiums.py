"""Five stated-premium expiry grids per strategy that can be checked without a recorded chain.

Incomplete strategies are reported. They are not given a passing payoff assertion.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.strategies.payoffs.helpers import multi_leg_payoff_at_expiry
from app.strategies.registry import LEG_QUANTITY_BY_INDEX, STRATEGY_REGISTRY
from app.strategies.structure_math import expiry_pnl

_FIXTURE = Path(__file__).with_name("stated_premiums.py")
_spec = importlib.util.spec_from_file_location("stated_premiums", _FIXTURE)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
INCOMPLETE = _module.INCOMPLETE
LABELS_INCOMPLETE = _module.LABELS_INCOMPLETE
SCENARIOS = _module.SCENARIOS
SHAPE_OF = _module.SHAPE_OF

_TOL = 0.01


def _template(strategy_id: str) -> list[tuple[str, str, int]]:
    spec = STRATEGY_REGISTRY[strategy_id]
    quantities = LEG_QUANTITY_BY_INDEX.get(strategy_id, {})
    rows: list[tuple[str, str, int]] = []
    for index, leg in enumerate(spec.leg_specs):
        count = quantities.get(index, 1)
        if leg.option_type == "stock":
            shares = spec.equity_leg_spec.shares_per_contract if spec.equity_leg_spec else 100
            rows.append((leg.side, "stock", shares * count))
        else:
            rows.append((leg.side, leg.option_type, count))
    return sorted(rows)


def _actual(legs: list[dict]) -> list[tuple[str, str, int]]:
    return sorted((str(leg["action"]), str(leg["side"]), int(leg["quantity"])) for leg in legs)


def test_every_registry_strategy_is_verified_or_reported_incomplete() -> None:
    ids = set(STRATEGY_REGISTRY)
    assert set(SHAPE_OF) | set(INCOMPLETE) == ids
    assert not (set(SHAPE_OF) & set(INCOMPLETE))
    for strategy_id, reason in INCOMPLETE.items():
        assert reason.strip(), strategy_id
    for label, reason in LABELS_INCOMPLETE.items():
        assert reason.strip(), label
        assert label not in SHAPE_OF


@pytest.mark.parametrize("strategy_id", sorted(SHAPE_OF))
def test_five_stated_premium_scenarios_match_expiry_grid(strategy_id: str) -> None:
    rows = SCENARIOS[SHAPE_OF[strategy_id]]
    assert len(rows) >= 5
    expected_shape = _template(strategy_id)
    for row in rows[:5]:
        assert row["source"].startswith("Stated premium")
        assert "Not a recorded" in row["source"]
        assert row["feed"] == "none"
        assert row["function"]
        assert _actual(row["legs"]) == expected_shape
        option_only = all(leg["side"] != "stock" for leg in row["legs"])
        for underlying, expected in row["checks"]:
            got = multi_leg_payoff_at_expiry(row["legs"], float(underlying))
            assert abs(got - float(expected)) <= _TOL, (strategy_id, row["name"], underlying, got, expected)
            if option_only:
                quoted = float(expiry_pnl(row["legs"], underlying))
                assert abs(quoted - float(expected)) <= _TOL, (strategy_id, row["name"], underlying, quoted, expected)
        for breakeven in row["breakevens"]:
            at_be = multi_leg_payoff_at_expiry(row["legs"], float(breakeven))
            assert abs(at_be) <= _TOL, (strategy_id, row["name"], breakeven, at_be)


def test_incomplete_strategies_are_not_given_a_green_payoff() -> None:
    """The incomplete list is the report. It must not be empty, and it must not be tested as a pass."""
    assert len(INCOMPLETE) == 17
    assert "apex_strategy" in INCOMPLETE
    assert "double_calendar" in INCOMPLETE
    assert "gamma_trampoline" in LABELS_INCOMPLETE
    for strategy_id in INCOMPLETE:
        assert strategy_id not in SHAPE_OF
