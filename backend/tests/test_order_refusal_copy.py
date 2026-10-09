"""Order refusals keep the measured fact and add one trader sentence. No log dict."""

from app.services.executability import spread_confirmation_text
from app.strategies.exceptions import StrategyValidationError


def test_spread_and_leg_count_refusals_keep_the_fact_and_add_why() -> None:
    spread = spread_confirmation_text(spread_pct=0.102, threshold=0.10, slippage=2578.50)
    assert "10.2%" in spread
    assert "wider than the 10% cap" in spread
    assert "Estimated slippage $2578.50" in spread
    assert "The price you would pay is not reliable." in spread
    assert "{" not in spread
    assert "strategy_id" not in spread

    legs = StrategyValidationError(
        strategy_id="short_iron_condor",
        ticker="TSLA",
        check="leg_count",
        expected="4",
        actual="3",
    ).trader_message()
    assert "expected 4, got 3" in legs
    assert "leg count" in legs
    assert "This is not the strategy on the card." in legs
    assert "{" not in legs
    assert "strategy_id" not in legs

    shape = StrategyValidationError(
        strategy_id="bull_call_spread",
        ticker="AAPL",
        check="breakeven_shape",
        expected="1",
        actual="0",
    ).trader_message()
    assert "expected 1, got 0" in shape
    assert "breakeven shape" in shape
    assert "The payoff is not the shape on the card." in shape
    assert "{" not in shape
