"""Reject explanation text whose numbers are not on the ledger.

The check extracts numbers, percentages, dates, and tickers. A token that does
not match a ledger value within display rounding rejects the text. The fallback
is the knowledge-base template with ledger values filled in, keeping only
sentences that themselves pass the check. Words such as high, low, rich, and
cheap must cite a ledger value and a ledger threshold in the same sentence.
This module does not compute prices, Greeks, or scores.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

from loguru import logger

from app.contracts import LedgerEntry
from app.services.evidence_ledger import get

_PERCENT = re.compile(
    r"(?<![\d.])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?:%|percent\b)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![\d.])([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?![\d%])")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_MDY = re.compile(rf"\b({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE)
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\s+(\d{{4}})\b", re.IGNORECASE)
_TICKER = re.compile(r"\b([A-Z]{1,5})\b")
_CLAIM = re.compile(r"\b(high|low|rich|cheap)\b", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.:]+)\}")

_MONTH_INDEX = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_STOP = frozenset(
    {
        "A",
        "I",
        "AM",
        "PM",
        "ET",
        "US",
        "OR",
        "TO",
        "IN",
        "ON",
        "AT",
        "BY",
        "OF",
        "IF",
        "IS",
        "IT",
        "AN",
        "AND",
        "THE",
        "FOR",
        "NOT",
        "VIA",
        "MID",
        "BID",
        "ASK",
        "IV",
        "HV",
        "DTE",
        "ATM",
        "OTM",
        "ITM",
        "RSI",
        "MACD",
        "EMA",
        "OCC",
        "OI",
        "ETF",
        "IR",
        "QA",
        "IVR",
        "ATR",
        "SMA",
        "USD",
        "NBBO",
        "OPRA",
        "PDF",
        "API",
        "EPS",
        "SEC",
        "PNL",
        "ROI",
        "YTD",
        "ATH",
        "GAAP",
        "RULE",
        "PUT",
        "CALL",
        "BUY",
        "SELL",
        "LONG",
        "SHORT",
        "NET",
        "MAX",
        "MIN",
        "HIGH",
        "LOW",
        "RICH",
        "CHEAP",
        "OK",
        "NO",
        "YES",
    }
)

_THRESHOLD_KEYS = frozenset({"threshold", "thresholds"})
_TICKER_KEYS = frozenset({"symbol", "ticker", "underlying"})

_log_lock = threading.Lock()
_rejection_log: dict[str, list[dict[str, Any]]] = {}


@dataclass(frozen=True)
class _Token:
    kind: str
    surface: str
    start: int
    end: int
    normalized: str


@dataclass(frozen=True)
class NarrativeResult:
    accepted: bool
    text: str
    used_fallback: bool
    unmatched: tuple[str, ...]
    qualitative: tuple[str, ...]


def reset_rejections() -> None:
    with _log_lock:
        _rejection_log.clear()


def rejections(scan_id: str) -> list[dict[str, Any]]:
    with _log_lock:
        return list(_rejection_log.get(scan_id, []))


def check_narrative(text: str, *, scan_id: str, strategy_id: str | None = None) -> NarrativeResult:
    """Accept text only when every extracted token is on the scan ledger."""
    entries = get(scan_id)
    values, thresholds, dates, tickers = _collect(entries)
    unmatched, qualitative = _problems(text or "", values, thresholds, dates, tickers)
    if not unmatched and not qualitative:
        return NarrativeResult(True, text, False, (), ())
    _remember(scan_id, strategy_id, unmatched, qualitative)
    fallback = _fallback(strategy_id, entries, values, thresholds, dates, tickers)
    return NarrativeResult(False, fallback, True, unmatched, qualitative)


def _problems(
    text: str,
    values: list[float],
    thresholds: list[float],
    dates: set[str],
    tickers: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    grounded = values + thresholds
    unmatched: list[str] = []
    for token in _tokenize(text):
        if token.kind == "date":
            if token.normalized not in dates:
                unmatched.append(token.surface)
        elif token.kind == "ticker":
            if token.normalized not in tickers:
                unmatched.append(token.surface)
        elif token.kind == "percent":
            if not _number_matches(token.surface, grounded, percent=True):
                unmatched.append(token.surface)
        elif not _number_matches(token.surface, grounded, percent=False):
            unmatched.append(token.surface)
    qualitative = _claim_words(text, values, thresholds)
    return tuple(unmatched), tuple(qualitative)


def _claim_words(text: str, values: list[float], thresholds: list[float]) -> list[str]:
    found: list[str] = []
    for sentence in _sentences(text):
        words = [match.group(1).lower() for match in _CLAIM.finditer(sentence)]
        if not words:
            continue
        numbers = [token for token in _tokenize(sentence) if token.kind in {"number", "percent"}]
        has_value = any(_number_matches(token.surface, values, percent=token.kind == "percent") for token in numbers)
        has_threshold = any(
            _number_matches(token.surface, thresholds, percent=token.kind == "percent") for token in numbers
        )
        if has_value and has_threshold:
            continue
        found.extend(words)
    return found


def _remember(scan_id: str, strategy_id: str | None, unmatched: tuple[str, ...], qualitative: tuple[str, ...]) -> None:
    row = {"unmatched": unmatched, "qualitative": qualitative, "strategy_id": strategy_id}
    with _log_lock:
        _rejection_log.setdefault(scan_id, []).append(row)
    logger.warning(
        f"narrative rejected scan_id={scan_id} strategy={strategy_id or ''} unmatched={list(unmatched)} qualitative={list(qualitative)}"
    )


def _fallback(
    strategy_id: str | None,
    entries: list[LedgerEntry],
    values: list[float],
    thresholds: list[float],
    dates: set[str],
    tickers: set[str],
) -> str:
    pieces: list[str] = []
    if strategy_id:
        from app.strategies.knowledge_base import entry_for

        kb = entry_for(strategy_id)
        if kb is not None:
            template = "\n".join((kb.title, kb.summary, kb.why_it_fits, kb.how_to_use, kb.key_risks))
            pieces.extend(_sentences(_fill_placeholders(template, entries)))
    pieces.extend(_fact_lines(entries))
    kept = [
        sentence
        for sentence in pieces
        if sentence and not _problems(sentence, values, thresholds, dates, tickers)[0]
        and not _problems(sentence, values, thresholds, dates, tickers)[1]
    ]
    text = " ".join(kept).strip()
    if not text:
        return "The generated explanation was rejected because a figure was not on the ledger."
    return text


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _collect(entries: list[LedgerEntry]) -> tuple[list[float], list[float], set[str], set[str]]:
    values: list[float] = []
    thresholds: list[float] = []
    dates: set[str] = set()
    tickers: set[str] = set()
    for entry in entries:
        _walk_values(entry.value, values, dates, tickers)
        _walk_values(entry.inputs, values, dates, tickers)
        _walk_thresholds(entry.value, thresholds)
        _walk_thresholds(entry.inputs, thresholds)
        _harvest_dates(entry.timestamp, dates)
        _add_ticker(entry.key, tickers)
    return values, thresholds, dates, tickers


def _walk_values(obj: Any, numbers: list[float], dates: set[str], tickers: set[str]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _THRESHOLD_KEYS:
                continue
            if key in _TICKER_KEYS and isinstance(val, str):
                _add_ticker(val, tickers)
            _walk_values(val, numbers, dates, tickers)
        return
    if isinstance(obj, (list, tuple)):
        for val in obj:
            _walk_values(val, numbers, dates, tickers)
        return
    if isinstance(obj, str):
        _harvest_dates(obj, dates)
        _add_ticker(obj, tickers)
        return
    _add_number(numbers, obj)


def _walk_thresholds(obj: Any, thresholds: list[float]) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key in _THRESHOLD_KEYS:
                _add_threshold_value(val, thresholds)
            else:
                _walk_thresholds(val, thresholds)
        return
    if isinstance(obj, (list, tuple)):
        for val in obj:
            _walk_thresholds(val, thresholds)


def _add_threshold_value(obj: Any, thresholds: list[float]) -> None:
    if isinstance(obj, dict):
        for val in obj.values():
            _add_threshold_value(val, thresholds)
        return
    if isinstance(obj, (list, tuple)):
        for val in obj:
            _add_threshold_value(val, thresholds)
        return
    _add_number(thresholds, obj)


def _add_number(bucket: list[float], value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    number = float(value)
    if math.isfinite(number):
        bucket.append(number)


def _add_ticker(text: str, tickers: set[str]) -> None:
    token = text.strip().upper()
    if re.fullmatch(r"[A-Z]{1,5}", token) and token not in _STOP:
        tickers.add(token)


def _harvest_dates(text: str, dates: set[str]) -> None:
    for token in _date_tokens(text):
        dates.add(token.normalized)


def _tokenize(text: str) -> list[_Token]:
    occupied: list[tuple[int, int]] = []
    tokens: list[_Token] = []
    for token in _date_tokens(text):
        tokens.append(token)
        occupied.append((token.start, token.end))
    for match in _PERCENT.finditer(text):
        span = match.span()
        if _overlaps(span, occupied):
            continue
        tokens.append(_Token("percent", match.group(1), span[0], span[1], match.group(1)))
        occupied.append(span)
    for match in _NUMBER.finditer(text):
        span = match.span()
        if _overlaps(span, occupied):
            continue
        tokens.append(_Token("number", match.group(1), span[0], span[1], match.group(1)))
        occupied.append(span)
    for match in _TICKER.finditer(text):
        span = match.span()
        if _overlaps(span, occupied):
            continue
        surface = match.group(1)
        if surface in _STOP:
            continue
        tokens.append(_Token("ticker", surface, span[0], span[1], surface))
    tokens.sort(key=lambda token: token.start)
    return tokens


def _date_tokens(text: str) -> list[_Token]:
    found: list[_Token] = []
    occupied: list[tuple[int, int]] = []
    patterns = (
        (_ISO, lambda match: _iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))),
        (_SLASH, lambda match: _iso_date(int(match.group(3)), int(match.group(1)), int(match.group(2)))),
        (
            _MDY,
            lambda match: _iso_date(int(match.group(3)), _MONTH_INDEX[match.group(1).lower()], int(match.group(2))),
        ),
        (
            _DMY,
            lambda match: _iso_date(int(match.group(3)), _MONTH_INDEX[match.group(2).lower()], int(match.group(1))),
        ),
    )
    for pattern, normalize in patterns:
        for match in pattern.finditer(text):
            span = match.span()
            if _overlaps(span, occupied):
                continue
            normalized = normalize(match)
            if normalized is None:
                continue
            found.append(_Token("date", match.group(0), span[0], span[1], normalized))
            occupied.append(span)
    return found


def _iso_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(not (end <= left or start >= right) for left, right in occupied)


def _number_matches(surface: str, candidates: list[float], *, percent: bool) -> bool:
    """True when the displayed token is the stored figure at that many decimal places.

    Whole numbers match only the stored whole number. A one-decimal token matches
    half-up rounding, so 30.31 can appear as 30.3 and 30.35 as 30.4.
    """
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    cleaned = surface.replace(",", "").strip()
    try:
        token = Decimal(cleaned)
    except InvalidOperation:
        return False
    places = _decimal_places(surface)
    quantum = Decimal("1") if places == 0 else Decimal(10) ** -places
    for raw in candidates:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
            continue
        try:
            stored = Decimal(str(raw))
        except InvalidOperation:
            continue
        pool = [stored]
        if percent and abs(stored) <= Decimal("1.5") and stored != stored.to_integral_value():
            pool.append(stored * Decimal("100"))
        for candidate in pool:
            if places == 0:
                if candidate == token:
                    return True
                continue
            if candidate.quantize(quantum, rounding=ROUND_HALF_UP) == token:
                return True
    return False


def _decimal_places(surface: str) -> int:
    plain = surface.replace(",", "").lstrip("+-")
    if "." not in plain:
        return 0
    return len(plain.split(".", 1)[1])


def _fill_placeholders(template: str, entries: list[LedgerEntry]) -> str:
    by_key: dict[str, Any] = {}
    for entry in entries:
        by_key[entry.key] = entry.value
        by_key.setdefault(entry.key.split(":")[-1], entry.value)

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in by_key:
            return match.group(0)
        return _plain(by_key[key])

    return _PLACEHOLDER.sub(repl, template)


def _fact_lines(entries: list[LedgerEntry]) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        origin = f"from {entry.source} via {entry.fn}"
        if entry.kind == "gate" and isinstance(entry.value, dict) and "measured" in entry.value:
            state = "pass" if entry.value.get("passed") else "fail"
            lines.append(
                f"{entry.key} measured {_plain(entry.value.get('measured'))} versus threshold "
                f"{_plain(entry.value.get('threshold'))}, {state}, {origin}."
            )
        elif isinstance(entry.value, (int, float, str)):
            lines.append(f"{entry.key} is {_plain(entry.value)} {origin}.")
    return lines


def _plain(value: Any) -> str:
    if isinstance(value, float):
        return format(value, ".10g")
    if isinstance(value, (str, int)) or value is None:
        return str(value)
    return json.dumps(value, default=str, sort_keys=True)
