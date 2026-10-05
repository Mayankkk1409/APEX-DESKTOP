"""Evaluation and evidence ledger for one scan.

Every gate, candidate, score component, rank, and card value is a frozen
``LedgerEntry``. Quote flags already on the payload (``inverted_put_skew``,
``crossed_market``, ``iv_outside_chain_range``) are copied. This module does
not recompute them and does not score, price, or choose a trade.
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from app.contracts import LedgerEntry

FLAG_CODES = frozenset({"inverted_put_skew", "crossed_market", "iv_outside_chain_range"})
_KINDS = frozenset({"value", "gate", "candidate", "score"})

_lock = threading.Lock()
_store: dict[str, list[LedgerEntry]] = {}


def reset_ledger(scan_id: str | None = None) -> None:
    """Drop one scan, or the whole store."""
    with _lock:
        if scan_id is None:
            _store.clear()
        else:
            _store.pop(scan_id, None)


def record(entry: LedgerEntry) -> None:
    """Append one entry. Refuses a row that has no provenance."""
    _require_provenance(entry)
    stored = copy.deepcopy(entry)
    with _lock:
        _store.setdefault(stored.scanId, []).append(stored)


def get(scan_id: str) -> list[LedgerEntry]:
    with _lock:
        return list(_store.get(scan_id, []))


def record_gate(
    scan_id: str,
    strategy_id: str,
    gate: str,
    measured: Any,
    threshold: Any,
    passed: bool,
    *,
    source: str,
    feed: str | None,
    timestamp: str,
    fn: str,
    inputs: dict[str, Any] | None = None,
) -> LedgerEntry:
    """Pass or fail for one gate, with the measured value and the threshold."""
    extra = dict(inputs or {})
    extra.update(
        {
            "strategy_id": strategy_id,
            "gate": gate,
            "measured": measured,
            "threshold": threshold,
            "passed": bool(passed),
        }
    )
    entry = LedgerEntry(
        scanId=scan_id,
        kind="gate",
        key=f"{strategy_id}:{gate}",
        value={"passed": bool(passed), "measured": measured, "threshold": threshold},
        inputs=extra,
        source=source,
        feed=feed,
        timestamp=timestamp,
        fn=fn,
    )
    record(entry)
    return entry


def record_candidate(
    scan_id: str,
    strategy_id: str,
    name: str,
    candidate: Any,
    *,
    source: str,
    feed: str | None,
    timestamp: str,
    fn: str,
    inputs: dict[str, Any] | None = None,
) -> LedgerEntry:
    extra = dict(inputs or {})
    extra["strategy_id"] = strategy_id
    extra["candidate"] = name
    entry = LedgerEntry(
        scanId=scan_id,
        kind="candidate",
        key=f"{strategy_id}:{name}",
        value=candidate,
        inputs=extra,
        source=source,
        feed=feed,
        timestamp=timestamp,
        fn=fn,
    )
    record(entry)
    return entry


def record_score(
    scan_id: str,
    strategy_id: str,
    component: str,
    score: Any,
    *,
    source: str,
    feed: str | None,
    timestamp: str,
    fn: str,
    inputs: dict[str, Any] | None = None,
) -> LedgerEntry:
    extra = dict(inputs or {})
    extra["strategy_id"] = strategy_id
    extra["component"] = component
    entry = LedgerEntry(
        scanId=scan_id,
        kind="score",
        key=f"{strategy_id}:{component}",
        value=score,
        inputs=extra,
        source=source,
        feed=feed,
        timestamp=timestamp,
        fn=fn,
    )
    record(entry)
    return entry


def record_rank(
    scan_id: str,
    strategy_id: str,
    rank: int,
    *,
    source: str,
    feed: str | None,
    timestamp: str,
    fn: str,
    inputs: dict[str, Any] | None = None,
) -> LedgerEntry:
    """Final rank. Stored as a score row because the frozen kinds have no rank type."""
    return record_score(
        scan_id,
        strategy_id,
        "rank",
        rank,
        source=source,
        feed=feed,
        timestamp=timestamp,
        fn=fn,
        inputs=inputs,
    )


def record_card_value(
    scan_id: str,
    key: str,
    value: Any,
    *,
    inputs: dict[str, Any],
    source: str,
    feed: str | None,
    timestamp: str,
    fn: str,
    strategy_id: str | None = None,
) -> LedgerEntry:
    """One card value. Inputs, source, feed, timestamp, and function are required."""
    if not inputs:
        raise ValueError("ledger entry inputs are required")
    payload = dict(inputs)
    if strategy_id is not None:
        payload["strategy_id"] = strategy_id
    entry = LedgerEntry(
        scanId=scan_id,
        kind="value",
        key=key,
        value=value,
        inputs=payload,
        source=source,
        feed=feed,
        timestamp=timestamp,
        fn=fn,
    )
    record(entry)
    return entry


def record_chain_flags(scan_id: str, payload: Any) -> list[LedgerEntry]:
    """Copy flags that are already on the quote payload.

    Does not inspect bids, asks, or implied vols, and does not call
    ``chain_quote_flags``. A payload with no flags records nothing.
    """
    recorded: list[LedgerEntry] = []
    for flag in _extract_flags(payload):
        code = str(flag.get("code"))
        measured = flag.get("value")
        threshold = flag.get("threshold")
        timestamp = flag.get("timestamp")
        stamp = timestamp if isinstance(timestamp, str) and timestamp.strip() else "unknown"
        source = flag.get("source")
        source_text = source.strip() if isinstance(source, str) and source.strip() else "unavailable"
        feed = flag.get("feed")
        feed_text = feed if isinstance(feed, str) or feed is None else str(feed)
        producer = flag.get("fn")
        fn = producer.strip() if isinstance(producer, str) and producer.strip() else "chain_quote_flags"
        entry = LedgerEntry(
            scanId=scan_id,
            kind="gate",
            key=code,
            value={"passed": False, "measured": measured, "threshold": threshold, "code": code},
            inputs={
                "strategy_id": "quote",
                "gate": code,
                "measured": measured,
                "threshold": threshold,
                "passed": False,
                "symbol": flag.get("symbol"),
                "strike": flag.get("strike"),
                "side": flag.get("side"),
                "detail": flag.get("detail"),
            },
            source=source_text,
            feed=feed_text,
            timestamp=stamp,
            fn=fn,
        )
        record(entry)
        recorded.append(entry)
    return recorded


def evaluation(scan_id: str) -> dict[str, Any]:
    """Gate-by-gate debug view for one scan."""
    strategies: dict[str, dict[str, Any]] = {}
    flags: list[dict[str, Any]] = []
    for entry in get(scan_id):
        strategy_id = _strategy_id(entry)
        row = strategies.setdefault(
            strategy_id,
            {"gates": [], "candidates": [], "scores": [], "rank": None},
        )
        if entry.kind == "gate":
            passed, measured, threshold = _gate_fields(entry)
            gate_row = {
                "key": entry.key,
                "gate": entry.inputs.get("gate") or entry.key.split(":")[-1],
                "passed": passed,
                "measured": measured,
                "threshold": threshold,
                "source": entry.source,
                "feed": entry.feed,
                "timestamp": entry.timestamp,
                "fn": entry.fn,
                "inputs": entry.inputs,
            }
            row["gates"].append(gate_row)
            if entry.key in FLAG_CODES or entry.inputs.get("gate") in FLAG_CODES:
                flags.append(gate_row)
        elif entry.kind == "candidate":
            row["candidates"].append(
                {
                    "key": entry.key,
                    "value": entry.value,
                    "source": entry.source,
                    "feed": entry.feed,
                    "timestamp": entry.timestamp,
                    "fn": entry.fn,
                }
            )
        elif entry.kind == "score":
            component = str(entry.inputs.get("component") or entry.key.split(":")[-1])
            if component == "rank":
                row["rank"] = entry.value
            else:
                row["scores"].append(
                    {
                        "component": component,
                        "value": entry.value,
                        "source": entry.source,
                        "feed": entry.feed,
                        "timestamp": entry.timestamp,
                        "fn": entry.fn,
                    }
                )
    return {"strategies": strategies, "flags": flags}


def _strategy_id(entry: LedgerEntry) -> str:
    named = entry.inputs.get("strategy_id")
    if isinstance(named, str) and named.strip():
        return named
    if ":" in entry.key:
        return entry.key.split(":", 1)[0]
    return entry.key


def _gate_fields(entry: LedgerEntry) -> tuple[Any, Any, Any]:
    value = entry.value
    if isinstance(value, dict) and "measured" in value:
        return value.get("passed"), value.get("measured"), value.get("threshold", entry.inputs.get("threshold"))
    return entry.inputs.get("passed"), value, entry.inputs.get("threshold")


def _extract_flags(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and item.get("code") in FLAG_CODES]
    if not isinstance(payload, dict):
        return []
    batches: list[list[Any]] = []
    if isinstance(payload.get("ledger_flags"), list):
        batches.append(payload["ledger_flags"])
    summary = payload.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("ledger_flags"), list):
        batches.append(summary["ledger_flags"])
    for container_key in ("options_chain_greeks", "layer_data"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        if isinstance(container.get("ledger_flags"), list):
            batches.append(container["ledger_flags"])
        nested = container.get("summary")
        if isinstance(nested, dict) and isinstance(nested.get("ledger_flags"), list):
            batches.append(nested["ledger_flags"])
    for batch in batches:
        flags = [item for item in batch if isinstance(item, dict) and item.get("code") in FLAG_CODES]
        if flags:
            return flags
    return []


def _require_provenance(entry: LedgerEntry) -> None:
    if entry.kind not in _KINDS:
        raise ValueError("ledger entry kind is not a frozen LedgerKind")
    if not isinstance(entry.scanId, str) or not entry.scanId.strip():
        raise ValueError("ledger entry scanId is required")
    if not isinstance(entry.key, str) or not entry.key.strip():
        raise ValueError("ledger entry key is required")
    if not isinstance(entry.inputs, dict):
        raise ValueError("ledger entry inputs must be a dict")
    if entry.kind == "value" and not entry.inputs:
        raise ValueError("ledger entry inputs are required")
    if not isinstance(entry.source, str) or not entry.source.strip():
        raise ValueError("ledger entry source is required")
    if entry.feed is not None and not isinstance(entry.feed, str):
        raise ValueError("ledger entry feed must be a string or null")
    if not isinstance(entry.timestamp, str) or not entry.timestamp.strip():
        raise ValueError("ledger entry timestamp is required")
    if not isinstance(entry.fn, str) or not entry.fn.strip():
        raise ValueError("ledger entry fn is required")
