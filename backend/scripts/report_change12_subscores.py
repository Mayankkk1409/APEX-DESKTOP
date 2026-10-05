"""Report sub-score distributions for the 50 QA tickers.

Reads captured scan output. Does not change composite weights and does not
fill a missing pillar with a number.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPO = ROOT.parent
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "change12_qa_replay.json"
DEFAULT_CSV = REPO / "docs" / "qa" / "APEX_QA_Test_Results.csv"

PILLARS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("technical", ("technicals", "technical")),
    ("volatility", ("volatility",)),
    ("greeks", ("options", "greeks")),
    ("sentiment", ("sentiment",)),
    ("fundamental", ("fundamentals", "fundamental")),
)


def qa_tickers(csv_path: Path | None = None) -> list[str]:
    path = csv_path or DEFAULT_CSV
    tickers: list[str] = []
    with path.open() as handle:
        for record in csv.DictReader(handle):
            ticker = str(record.get("Ticker") or "").strip()
            if ticker:
                tickers.append(ticker)
    return tickers


def pillar_value(components: dict | None, keys: tuple[str, ...]) -> float | None:
    """First stored numeric pillar. A missing or non-numeric value stays absent."""
    if not isinstance(components, dict):
        return None
    for key in keys:
        if key not in components:
            continue
        value = components[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)
    return None


def _weights_text() -> str:
    from app.analysis.layers import APEX_COMPOSITE_WEIGHTS

    order = ("technicals", "volatility", "options", "sentiment", "fundamentals", "risk")
    parts = [f"{key} {float(APEX_COMPOSITE_WEIGHTS[key]):.0%}" for key in order]
    return (
        "Weights were not changed. Read from APEX_COMPOSITE_WEIGHTS: "
        + ", ".join(parts)
        + ". Risk stays advisory."
    )


def _distribution(values: list[float]) -> str:
    if not values:
        return "n=0 mean=absent population_stdev=absent min=absent max=absent distinct_1dp=0"
    rounded = [round(value, 1) for value in values]
    distinct = len(set(rounded))
    spread = 0.0 if len(values) == 1 else statistics.pstdev(values)
    return (
        f"n={len(values)} mean={statistics.fmean(values):.2f} "
        f"population_stdev={spread:.2f} min={min(values):.2f} max={max(values):.2f} "
        f"distinct_1dp={distinct}"
    )


def render_distribution(payload: dict, tickers: list[str] | None = None) -> str:
    names = list(tickers) if tickers is not None else qa_tickers()
    by_ticker = {row.get("ticker"): row for row in payload.get("rows") or [] if isinstance(row, dict)}
    lines = ["Sub-score distribution. Missing pillars are absent. No score was filled in.", _weights_text(), ""]
    series: dict[str, list[float]] = {label: [] for label, _keys in PILLARS}
    absent: dict[str, list[str]] = {label: [] for label, _keys in PILLARS}
    compressed: list[str] = []
    for ticker in names:
        row = by_ticker.get(ticker)
        components = None
        reason = ""
        if row is None:
            reason = "no snapshot"
        elif row.get("error") and not isinstance((row.get("summary") or {}).get("components"), dict):
            reason = str(row.get("error"))
        else:
            summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
            components = summary.get("components") if isinstance(summary.get("components"), dict) else None
            if components is None:
                reason = "components absent"
        for label, keys in PILLARS:
            value = pillar_value(components, keys)
            if value is None:
                detail = reason or "pillar absent"
                absent[label].append(f"{ticker} ({detail})")
            else:
                series[label].append(value)
    for label, _keys in PILLARS:
        lines.append(f"{label}: {_distribution(series[label])} absent={len(absent[label])}")
        if absent[label]:
            lines.append("  absent: " + "; ".join(absent[label]))
        else:
            lines.append("  absent: none")
        values = series[label]
        if len(values) >= 2:
            spread = statistics.pstdev(values)
            distinct = len({round(value, 1) for value in values})
            if spread < 5 or distinct <= 3:
                compressed.append(f"{label} (population stdev {spread:.2f}, {distinct} values at 1 decimal)")
    lines.append("")
    if compressed:
        lines.append(
            "Proposal: leave the weights as they are. These pillars are compressed on this capture: "
            + "; ".join(compressed)
            + ". Recalibrate those scorers before any weight change. This script does not write weights."
        )
    else:
        lines.append(
            "Proposal: leave the weights as they are. No pillar on this capture is compressed "
            "under a population stdev of 5 or three or fewer distinct one-decimal values. "
            "This script does not write weights."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT_FIXTURE
    if not path.is_file():
        print(f"fixture not found: {path}", file=sys.stderr)
        return 1
    payload = json.loads(path.read_text())
    sys.stdout.write(render_distribution(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
