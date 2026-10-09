"""Unit tests for volatility math + intel payload honesty."""

from __future__ import annotations

import math

from app.analysis.volatility import (
    expected_move,
    hv_rank_bundle,
    iv_rank_from_history,
    percentile_rank,
    range_rank,
    realized_vol,
)
from app.schemas.market import OptionChain, OptionContract
from app.services.volatility_intel import build_volatility_payload, synthesize_iv_history_from_underlying


def _closes(n: int = 80, start: float = 100.0) -> list[float]:
    # Mild trending + oscillation so HV is non-zero and ranks are defined.
    out = []
    px = start
    for i in range(n):
        px *= 1.0 + 0.004 * math.sin(i / 3.0) + 0.0005
        out.append(px)
    return out


def test_realized_vol_needs_enough_returns() -> None:
    assert realized_vol([100.0], 5) is None
    assert realized_vol(_closes(30), 21) is not None


def test_range_rank_and_percentile_floor() -> None:
    series = [0.1 + i * 0.01 for i in range(10)]
    assert range_rank(series, 0.15) is None  # < MIN_RANK_SAMPLES
    assert percentile_rank(series, 0.15) is None
    series = [0.1 + i * 0.01 for i in range(30)]
    assert 0.0 <= (range_rank(series, 0.25) or -1) <= 100.0
    assert 0.0 <= (percentile_rank(series, 0.25) or -1) <= 100.0


def test_expected_move_formula() -> None:
    out = expected_move(100.0, 0.20, 365)
    assert out["dollars"] is not None
    assert abs(out["dollars"] - 20.0) < 1e-9
    assert out["percent"] == 20.0
    assert expected_move(None, 0.2, 30)["dollars"] is None


def test_iv_rank_never_invented_from_empty_history() -> None:
    empty = iv_rank_from_history([], 0.25)
    assert empty["iv_rank"] is None
    assert empty["iv_percentile"] is None


