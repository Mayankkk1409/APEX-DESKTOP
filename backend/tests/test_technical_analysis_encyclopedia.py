"""Encyclopedia fidelity tests — 100 patterns, 10 layers, export rules."""

from __future__ import annotations

import pytest

from app.analysis.ta.detectors.candlesticks import detect_candlestick_patterns
from app.analysis.ta.detectors.charts import detect_chart_patterns
from app.analysis.ta.detectors.indicators import detect_indicator_patterns
from app.analysis.ta.detectors.levels_gaps import detect_levels_gaps_harmonic
from app.analysis.ta.detectors import export_patterns, patterns_implemented_count
from app.analysis.ta.ohlc_utils import OhlcWindow
from app.analysis.ta.pattern_catalog import FAMILY_PATTERN_COUNT, PATTERN_CATALOG
from app.analysis.ta.pipeline import TECH_LAYER_WEIGHTS, composite_technical_score, compute_layer_scores
from app.analysis.technical_analysis import analyze_technicals


def _indicators(**overrides):
    base = {
        "ema": {9: 101, 21: 100, 50: 98, 100: 95, 200: 90},
        "supertrend": {"direction": "bullish", "value": 99.0},
        "macd": {"line": 0.5, "signal": 0.3, "histogram": 0.2},
        "rsi": 55.0,
        "bollinger": {"width": 0.05, "upper": 110.0, "lower": 90.0, "mid": 100.0},
        "volume": {"last": 1_200_000, "avg": 1_000_000},
        "pivots": {"pp": 100.0, "r1": 102.0, "s1": 98.0},
        "ema_aligned_bullish": True,
        "ema_aligned_bearish": False,
        "bollinger_series": {"upper": [110.0] * 30, "lower": [90.0] * 30, "width": [0.05] * 30},
        "supertrend_series": [{"direction": 1}] * 30,
    }
    base.update(overrides)
    return base


