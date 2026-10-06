"""Reject explanation text whose numbers are not on the ledger.

The check extracts numbers, percentages, dates, and tickers. A token that does
not match a ledger value within display rounding rejects the text. The fallback
is a short knowledge-base sentence for the selected strategy with that
strategy's values filled in, plus one headline figure sentence, keeping only
sentences that themselves pass the check. Words such as high, low, rich, and
cheap must cite a ledger value and a ledger threshold in the same sentence.
The evidence ledger itself is never prose: rows stay on ``GET /api/ledger`` and
in the rejection log, never on the card. This module does not compute prices,
Greeks, or scores.
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
        "APEX",
    }
)

_THRESHOLD_KEYS = frozenset({"threshold", "thresholds"})
_TICKER_KEYS = frozenset({"symbol", "ticker", "underlying"})

# why-it-fits, then the short risk line. The summary repeats the name and the model grid.
_FALLBACK_FIELDS = ("why_it_fits", "key_risks")
_FALLBACK_SENTENCE_CAP = 1
_GRID_PROSE = ("model grid", "payoff grid", "payoff_grid")

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
    unmatched, qualitative = _problems(
        text or "",
        values,
        thresholds,
        dates,
        tickers,
        _identifier_strings(entries),
    )
    if not unmatched and not qualitative:
        return NarrativeResult(True, text, False, (), ())
    _remember(scan_id, strategy_id, unmatched, qualitative)
    fallback = _fallback(strategy_id, entries, values, thresholds, dates, tickers)
    return NarrativeResult(False, fallback, True, unmatched, qualitative)


def _scenario_label(text: str, token: _Token) -> bool:
    """Scenario B and Scenario C are labels, not the tickers B and C."""
    if len(token.normalized) != 1:
        return False
    prior = text[max(0, token.start - 12) : token.start].lower()
    return prior.endswith("scenario ") or prior.endswith("strike ")


def _inside_identifier(surface: str, identifiers: list[str]) -> bool:
    """Digits that are part of a recorded contract symbol are not a separate figure."""
    if len(surface) < 4:
        return False
    return any(surface in ident for ident in identifiers)


def _identifier_strings(entries: list[LedgerEntry]) -> list[str]:
    found: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for val in obj.values():
                walk(val)
        elif isinstance(obj, (list, tuple)):
            for val in obj:
                walk(val)
        elif isinstance(obj, str) and len(obj) >= 8 and any(ch.isdigit() for ch in obj):
            found.append(obj)

    for entry in entries:
        walk(entry.value)
        walk(entry.inputs)
    return found


def _problems(
    text: str,
    values: list[float],
    thresholds: list[float],
    dates: set[str],
    tickers: set[str],
    identifiers: list[str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    grounded = values + thresholds
    identifiers = identifiers or []
    unmatched: list[str] = []
    for token in _tokenize(text):
        if token.kind == "date":
            if token.normalized not in dates:
                unmatched.append(token.surface)
        elif token.kind == "ticker":
            if token.normalized not in tickers and not _scenario_label(text, token):
                unmatched.append(token.surface)
        elif token.kind == "percent":
            if not _number_matches(token.surface, grounded, percent=True) and not _inside_identifier(
                token.surface, identifiers
            ):
                unmatched.append(token.surface)
        elif not _number_matches(token.surface, grounded, percent=False) and not _inside_identifier(
            token.surface, identifiers
        ):
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
    """Short knowledge-base copy for the selected strategy, filled with its values.

    The evidence ledger is not card copy. Rows stay on ``GET /api/ledger`` and in
    the rejection log. This never joins ledger rows into the text, so gate names,
    producing functions, unselected-strategy scores, and payoff-grid points cannot
    reach the card.
    """

    def grounded(sentence: str) -> bool:
        unmatched, qualitative = _problems(sentence, values, thresholds, dates, tickers)
        return not unmatched and not qualitative

    kept: list[str] = []
    for sentence in _catalog_sentences(strategy_id, entries):
        if len(kept) >= _FALLBACK_SENTENCE_CAP:
            break
        if sentence not in kept and grounded(sentence):
            kept.append(sentence)
    figures = _figure_sentence(strategy_id, entries)
    if figures and figures not in kept and grounded(figures):
        kept.append(figures)
    conflict = _conflict_sentence(strategy_id, entries)
    if conflict and conflict not in kept and grounded(conflict):
        kept.append(conflict)
    text = " ".join(kept).strip()
    if not text:
        return "The generated explanation was rejected because a figure was not on the ledger."
    return text


def _catalog_sentences(strategy_id: str | None, entries: list[LedgerEntry]) -> list[str]:
    """Knowledge-base sentences for the selected strategy only, placeholders filled.

    A sentence that is only the strategy's own name is dropped so the card names
    the structure once.
    """
    if not strategy_id:
        return []
    from app.strategies.knowledge_base import entry_for

    kb = entry_for(strategy_id)
    if kb is None:
        return []
    title = str(getattr(kb, "title", "") or "").strip().rstrip(".").lower()
    out: list[str] = []
    for field in _FALLBACK_FIELDS:
        raw = str(getattr(kb, field, "") or "")
        if not raw.strip():
            continue
        for sentence in _sentences(_fill_placeholders(raw, entries)):
            if title and sentence.strip().rstrip(".").lower() == title:
                continue
            if any(phrase in sentence.lower() for phrase in _GRID_PROSE):
                continue
            out.append(sentence)
    return out


def _named_strategy(entry: LedgerEntry) -> str | None:
    for key in ("strategy", "strategy_id"):
        named = entry.inputs.get(key)
        if isinstance(named, str) and named.strip():
            return named.strip()
    return None


def _latest_card_number(entries: list[LedgerEntry], strategy_id: str | None, key: str) -> float | None:
    """Last headline figure for the selected strategy.

    An earlier row for another pass, or an untagged row, does not replace the
    value recorded for the strategy the card is explaining.
    """
    tagged: float | None = None
    untagged: float | None = None
    for entry in entries:
        if entry.kind != "value" or entry.key != key:
            continue
        number = _card_number(entry.value)
        if number is None:
            continue
        named = _named_strategy(entry)
        if named:
            if strategy_id and named == strategy_id:
                tagged = number
            continue
        untagged = number
    if tagged is not None:
        return tagged
    return untagged


def _figure_sentence(strategy_id: str | None, entries: list[LedgerEntry]) -> str | None:
    """One plain sentence with the selected strategy's headline figures."""
    composite = _latest_card_number(entries, strategy_id, "composite")
    volatility: list[str] = []
    for label, key in (("IV", "iv"), ("HV", "hv")):
        number = _latest_card_number(entries, strategy_id, key)
        if number is not None:
            volatility.append(f"{label} {_one_decimal(_as_percent_points(number))} percent")
    vol_text = " and ".join(volatility)
    if composite is not None and vol_text:
        return f"The composite is {_one_decimal(composite)} with {vol_text}."
    if composite is not None:
        return f"The composite is {_one_decimal(composite)}."
    if vol_text:
        return f"Measured {vol_text}."
    return None