def test_payload_iv_rank_from_atm_when_no_recommended_contract() -> None:
    closes = _closes(120)
    bars = [{"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "c": c, "o": c, "h": c, "l": c, "v": 1} for i, c in enumerate(closes)]
    contracts = [
        OptionContract(symbol="AAPL261218C00100000", strike=100.0, side="call", iv=0.22),
        OptionContract(symbol="AAPL261218P00100000", strike=100.0, side="put", iv=0.24),
    ]
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-12-18",
        spot=100.0,
        feed="indicative",
        contracts=contracts,
        status="live",
    )
    payload = build_volatility_payload(symbol="AAPL", bars=bars, chain=chain, expiry="2026-12-18", spot=100.0)
    assert payload["iv"] is not None
    assert payload["iv_rank"] is not None
    assert payload["iv_percentile"] is not None
    assert payload.get("iv_history_source") in {"atm_synthetic", "recommended_synthetic", "recommended_leg", "none"}
    assert payload["series"]["bar_count"] >= 20


def test_payload_marks_iv_rank_unavailable_without_history() -> None:
    closes = _closes(120)
    bars = [{"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "c": c, "o": c, "h": c, "l": c, "v": 1} for i, c in enumerate(closes)]
    contracts = [
        OptionContract(symbol="AAPL261218C00100000", strike=100.0, side="call", iv=0.22),
        OptionContract(symbol="AAPL261218P00100000", strike=100.0, side="put", iv=0.24),
    ]
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-12-18",
        spot=100.0,
        feed="indicative",
        contracts=contracts,
        status="live",
    )
    payload = build_volatility_payload(symbol="AAPL", bars=bars, chain=chain, expiry="2026-12-18", spot=100.0)
    assert payload["iv"] is not None
    assert payload["atm_iv"] is not None
    assert abs(payload["atm_iv"] - 0.23) < 1e-9
    assert payload["iv_rank"] is not None
    assert payload["iv_percentile"] is not None
    assert payload["expected_move"]["dollars"] is not None
    assert payload["dte"] is not None
    assert any(c["id"] == "iv_rank" for c in payload["cards"])
    iv_rank_card = next(c for c in payload["cards"] if c["id"] == "iv_rank")
    assert "unavailable" not in iv_rank_card["body"].lower()


def test_recommended_contract_card_when_iv_missing_from_chain() -> None:
    closes = _closes(120)
    bars = [{"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "c": c, "o": c, "h": c, "l": c, "v": 1} for i, c in enumerate(closes)]
    contracts = [
        OptionContract(symbol="AAPL261218C00105000", strike=105.0, side="call", iv=None),
        OptionContract(symbol="AAPL261218P00100000", strike=100.0, side="put", iv=0.24),
    ]
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-12-18",
        spot=100.0,
        feed="indicative",
        contracts=contracts,
        status="live",
    )
    recommended = {
        "symbol": "AAPL",
        "expiry": "2026-12-18",
        "strike": 105.0,
        "side": "call",
        "contract_id": "AAPL261218C00105000",
    }
    payload = build_volatility_payload(
        symbol="AAPL",
        bars=bars,
        chain=chain,
        expiry="2026-12-18",
        spot=100.0,
        recommended_contract=recommended,
    )
    card = next(c for c in payload["cards"] if c["id"] == "recommended_vs_atm")
    assert "No recommended contract is attached" not in card["body"]
    assert "105" in card["body"]


def test_payload_iv_rank_computed_with_recommended_contract_history() -> None:
    closes = _closes(120)
    bars = [{"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00Z", "c": c, "o": c, "h": c, "l": c, "v": 1} for i, c in enumerate(closes)]
    contracts = [
        OptionContract(symbol="AAPL261218C00100000", strike=100.0, side="call", iv=0.22),
        OptionContract(symbol="AAPL261218P00100000", strike=100.0, side="put", iv=0.24),
    ]
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-12-18",
        spot=100.0,
        feed="indicative",
        contracts=contracts,
        status="live",
    )
    recommended = {
        "symbol": "AAPL",
        "expiry": "2026-12-18",
        "strike": 100.0,
        "side": "call",
        "contract_id": "AAPL261218C00100000",
    }
    payload = build_volatility_payload(
        symbol="AAPL",
        bars=bars,
        chain=chain,
        expiry="2026-12-18",
        spot=100.0,
        recommended_contract=recommended,
    )
    assert payload["iv_history_points"] is not None
    assert payload["iv_history_points"] >= 20
    assert payload["iv_rank"] is not None
    assert payload["iv_percentile"] is not None
    assert 0.0 <= payload["iv_rank"] <= 100.0
    assert 0.0 <= payload["iv_percentile"] <= 100.0
    iv_series = payload["series"]["iv_series"]
    assert len(iv_series) >= 20
    assert len({round(p["iv"], 6) for p in iv_series if p["iv"] is not None}) >= 2
    iv_rank_card = next(c for c in payload["cards"] if c["id"] == "iv_rank")
    assert "unavailable" not in iv_rank_card["body"].lower()
    iv_pct_card = next(c for c in payload["cards"] if c["id"] == "iv_percentile")
    assert "unavailable" not in iv_pct_card["body"].lower()


def test_synthesize_iv_history_produces_enough_points() -> None:
    closes = _closes(80)
    bars = [{"t": f"2026-02-{(i % 28) + 1:02d}T00:00:00Z", "c": c} for i, c in enumerate(closes)]
    hist = synthesize_iv_history_from_underlying(
        bars,
        strike=100.0,
        side="call",
        expiry="2026-12-18",
    )
    assert len(hist) >= 20
    values = [round(v, 6) for _, v in hist]
    assert len(set(values)) >= 2


def test_payload_without_expiry_is_honest() -> None:
    closes = _closes(60)
    bars = [{"t": f"t{i}", "c": c, "o": c, "h": c, "l": c, "v": 1} for i, c in enumerate(closes)]
    payload = build_volatility_payload(symbol="AAPL", bars=bars, chain=None, expiry=None, spot=100.0)
    assert payload["iv"] is None
    assert payload["dte"] is None
    assert payload["expected_move"]["dollars"] is None
    assert payload["hv"] is not None or payload["hv_by_window"]


def test_hv_rank_bundle_warms_up() -> None:
    bundle = hv_rank_bundle(_closes(200), "30D")
    assert bundle["hv"] is not None
    assert bundle["hv_rank"] is not None
    assert bundle["hv_percentile"] is not None


def test_iv_series_not_flat_from_varying_option_bars() -> None:
    """IV history must vary day-to-day — not one snapshot repeated."""
    from datetime import date

    from app.services.volatility_intel import build_iv_series_from_option_bars

    underlying = {
        f"2026-08-{d:02d}": 100.0 + d * 0.5
        for d in range(18, 25)
    }
    option_bars = [
        {"t": f"2026-08-{d:02d}T00:00:00Z", "c": 9.5 + (d - 18) * 0.25}
        for d in range(18, 25)
    ]
    series = build_iv_series_from_option_bars(
        option_bars,
        underlying,
        strike=100.0,
        side="call",
        expiry="2026-08-26",
        today=date(2026, 8, 24),
    )
    assert len(series) >= 3
    values = [round(v, 6) for _, v in series]
    assert len(set(values)) >= 2, "IV series must show day-to-day variation"


def test_missing_iv_history_is_a_gap_not_an_hv_proxy() -> None:
    contracts = [
        OptionContract(symbol="AAPL261218C00100000", strike=100.0, side="call", iv=0.22),
        OptionContract(symbol="AAPL261218P00100000", strike=100.0, side="put", iv=0.24),
    ]
    chain = OptionChain(
        symbol="AAPL",
        expiry="2026-12-18",
        spot=100.0,
        feed="indicative",
        contracts=contracts,
        status="live",
        as_of="2026-10-05T15:00:00+00:00",
    )
    payload = build_volatility_payload(symbol="AAPL", bars=[], chain=chain, expiry="2026-12-18", spot=100.0)
    assert payload["iv_rank"] is None
    assert payload["iv_rank_gap"]
    assert "not IV rank" in payload["iv_rank_gap"]
    assert payload["feed"] == "indicative"
    assert payload["quoted_at"] == "2026-10-05T15:00:00+00:00"
