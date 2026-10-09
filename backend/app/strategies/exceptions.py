from __future__ import annotations


class StrategyValidationError(Exception):
    """Raised when strategy leg structure or payoff metrics fail validation."""

    def __init__(
        self,
        *,
        strategy_id: str,
        ticker: str,
        check: str,
        expected: str,
        actual: str,
    ) -> None:
        self.strategy_id = strategy_id
        self.ticker = ticker
        self.check = check
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Strategy validation failed [{strategy_id}] {ticker}: {check} — expected {expected}, got {actual}"
        )

    def to_log_dict(self) -> dict[str, str]:
        return {
            "strategy_id": self.strategy_id,
            "ticker": self.ticker,
            "check": self.check,
            "expected": self.expected,
            "actual": self.actual,
        }

    def trader_message(self) -> str:
        """Fact plus one why sentence for the order screen. The log dict stays off the UI."""
        from app.strategies.registry import get_strategy_spec

        spec = get_strategy_spec(self.strategy_id)
        name = spec.display_name if spec is not None else self.strategy_id.replace("_", " ")
        check = self.check.replace("_", " ")
        fact = (
            f"{name} on {self.ticker} failed the {check} check: "
            f"expected {self.expected}, got {self.actual}."
        )
        return f"{fact} {_why_sentence(self.check)}"


def _why_sentence(check: str) -> str:
    """One trader sentence after the measured fact. The log dict stays off this line."""
    key = check.lower()
    if "leg_count" in key:
        return "This is not the strategy on the card."
    if "breakeven" in key:
        return "The payoff is not the shape on the card."
    if "spread" in key:
        return "The price you would pay is not reliable."
    if "buying_power" in key or "buying power" in key:
        return "The account cannot cover the order."
    return "This check is enough to hold the order."
