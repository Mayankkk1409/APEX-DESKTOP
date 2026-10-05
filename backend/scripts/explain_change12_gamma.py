"""Print why Gamma Trampoline was or was not selected on the ten catalyst names.

Reads the evaluation ledger stored on a QA snapshot. Measured values come from
those rows. A missing IV or IV rank is labeled a data defect. The eight
historical earnings moves are never filled in.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "change12_qa_replay.json"
GAMMA = "Gamma Trampoline™"
GAMMA_NAMES = ("JPM", "GS", "C", "JNJ", "UNH", "BAC", "WFC", "MS", "BLK", "PLD")

_GATE_ORDER = (
    "catalyst",
    "iv_rank",
    "term_structure",
    "history",
    "adv",
    "open_interest",
    "spread",
    "structure",
    "other",
)


def _ratio_threshold() -> str:
    """Live gate setting. The measured ratio still comes from the ledger note."""
    from app.analysis.gate_config import gamma_front_back_iv_ratio_min

    return f"{gamma_front_back_iv_ratio_min():g}"


def classify_gate_note(note: str) -> dict[str, str]:
    """Turn one ledger sentence into a gate, a result, a measured value, and a threshold."""
    text = str(note).strip()
    rules: list[tuple[str, str, re.Pattern[str], str]] = [
        (
            "catalyst",
            "pass",
            re.compile(r"Catalyst window (\d+(?:\.\d+)?) calendar days is inside (\d+(?:\.\d+)?) to (\d+(?:\.\d+)?)"),
            "measured={0} calendar days; threshold={1} to {2}",
        ),
        (
            "catalyst",
            "fail",
            re.compile(r"Calendar days to confirmed earnings (\d+(?:\.\d+)?) is outside (\d+(?:\.\d+)?) to (\d+(?:\.\d+)?)"),
            "measured={0} calendar days; threshold={1} to {2}",
        ),
        (
            "catalyst",
            "fail_closed",
            re.compile(r"Earnings date is missing"),
            "measured=absent; threshold=a confirmed earnings date",
        ),
        (
            "iv_rank",
            "data_defect",
            re.compile(r"Front-week IV rank is missing, so the (\d+(?:\.\d+)?) minimum cannot pass"),
            "measured=absent; threshold=above {0}",
        ),
        (
            "iv_rank",
            "pass",
            re.compile(r"Front-week IVR (\d+(?:\.\d+)?) is above (\d+(?:\.\d+)?)"),
            "measured={0}; threshold=above {1}",
        ),
        (
            "iv_rank",
            "fail",
            re.compile(r"Front-week IV rank (\d+(?:\.\d+)?) is not above (\d+(?:\.\d+)?)"),
            "measured={0}; threshold=above {1}",
        ),
        (
            "term_structure",
            "data_defect",
            re.compile(r"Front-week IV divided by back-week IV is missing, so the (\d+(?:\.\d+)?) minimum cannot pass"),
            "measured=absent; threshold=at least {0}",
        ),
        (
            "term_structure",
            "fail",
            re.compile(r"Front-week IV divided by back-week IV is (\d+(?:\.\d+)?), below (\d+(?:\.\d+)?)"),
            "measured={0}; threshold=at least {1}",
        ),
        (
            "term_structure",
            "pass",
            re.compile(r"Front-week IV / back-week IV is (\d+(?:\.\d+)?)"),
            "measured={0}",
        ),
        (
            "history",
            "fail_closed",
            re.compile(r"Earnings move history is missing; the last ([0-9]+) reports are not in the data"),
            "measured=absent; threshold=last {0} reports in the data",
        ),
        (
            "history",
            "fail",
            re.compile(
                r"Only ([0-9]+) of the last ([0-9]+) earnings moves were smaller than the implied move; "
                r"at least ([0-9]+) of ([0-9]+) are required"
            ),
            "measured={0} of {1}; threshold=at least {2} of {3}",
        ),
        (
            "history",
            "pass",
            re.compile(r"([0-9]+) of the last ([0-9]+) earnings moves were smaller than the implied move"),
            "measured={0} of {1}",
        ),
        (
            "adv",
            "fail_closed",
            re.compile(r"ADV is missing, so the ([0-9,]+) share minimum cannot pass"),
            "measured=absent; threshold=above {0} shares",
        ),
        (
            "adv",
            "pass",
            re.compile(r"ADV ([0-9,]+) is above ([0-9,]+) shares"),
            "measured={0} shares; threshold=above {1} shares",
        ),
        (
            "adv",
            "fail",
            re.compile(r"ADV ([0-9,]+) is not above ([0-9,]+) shares"),
            "measured={0} shares; threshold=above {1} shares",
        ),
        (
            "open_interest",
            "fail_closed",
            re.compile(r"Open interest is missing, so the ([0-9,]+) minimum"),
            "measured=absent; threshold=above {0} on each strike",
        ),
        (
            "open_interest",
            "fail",
            re.compile(r"Open interest ([0-9,]+) is not above ([0-9,]+)"),
            "measured={0}; threshold=above {1}",
        ),
        (
            "open_interest",
            "pass",
            re.compile(r"Open interest ([0-9,]+) is above ([0-9,]+)"),
            "measured={0}; threshold=above {1}",
        ),
        (
            "spread",
            "fail_closed",
            re.compile(r"Bid/ask spread is missing, so the (\d+(?:\.\d+)?)% of mid cap cannot pass"),
            "measured=absent; threshold=below {0}% of mid",
        ),
        (
            "spread",
            "fail",
            re.compile(r"Bid/ask spread is (\d+(?:\.\d+)?)% of mid, not below (\d+(?:\.\d+)?)%"),
            "measured={0}% of mid; threshold=below {1}% of mid",
        ),
        (
            "spread",
            "pass",
            re.compile(r"Spread (\d+(?:\.\d+)?)% of mid is below (\d+(?:\.\d+)?)%"),
            "measured={0}% of mid; threshold=below {1}% of mid",
        ),
        (
            "structure",
            "pass",
            re.compile(r"Front expiry after earnings and back expiry about 2 weeks later are both listed"),
            "measured=listed; threshold=front expiry after earnings and back expiry about 2 weeks later, same strikes",
        ),
        (
            "structure",
            "fail",
            re.compile(r"The 4-leg structure is not listed"),
            "measured=not listed; threshold=front expiry after earnings and back expiry about 2 weeks later",
        ),
        (
            "structure",
            "fail",
            re.compile(r"Front and back expirations must use the same strikes"),
            "measured=strikes differ; threshold=same strikes on each side",
        ),
    ]
    for gate, result, pattern, template in rules:
        match = pattern.search(text)
        if match is None:
            continue
        detail = template.format(*match.groups()) if match.groups() else template
        if gate == "term_structure" and result == "pass" and "threshold=" not in detail:
            detail = f"{detail}; threshold=at least {_ratio_threshold()}"
        comment = ""
        if result == "data_defect":
            comment = "A missing IV or IV rank is a data defect, not a strategy verdict."
        elif gate == "history" and result == "fail_closed":
            comment = "The eight historical earnings moves were not invented."
        return {
            "gate": gate,
            "result": result,
            "detail": detail,
            "ledger": text,
            "comment": comment,
        }
    if text == "Gamma Trampoline earnings gates passed":
        return {
            "gate": "other",
            "result": "pass",
            "detail": "ledger records that the earnings gates passed",
            "ledger": text,
            "comment": "",
        }
    return {
        "gate": "other",
        "result": "recorded",
        "detail": "measured=not parsed from this note; threshold=not parsed from this note",
        "ledger": text,
        "comment": "",
    }


def ledger_entries(snapshot: dict) -> list[dict]:
    """Ledger rows for one snapshot. An explicit empty evaluation ledger stays empty."""
    if "evaluation_ledger" in snapshot:
        raw = snapshot.get("evaluation_ledger") or []
        return [row for row in raw if isinstance(row, dict)]
    rows: list[dict] = []
    seen: set[str] = set()
    for key in ("ledger_gamma", "candidates"):
        for row in snapshot.get(key) or []:
            if not isinstance(row, dict):
                continue
            token = json.dumps(
                {
                    "kind": row.get("kind"),
                    "key": row.get("key"),
                    "value": row.get("value"),
                    "inputs": row.get("inputs"),
                },
                sort_keys=True,
                default=str,
            )
            if token in seen:
                continue
            seen.add(token)
            rows.append(row)
    return rows


def _gamma_candidate(entries: list[dict]) -> dict | None:
    for entry in entries:
        if entry.get("kind") == "candidate" and entry.get("key") == GAMMA:
            return entry
    return None


def explain_ticker(ticker: str, snapshot: dict | None) -> str:
    """One ticker block. Missing snapshots and empty ledgers are stated, not filled in."""
    if snapshot is None:
        return f"{ticker}: no snapshot."
    lines = [f"{ticker}:"]
    error = snapshot.get("error")
    if error:
        lines.append(f"  capture error: {error}")
    entries = ledger_entries(snapshot)
    if not entries:
        lines.append("  this snapshot has no ledger rows.")
        return "\n".join(lines)
    candidate = _gamma_candidate(entries)
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    best = summary.get("strategy")
    if candidate is None:
        lines.append(
            f"  the ledger has {len(entries)} rows and no {GAMMA} candidate, so selection was not recorded."
        )
        lines.append(f"  best match on the snapshot: {best if best else 'absent'}.")
        return "\n".join(lines)
    value = candidate.get("value") if isinstance(candidate.get("value"), dict) else {}
    eligible = bool(value.get("eligible"))
    selected = eligible and best == GAMMA
    score = value.get("score")
    score_text = "absent" if score is None else str(score)
    lines.append(
        f"  selected: {'yes' if selected else 'no'}. "
        f"best match: {best if best else 'absent'}. "
        f"{GAMMA} eligible: {'yes' if eligible else 'no'}. "
        f"score: {score_text}."
    )
    notes = (candidate.get("inputs") or {}).get("gate_notes") if isinstance(candidate.get("inputs"), dict) else None
    if not notes:
        lines.append("  gate notes: absent.")
        return "\n".join(lines)
    classified = [classify_gate_note(str(note)) for note in notes if str(note).strip()]
    classified.sort(key=lambda item: _GATE_ORDER.index(item["gate"]) if item["gate"] in _GATE_ORDER else len(_GATE_ORDER))
    for index, item in enumerate(classified, start=1):
        lines.append(f"  {index}. {item['gate']}: {item['result']}")
        lines.append(f"     {item['detail']}")
        if item["comment"]:
            lines.append(f"     {item['comment']}")
        lines.append(f"     ledger: {item['ledger']}")
    return "\n".join(lines)


def render_report(payload: dict, tickers: tuple[str, ...] = GAMMA_NAMES) -> str:
    by_ticker = {row.get("ticker"): row for row in payload.get("rows") or [] if isinstance(row, dict)}
    blocks = [explain_ticker(ticker, by_ticker.get(ticker)) for ticker in tickers]
    return "\n\n".join(blocks) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT_FIXTURE
    if not path.is_file():
        print(f"fixture not found: {path}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text())
    sys.stdout.write(render_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
