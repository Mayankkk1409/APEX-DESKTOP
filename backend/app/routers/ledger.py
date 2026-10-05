"""Debug read of the evaluation and evidence ledger for one scan."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.models.user import User
from app.services.evidence_ledger import evaluation, get
from app.services.narrative_guard import rejections

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/{scan_id}")
async def get_scan_ledger(scan_id: str, _user: User = Depends(current_user)) -> dict:
    entries = get(scan_id)
    return {
        "scanId": scan_id,
        "entries": [asdict(entry) for entry in entries],
        "evaluation": evaluation(scan_id),
        "rejections": rejections(scan_id),
    }
