"""Configurable pre-trade gates. Thresholds come from settings, not call-site literals."""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Feature.txt compares market data on a 5-minute cycle. A quote older than that is stale.
QUOTE_FRESHNESS_SECONDS = 5 * 60
IV_MISMATCH_VOL_POINTS = 5.0
PLAIN_LONG_PREMIUM = frozenset(
    {
        "Long Call",
        "Long Put",
        "APEX Benchmark Greeks Strategy",
        "At-The-Money Call",
        "At-The-Money Put",
        "Deep ITM Call",
        "Deep ITM Put",
        "Long Call LEAPS",
        "Long Put LEAPS",
    }
)
CREDIT_STRUCTURES = frozenset(
    {
        "Short Iron Condor",
        "Bull Put Spread (credit)",
        "Bear Call Spread (credit)",
    }
)
DEBIT_VERTICALS = frozenset({"Bull Call Spread", "Bear Put Spread"})
NOT_EXECUTABLE = "NOT EXECUTABLE"


def theta_filter_mode() -> str:
    mode = str(get_settings().theta_filter_mode or "pct_of_premium")
    if mode not in {"abs_per_share", "pct_of_premium"}:
        return "pct_of_premium"
    return mode


def theta_max_pct_per_day() -> float:
    return float(get_settings().theta_max_pct_per_day)


def entry_composite_min() -> float:
    return float(get_settings().entry_composite_min)


def exit_composite_min() -> float:
    return float(get_settings().exit_composite_min)


def min_iv_inversion_pts() -> float:
    return float(get_settings().min_iv_inversion_pts)


def rule1_delta_min() -> float:
    return float(get_settings().rule1_delta_min)


def rule1_dte_min() -> int:
    return int(get_settings().rule1_dte_min)


def rule1_dte_max() -> int:
    return int(get_settings().rule1_dte_max)


def rule1_theta_pct_per_day() -> float:
    """Daily |theta| / mid cap for Rule 1. Default 0.010, replacing the 1.5% buy cap for this rule."""
    return float(get_settings().rule1_theta_pct_per_day)


def rule1_delta_theta_ratio_min() -> float:
    return float(get_settings().rule1_delta_theta_ratio_min)


def rule1_spread_max() -> float:
    return float(get_settings().rule1_spread_max)


def rule1_sentiment_bull_min() -> float:
    """Existing actionable bullish line on the sentiment pillar's 0–100 score."""
    return float(get_settings().rule1_sentiment_bull_min)


def rule1_sentiment_bear_max() -> float:
    """Existing Bearish band on the sentiment pillar's 0–100 score (signed composite <= -20)."""
    return float(get_settings().rule1_sentiment_bear_max)


def rule2_iv_rank_min() -> float:
    return float(get_settings().rule2_iv_rank_min)


def rule2_rsi_min() -> float:
    return float(get_settings().rule2_rsi_min)


def rule2_rsi_max() -> float:
    return float(get_settings().rule2_rsi_max)


def rule2_short_delta_max() -> float:
    return float(get_settings().rule2_short_delta_max)


def rule2_dte_min() -> int:
    return int(get_settings().rule2_dte_min)


def rule2_dte_max() -> int:
    return int(get_settings().rule2_dte_max)


def rule2_wing_width_pct() -> float:
    return float(get_settings().rule2_wing_width_pct)


def rule2_spread_max() -> float:
    return float(get_settings().rule2_spread_max)


def rule2_credit_min_pct_of_width() -> float:
    return float(get_settings().rule2_credit_min_pct_of_width)


def gamma_earnings_days_min() -> int:
    return int(get_settings().gamma_earnings_days_min)


def gamma_earnings_days_max() -> int:
    return int(get_settings().gamma_earnings_days_max)


def gamma_front_iv_rank_min() -> float:
    return float(get_settings().gamma_front_iv_rank_min)


def gamma_front_back_iv_ratio_min() -> float:
    return float(get_settings().gamma_front_back_iv_ratio_min)


def gamma_history_hits_min() -> int:
    return int(get_settings().gamma_history_hits_min)


def gamma_history_lookback() -> int:
    return int(get_settings().gamma_history_lookback)


def gamma_adv_min() -> float:
    return float(get_settings().gamma_adv_min)


def gamma_open_interest_min() -> int:
    return int(get_settings().gamma_open_interest_min)


def gamma_spread_max() -> float:
    return float(get_settings().gamma_spread_max)


def gamma_back_week_days() -> int:
    return int(get_settings().gamma_back_week_days)


def gamma_back_week_tolerance_days() -> int:
    return int(get_settings().gamma_back_week_tolerance_days)


def apex_delta_theta_ratio(delta: float, spot: float, theta_per_share: float) -> float | None:
    """( |delta| × underlying × 0.01 ) / |theta per share|.

    A 1% favorable move versus one day of decay. This is the Rule 1 ratio.
    It replaces |delta| / |theta| for this rule only.
    """
    if spot is None or spot <= 0:
        return None
    decay = abs(float(theta_per_share))
    if decay <= 0 or not math.isfinite(decay) or not math.isfinite(float(delta)):
        return None
    return (abs(float(delta)) * float(spot) * 0.01) / decay


