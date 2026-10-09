"""APEX Benchmark Greeks Strategy — Rule 1 buy and Rule 2 defined-risk sell.

Directional alignment uses the existing pillars. It does not add a new score.

Technical trend is ``synthesize_direction`` in ``app.analysis.ta.pipeline``:
bullish when SuperTrend is bullish, the MACD histogram is at least zero, and the
EMA-stack layer score is at least 70 (or confirmed bullish patterns outnumber
bearish ones). The scan already publishes that as ``direction``.

Sentiment is the existing 0–100 pillar ``score_0_100 = (signed composite + 100) / 2``.
Clearly bullish is score_0_100 >= 65 and a bias that contains "bull". 65 is the
actionable bullish line already used by the sentiment narrative. Clearly bearish
is score_0_100 <= 40, which is signed composite <= -20, the existing Bearish band
in ``sentiment_layer._sentiment_band``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.analysis.gate_config import (
    apex_delta_theta_ratio,
    rule1_delta_min,
    rule1_delta_theta_ratio_min,
    rule1_dte_max,
    rule1_dte_min,
    rule1_sentiment_bear_max,
    rule1_sentiment_bull_min,
    rule1_spread_max,
    rule1_theta_pct_per_day,
    rule2_credit_min_pct_of_width,
    rule2_dte_max,
    rule2_dte_min,
    rule2_iv_rank_min,
    rule2_rsi_max,
    rule2_rsi_min,
    rule2_short_delta_max,
    rule2_spread_max,
    rule2_wing_width_pct,
)

Side = Literal["call", "put"]
Rule2Structure = Literal["iron_condor", "bull_put", "bear_call"]

RULE1_WHY = (
    "High delta gives the option meaningful participation in the stock's move, while its daily time decay "
    "is small relative to its price. Implied volatility is below the stock's recent realized volatility, "
    "so you are not overpaying for the option."
)
RULE1_RATIO_EXPLANATION = (
    "The ratio compares what a 1% move in your favor earns against what one day of time decay costs. "
    "A ratio above 10 means a 1% favorable move earns more than ten days of decay."
)
RULE1_HOW = (
    "Buy the option with a limit order near the mid-price. Size the position so that the full premium is "
    "an amount you can afford to lose. Consider taking profits at a predefined target, and exit or "
    "re-evaluate if the trend or sentiment alignment breaks. Close or roll before the final 21 days, "
    "when time decay accelerates."
)
RULE1_RISKS = (
    "The full premium can be lost if the stock does not move in the expected direction before expiration. "
    "A drop in implied volatility reduces the option's value even when the stock price is unchanged."
)
RULE2_WHY = (
    "Implied volatility is high relative to its past year, so option premiums are rich. Momentum is neutral, "
    "which suggests the stock is less likely to make a strong directional move. The short strike sits well "
    "outside the current price, and the long wing caps the maximum loss."
)
RULE2_PROBABILITY = (
    "A short-strike delta of 0.20 or less roughly corresponds to an 80% or greater chance that strike expires "
    "out of the money, under standard pricing assumptions. The app shows the model-calculated probability of "
    "profit for the entire position, which is the figure to rely on."
)
RULE2_HOW = (
    "Enter with a limit order near the mid-price for the net credit. A common management approach is to close "
    "the position once about 50% of the maximum profit has been captured, and to close it if the loss reaches "
    "about 2 times the credit received or the position reaches 21 days to expiration, whichever comes first. "
    "Watch for early-assignment risk on short calls ahead of ex-dividend dates."
)
RULE2_RISKS = (
    "A sharp move through the short strike can produce a loss up to the stated maximum. High implied volatility "
    "can rise further before it falls. Early assignment of a short option is possible, especially before "
    "ex-dividend dates."
)

RULE2_NAMES = {
    "iron_condor": "Short Iron Condor",
    "bull_put": "Bull Put Spread (credit)",
    "bear_call": "Bear Call Spread (credit)",
}


@dataclass
class RuleResult:
    eligible: bool
    entry_id: str
    structure: str | None = None
    side: Side | None = None
    reasons: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    legs: list[dict[str, Any]] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "entry_id": self.entry_id,
            "structure": self.structure,
            "side": self.side,
            "reasons": list(self.reasons),
            "passed": list(self.passed),
        }


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number else None


def alignment_label(
    *,
    technical_direction: str | None,
    sentiment_score: float | None,
    sentiment_bias: str | None,
) -> str:
    """clear_bull, clear_bear, mild_bull, mild_bear, or neutral. Uses the existing pillars."""
    direction = str(technical_direction or "neutral")
    bias = str(sentiment_bias or "")
    bull_line = rule1_sentiment_bull_min()
    bear_line = rule1_sentiment_bear_max()
    clear_bull = (
        direction == "bullish"
        and sentiment_score is not None
        and float(sentiment_score) >= bull_line
        and "bull" in bias.lower()
    )
    clear_bear = direction == "bearish" and sentiment_score is not None and float(sentiment_score) <= bear_line
    if clear_bull:
        return "clear_bull"
    if clear_bear:
        return "clear_bear"
    if direction == "bullish":
        return "mild_bull"
    if direction == "bearish":
        return "mild_bear"
    return "neutral"


def rule2_structure_for(label: str) -> Rule2Structure | None:
    if label == "neutral":
        return "iron_condor"
    if label == "mild_bull":
        return "bull_put"
    if label == "mild_bear":
        return "bear_call"
    return None


def evaluate_rule1(
    *,
    technical_direction: str | None,
    sentiment_score: float | None,
    sentiment_bias: str | None,
    delta: float | None,
    spot: float | None,
    theta_per_share: float | None,
    mid: float | None,
    dte: int | None,
    contract_iv: float | None,
    hv20: float | None,
    bid: float | None = None,
    ask: float | None = None,
    spread_pct: float | None = None,
) -> RuleResult:
    """Every Rule 1 gate. A miss lists that gate and the value. Puts use absolute delta."""
    reasons: list[str] = []
    passed: list[str] = []
    label = alignment_label(
        technical_direction=technical_direction,
        sentiment_score=sentiment_score,
        sentiment_bias=sentiment_bias,
    )
    side: Side | None
    if label == "clear_bull":
        side = "call"
        passed.append(
            f"Directional alignment: technical direction bullish and sentiment score {sentiment_score:g} "
            f"is at least {rule1_sentiment_bull_min():g} with a bullish bias"
        )
    elif label == "clear_bear":
        side = "put"
        passed.append(
            f"Directional alignment: technical direction bearish and sentiment score {sentiment_score:g} "
            f"is at or below {rule1_sentiment_bear_max():g}"
        )
    else:
        side = None
        shown_score = "missing" if sentiment_score is None else f"{float(sentiment_score):g}"
        reasons.append(
            "Directional alignment failed: technical direction "
            f"{technical_direction or 'missing'} and sentiment score {shown_score} "
            "are not both clearly bullish for a call or both clearly bearish for a put"
        )

    abs_delta = abs(delta) if delta is not None else None
    floor = rule1_delta_min()
    if abs_delta is None:
        reasons.append(f"Absolute delta is missing, so the {floor:g} minimum cannot pass")
    elif abs_delta < floor:
        reasons.append(f"Absolute delta {abs_delta:.2f} is below {floor:g}")
    else:
        passed.append(f"Absolute delta {abs_delta:.2f} is at least {floor:g}")

    dte_lo, dte_hi = rule1_dte_min(), rule1_dte_max()
    if dte is None:
        reasons.append(f"DTE is missing, so the {dte_lo} to {dte_hi} window cannot pass")
    elif dte < dte_lo or dte > dte_hi:
        reasons.append(f"DTE {dte} is outside {dte_lo} to {dte_hi}")
    else:
        passed.append(f"DTE {dte} is inside {dte_lo} to {dte_hi}")

    cap = rule1_theta_pct_per_day()
    if theta_per_share is None or mid is None or mid <= 0:
        reasons.append("Daily theta percent cannot pass because theta per share or the option mid is missing")
    else:
        pct = abs(float(theta_per_share)) / float(mid)
        if pct > cap + 1e-12:
            reasons.append(
                f"Daily theta is {pct * 100:.2f}% of the mid, not at or below {cap * 100:.1f}% per day"
            )
        else:
            passed.append(f"Daily theta is {pct * 100:.2f}% of the mid, at or below {cap * 100:.1f}% per day")

    ratio_floor = rule1_delta_theta_ratio_min()
    ratio = None
    if delta is not None and spot is not None and theta_per_share is not None:
        ratio = apex_delta_theta_ratio(delta, spot, theta_per_share)
    if ratio is None:
        reasons.append(f"APEX Delta/Theta Ratio is missing, so the {ratio_floor:g} minimum cannot pass")
    elif ratio <= ratio_floor:
        reasons.append(f"APEX Delta/Theta Ratio {ratio:.2f} is not above {ratio_floor:g}")
    else:
        passed.append(f"APEX Delta/Theta Ratio {ratio:.2f} is above {ratio_floor:g}")

    iv_n, hv_n = _num(contract_iv), _num(hv20)
    if iv_n is not None and iv_n > 3:
        iv_n = iv_n / 100.0
    if hv_n is not None and hv_n > 3:
        hv_n = hv_n / 100.0
    if iv_n is None or hv_n is None:
        reasons.append("Option IV versus 20-day historical volatility cannot pass because one side is missing")
    elif iv_n >= hv_n:
        reasons.append(f"Option IV {iv_n:.4f} is not below 20-day historical volatility {hv_n:.4f}")
    else:
        passed.append(f"Option IV {iv_n:.4f} is below 20-day historical volatility {hv_n:.4f}")

    spread = spread_pct
    if spread is None and bid is not None and ask is not None and bid > 0 and ask > 0:
        mid_px = (float(bid) + float(ask)) / 2.0
        if mid_px > 0:
            spread = (float(ask) - float(bid)) / mid_px
    spread_cap = rule1_spread_max()
    if spread is None:
        reasons.append(f"Bid/ask spread is missing, so the {spread_cap * 100:.0f}% of mid cap cannot pass")
    elif spread >= spread_cap:
        reasons.append(f"Bid/ask spread is {spread * 100:.1f}% of mid, not below {spread_cap * 100:.0f}%")
    else:
        passed.append(f"Bid/ask spread is {spread * 100:.1f}% of mid, below {spread_cap * 100:.0f}%")

    return RuleResult(
        eligible=not reasons,
        entry_id="apex_benchmark_greeks_buy",
        structure="long_option" if not reasons else None,
        side=side if not reasons else side,
        reasons=reasons,
        passed=passed,
    )


def _spread_of(leg: dict[str, Any]) -> float | None:
    bid, ask = leg.get("bid"), leg.get("ask")
    if not isinstance(bid, (int, float)) or not isinstance(ask, (int, float)):
        return None
    if isinstance(bid, bool) or isinstance(ask, bool) or bid <= 0 or ask <= 0:
        return None
    mid = (float(bid) + float(ask)) / 2.0
    if mid <= 0:
        return None
    return (float(ask) - float(bid)) / mid


def _mid_of(leg: dict[str, Any]) -> float | None:
    bid, ask = leg.get("bid"), leg.get("ask")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and not isinstance(bid, bool) and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    mid = leg.get("mid")
    if isinstance(mid, (int, float)) and not isinstance(mid, bool) and mid > 0:
        return float(mid)
    return None


def _pick_short(contracts: list[dict[str, Any]], side: Side, cap: float) -> dict[str, Any] | None:
    pool = []
    for row in contracts:
        if row.get("side") != side or row.get("strike") is None or row.get("delta") is None:
            continue
        if abs(float(row["delta"])) <= cap + 1e-9:
            pool.append(row)
    if not pool:
        return None
    return max(pool, key=lambda row: abs(float(row["delta"])))


def _wing(contracts: list[dict[str, Any]], side: Side, short_strike: float, spot: float, width_pct: float) -> dict[str, Any] | None:
    target = abs(width_pct * spot)
    pool = []
    for row in contracts:
        if row.get("side") != side or row.get("strike") is None:
            continue
        strike = float(row["strike"])
        if side == "put" and strike < short_strike - 1e-9:
            pool.append(row)
        elif side == "call" and strike > short_strike + 1e-9:
            pool.append(row)
    if not pool:
        return None
    return min(pool, key=lambda row: (abs(abs(float(row["strike"]) - short_strike) - target), abs(float(row["strike"]) - short_strike)))


def evaluate_rule2(
    *,
    technical_direction: str | None,
    sentiment_score: float | None,
    sentiment_bias: str | None,
    iv_rank: float | None,
    rsi: float | None,
    dte: int | None,
    contracts: list[dict[str, Any]] | None,
    spot: float | None,
) -> RuleResult:
    """Defined-risk Rule 2. A naked short is never returned."""
    reasons: list[str] = []
    passed: list[str] = []
    label = alignment_label(
        technical_direction=technical_direction,
        sentiment_score=sentiment_score,
        sentiment_bias=sentiment_bias,
    )
    structure = rule2_structure_for(label)
    if structure is None:
        reasons.append(
            "Rule 2 requires a neutral or mild bias; technical direction and sentiment are both clearly directional"
        )
    else:
        passed.append(f"Bias {label} maps to {RULE2_NAMES[structure]}")

    rank_floor = rule2_iv_rank_min()
    if iv_rank is None:
        reasons.append(f"IV Rank is missing, so the {rank_floor:g} minimum cannot pass")
    elif float(iv_rank) <= rank_floor:
        reasons.append(f"IV Rank {float(iv_rank):g} is not above {rank_floor:g}")
    else:
        passed.append(f"IV Rank {float(iv_rank):g} is above {rank_floor:g}")

    rsi_lo, rsi_hi = rule2_rsi_min(), rule2_rsi_max()
    if rsi is None:
        reasons.append(f"RSI(14) is missing, so the {rsi_lo:g} to {rsi_hi:g} band cannot pass")
    elif float(rsi) < rsi_lo or float(rsi) > rsi_hi:
        reasons.append(f"RSI(14) {float(rsi):g} is outside {rsi_lo:g} to {rsi_hi:g}")
    else:
        passed.append(f"RSI(14) {float(rsi):g} is inside {rsi_lo:g} to {rsi_hi:g}")

    dte_lo, dte_hi = rule2_dte_min(), rule2_dte_max()
    if dte is None:
        reasons.append(f"DTE is missing, so the {dte_lo} to {dte_hi} window cannot pass")
    elif dte < dte_lo or dte > dte_hi:
        reasons.append(f"DTE {dte} is outside {dte_lo} to {dte_hi}")
    else:
        passed.append(f"DTE {dte} is inside {dte_lo} to {dte_hi}")

    rows = list(contracts or [])
    if spot is None or spot <= 0 or not rows or structure is None:
        if structure is not None:
            reasons.append("The defined-risk wings cannot be built because the chain or the spot is missing")
        return RuleResult(
            eligible=False,
            entry_id="apex_benchmark_greeks_sell",
            structure=None,
            reasons=reasons,
            passed=passed,
        )

    cap = rule2_short_delta_max()
    width_pct = rule2_wing_width_pct()
    legs: list[dict[str, Any]] = []
    if structure == "bull_put":
        short = _pick_short(rows, "put", cap)
        wing = _wing(rows, "put", float(short["strike"]), spot, width_pct) if short else None
        if short is None:
            reasons.append(f"No short put has absolute delta at or below {cap:.2f}")
        elif wing is None:
            reasons.append("Protective wing is not listed, so a naked short put is not used")
        else:
            legs = [("sell", short), ("buy", wing)]
    elif structure == "bear_call":
        short = _pick_short(rows, "call", cap)
        wing = _wing(rows, "call", float(short["strike"]), spot, width_pct) if short else None
        if short is None:
            reasons.append(f"No short call has absolute delta at or below {cap:.2f}")
        elif wing is None:
            reasons.append("Protective wing is not listed, so a naked short call is not used")
        else:
            legs = [("sell", short), ("buy", wing)]
    else:
        short_put = _pick_short(rows, "put", cap)
        short_call = _pick_short(rows, "call", cap)
        put_wing = _wing(rows, "put", float(short_put["strike"]), spot, width_pct) if short_put else None
        call_wing = _wing(rows, "call", float(short_call["strike"]), spot, width_pct) if short_call else None
        if short_put is None or short_call is None:
            missing = []
            if short_put is None:
                missing.append("put")
            if short_call is None:
                missing.append("call")
            reasons.append(
                f"No short {' and '.join(missing)} has absolute delta at or below {cap:.2f}"
            )
        elif put_wing is None or call_wing is None:
            reasons.append("Protective wings are not listed, so a naked short is not used")
        else:
            legs = [("sell", short_put), ("buy", put_wing), ("sell", short_call), ("buy", call_wing)]

    spread_cap = rule2_spread_max()
    credit = 0.0
    widths: list[float] = []
    built: list[dict[str, Any]] = []
    for action, row in legs:
        spread = _spread_of(row)
        name = f"{action} {row.get('side')} {row.get('strike')}"
        if spread is None:
            reasons.append(f"Bid/ask spread on {name} is missing, so the {spread_cap * 100:.0f}% cap cannot pass")
        elif spread >= spread_cap:
            reasons.append(
                f"Bid/ask spread on {name} is {spread * 100:.1f}% of mid, not below {spread_cap * 100:.0f}%"
            )
        else:
            passed.append(f"Bid/ask spread on {name} is {spread * 100:.1f}% of mid")
        mid = _mid_of(row) or 0.0
        if action == "sell":
            credit += mid
            if row.get("delta") is not None and abs(float(row["delta"])) > cap + 1e-9:
                reasons.append(f"Short option absolute delta {abs(float(row['delta'])):.2f} is above {cap:.2f}")
        else:
            credit -= mid
        built.append({"action": action, **row, "mid": mid})
    if structure == "bull_put" and len(built) == 2:
        widths.append(abs(float(built[0]["strike"]) - float(built[1]["strike"])))
    elif structure == "bear_call" and len(built) == 2:
        widths.append(abs(float(built[0]["strike"]) - float(built[1]["strike"])))
    elif structure == "iron_condor" and len(built) == 4:
        widths.append(abs(float(built[0]["strike"]) - float(built[1]["strike"])))
        widths.append(abs(float(built[2]["strike"]) - float(built[3]["strike"])))

    credit_floor = rule2_credit_min_pct_of_width()
    if widths:
        width = max(widths)
        if credit <= 0:
            reasons.append(f"Net credit {credit:.2f} is not positive, so it is below {credit_floor * 100:.0f}% of the wing width {width:.2f}")
        elif credit < credit_floor * width - 1e-9:
            reasons.append(
                f"Net credit {credit:.2f} is below {credit_floor * 100:.0f}% of the wing width {width:.2f}"
            )
        else:
            passed.append(f"Net credit {credit:.2f} is at least {credit_floor * 100:.0f}% of the wing width {width:.2f}")

    naked = any(item["action"] == "sell" for item in built) and not any(item["action"] == "buy" for item in built)
    if naked:
        reasons.append("A naked short is not allowed")

    return RuleResult(
        eligible=not reasons and bool(built) and not naked,
        entry_id="apex_benchmark_greeks_sell",
        structure=structure if not reasons else None,
        reasons=reasons,
        passed=passed,
        legs=[{"action": row["action"], "side": row.get("side"), "strike": row.get("strike"), "mid": row.get("mid")} for row in built] if not reasons else [],
    )
