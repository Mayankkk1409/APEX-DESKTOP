"""10-layer APEX Composite Technical Score pipeline."""

from __future__ import annotations

from typing import Any, Literal

from app.analysis.ta.ohlc_utils import OhlcWindow, PatternSignal, STRENGTH_EXPORT_FLOOR

# Encyclopedia 10-layer weights (sum = 1.0)
TECH_LAYER_WEIGHTS: dict[str, float] = {
    "macd": 0.12,
    "rsi": 0.10,
    "ema_stack": 0.18,
    "supertrend": 0.14,
    "bollinger": 0.08,
    "candlestick": 0.10,
    "pivot_sr": 0.08,
    "chart_patterns": 0.08,
    "volume": 0.08,
    "momentum": 0.04,
}


def compute_layer_scores(
    w: OhlcWindow,
    indicators: dict[str, Any],
    patterns: list[PatternSignal],
) -> dict[str, float]:
    ema = indicators.get("ema") or {}
    st = indicators.get("supertrend") or {}
    macd = indicators.get("macd") or {}
    rsi = float(indicators.get("rsi") or 50.0)
    bb = indicators.get("bollinger") or {}
    vol = indicators.get("volume") or {}
    ema_bullish = bool(indicators.get("ema_aligned_bullish"))
    ema_bearish = bool(indicators.get("ema_aligned_bearish"))
    last = w.closes[-1] if w.closes else 0.0
    ema200 = ema.get(200)
    layer: dict[str, float] = {}

    # Layer 1: MACD
    hist = float(macd.get("histogram") or 0.0)
    line = float(macd.get("line") or 0.0)
    signal = float(macd.get("signal") or 0.0)
    if line > signal and hist > 0:
        layer["macd"] = 88.0
    elif line > signal:
        layer["macd"] = 75.0
    elif line < signal and hist < 0:
        layer["macd"] = 85.0
    elif line < signal:
        layer["macd"] = 70.0
    else:
        layer["macd"] = 55.0

    # Layer 2: RSI with EMA trend-riding filter
    if ema_bullish and 45 <= rsi <= 65:
        layer["rsi"] = 78.0
    elif ema_bearish and 35 <= rsi <= 55:
        layer["rsi"] = 78.0
    elif 40 <= rsi <= 60:
        layer["rsi"] = 72.0
    elif rsi > 70:
        layer["rsi"] = 58.0
    elif rsi < 30:
        layer["rsi"] = 60.0
    else:
        layer["rsi"] = 65.0

    # Layer 3: EMA stack
    if ema_bullish:
        layer["ema_stack"] = 92.0
    elif ema_bearish:
        layer["ema_stack"] = 88.0
    elif ema.get(50) and ema.get(200) and ema[50] > ema[200]:
        layer["ema_stack"] = 62.0
    else:
        layer["ema_stack"] = 45.0

    # Layer 4: SuperTrend
    st_dir = st.get("direction", "neutral")
    if st_dir == "bullish" and ema200 and last > ema200:
        layer["supertrend"] = 90.0
    elif st_dir == "bearish" and ema200 and last < ema200:
        layer["supertrend"] = 88.0
    elif st_dir == "bullish":
        layer["supertrend"] = 68.0
    else:
        layer["supertrend"] = 50.0

    # Layer 5: Bollinger — squeeze is vol precursor until breakout
    width = float(bb.get("width") or 0.05)
    upper = bb.get("upper")
    lower = bb.get("lower")
    squeeze = width < 0.04
    vol_last = float(vol.get("last") or 0)
    vol_avg = float(vol.get("avg") or 1)
    vol_ratio = vol_last / vol_avg if vol_avg else 1.0
    breakout_confirmed = False
    if squeeze and upper is not None and lower is not None:
        if last > float(upper) and vol_ratio >= 1.2:
            breakout_confirmed = True
        elif last < float(lower) and vol_ratio >= 1.2:
            breakout_confirmed = True
    bb_sigs = [p for p in patterns if p.family == "volatility" and p.id == "bollinger_squeeze"]
    if squeeze and not breakout_confirmed and not any(p.status == "confirmed" and p.direction != "neutral" for p in bb_sigs):
        layer["bollinger"] = 55.0
    elif breakout_confirmed:
        layer["bollinger"] = 78.0
    elif width > 0.12:
        layer["bollinger"] = 58.0
    else:
        layer["bollinger"] = 65.0

    # Layer 6: Candlestick patterns (families 1-3)
    candle_confirmed = [
        p for p in patterns
        if p.family in ("single_candle_reversal", "multi_candle_reversal", "continuation_candlestick")
        and p.status == "confirmed"
        and p.reliability_tier in ("high", "medium")
        and p.strength >= STRENGTH_EXPORT_FLOOR
    ]
    if candle_confirmed:
        layer["candlestick"] = min(95.0, max(p.strength for p in candle_confirmed))
    elif any(p.family.startswith("single") or "candle" in p.family for p in patterns):
        layer["candlestick"] = 50.0
    else:
        layer["candlestick"] = 48.0

    # Layer 7: Pivot / S-R — confluence context
    sr_patterns = [p for p in patterns if p.family == "sr_pivot_fibonacci"]
    pivots = indicators.get("pivots") or {}
    pp = pivots.get("pp")
    if sr_patterns:
        layer["pivot_sr"] = min(78.0, max(p.strength for p in sr_patterns) * 0.85)
    elif pp is not None and last:
        dist_pct = abs(last - float(pp)) / max(last, 0.01) * 100
        layer["pivot_sr"] = 72.0 if dist_pct < 1.0 else 58.0 if dist_pct < 2.5 else 52.0
    else:
        layer["pivot_sr"] = 52.0

    # Layer 8: Chart pattern geometry (families 4-5)
    chart_confirmed = [
        p for p in patterns
        if p.family in ("classical_reversal_chart", "classical_continuation_chart")
        and p.status == "confirmed"
        and p.strength >= 60
    ]
    if chart_confirmed:
        layer["chart_patterns"] = min(92.0, max(p.strength for p in chart_confirmed))
    else:
        layer["chart_patterns"] = 50.0

    # Layer 9: Volume confirmation
    vol_patterns = [p for p in patterns if p.family == "volume" and p.status == "confirmed"]
    if vol_patterns:
        layer["volume"] = min(90.0, max(p.strength for p in vol_patterns))
    else:
        layer["volume"] = 80.0 if vol_ratio > 1.3 else 55.0 if vol_ratio < 0.7 else 68.0

    # Layer 10: Momentum / oscillator confluence
    mom = [p for p in patterns if p.family in ("momentum_oscillator", "trend_structure") and p.status == "confirmed"]
    if mom:
        layer["momentum"] = min(90.0, max(p.strength for p in mom))
    elif len(w.closes) >= 5:
        momentum = (w.closes[-1] - w.closes[-5]) / w.closes[-5] * 100 if w.closes[-5] else 0
        layer["momentum"] = min(90.0, 55.0 + abs(momentum) * 3)
    else:
        layer["momentum"] = 50.0

    # Harmonic/Elliott — low-weight confluence bump only
    harmonic = [p for p in patterns if p.family == "harmonic_elliott" and p.status == "forming"]
    if harmonic:
        layer["momentum"] = min(90.0, layer.get("momentum", 50.0) + 3.0)

    return layer


