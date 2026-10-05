"""Change 12 frozen contracts.

Field names and types are frozen. ``canAutoExecute`` delegates to
``app.services.executability.can_auto_execute`` and returns the same shape.
``Ledger.record`` drops the entry and ``Ledger.get`` returns an empty list.
The live store is ``app.services.evidence_ledger``. Do not call ``ledger.record``
for persistence.
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
    """Same decision as ``app.services.executability.can_auto_execute``."""
    from app.services.executability import can_auto_execute

    decision = can_auto_execute(scan, userSettings)
    return AutoExecuteDecision(eligible=bool(decision.eligible), reasons=list(decision.reasons))


class Ledger:
    """In-memory stub. record drops the entry. get returns an empty list."""

    def record(self, entry: LedgerEntry) -> None:
        return None

    def get(self, scanId: str) -> list[LedgerEntry]:
        return []


ledger = Ledger()