def _as_fraction(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    if number > 3.0:
        number = number / 100.0
    return number


def inversion_vol_points(front_iv: Any, back_iv: Any) -> float | None:
    """Front IV minus back IV, in volatility points. 0.35 and 0.30 is 5 points."""
    front = _as_fraction(front_iv)
    back = _as_fraction(back_iv)
    if front is None or back is None:
        return None
    return (front - back) * 100.0


def classify_vol_regime(*, iv_rank: Any, iv: Any, hv: Any) -> str:
    """Plain-word regime. Sell premium only when IV rank is above 50 and IV is not below HV."""
    pair_iv = _as_fraction(iv)
    pair_hv = _as_fraction(hv)
    iv_below_hv = pair_iv is not None and pair_hv is not None and pair_iv < pair_hv
    rank: float | None = None
    if isinstance(iv_rank, (int, float)) and not isinstance(iv_rank, bool) and math.isfinite(float(iv_rank)):
        rank = float(iv_rank)
    if rank is not None and rank > 50.0 and not iv_below_hv:
        return "sell premium"
    if (rank is not None and rank < 30.0) or iv_below_hv:
        return "buy premium"
    return "fair"


def hysteresis_action(
    composite: float,
    *,
    in_position: bool,
    entry_min: float | None = None,
    exit_min: float | None = None,
) -> str:
    """Enter only at or above the entry line. Exit an open position only below the exit line."""
    entry = float(entry_composite_min() if entry_min is None else entry_min)
    exit_line = float(exit_composite_min() if exit_min is None else exit_min)
    if entry <= exit_line:
        raise ValueError("ENTRY_COMPOSITE_MIN must be greater than EXIT_COMPOSITE_MIN")
    if in_position:
        return "exit" if float(composite) < exit_line else "hold"
    return "enter" if float(composite) >= entry else "no_entry"


def rule1_theta_failures(
    *,
    delta: float,
    theta_per_share: float,
    premium: float | None,
    mode: str | None = None,
    max_pct: float | None = None,
) -> tuple[list[str], list[str]]:
    """Return (failures, notes). The delta/theta ratio is required only in abs_per_share mode."""
    selected = mode or theta_filter_mode()
    cap = float(theta_max_pct_per_day() if max_pct is None else max_pct)
    failures: list[str] = []
    notes: list[str] = []
    if abs(delta) < 0.55:
        failures.append(f"buy delta {abs(delta):.2f} is below 0.55")
    if selected == "abs_per_share":
        if abs(theta_per_share) >= 0.05:
            failures.append(f"daily theta {abs(theta_per_share):.2f} per share is not below 0.05")
        decay = abs(theta_per_share)
        ratio = abs(delta) / decay if decay > 0 else None
        if ratio is None or ratio <= 10:
            shown = f"{ratio:.2f}" if ratio is not None else "unavailable"
            failures.append(f"delta/theta {shown} is not above 10")
        return failures, notes
    notes.append("delta/theta ratio skipped in pct_of_premium mode")
    logger.info("delta/theta ratio skipped in pct_of_premium mode")
    if premium is None or premium <= 0:
        failures.append("premium is missing, so theta as a percent of premium cannot pass")
        return failures, notes
    pct = abs(theta_per_share) / premium
    if pct >= cap:
        failures.append(
            f"daily theta is {pct * 100:.2f}% of premium, not below {cap * 100:.2f}% per day"
        )
    return failures, notes


def iv_below_hv(contract_iv: Any, hv: Any) -> bool | None:
    """True when the selected contract's IV is below HV. None when either side is missing."""
    iv_f = _as_fraction(contract_iv)
    hv_f = _as_fraction(hv)
    if iv_f is None or hv_f is None:
        return None
    return iv_f < hv_f


def positive_loss(value: float | None) -> float | None:
    if value is None:
        return None
    return round(abs(float(value)), 2)


def refuse_if_checks_failed(*, checks_passed: bool | None, auto_execute: bool = False) -> None:
    """Server-side order guard. A client auto-execute flag cannot override a failed check."""
    if checks_passed is False:
        _ = auto_execute
        raise ValueError("Order refused: pre-trade checks did not all pass")


def _parse_day(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "unconfirmed"}:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def earnings_before_expiry(
    next_date: Any,
    latest_expiry: Any,
    *,
    today: date | None = None,
    confirmed: bool = True,
) -> tuple[bool, str | None]:
    """Confirmed earnings between today and the latest leg expiry, or an unconfirmed note."""
    if not confirmed or next_date in (None, ""):
        return False, "Earnings date is unconfirmed."
    earn = _parse_day(next_date)
    expiry = _parse_day(latest_expiry)
    if earn is None:
        return False, "Earnings date is unconfirmed."
    if expiry is None:
        return False, None
    start = today or datetime.now(timezone.utc).date()
    if start <= earn <= expiry:
        label = earn.strftime("%b %-d, %Y") if hasattr(earn, "strftime") else str(earn)
        # %-d is not portable on Windows; this desk runs on darwin. Fall back if needed.
        try:
            label = earn.strftime("%b %-d, %Y")
        except ValueError:
            label = earn.strftime("%b %d, %Y").replace(" 0", " ")
        return True, f"Earnings on {label} before expiry — post-event IV crush risk"
    return False, None


def quote_is_stale(quote_as_of: Any, *, now: datetime | None = None) -> bool:
    if not quote_as_of:
        return False
    text = str(quote_as_of).strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    age = (clock - parsed).total_seconds()
    return age > QUOTE_FRESHNESS_SECONDS


def mids_are_exact_double(mids: list[float]) -> bool:
    """True when one quoted mid is exactly twice another (the 2:1 suspect-quote fingerprint)."""
    clean = [m for m in mids if m > 0]
    for i, left in enumerate(clean):
        for right in clean[i + 1 :]:
            ratio = left / right if left >= right else right / left
            if abs(ratio - 2.0) <= 0.005:
                return True
    return False