def _conflict_sentence(strategy_id: str | None, entries: list[LedgerEntry]) -> str | None:
    """The recorded sentiment-conflict sentence, only when this strategy has one."""
    text: str | None = None
    for entry in entries:
        if entry.key != "sentiment_conflict" or not isinstance(entry.value, str) or not entry.value.strip():
            continue
        named = _named_strategy(entry)
        if named and strategy_id and named != strategy_id:
            continue
        text = entry.value.strip()
    if not text:
        return None
    return _sentences(text)[0]


def _card_number(value: Any) -> float | None:
    if isinstance(value, dict):
        return _card_number(value.get("measured"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _as_percent_points(value: float) -> float:
    """A stored fraction such as 0.3031 displays as 30.3 percent."""
    if 0 < abs(value) <= 1.5 and float(value) != float(int(value)):
        return value * 100.0
    return value


def _one_decimal(value: float) -> str:
    from decimal import Decimal, ROUND_HALF_UP

    quantized = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if quantized == quantized.to_integral_value():
        return str(quantized.to_integral_value())
    return str(quantized)


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


def _plain(value: Any) -> str:
    if isinstance(value, float):
        return format(value, ".10g")
    if isinstance(value, (str, int)) or value is None:
        return str(value)
    return json.dumps(value, default=str, sort_keys=True)
