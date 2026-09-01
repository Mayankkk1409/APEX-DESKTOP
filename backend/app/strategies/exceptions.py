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
