"""Change 12 frozen contracts.

Field names and types are frozen. ``canAutoExecute`` stays an unwired stub.
``Ledger.record`` drops the entry and ``Ledger.get`` returns an empty list.
The live store is ``app.services.evidence_ledger``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FeedName = Literal["indicative", "opra", "other"]
EarningsStatus = Literal["confirmed", "estimated", "unknown"]
LedgerKind = Literal["value", "gate", "candidate", "score"]


@dataclass
class QuoteMeta:
    provider: str
    feed: FeedName
    quotedAt: str | None
    receivedAt: str | None
    bid: float | None
    ask: float | None
    bidSize: float | None
    askSize: float | None
    isStale: bool
    staleReason: str | None


@dataclass
class EarningsInfo:
    date: str | None
    status: EarningsStatus
    sources: list[str]
    securityType: str


@dataclass
class ExecutabilityVerdict:
    executable: bool
    reasons: list[str]
    checkedAt: str


@dataclass
class AutoExecuteDecision:
    eligible: bool
    reasons: list[str]


@dataclass
class VolRegime:
    ivMinusHvPts: float | None
    ivToHv: float | None
    ivRank: float | None
    verdict: str
    rule: str


@dataclass
class LedgerEntry:
    scanId: str
    kind: LedgerKind
    key: str
    value: Any
    inputs: dict[str, Any]
    source: str
    feed: str | None
    timestamp: str
    fn: str


def canAutoExecute(scan: Any, userSettings: Any) -> AutoExecuteDecision:
    """Frozen signature. Not wired. Raises so a stray call cannot mark a trade eligible."""
    raise NotImplementedError("canAutoExecute is a Change 12 stub and is not wired")


class Ledger:
    """In-memory stub. record drops the entry. get returns an empty list."""

    def record(self, entry: LedgerEntry) -> None:
        return None

    def get(self, scanId: str) -> list[LedgerEntry]:
        return []


ledger = Ledger()
