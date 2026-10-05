"""Shared eligibility, submission-time quotes, and executability rank."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.executability import (
    can_auto_execute,
    eligibility_sentence,
    enforce_submission_quotes,
    marketable_limit,
    order_candidates_by_executability,
    quote_age_phrase,
    quote_problem,
    slippage_dollars,
    spread_confirmation_text,
)
from app.services.fills import execute_market_fill, execute_strategy_legs
from app.services.stock_leg import Holdings, plan_stock
from app.services.strategy_engine import _prefer_executable_match, _protective_put_label

CSV = Path(__file__).resolve().parents[2] / "docs" / "qa" / "APEX_QA_Test_Results.csv"


def _cand(name: str, score: float, *, eligible: bool = True, defined_risk: bool = True) -> SimpleNamespace:
    return SimpleNamespace(name=name, score=score, eligible=eligible, defined_risk=defined_risk)


def test_score_above_equal_and_below_the_minimum() -> None:
    settings = {"auto_execution_threshold": 85}
    above = can_auto_execute(
        {"composite_score": 86, "executable": True, "validation_passed": True},
        settings,
    )
    equal = can_auto_execute(
        {"composite_score": 85, "executable": True, "validation_passed": True},
        settings,
    )
    below = can_auto_execute(
        {"composite_score": 84.9, "executable": True, "validation_passed": True},
        settings,
    )
    assert above.eligible is True
    assert above.reasons == []
    assert equal.eligible is True
    assert below.eligible is False
    line = eligibility_sentence(84.9, 85, below)
    assert line == "Composite 84.9. Your minimum 85.0. Not auto-executable: composite is below your minimum."
    assert "Auto-execute eligible" not in line
    assert "NO TRADE" not in line


def test_jpm_not_executable_does_not_say_auto_execute_eligible() -> None:
    decision = can_auto_execute(
        {
            "composite_score": 62.9,
            "executable": False,
            "validation_passed": False,
            "executability_reason": "quote 17 min old",
        },
        {"auto_execution_threshold": 50},
    )
    assert decision.eligible is False
    line = eligibility_sentence(62.9, 50, decision)
    assert line == "Composite 62.9. Your minimum 50.0. Not auto-executable: quote 17 min old."
    assert "Auto-execute eligible" not in line


def test_qa_not_executable_rows_are_not_auto_execute_eligible() -> None:
    """The recorded bug: NOT EXECUTABLE on the slide, Auto-execute eligible on Risk Review."""
    rows = list(csv.DictReader(CSV.open(newline="", encoding="utf-8")))
    mismatches = [
        row
        for row in rows
        if row["Strategy Status"] == "NOT EXECUTABLE" and row["Risk Review Eligibility"] == "Auto-execute eligible"
    ]
    assert len(mismatches) >= 27
    for row in mismatches:
        score = float(row["Composite Score"])
        reason = row["Failed Check"] or "Not executable."
        decision = can_auto_execute(
            {
                "composite_score": score,
                "executable": False,
                "validation_passed": False,
                "executability_reason": reason,
            },
            {"auto_execution_threshold": 50},
        )
        line = eligibility_sentence(score, 50, decision)
        assert decision.eligible is False
        assert "Auto-execute eligible" not in line
        assert row["Recommended Strategy"] not in {"NO TRADE", "Wait for IV Crush"}


def test_quote_seventeen_minutes_old_is_not_current() -> None:
    now = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    stamped = (now - timedelta(minutes=17)).isoformat()
    phrase = quote_age_phrase(stamped, now=now)
    assert phrase == "quote 17 min old"
    problem = quote_problem({"price": 100, "bid": 99, "ask": 101, "as_of": stamped}, now=now)
    assert problem is not None
    assert "Quote not current" in problem
    assert stamped in problem


def test_missing_timestamp_with_a_price_is_not_stale() -> None:
    assert quote_problem({"price": 11.96, "bid": None, "ask": None, "as_of": None}) is None


@pytest.mark.asyncio
async def test_stale_quote_is_refetched_once_then_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the clock inside the regular session. After the close, the same age is last close.
    session = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is None:
                return session.replace(tzinfo=None)
            return session.astimezone(tz)

    monkeypatch.setattr("app.services.executability.datetime", Frozen)
    stale = (session - timedelta(minutes=17)).isoformat()

    class Adapter:
        def __init__(self) -> None:
            self.quotes = 0
            self.submits = 0

        async def quote(self, symbol: str) -> SimpleNamespace:
            self.quotes += 1
            return SimpleNamespace(price=1.0, bid=1.0, ask=1.02, as_of=stale, source="test")

        async def submit_order(self, **kwargs: object) -> dict:
            self.submits += 1
            return {"filled_avg_price": 1.0}

    adapter = Adapter()
    with pytest.raises(ValueError, match="Quote not current"):
        await enforce_submission_quotes(adapter, ["AAPL270115C00150000"], path="place_order")
    assert adapter.quotes == 2
    assert adapter.submits == 0

    with pytest.raises(ValueError, match="Quote not current"):
        await execute_market_fill(
            user=SimpleNamespace(),  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=adapter,
            symbol="AAPL270115C00150000",
            side="buy",
            qty=1,
            asset_class="us_option",
            order_type="market",
            submission_path="place_order",
        )
    assert adapter.submits == 0


@pytest.mark.asyncio
async def test_wide_spread_blocks_until_confirmed_and_states_slippage() -> None:
    class Adapter:
        async def quote(self, symbol: str) -> SimpleNamespace:
            return SimpleNamespace(price=1.1, bid=1.0, ask=1.2, as_of=datetime.now(timezone.utc).isoformat())

    text = spread_confirmation_text(spread_pct=0.1818, threshold=0.10, slippage=slippage_dollars({"bid": 1.0, "ask": 1.2}))
    assert "wider than the 10% cap" in text
    assert "Estimated slippage $10.00" in text
    with pytest.raises(ValueError, match="wider than the 10% cap"):
        await enforce_submission_quotes(Adapter(), ["AAPL270115C00150000"], path="place_order")
    await enforce_submission_quotes(
        Adapter(),
        ["AAPL270115C00150000"],
        path="place_order",
        spread_confirmed=True,
    )


@pytest.mark.asyncio
async def test_spread_equal_to_the_cap_is_not_wider() -> None:
    """Exactly 10% of mid is the cap, not a wider spread. Do not reject it."""

    class Adapter:
        async def quote(self, symbol: str) -> SimpleNamespace:
            return SimpleNamespace(
                price=1.0,
                bid=0.95,
                ask=1.05,
                as_of=datetime.now(timezone.utc).isoformat(),
                source="test",
            )

    await enforce_submission_quotes(Adapter(), ["AAPL270115C00150000"], path="place_order")


@pytest.mark.asyncio
async def test_demo_fill_is_blocked_when_checks_failed() -> None:
    class Adapter:
        def __init__(self) -> None:
            self.quotes = 0

        async def quote(self, symbol: str) -> SimpleNamespace:
            self.quotes += 1
            return SimpleNamespace(price=1.0, as_of=None)

        async def submit_order(self, **kwargs: object) -> dict:
            raise AssertionError("demo fill must not run")

    adapter = Adapter()
    with pytest.raises(ValueError, match="pre-trade checks"):
        await execute_strategy_legs(
            user=SimpleNamespace(),  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=adapter,
            legs=[{"symbol": "AAPL270115C00150000", "side": "buy", "qty": 1}],
            checks_passed=False,
            submission_path="place_order",
        )
    assert adapter.quotes == 0


def test_options_limit_is_the_ask_for_a_buy() -> None:
    assert marketable_limit("buy", {"bid": 11.70, "ask": 12.22}) == (12.22, "ask")
    assert marketable_limit("sell", {"bid": 11.70, "ask": 12.22}) == (11.70, "bid")
    assert marketable_limit("buy", {"price": 11.96}) is None


def test_close_score_executable_outranks_a_blocked_name() -> None:
    ranked = [_cand("Married Put", 66), _cand("Bull Put Spread", 63)]
    flags = {"Married Put": False, "Bull Put Spread": True}
    ordered = order_candidates_by_executability(ranked, flags)
    assert [row.name for row in ordered] == ["Bull Put Spread", "Married Put"]
    far = order_candidates_by_executability(
        [_cand("Married Put", 80), _cand("Bull Put Spread", 70)],
        {"Married Put": False, "Bull Put Spread": True},
    )
    assert [row.name for row in far] == ["Married Put", "Bull Put Spread"]
    none = order_candidates_by_executability(
        [_cand("Married Put", 65), _cand("Bull Put Spread", 62)],
        {"Married Put": False, "Bull Put Spread": False},
    )
    assert [row.name for row in none] == ["Married Put", "Bull Put Spread"]


def test_none_executable_keeps_the_real_strategy_name() -> None:
    rec = SimpleNamespace(
        best_match="Married Put",
        leg_structure="Married Put",
        candidates=[_cand("Married Put", 65.5), _cand("Long Put", 60)],
    )
    kept = _prefer_executable_match(rec, {"Married Put": False, "Long Put": False})
    assert kept.best_match == "Married Put"
    assert "NO TRADE" not in kept.best_match
    assert "Wait for IV Crush" not in kept.best_match


def test_held_shares_are_a_protective_put_and_the_note_counts_them() -> None:
    label = _protective_put_label(
        [
            {"side": "stock", "action": "buy", "quantity": 100},
            {"side": "put", "action": "buy", "quantity": 1},
        ],
        covered=True,
    )
    assert label == "Protective Put"
    plan = plan_stock(
        equity_side="buy",
        contracts=1,
        multiplier=100,
        holdings=Holdings(shares_long=150, avg_cost=None),
    )
    assert plan.note is not None
    assert "Uses 100 of your 150 shares" in plan.note
    assert "No additional shares are bought" in plan.note


def test_last_close_is_not_a_stale_failure_and_the_session_cap_stays() -> None:
    """Saturday last close is not stale. 301s during the session still is. Cap stays 300s."""
    saturday = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc)
    old = (saturday - timedelta(hours=20)).isoformat()
    assert quote_problem({"price": 100, "bid": 99, "ask": 101, "as_of": old}, now=saturday) is None
    labeled = quote_problem(
        {
            "price": 100,
            "bid": 99,
            "ask": 101,
            "as_of": old,
            "quote_meta": {"staleReason": "last_close", "isStale": False},
        },
        now=saturday,
    )
    assert labeled is None
    session = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
    stale = (session - timedelta(seconds=301)).isoformat()
    fresh = (session - timedelta(seconds=299)).isoformat()
    assert "Quote not current" in (quote_problem({"price": 100, "bid": 99, "ask": 101, "as_of": stale}, now=session) or "")
    assert quote_problem({"price": 100, "bid": 99, "ask": 101, "as_of": fresh}, now=session) is None
    from app.services.strategy_engine import suspect_quote_failures

    quiet = suspect_quote_failures(
        [{"side": "call", "quote_as_of": old, "quote_meta": {"staleReason": "last_close", "isStale": False}}],
        [],
        spot=100.0,
        now=saturday,
    )
    assert "Stale or suspect quote" not in quiet
    loud = suspect_quote_failures(
        [{"side": "call", "quote_as_of": stale}],
        [],
        spot=100.0,
        now=session,
    )
    assert "Stale or suspect quote" in loud
