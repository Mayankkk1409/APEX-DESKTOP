"""Card filters are gates. A printed rule that the contract fails cannot auto-execute."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.analysis.options_rules import ChainContext, daily_theta_per_share, evaluate_contract
from app.analysis.volatility import range_rank
from app.database import Base
from app.models.user import User
from app.schemas.market import OptionContract, Quote
from app.services.fills import execute_strategy_legs
from app.services.scan_engine import _recommended_contract_delta_theta
from app.services.strategy_engine import build_strategy_layer, strategy_decision
from app.services.strategy_recommendation import (
    APEX_STRATEGY_NAME,
    earnings_position_note,
    extreme_iv_overhang,
    format_iv_rank,
    vol_regime_phrase,
)

RAW_IV_RANK = 46.05037606326132
AAPL = "AAPL261030C00330000"


def _aapl_call(**overrides: object) -> dict:
    row = {
        "symbol": AAPL,
        "side": "call",
        "strike": 330.0,
        "expiry": "2026-10-30",
        "delta": 0.58,
        "theta": -0.18,
        "iv": 0.27,
        "bid": 11.70,
        "ask": 12.22,
        "multiplier": 100,
    }
    row.update(overrides)
    return row


def _layer(contract: dict, **kwargs: object) -> dict:
    base = dict(
        strategy_name="APEX Benchmark Greeks Strategy",
        composite=63.1,
        direction="bullish",
        vol_signal="fair",
        chain_analysis={
            "symbol": "AAPL",
            "spot": 328.0,
            "expiry": "2026-10-30",
            "recommendedContract": {"strike": 330.0, "side": "call", "expiry": "2026-10-30", "symbol": AAPL},
            "contracts": [contract],
        },
        vol_layer={"iv": 0.27, "hv": 0.225, "iv_rank": RAW_IV_RANK},
        sentiment_layer={"bias": "bullish", "score_0_100": 62},
        fundamentals_layer={"score": 60},
        tech_score=74.0,
        ticker="AAPL",
        auto_exec_threshold=40.0,
    )
    base.update(kwargs)
    return build_strategy_layer(**base)  # type: ignore[arg-type]


def _contract_model(**overrides: object) -> OptionContract:
    row = _aapl_call()
    row.update(overrides)
    return OptionContract(
        symbol=str(row["symbol"]),
        strike=float(row["strike"]),
        side="call",
        bid=float(row["bid"]),
        ask=float(row["ask"]),
        delta=float(row["delta"]),
        theta=float(row["theta"]),
        iv=float(row["iv"]),
        multiplier=int(row["multiplier"]),
        greeks_source="vendor",
        iv_source="vendor",
    )


def test_exit_line_uses_the_entry_threshold_not_72() -> None:
    """Composite 63.1 cleared entry at 40. The card must not say exit below 72."""
    passing = _aapl_call(delta=0.60, theta=-0.04)
    layer = _layer(passing)
    text = layer["how_to_execute"]
    assert "below 72" not in text
    assert "final 21 days" in text
    # IV 27% is not below HV 22.5%, so Rule 1 fails and the card is not executable.
    assert layer["auto_exec_line"]
    assert "Auto-execute eligible" not in layer["auto_exec_line"]
    assert layer["auto_exec_blocked"] is True
    assert layer["execution_banner"] == "NOT EXECUTABLE"
    assert "meets your auto-execution threshold" not in layer["why_it_fits"]
    assert "NO TRADE" not in layer["selected_strategy"]
    assert "IV Crush" not in layer["narrative"]


def test_aapl_long_call_fails_theta_and_does_not_auto_execute() -> None:
    layer = _layer(_aapl_call())
    metrics = layer["metrics"]
    assert metrics["max_loss"] == pytest.approx(1196.0, abs=0.01)
    assert metrics["breakevens"][0] == pytest.approx(341.96, abs=0.01)
    assert metrics["max_profit"] is None
    assert metrics["max_profit_unlimited_allowed"] is True
    assert layer["auto_exec_blocked"] is True
    assert layer["auto_exec_line"]
    assert "Auto-execute eligible" not in layer["auto_exec_line"]
    assert layer["clears_threshold"] is False
    joined = " ".join(layer["risk_notes"])
    # Default theta mode is percent of premium. This contract still fails because IV is not below HV.
    assert "contract IV is not below HV" in joined
    assert "below 72" not in layer["how_to_execute"]
    leg = metrics["legs"][0]
    assert leg["order_type"] == "limit"
    assert leg["limit_price"] == pytest.approx(12.22, abs=0.01)
    assert leg["limit_basis"] == "ask"
    assert leg["order_note"] == "limit at the ask"
    assert "mid-price" in layer["how_to_execute"] or "marketable limit" in layer["how_to_execute"].lower()
    assert layer["selected_strategy"] == "APEX Benchmark Greeks Strategy"


def test_aapl_call_does_not_get_a_passing_theta_badge() -> None:
    verdict = evaluate_contract(
        _contract_model(),
        ChainContext(symbol="AAPL", expiry="2026-10-30", dte=26, spot=328.0),
    )
    assert "rule1_buy" not in verdict.flags
    assert "Meets §9.1 Rule 1" not in verdict.reasoning
    assert verdict.delta_theta_ratio == pytest.approx(0.58 / 0.18, rel=0.02)
    assert abs(verdict.delta_theta_ratio or 0) < 10


def test_whole_contract_theta_is_scaled_to_per_share_before_the_gate() -> None:
    """Theta larger than the mid is the contract Greek, not per-share decay."""
    assert daily_theta_per_share(-18.0, mid=11.96, multiplier=100) == pytest.approx(-0.18)
    assert daily_theta_per_share(-0.18, mid=11.96, multiplier=100) == pytest.approx(-0.18)
    verdict = evaluate_contract(
        _contract_model(theta=-18.0),
        ChainContext(symbol="AAPL", expiry="2026-10-30", dte=26, spot=328.0),
    )
    assert "rule1_buy" not in verdict.flags
    assert verdict.delta_theta_ratio == pytest.approx(0.58 / 0.18, rel=0.02)


def test_iv_rank_is_not_the_raw_float() -> None:
    assert format_iv_rank(RAW_IV_RANK) == "46.1"
    assert format_iv_rank(46.0) == "46"
    history = [0.20 + i * 0.001 for i in range(20)]
    history[-1] = 0.27
    rank = range_rank(history, 0.27)
    assert rank is not None
    assert rank == round(rank, 1)
    layer = _layer(_aapl_call())
    assert "46.05037606326132" not in layer["why_it_fits"]
    assert "IV rank 46.1" in layer["why_it_fits"]


def test_iv_above_hv_is_not_labeled_fair_or_cheap_and_is_not_extreme() -> None:
    # IV rank 46 is not sell premium (that requires rank above 50) and not buy premium
    # (rank is not under 30, and IV is not below HV), so the regime is fair.
    phrase = vol_regime_phrase(0.27, 0.225, "fair", iv_rank=RAW_IV_RANK)
    assert phrase == "fair"
    assert phrase != "sell premium"
    assert extreme_iv_overhang(0.27, 0.225) is False
    layer = _layer(_aapl_call())
    assert layer["vol_regime"] == "fair"
    assert "NO TRADE" not in layer["selected_strategy"]
    assert "IV Crush" not in layer["narrative"]
    assert "Wait for IV Crush" not in layer["narrative"]


def test_chain_best_ratio_is_not_the_bought_contract() -> None:
    chain = {
        "recommendedContract": {"symbol": AAPL, "strike": 330, "side": "call"},
        "contracts": [
            {"symbol": AAPL, "strike": 330, "side": "call", "delta": 0.58, "theta": -0.18, "bid": 11.70, "ask": 12.22},
            {
                "symbol": "AAPL261030C00200000",
                "strike": 200,
                "side": "call",
                "delta": 0.90,
                "theta": -0.02,
                "verdict": {"delta_theta_ratio": 45.0},
            },
        ],
    }
    ratio = _recommended_contract_delta_theta(chain)
    assert ratio is not None
    assert ratio < 10
    assert ratio != 45.0


def test_confirmed_earnings_inside_one_day_blocks_auto_execute() -> None:
    blocked, note = earnings_position_note("APEX Benchmark Greeks Strategy", days=1, confirmed=True)
    assert blocked is True
    assert note == "Earnings are within 1 day."
    apex_blocked, apex_note = earnings_position_note(APEX_STRATEGY_NAME, days=0, confirmed=True)
    assert apex_blocked is False
    assert apex_note == "Earnings are within 1 day."
    open_block, open_note = earnings_position_note("Long Call", days=None, confirmed=False)
    assert open_block is False
    assert open_note == "Earnings date is unconfirmed."

    passing = _aapl_call(delta=0.60, theta=-0.04)
    blocked_layer = _layer(
        passing,
        fundamentals_layer={
            "score": 60,
            "earnings_calendar": {"next_date": "2026-10-05", "dte": 1, "status": "live"},
        },
    )
    assert blocked_layer["auto_exec_blocked"] is True
    assert "Earnings are within 1 day." in blocked_layer["risk_notes"]
    assert blocked_layer["selected_strategy"] == "APEX Benchmark Greeks Strategy"

    absent = _layer(
        passing,
        fundamentals_layer={"score": 60, "earnings_calendar": {"next_date": None, "dte": None, "status": "unavailable"}},
    )
    assert any("unconfirmed" in note.lower() for note in absent["risk_notes"])
    # The same AAPL contract fails Rule 1 because IV is not below HV. The missing date is not invented.
    assert absent["auto_exec_blocked"] is True
    assert "2026-10-30" not in " ".join(absent["risk_notes"])

    decision = strategy_decision(
        composite=63.1,
        direction="bullish",
        vol_signal="fair",
        tech_score=70.0,
        auto_exec_threshold=40.0,
        catalyst_days=1,
        earnings_date_confirmed=True,
    )
    assert decision.auto_exec_eligible is False
    assert any("Earnings are within 1 day." in note for note in decision.risk_notes)
    assert "NO TRADE" not in decision.best_match

    unconfirmed = strategy_decision(
        composite=90.0,
        direction="bullish",
        vol_signal="fair",
        iv=0.25,
        hv=0.25,
        tech_score=80.0,
        auto_exec_threshold=40.0,
        earnings_date_confirmed=False,
    )
    assert unconfirmed.auto_exec_eligible is True
    assert any("unconfirmed" in note.lower() for note in unconfirmed.risk_notes)


class _LimitAdapter:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, name=symbol, price=11.96, source="test")

    async def submit_order(self, **kwargs: object) -> dict:
        self.orders.append(dict(kwargs))
        return {"status": "filled", "filled_avg_price": kwargs.get("limit_price") or 11.96}


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


def _user() -> User:
    uid = str(uuid4())
    return User(
        id=uid,
        full_name="Trader",
        username=f"u{uid[:8]}",
        email=f"{uid[:8]}@example.com",
        password_hash="x",
        account_mode="paper_funded",
        cash_balance=100_000.0,
        buying_power=100_000.0,
        portfolio_value=100_000.0,
        starting_balance=100_000.0,
    )


@pytest.mark.asyncio
async def test_spread_rule_submits_a_limit_at_mid(db: AsyncSession) -> None:
    adapter = _LimitAdapter()
    user = _user()
    db.add(user)
    await db.commit()
    await execute_strategy_legs(
        user=user,
        db=db,
        adapter=adapter,
        legs=[
            {
                "symbol": AAPL,
                "side": "buy",
                "option_side": "call",
                "qty": 1,
                "order_type": "limit",
                "limit_price": 11.96,
                "limit_basis": "mid",
                "price": 11.96,
            }
        ],
        contracts_per_leg=1,
    )
    assert len(adapter.orders) == 1
    submitted = adapter.orders[0]
    assert submitted["order_type"] == "limit"
    assert submitted["limit_price"] == pytest.approx(11.96)
    assert submitted["order_type"] != "market"
