from __future__ import annotations

from enum import StrEnum


class DeepScanLayer(StrEnum):
    TECHNICAL = "technical"
    VOLUME = "volume"
    CANDLESTICK_PATTERNS = "candlestick_patterns"
    MACD = "macd"
    RSI = "rsi"
    EMA = "ema"
    SUPERTREND = "supertrend"
    BOLLINGER = "bollinger"
    PIVOT_POINTS = "pivot_points"
    SUPPORT_RESISTANCE = "support_resistance"
    # Full Document §5 is a single section ("OPTIONS CHAIN ANALYSIS & GREEKS ENGINE").
    # Chain structure and Greek fitness are one screen so a strike's liquidity gates and
    # its Greek verdict are read together instead of two slides apart.
    OPTIONS_CHAIN_GREEKS = "options_chain_greeks"
    VOLATILITY = "volatility"
    SENTIMENT = "sentiment"
    FUNDAMENTALS = "fundamentals"
    APEX_SCORE = "apex_score"
    STRATEGY = "strategy"
    RISK_REVIEW = "risk_review"


DEEP_SCAN_LAYERS: list[DeepScanLayer] = list(DeepScanLayer)

# User-facing Deep Scan carousel (frontend SCAN_SLIDE_LAYERS must match this order).
SCAN_SLIDE_LAYERS: tuple[str, ...] = (
    "technical",
    "options_chain_greeks",
    "volatility",
    "sentiment",
    "fundamentals",
    "apex_score",
    "strategy",
    "risk_review",
)

# Documented parameters — Full Document §4 and Project APEX §4
EMA_PERIODS = (9, 21, 50, 100, 200)
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14
SUPERTREND_ATR = 10
SUPERTREND_FACTOR = 3.0
BOLLINGER_PERIOD = 20
BOLLINGER_STD = 2.0
COMPOSITE_THRESHOLD_FULL_DOC = 72
COMPOSITE_THRESHOLD_PROJECT = 85
EXECUTION_SCORE_BLOCKED_MAX = 50

# Full Document §8.1 composite weights. Risk is advisory (0) and does not enter the sum.
APEX_COMPOSITE_WEIGHTS: dict[str, float] = {
    "technicals": 0.30,
    "volatility": 0.25,
    "options": 0.20,
    "sentiment": 0.15,
    "fundamentals": 0.10,
    "risk": 0.0,
}

# Strategy recommendation score tiers
SCORE_TIER_NO_TRADE_MAX = 59
SCORE_TIER_WATCHLIST_MAX = 71
SCORE_TIER_CANDIDATE_MIN = 72
DEFAULT_AUTO_EXEC_THRESHOLD = 85

APEX_STRATEGY_NAME = "APEX Strategy"
