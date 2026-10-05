"""OCC option symbol parsing shared by expiry watch and brokerage alerts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_OCC = re.compile(r"([A-Z]{1,6})(\d{6})([CP])(\d{8})")


@dataclass(frozen=True)
class OccContract:
    root: str
    expiry: date
    right: str
    strike: float


def parse_occ(symbol: str) -> OccContract | None:
    raw = symbol.upper().replace(" ", "")
    match = _OCC.search(raw)
    if not match:
        return None
    yymmdd = match.group(2)
    year = 2000 + int(yymmdd[:2])
    try:
        expiry = date(year, int(yymmdd[2:4]), int(yymmdd[4:6]))
    except ValueError:
        return None
    return OccContract(
        root=match.group(1),
        expiry=expiry,
        right=match.group(3),
        strike=int(match.group(4)) / 1000.0,
    )


def parse_occ_expiry(symbol: str) -> date | None:
    parsed = parse_occ(symbol)
    return parsed.expiry if parsed else None


def expiry_iso_from_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            return None
    parsed = parse_occ_expiry(text)
    return parsed.isoformat() if parsed else None
