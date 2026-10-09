"""Shared auto-execute decision for the strategy slide, Risk Review, and every order path.

Eligibility is composite >= the saved minimum AND executable AND pre-trade validation.
The frozen ``contracts.canAutoExecute`` stub is not called. This function has the same
signature and return shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.analysis.gate_config import QUOTE_FRESHNESS_SECONDS, quote_is_stale
from app.analysis.options_rules import classify_quote_freshness

# The spec says a non-executable candidate must not outrank an executable one
# with a close score. It does not define "close". Five points stays inside the
# ordinary matrix bonuses (1–6) and is recorded as an open question.
CLOSE_SCORE_GAP = 5.0

# Options rules §5.5. Do not loosen. Equal to the cap is not wider.
DEFAULT_SPREAD_MAX = 0.10
EPS = 1e-9


@dataclass
class AutoExecuteDecision:
    eligible: bool
    reasons: list[str]


def can_auto_execute(scan: Any, user_settings: Any) -> AutoExecuteDecision:
    """Return whether Acknowledge may submit this scan.

    ``scan`` and ``user_settings`` may be mappings or objects. Missing executable
    or validation flags are not treated as a pass.
    """
    composite = _number(_pick(scan, "composite_score", "composite", "score"))
    minimum = _number(
        _pick(user_settings, "auto_execution_threshold", "autoExecMinScore", "threshold")
    )
    if minimum is None:
        minimum = 85.0
    executable = _flag(_pick(scan, "executable"))
    validation_passed = _flag(_pick(scan, "validation_passed", "checks_passed"))
    auto_enabled = _pick(user_settings, "auto_execution_enabled", "autoExecEnabled")
    reasons: list[str] = []
    if auto_enabled is False:
        reasons.append("Auto-execution is off.")
    if executable is not True:
        detail = _text(_pick(scan, "executability_reason", "block_reason"))
        reasons.append(detail or "Not executable.")
    if validation_passed is not True:
        detail = _text(_pick(scan, "validation_reason"))
        reasons.append(detail or "Pre-trade validation did not pass.")
    if composite is None:
        reasons.append("Composite score is missing.")
    elif composite < minimum:
        reasons.append("Composite is below your minimum.")
    eligible = (
        auto_enabled is not False
        and executable is True
        and validation_passed is True
        and composite is not None
        and composite >= minimum
    )
    if eligible:
        return AutoExecuteDecision(eligible=True, reasons=[])
    return AutoExecuteDecision(eligible=False, reasons=_dedupe(reasons))


def eligibility_sentence(
    composite: float,
    minimum: float,
    decision: AutoExecuteDecision,
) -> str:
    """Plain line both screens show. One decimal, no second score formatter."""
    head = f"Composite {_one_decimal(composite)}. Your minimum {_one_decimal(minimum)}."
    if decision.eligible:
        return f"{head} Auto-execute eligible."
    raw = decision.reasons[0] if decision.reasons else "pre-trade checks did not pass"
    detail = _short_block(raw)
    if not detail.endswith("."):
        detail = f"{detail}."
    return f"{head} Not auto-executable: {detail}"


def order_candidates_by_executability(
    ranked: list[Any],
    executable_by_name: dict[str, bool] | None,
    *,
    close_gap: float = CLOSE_SCORE_GAP,
) -> list[Any]:
    """Keep score order unless a non-executable name sits within ``close_gap`` of an executable one.

    When ``executable_by_name`` is missing, the list is returned unchanged so a
    market-wide quote problem does not reshuffle candidates that all fail together.
    """
    if not executable_by_name or not ranked:
        return list(ranked)
    ordered = list(ranked)
    changed = True
    while changed:
        changed = False
        for index in range(len(ordered) - 1):
            left = ordered[index]
            right = ordered[index + 1]
            left_name = str(getattr(left, "name", "") or "")
            right_name = str(getattr(right, "name", "") or "")
            if executable_by_name.get(left_name, True):
                continue
            if not executable_by_name.get(right_name, False):
                continue
            left_score = float(getattr(left, "score", 0) or 0)
            right_score = float(getattr(right, "score", 0) or 0)
            if left_score - right_score > close_gap:
                continue
            ordered[index], ordered[index + 1] = right, left
            changed = True
    return ordered


def quote_age_phrase(quote_as_of: Any, *, now: datetime | None = None) -> str | None:
    parsed = _parse_time(quote_as_of)
    if parsed is None:
        return None
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    minutes = int(max((clock - parsed).total_seconds(), 0) // 60)
    if minutes < 1:
        return "quote under 1 min old"
    return f"quote {minutes} min old"


def quote_problem(quote: Any, *, now: datetime | None = None) -> str | None:
    """Stale, missing, or suspect.

    A price, bid, or ask with no timestamp is not fresh. Order paths re-check here.
    ``quote_is_stale`` still treats a missing timestamp as not an age failure; this
    function does not.
    """
    if quote is None:
        return "Quote not current."
    as_of = getattr(quote, "as_of", None)
    if as_of is None and isinstance(quote, dict):
        as_of = quote.get("as_of") or quote.get("quote_as_of")
    bid = _number(_attr(quote, "bid"))
    ask = _number(_attr(quote, "ask"))
    price = _number(_attr(quote, "price"))
    if bid is not None and ask is not None and bid > ask:
        return "Quote not current. Bid is above the ask."
    has_price = price is not None or bid is not None or ask is not None
    if has_price and _parse_time(as_of) is None:
        return "Quote not current. Quoted unknown time."
    if _quote_failed_stale(quote, as_of, now=now):
        age = quote_age_phrase(as_of, now=now)
        stamp = _text(as_of) or "unknown time"
        if age:
            return f"Quote not current. {age}. Quoted {stamp}."
        return f"Quote not current. Quoted {stamp}."
    if price is None and bid is None and ask is None:
        return "Quote not current. No bid, ask, or price."
    _ = QUOTE_FRESHNESS_SECONDS
    return None


def spread_vs_mid(quote: Any) -> float | None:
    bid = _number(_attr(quote, "bid"))
    ask = _number(_attr(quote, "ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid


def slippage_dollars(quote: Any, *, qty: float = 1, multiplier: int = 100) -> float | None:
    """Half the bid/ask width times contract multiplier. None when a side is missing."""
    bid = _number(_attr(quote, "bid"))
    ask = _number(_attr(quote, "ask"))
    if bid is None or ask is None or ask < bid:
        return None
    return round((ask - bid) / 2.0 * max(qty, 0) * multiplier, 2)


def spread_confirmation_text(
    *,
    spread_pct: float,
    threshold: float,
    slippage: float | None,
) -> str:
    slip = f"${slippage:.2f}" if slippage is not None else "unavailable"
    return (
        f"Bid/ask spread is {spread_pct * 100:.1f}% of mid, wider than the "
        f"{threshold * 100:.0f}% cap. Estimated slippage {slip}. "
        "The price you would pay is not reliable."
    )


def marketable_limit(side: str, quote: Any) -> tuple[float, str] | None:
    """Buy at the ask, sell at the bid. None when that side is missing."""
    bid = _number(_attr(quote, "bid"))
    ask = _number(_attr(quote, "ask"))
    action = side.lower()
    if action == "buy" and ask is not None and ask > 0:
        return round(ask, 2), "ask"
    if action == "sell" and bid is not None and bid > 0:
        return round(bid, 2), "bid"
    return None


def is_spread_note(note: str) -> bool:
    text = note.lower()
    return "bid/ask spread" in text or "spread is" in text and "% of mid" in text


def split_block_notes(notes: list[str]) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    spread: list[str] = []
    for note in notes:
        if not isinstance(note, str) or not note.strip():
            continue
        if is_spread_note(note):
            spread.append(note.strip())
        else:
            hard.append(note.strip())
    return hard, spread


def submission_block_reason(
    strategy_layer: dict[str, Any] | None,
    *,
    spread_confirmed: bool,
) -> str | None:
    """Why this scan cannot be submitted. None when the order may proceed.

    A wide spread alone can proceed only after the caller confirms it.
    Stale, missing, suspect, or any other failed check cannot.
    """
    if not strategy_layer:
        return None
    if strategy_layer.get("placeable") is False:
        reason = _text(strategy_layer.get("block_reason")) or "Pre-trade validation did not pass."
        _log_block(reason)
        return reason
    spread = [note for note in (strategy_layer.get("spread_block_reasons") or []) if isinstance(note, str) and note.strip()]
    if spread and not spread_confirmed:
        _log_block(spread[0])
        return spread[0]
    return None


def order_symbols(*groups: Any) -> list[str]:
    """Unique symbols from leg rows or plain strings, in first-seen order."""
    found: list[str] = []
    for group in groups:
        rows: list[Any]
        if isinstance(group, str):
            rows = [group]
        elif isinstance(group, dict):
            rows = [group]
        else:
            rows = list(group or [])
        for row in rows:
            if isinstance(row, str):
                symbol = row.strip().upper()
            elif isinstance(row, dict):
                symbol = str(row.get("symbol") or "").strip().upper()
            else:
                symbol = ""
            if symbol and symbol not in found:
                found.append(symbol)
    return found


async def enforce_submission_quotes(
    adapter: Any,
    symbols: list[str],
    *,
    path: str,
    spread_confirmed: bool = False,
    contracts: float = 1,
    multiplier: int = 100,
    spread_max: float = DEFAULT_SPREAD_MAX,
    user_override: bool = False,
) -> None:
    """Re-check freshness and spread before Alpaca paper or demo fill. Log every block.

    ``user_override`` still refetches a stale quote once, then continues. Auto-execution
    must not set this flag. Only an explicit user click may.
    """
    for symbol in symbols:
        if not symbol:
            continue
        _quote, problem = await load_submission_quote(adapter, symbol)
        if problem and not user_override:
            logger.warning("order blocked path={} symbol={} reason={}", path, symbol, problem)
            raise ValueError(problem)
        if problem and user_override:
            logger.info("user override quote path={} symbol={} reason={}", path, symbol, problem)
        frac = spread_vs_mid(_quote)
        if frac is not None and frac > spread_max + EPS and not spread_confirmed and not user_override:
            slip = slippage_dollars(_quote, qty=contracts, multiplier=multiplier)
            reason = spread_confirmation_text(spread_pct=frac, threshold=spread_max, slippage=slip)
            logger.warning("order blocked path={} symbol={} reason={}", path, symbol, reason)
            raise ValueError(reason)


async def load_submission_quote(adapter: Any, symbol: str) -> tuple[Any, str | None]:
    """Fetch the quote. If it is stale, missing, or suspect, refetch once."""
    quote = await _read_quote(adapter, symbol)
    problem = quote_problem(quote)
    if problem is None:
        return quote, None
    logger.warning("order quote refetch symbol={} reason={}", symbol, problem)
    retried = await _read_quote(adapter, symbol)
    checked = retried if retried is not None else quote
    again = quote_problem(checked)
    if again:
        _log_block(again, symbol=symbol)
        return retried if retried is not None else quote, again
    return retried, None


def _log_block(reason: str, *, symbol: str | None = None) -> None:
    if symbol:
        logger.warning("order blocked symbol={} reason={}", symbol, reason)
    else:
        logger.warning("order blocked reason={}", reason)


async def _read_quote(adapter: Any, symbol: str) -> Any:
    try:
        return await adapter.quote(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("order quote failed symbol={} reason={}", symbol, exc)
        return None


def _pick(source: Any, *names: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        for name in names:
            if name in source and source[name] is not None:
                return source[name]
        return None
    for name in names:
        if hasattr(source, name):
            value = getattr(source, name)
            if value is not None:
                return value
    return None


def _attr(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip().rstrip(".")
    return None


def _short_block(reason: str) -> str:
    import re

    match = re.search(r"quote \d+ min old", reason.lower())
    if match:
        return match.group(0)
    lowered = reason.lower()
    if "quote not current" in lowered or "stale" in lowered or "suspect" in lowered:
        return "quote not current"
    if reason[:1].isupper():
        return reason[0].lower() + reason[1:]
    return reason


def _one_decimal(value: float) -> str:
    """One decimal. 59 → 59.0. 62.9 stays 62.9. Does not change the score."""
    return f"{float(value):.1f}"


def _quote_failed_stale(quote: Any, as_of: Any, *, now: datetime | None) -> bool:
    """Age past the cap during the session is stale. A last close is not.

    ``QUOTE_FRESHNESS_SECONDS`` is unchanged. Outside the regular session the
    classifier returns ``last_close`` and this is not a failure.
    """
    meta = None
    if isinstance(quote, dict):
        raw = quote.get("quote_meta") or quote.get("quoteMeta")
        if isinstance(raw, dict):
            meta = raw
    elif quote is not None:
        raw = getattr(quote, "quote_meta", None) or getattr(quote, "quoteMeta", None)
        if isinstance(raw, dict):
            meta = raw
    parsed_as_of = _parse_time(as_of)
    if parsed_as_of is None:
        return True
    if meta is not None and meta.get("staleReason") == "last_close":
        return False
    clock = now or datetime.now(timezone.utc)
    is_stale, reason = classify_quote_freshness(quoted_at=as_of, now=clock)
    if reason == "last_close":
        return False
    if meta is not None and meta.get("isStale") is True and reason != "last_close":
        return True
    if is_stale:
        return True
    # Same 300s cap when the clock is inside the session and meta is absent.
    return quote_is_stale(as_of, now=clock) and reason != "last_close"


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
