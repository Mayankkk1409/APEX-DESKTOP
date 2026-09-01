"""APEX Technical Analysis Pattern Encyclopedia — 100 patterns across 12 families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PatternFamily = Literal[
    "single_candle_reversal",
    "multi_candle_reversal",
    "continuation_candlestick",
    "classical_reversal_chart",
    "classical_continuation_chart",
    "momentum_oscillator",
    "trend_structure",
    "volatility",
    "volume",
    "sr_pivot_fibonacci",
    "harmonic_elliott",
    "gap",
]

PatternDirection = Literal["bullish", "bearish", "neutral"]
ReliabilityTier = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class PatternDefinition:
    id: str
    name: str
    family: PatternFamily
    direction: PatternDirection
    min_bars: int
    default_reliability: ReliabilityTier


# fmt: off
PATTERN_CATALOG: tuple[PatternDefinition, ...] = (
    # Family 1 — Single-candle reversals (12)
    PatternDefinition("hammer", "Hammer", "single_candle_reversal", "bullish", 1, "high"),
    PatternDefinition("inverted_hammer", "Inverted Hammer", "single_candle_reversal", "bullish", 1, "medium"),
    PatternDefinition("hanging_man", "Hanging Man", "single_candle_reversal", "bearish", 1, "medium"),
    PatternDefinition("shooting_star", "Shooting Star", "single_candle_reversal", "bearish", 1, "high"),
    PatternDefinition("doji", "Doji", "single_candle_reversal", "neutral", 1, "low"),
    PatternDefinition("dragonfly_doji", "Dragonfly Doji", "single_candle_reversal", "bullish", 1, "medium"),
    PatternDefinition("gravestone_doji", "Gravestone Doji", "single_candle_reversal", "bearish", 1, "medium"),
    PatternDefinition("spinning_top", "Spinning Top", "single_candle_reversal", "neutral", 1, "low"),
    PatternDefinition("bullish_marubozu", "Bullish Marubozu", "single_candle_reversal", "bullish", 1, "high"),
    PatternDefinition("bearish_marubozu", "Bearish Marubozu", "single_candle_reversal", "bearish", 1, "high"),
    # Family 2 — Multi-candle reversals (18)
    PatternDefinition("bullish_engulfing", "Bullish Engulfing", "multi_candle_reversal", "bullish", 2, "high"),
    PatternDefinition("bearish_engulfing", "Bearish Engulfing", "multi_candle_reversal", "bearish", 2, "high"),
    PatternDefinition("piercing_line", "Piercing Line", "multi_candle_reversal", "bullish", 2, "medium"),
    PatternDefinition("dark_cloud_cover", "Dark Cloud Cover", "multi_candle_reversal", "bearish", 2, "medium"),
    PatternDefinition("morning_star", "Morning Star", "multi_candle_reversal", "bullish", 3, "high"),
    PatternDefinition("evening_star", "Evening Star", "multi_candle_reversal", "bearish", 3, "high"),
    PatternDefinition("bullish_harami", "Bullish Harami", "multi_candle_reversal", "bullish", 2, "medium"),
    PatternDefinition("bearish_harami", "Bearish Harami", "multi_candle_reversal", "bearish", 2, "medium"),
    PatternDefinition("tweezer_top", "Tweezer Top", "multi_candle_reversal", "bearish", 2, "medium"),
    PatternDefinition("tweezer_bottom", "Tweezer Bottom", "multi_candle_reversal", "bullish", 2, "medium"),
    PatternDefinition("three_inside_up", "Three Inside Up", "multi_candle_reversal", "bullish", 3, "high"),
    PatternDefinition("three_inside_down", "Three Inside Down", "multi_candle_reversal", "bearish", 3, "high"),
    PatternDefinition("abandoned_baby_bullish", "Abandoned Baby Bullish", "multi_candle_reversal", "bullish", 3, "high"),
    PatternDefinition("abandoned_baby_bearish", "Abandoned Baby Bearish", "multi_candle_reversal", "bearish", 3, "high"),
    PatternDefinition("kicking_bullish", "Kicking Bullish", "multi_candle_reversal", "bullish", 2, "high"),
    PatternDefinition("kicking_bearish", "Kicking Bearish", "multi_candle_reversal", "bearish", 2, "high"),
    # Family 3 — Continuation candlesticks (8)
    PatternDefinition("three_white_soldiers", "Three White Soldiers", "continuation_candlestick", "bullish", 3, "high"),
    PatternDefinition("three_black_crows", "Three Black Crows", "continuation_candlestick", "bearish", 3, "high"),
    PatternDefinition("rising_three_methods", "Rising Three Methods", "continuation_candlestick", "bullish", 5, "medium"),
    PatternDefinition("falling_three_methods", "Falling Three Methods", "continuation_candlestick", "bearish", 5, "medium"),
    PatternDefinition("upside_tasuki_gap", "Upside Tasuki Gap", "continuation_candlestick", "bullish", 3, "medium"),
    PatternDefinition("downside_tasuki_gap", "Downside Tasuki Gap", "continuation_candlestick", "bearish", 3, "medium"),
    PatternDefinition("inside_bar", "Inside Bar", "continuation_candlestick", "neutral", 2, "low"),
    # Family 4 — Classical reversal chart patterns (12)
    PatternDefinition("head_shoulders", "Head & Shoulders", "classical_reversal_chart", "bearish", 30, "high"),
    PatternDefinition("inverse_head_shoulders", "Inverse Head & Shoulders", "classical_reversal_chart", "bullish", 30, "high"),
    PatternDefinition("double_top", "Double Top", "classical_reversal_chart", "bearish", 20, "high"),
    PatternDefinition("double_bottom", "Double Bottom", "classical_reversal_chart", "bullish", 20, "high"),
    PatternDefinition("rounding_top", "Rounding Top", "classical_reversal_chart", "bearish", 40, "medium"),
    PatternDefinition("rounding_bottom", "Rounding Bottom", "classical_reversal_chart", "bullish", 40, "medium"),
    # Family 5 — Classical continuation chart patterns (12)
    PatternDefinition("bull_flag", "Bull Flag", "classical_continuation_chart", "bullish", 20, "high"),
    PatternDefinition("bear_flag", "Bear Flag", "classical_continuation_chart", "bearish", 20, "high"),
    PatternDefinition("ascending_triangle", "Ascending Triangle", "classical_continuation_chart", "bullish", 25, "medium"),
    PatternDefinition("descending_triangle", "Descending Triangle", "classical_continuation_chart", "bearish", 25, "medium"),
    PatternDefinition("symmetrical_triangle", "Symmetrical Triangle", "classical_continuation_chart", "neutral", 25, "medium"),
    PatternDefinition("rising_wedge", "Rising Wedge", "classical_continuation_chart", "bearish", 25, "medium"),
    PatternDefinition("falling_wedge", "Falling Wedge", "classical_continuation_chart", "bullish", 25, "medium"),
    PatternDefinition("cup_handle", "Cup & Handle", "classical_continuation_chart", "bullish", 50, "high"),
    PatternDefinition("inverted_cup_handle", "Inverted Cup & Handle", "classical_continuation_chart", "bearish", 50, "high"),
    PatternDefinition("rising_channel", "Rising Channel", "classical_continuation_chart", "bullish", 20, "medium"),
    PatternDefinition("falling_channel", "Falling Channel", "classical_continuation_chart", "bearish", 20, "medium"),
    # Family 6 — Momentum oscillator signals (12)
    PatternDefinition("macd_bullish_cross", "MACD Bullish Crossover", "momentum_oscillator", "bullish", 26, "high"),
    PatternDefinition("macd_bearish_cross", "MACD Bearish Crossover", "momentum_oscillator", "bearish", 26, "high"),
    PatternDefinition("macd_bullish_divergence", "MACD Bullish Divergence", "momentum_oscillator", "bullish", 30, "medium"),
    PatternDefinition("macd_bearish_divergence", "MACD Bearish Divergence", "momentum_oscillator", "bearish", 30, "medium"),
    PatternDefinition("rsi_oversold_bounce", "RSI Oversold Bounce", "momentum_oscillator", "bullish", 14, "high"),
    PatternDefinition("rsi_overbought_rejection", "RSI Overbought Rejection", "momentum_oscillator", "bearish", 14, "high"),
    PatternDefinition("rsi_bullish_divergence", "RSI Bullish Divergence", "momentum_oscillator", "bullish", 20, "medium"),
    PatternDefinition("rsi_bearish_divergence", "RSI Bearish Divergence", "momentum_oscillator", "bearish", 20, "medium"),
    PatternDefinition("stoch_oversold_cross", "Stochastic Oversold Cross", "momentum_oscillator", "bullish", 14, "medium"),
    PatternDefinition("stoch_overbought_cross", "Stochastic Overbought Cross", "momentum_oscillator", "bearish", 14, "medium"),
    PatternDefinition("cci_oversold", "CCI Oversold", "momentum_oscillator", "bullish", 20, "medium"),
    PatternDefinition("cci_overbought", "CCI Overbought", "momentum_oscillator", "bearish", 20, "medium"),
    # Family 7 — Trend structure (10)
    PatternDefinition("ema_stack_bullish", "EMA Stack Bullish", "trend_structure", "bullish", 200, "high"),
    PatternDefinition("ema_stack_bearish", "EMA Stack Bearish", "trend_structure", "bearish", 200, "high"),
    PatternDefinition("golden_cross", "Golden Cross", "trend_structure", "bullish", 200, "high"),
    PatternDefinition("death_cross", "Death Cross", "trend_structure", "bearish", 200, "high"),
    PatternDefinition("supertrend_bullish_flip", "SuperTrend Bullish Flip", "trend_structure", "bullish", 10, "high"),
    PatternDefinition("supertrend_bearish_flip", "SuperTrend Bearish Flip", "trend_structure", "bearish", 10, "high"),
    PatternDefinition("ema21_bounce", "EMA 21 Bounce", "trend_structure", "bullish", 21, "medium"),
    PatternDefinition("ema50_bounce", "EMA 50 Bounce", "trend_structure", "bullish", 50, "medium"),
    PatternDefinition("ema200_bounce", "EMA 200 Bounce", "trend_structure", "bullish", 200, "medium"),
    PatternDefinition("ma_ribbon_expansion", "MA Ribbon Expansion", "trend_structure", "neutral", 50, "medium"),
    # Family 8 — Volatility (8)
    PatternDefinition("bollinger_squeeze", "Bollinger Squeeze", "volatility", "neutral", 20, "medium"),
    PatternDefinition("bollinger_walk_upper", "Bollinger Walk Upper", "volatility", "bullish", 20, "medium"),
    PatternDefinition("bollinger_walk_lower", "Bollinger Walk Lower", "volatility", "bearish", 20, "medium"),
    PatternDefinition("percent_b_w_bottom", "%B W-Bottom", "volatility", "bullish", 20, "medium"),
    PatternDefinition("percent_b_m_top", "%B M-Top", "volatility", "bearish", 20, "medium"),
    PatternDefinition("keltner_squeeze", "Keltner Channel Squeeze", "volatility", "neutral", 20, "medium"),
    PatternDefinition("ttm_squeeze", "TTM Squeeze", "volatility", "neutral", 20, "medium"),
    PatternDefinition("atr_expansion_breakout", "ATR Expansion Breakout", "volatility", "neutral", 14, "medium"),
    # Family 9 — Volume (6)
    PatternDefinition("obv_bullish_divergence", "OBV Bullish Divergence", "volume", "bullish", 20, "medium"),
    PatternDefinition("obv_bearish_divergence", "OBV Bearish Divergence", "volume", "bearish", 20, "medium"),
    PatternDefinition("vwap_reclaim", "VWAP Reclaim", "volume", "bullish", 5, "medium"),
    PatternDefinition("vwap_rejection", "VWAP Rejection", "volume", "bearish", 5, "medium"),
    PatternDefinition("volume_climax_bullish", "Volume Climax Bullish", "volume", "bullish", 20, "high"),
    PatternDefinition("volume_breakout_confirm", "Volume Breakout Confirmation", "volume", "neutral", 20, "high"),
    # Family 10 — S/R, pivots, Fibonacci (6)
    PatternDefinition("pivot_classic_bounce", "Classic Pivot Bounce", "sr_pivot_fibonacci", "neutral", 1, "medium"),
    PatternDefinition("support_zone", "Support Zone", "sr_pivot_fibonacci", "bullish", 10, "high"),
    PatternDefinition("resistance_zone", "Resistance Zone", "sr_pivot_fibonacci", "bearish", 10, "high"),
    PatternDefinition("polarity_flip", "Support/Resistance Polarity Flip", "sr_pivot_fibonacci", "neutral", 15, "medium"),
    PatternDefinition("fib_confluence", "Fibonacci Confluence", "sr_pivot_fibonacci", "neutral", 20, "medium"),
    PatternDefinition("fib_382_retrace", "Fib 38.2% Retracement", "sr_pivot_fibonacci", "neutral", 20, "medium"),
    # Family 11 — Harmonic / Elliott (2 — low weight confluence only)
    PatternDefinition("gartley_bullish", "Gartley Bullish", "harmonic_elliott", "bullish", 40, "low"),
    PatternDefinition("gartley_bearish", "Gartley Bearish", "harmonic_elliott", "bearish", 40, "low"),
    # Family 12 — Gap patterns (6)
    PatternDefinition("breakaway_gap_bullish", "Breakaway Gap Bullish", "gap", "bullish", 3, "high"),
    PatternDefinition("breakaway_gap_bearish", "Breakaway Gap Bearish", "gap", "bearish", 3, "high"),
    PatternDefinition("runaway_gap_bullish", "Runaway Gap Bullish", "gap", "bullish", 5, "medium"),
    PatternDefinition("runaway_gap_bearish", "Runaway Gap Bearish", "gap", "bearish", 5, "medium"),
    PatternDefinition("exhaustion_gap_bullish", "Exhaustion Gap Bullish", "gap", "bullish", 5, "medium"),
    PatternDefinition("exhaustion_gap_bearish", "Exhaustion Gap Bearish", "gap", "bearish", 5, "medium"),
)
# fmt: on

assert len(PATTERN_CATALOG) == 100, f"Expected 100 patterns, got {len(PATTERN_CATALOG)}"

PATTERN_BY_ID: dict[str, PatternDefinition] = {p.id: p for p in PATTERN_CATALOG}

FAMILY_PATTERN_COUNT: dict[str, int] = {}
for _p in PATTERN_CATALOG:
    FAMILY_PATTERN_COUNT[_p.family] = FAMILY_PATTERN_COUNT.get(_p.family, 0) + 1