def _hammer_fixture() -> OhlcWindow:
    """Synthetic hammer with bullish confirmation on last bar."""
    opens = [108.0, 106.0, 104.0, 100.0]
    closes = [106.0, 104.0, 99.0, 100.5]
    highs = [108.5, 106.5, 104.5, 100.8]
    lows = [105.0, 103.0, 101.0, 94.0]
    volumes = [1_000_000.0] * 4
    return OhlcWindow.from_lists(opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def _engulfing_fixture() -> OhlcWindow:
    opens = [100.0, 102.0, 100.0]
    closes = [102.0, 100.0, 103.5]
    highs = [102.5, 100.5, 104.0]
    lows = [99.5, 99.0, 99.0]
    volumes = [900_000.0, 900_000.0, 1_100_000.0]
    return OhlcWindow.from_lists(opens=opens, highs=highs, lows=lows, closes=closes, volumes=volumes)


def test_pattern_catalog_has_100_patterns() -> None:
    assert patterns_implemented_count() == 100
    assert len(PATTERN_CATALOG) == 100
    assert sum(FAMILY_PATTERN_COUNT.values()) == 100


@pytest.mark.parametrize(
    "family,module",
    [
        ("single_candle_reversal", detect_candlestick_patterns),
        ("multi_candle_reversal", detect_candlestick_patterns),
        ("continuation_candlestick", detect_candlestick_patterns),
        ("classical_reversal_chart", detect_chart_patterns),
        ("classical_continuation_chart", detect_chart_patterns),
        ("momentum_oscillator", detect_indicator_patterns),
        ("trend_structure", detect_indicator_patterns),
        ("volatility", detect_indicator_patterns),
        ("volume", detect_indicator_patterns),
        ("sr_pivot_fibonacci", detect_levels_gaps_harmonic),
        ("harmonic_elliott", detect_levels_gaps_harmonic),
        ("gap", detect_levels_gaps_harmonic),
    ],
)
def test_each_family_has_catalogued_patterns(family: str, module) -> None:
    assert FAMILY_PATTERN_COUNT.get(family, 0) > 0


def test_hammer_requires_confirmation_for_confirmed_status() -> None:
    w = _hammer_fixture()
    patterns = detect_candlestick_patterns(w)
    hammer = next((p for p in patterns if p.id == "hammer"), None)
    assert hammer is not None
    assert hammer.status == "confirmed"
    assert hammer.confirmation_evidence


def test_engulfing_detection_on_synthetic_fixture() -> None:
    w = _engulfing_fixture()
    patterns = detect_candlestick_patterns(w)
    engulf = next((p for p in patterns if p.id == "bullish_engulfing"), None)
    assert engulf is not None
    assert engulf.direction == "bullish"


def test_invalidation_clears_export_for_weak_patterns() -> None:
    """Forming/low-tier patterns must not export."""
    sigs = [
        type("P", (), {
            "id": "doji", "name": "Doji", "family": "single_candle_reversal",
            "direction": "neutral", "status": "forming", "strength": 42.0,
            "reliability_tier": "low", "confirmation_evidence": (), "invalidation": (),
            "bar_index": 0, "invalidation_price": None, "timeframe": "daily",
            "timestamp": None, "freshness": "current",
            "to_api_dict": lambda self: {},
        })(),
    ]
    from app.analysis.ta.ohlc_utils import PatternSignal
    p = PatternSignal(
        id="doji", name="Doji", family="single_candle_reversal", direction="neutral",
        status="forming", strength=42.0, reliability_tier="low",
    )
    assert export_patterns([p]) == []


def test_ema_stack_downweights_counter_trend_hammer() -> None:
    closes = [110, 109, 108, 107, 106, 105, 104]
    opens = [c + 0.3 for c in closes]
    highs = [c + 0.5 for c in closes]
    lows = [c - 2.5 for c in closes]
    volumes = [900_000] * len(closes)
    result = analyze_technicals(
        opens=opens, closes=closes, highs=highs, lows=lows, volumes=volumes,
        indicators=_indicators(ema_aligned_bullish=True),
    )
    shooting = next((p for p in result.patterns if p.id == "shooting_star"), None)
    if shooting:
        assert shooting.strength < 76.0 or shooting.status != "confirmed"


def test_bollinger_squeeze_not_bullish_without_breakout() -> None:
    closes = [100.0] * 25
    opens = closes[:]
    highs = [100.3] * 25
    lows = [99.7] * 25
    volumes = [1_000_000.0] * 25
    ind = _indicators(
        bollinger={"width": 0.03, "upper": 100.5, "lower": 99.5, "mid": 100.0},
        bollinger_series={"upper": [100.5] * 25, "lower": [99.5] * 25, "width": [0.03] * 25},
    )
    result = analyze_technicals(
        opens=opens, closes=closes, highs=highs, lows=lows, volumes=volumes, indicators=ind,
    )
    squeeze_exported = [p for p in result.chart_patterns if p.id == "bollinger_squeeze" and p.direction == "bullish"]
    assert not squeeze_exported
    assert result.layer_scores.get("bollinger", 60) <= 58


def test_composite_technical_score_breakdown_sums() -> None:
    layer = {k: 70.0 for k in TECH_LAYER_WEIGHTS}
    score = composite_technical_score(layer)
    breakdown_sum = round(sum(layer[k] * TECH_LAYER_WEIGHTS[k] for k in TECH_LAYER_WEIGHTS), 1)
    assert score == breakdown_sum
    assert score == pytest.approx(70.0, abs=0.2)


def test_only_top_confirmed_patterns_exported() -> None:
    closes = list(range(100, 130))
    opens = [c - 0.2 for c in closes]
    highs = [c + 1.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    volumes = [1_200_000] * len(closes)
    result = analyze_technicals(
        opens=opens, closes=closes, highs=highs, lows=lows, volumes=volumes,
        indicators=_indicators(),
    )
    api = result.to_api_dict()
    assert len(api["patterns"]) <= 3
    assert all(p["status"] == "confirmed" for p in api["patterns"])
    assert all(p["strength"] >= 65 for p in api["patterns"])


def test_narrative_avoids_raw_indicator_dumps() -> None:
    result = analyze_technicals(
        opens=[100, 101], closes=[101, 102], highs=[102, 103], lows=[99, 100], volumes=[1e6, 1e6],
        indicators=_indicators(),
    )
    assert "RSI14" not in result.narrative
    assert "MACD line" not in result.narrative
    assert "Composite technical score" in result.narrative


def test_layer_scores_all_ten_layers_present() -> None:
    w = OhlcWindow.from_lists(
        opens=[100, 101], highs=[102, 103], lows=[99, 100], closes=[101, 102], volumes=[1e6, 1e6],
    )
    layer = compute_layer_scores(w, _indicators(), [])
    assert set(layer.keys()) == set(TECH_LAYER_WEIGHTS.keys())
