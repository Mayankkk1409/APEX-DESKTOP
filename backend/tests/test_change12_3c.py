"""Change 12 agent 3C. Verify the order path. Do not loosen the 300-second cap."""

from __future__ import annotations

import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.demo import DemoAdapter
from app.analysis.gate_config import QUOTE_FRESHNESS_SECONDS, quote_is_stale
from app.contracts import AutoExecuteDecision, canAutoExecute
from app.services.executability import enforce_submission_quotes, quote_problem
from app.services.fills import execute_market_fill, execute_strategy_legs

_SESSION = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)
_APP = Path(__file__).resolve().parents[1] / "app"
_ORDER_SOURCES = (
    _APP / "services" / "fills.py",
    _APP / "services" / "executability.py",
    _APP / "services" / "expiry_close.py",
    _APP / "routers" / "portfolio.py",
    _APP / "adapters" / "demo.py",
    _APP / "contracts.py",
)


def _priced(**extra: object) -> dict[str, object]:
    quote: dict[str, object] = {"price": 4.02, "bid": 4.0, "ask": 4.04}
    quote.update(extra)
    return quote


class _Untimed:
    def __init__(self) -> None:
        self.quotes = 0

    async def quote(self, symbol: str) -> SimpleNamespace:
        self.quotes += 1
        return SimpleNamespace(price=4.02, bid=4.0, ask=4.04, as_of=None, source="demo")

    async def submit_order(self, **kwargs: object) -> dict:
        raise AssertionError("live submit must not run")


def test_priced_quote_without_a_timestamp_is_unknown_time() -> None:
    """``quote_is_stale`` still ignores a missing clock. The order path does not."""
    assert QUOTE_FRESHNESS_SECONDS == 300
    assert quote_is_stale(None, now=_SESSION) is False
    assert quote_is_stale("", now=_SESSION) is False
    for missing in (None, "", "not-a-time"):
        problem = quote_problem(_priced(as_of=missing), now=_SESSION)
        assert problem == "Quote not current. Quoted unknown time."


def test_three_hundred_second_cap_is_unchanged() -> None:
    fresh = (_SESSION - timedelta(seconds=300)).isoformat()
    stale = (_SESSION - timedelta(seconds=301)).isoformat()
    assert quote_problem(_priced(as_of=fresh), now=_SESSION) is None
    problem = quote_problem(_priced(as_of=stale), now=_SESSION)
    assert problem is not None
    assert "Quote not current" in problem
    assert "unknown time" not in problem


@pytest.mark.asyncio
async def test_demo_quote_carries_a_timestamp() -> None:
    adapter = DemoAdapter()
    for symbol in ("AAPL", "AAPL261016C00100000"):
        quote = await adapter.quote(symbol)
        assert quote.price is not None
        assert quote.as_of
        assert quote_problem(quote, now=datetime.now(timezone.utc)) is None


@pytest.mark.asyncio
async def test_demo_fill_blocks_a_price_with_no_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def _refuse(self: DemoAdapter, **kwargs: object) -> dict:
        calls["n"] += 1
        raise AssertionError("demo fill must not run")

    monkeypatch.setattr(DemoAdapter, "submit_order", _refuse)
    adapter = _Untimed()
    with pytest.raises(ValueError, match="Quoted unknown time"):
        await execute_market_fill(
            user=SimpleNamespace(account_mode="paper_funded"),  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=adapter,
            symbol="AAPL261016C00100000",
            side="buy",
            qty=1,
            asset_class="us_option",
            force_paper=True,
            submission_path="place_order",
        )
    assert calls["n"] == 0
    assert adapter.quotes == 2

    with pytest.raises(ValueError, match="Quoted unknown time"):
        await execute_strategy_legs(
            user=SimpleNamespace(account_mode="paper_funded"),  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=adapter,
            legs=[{"symbol": "AAPL261016C00100000", "side": "buy"}],
            checks_passed=True,
            submission_path="place_order",
        )
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_expiry_close_path_uses_the_same_quote_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def _refuse(self: DemoAdapter, **kwargs: object) -> dict:
        calls["n"] += 1
        raise AssertionError("demo fill must not run")

    monkeypatch.setattr(DemoAdapter, "submit_order", _refuse)
    with pytest.raises(ValueError, match="Quoted unknown time"):
        await enforce_submission_quotes(_Untimed(), ["AAPL261016C00100000"], path="expiry_close")
    with pytest.raises(ValueError, match="Quoted unknown time"):
        await execute_market_fill(
            user=SimpleNamespace(account_mode="paper_funded"),  # type: ignore[arg-type]
            db=None,  # type: ignore[arg-type]
            adapter=_Untimed(),
            symbol="AAPL261016C00100000",
            side="sell",
            qty=1,
            asset_class="us_option",
            force_paper=True,
            closing=True,
            submission_path="expiry_close",
        )
    assert calls["n"] == 0


def test_can_auto_execute_delegates_and_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.executability import AutoExecuteDecision as LiveDecision

    seen: dict[str, object] = {}

    def _fake(scan: object, settings: object) -> LiveDecision:
        seen["scan"] = scan
        seen["settings"] = settings
        return LiveDecision(eligible=False, reasons=["Composite is below your minimum."])

    monkeypatch.setattr("app.services.executability.can_auto_execute", _fake)
    decision = canAutoExecute({"composite_score": 39}, {"auto_execution_threshold": 40})
    assert seen["scan"] == {"composite_score": 39}
    assert seen["settings"] == {"auto_execution_threshold": 40}
    assert isinstance(decision, AutoExecuteDecision)
    assert decision.eligible is False
    assert decision.reasons == ["Composite is below your minimum."]
    monkeypatch.undo()

    for scan, settings in (
        (None, None),
        ({}, {}),
        ("AAPL", 40),
        (object(), object()),
        ({"composite_score": 90, "executable": True, "validation_passed": True}, {"auto_execution_threshold": 85}),
    ):
        result = canAutoExecute(scan, settings)
        assert isinstance(result, AutoExecuteDecision)
        assert isinstance(result.eligible, bool)
        assert isinstance(result.reasons, list)


def test_skip_quote_check_is_absent_from_order_paths() -> None:
    for fn in (execute_market_fill, execute_strategy_legs, enforce_submission_quotes):
        assert "skip_quote_check" not in inspect.signature(fn).parameters
    for path in _ORDER_SOURCES:
        assert "skip_quote_check" not in path.read_text()
    bypass = re.compile(r"skip_quote_check\s*=")
    tests = Path(__file__).resolve().parent
    for path in tests.rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            assert bypass.search(code) is None, f"{path.name}:{lineno} passes a quote-check bypass"