def composite_technical_score(layer_scores: dict[str, float]) -> float:
    from app.analysis.score_bounds import assert_score_in_bounds

    score = sum(layer_scores.get(k, 50.0) * w for k, w in TECH_LAYER_WEIGHTS.items())
    bounded = round(max(5.0, min(98.0, score)), 1)
    return assert_score_in_bounds("technical_score", bounded) or bounded


def synthesize_direction(
    layer_scores: dict[str, float],
    patterns: list[PatternSignal],
    indicators: dict[str, Any],
) -> Literal["bullish", "bearish", "neutral", "mixed"]:
    st = indicators.get("supertrend") or {}
    st_dir = st.get("direction", "neutral")
    hist = float((indicators.get("macd") or {}).get("histogram") or 0.0)
    bull_pts = sum(1 for p in patterns if p.direction == "bullish" and p.status == "confirmed" and p.strength >= 65)
    bear_pts = sum(1 for p in patterns if p.direction == "bearish" and p.status == "confirmed" and p.strength >= 65)

    if bull_pts > 0 and bear_pts > 0:
        return "mixed"
    if st_dir == "bullish" and hist >= 0 and layer_scores.get("ema_stack", 50) >= 70:
        return "bullish"
    if st_dir == "bearish" and hist < 0 and layer_scores.get("ema_stack", 50) >= 70:
        return "bearish"
    if bull_pts > bear_pts:
        return "bullish"
    if bear_pts > bull_pts:
        return "bearish"
    return "neutral"


def professional_narrative(
    score: float,
    direction: str,
    patterns: list[PatternSignal],
    layer_scores: dict[str, float],
    indicators: dict[str, Any],
) -> str:
    ema_bull = indicators.get("ema_aligned_bullish")
    ema_bear = indicators.get("ema_aligned_bearish")
    confirmed = [p for p in patterns if p.status == "confirmed" and p.strength >= 65 and p.reliability_tier in ("high", "medium")]

    trend_clause = "Trend structure aligns bullish across the EMA stack and SuperTrend." if ema_bull else (
        "Trend structure aligns bearish across the EMA stack and SuperTrend." if ema_bear else
        "Trend structure is mixed — no full EMA-stack alignment."
    )
    pattern_clause = "No high-confidence confirmed patterns on the captured window." if not confirmed else (
        f"Strongest confirmed setup: {confirmed[0].name} ({confirmed[0].direction})."
        + (f" Secondary: {confirmed[1].name}." if len(confirmed) > 1 else "")
    )
    vol_note = ""
    bb = layer_scores.get("bollinger", 55)
    if bb <= 58:
        vol_note = " Volatility is compressed — treat Bollinger squeeze as a precursor until a volume-backed breakout confirms direction."

    return (
        f"Composite technical score {score}/100 — {direction.capitalize()} bias. "
        f"{trend_clause} {pattern_clause}{vol_note}"
    ).strip()
