"""Capture one live scan per QA sheet row. Does not invent a chain."""

from __future__ import annotations

import asyncio
import csv
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from app.adapters.alpaca import AlpacaAdapter  # noqa: E402
from app.analysis.layers import DEFAULT_AUTO_EXEC_THRESHOLD  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.schemas.market import ChartSnapshot  # noqa: E402
from app.services.evidence_ledger import get, reset_ledger  # noqa: E402
from app.services.fundamentals_layer import build_fundamentals_layer  # noqa: E402
from app.services.narrative_guard import check_narrative  # noqa: E402
from app.services.scan_engine import build_layers  # noqa: E402
from app.services.sentiment_layer import build_sentiment_layer  # noqa: E402
from app.strategies.expiry_utils import next_expiry_after  # noqa: E402

CSV_PATH = REPO / "docs" / "qa" / "APEX_QA_Test_Results.csv"
OUT_PATH = ROOT / "tests" / "fixtures" / "change12_qa_replay.json"
# The QA sheet marks 49.7 manual and 50.2 auto-execute eligible. 50 matches that split.
QA_MINIMUM = 50.0
GAMMA = "Gamma Trampoline™"


def _dump(model) -> dict | None:
    if model is None:
        return None
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return None


def _texts(strategy: dict) -> list[str]:
    notes = strategy.get("risk_notes") or []
    chunks = [
        strategy.get("why_it_fits") or strategy.get("why_recommended") or "",
        strategy.get("how_to_execute") or strategy.get("how_to_use") or "",
        strategy.get("what_is_this") or "",
        strategy.get("auto_exec_line") or "",
        strategy.get("narrative") or "",
        strategy.get("outlook") or "",
    ]
    chunks.extend(note for note in notes if isinstance(note, str))
    return [text for text in chunks if text]


async def _one(adapter: AlpacaAdapter, settings, ticker: str, expiry: str) -> dict:
    reset_ledger(ticker)
    now = datetime.now(timezone.utc).isoformat()
    snap = ChartSnapshot(
        symbol=ticker,
        timeframe="15Min",
        visible_from="2026-08-01T13:30:00Z",
        visible_to=now,
        studies=[],
        captured_at=now,
    )
    quote = await adapter.quote(ticker)
    bars = await adapter.bars(ticker, "15Min", 180)
    daily = await adapter.bars(ticker, "1D", 400)
    chain = await adapter.option_chain(ticker, expiry)
    back = None
    back_expiry = None
    if chain and chain.expiry_valid:
        expirations = await adapter.expirations(ticker)
        back_expiry = next_expiry_after([item.date for item in expirations], expiry)
        if back_expiry:
            back = await adapter.option_chain(ticker, back_expiry)
    if not bars:
        return {"ticker": ticker, "expiry": expiry, "error": "no bars returned"}
    fundamentals = await build_fundamentals_layer(ticker, quote, settings)
    sentiment = await build_sentiment_layer(
        ticker,
        settings,
        chain=chain,
        chain_summary=None,
        fundamentals=fundamentals,
    )
    layers = build_layers(
        snap,
        quote,
        bars,
        chain,
        sentiment_score=(
            float(sentiment["score_0_100"])
            if isinstance(sentiment.get("score_0_100"), (int, float))
            else None
        ),
        expiry=expiry,
        daily_bars=daily,
        sentiment_layer=sentiment,
        fundamentals_layer=fundamentals,
        auto_execution_threshold=QA_MINIMUM,
        back_month_chain=back,
    )
    strategy = layers["strategy"]
    score = layers["apex_score"]
    risk = layers["risk_review"]
    vol = layers["volatility"]
    chain_layer = layers["options_chain_greeks"]
    components = {
        section.get("id"): section.get("score")
        for section in (score.get("sections") or [])
        if isinstance(section, dict)
    }
    ledger = []
    for entry in get(ticker):
        ledger.append(
            {
                "kind": entry.kind,
                "key": entry.key,
                "value": entry.value,
                "inputs": entry.inputs,
            }
        )
    unmatched: list[str] = []
    for text in _texts(strategy):
        result = check_narrative(text, scan_id=ticker, strategy_id=str(strategy.get("selected_strategy") or ""))
        if not result.accepted:
            unmatched.extend(result.problems)
    calendar = (fundamentals or {}).get("earnings_calendar") or {}
    metrics = strategy.get("metrics") or {}
    legs = metrics.get("legs") or []
    return {
        "ticker": ticker,
        "expiry": expiry,
        "error": None,
        "back_expiry": back_expiry,
        "quote": _dump(quote),
        "chain_status": None if chain is None else chain.status,
        "chain_count": 0 if chain is None else len(chain.contracts),
        "back_count": 0 if back is None else len(back.contracts),
        "chain_as_of": None if chain is None else chain.as_of,
        "chain_feed": None if chain is None else chain.feed,
        "summary": {
            "strategy": strategy.get("selected_strategy"),
            "status": strategy.get("execution_banner") or "BEST MATCH",
            "composite": score.get("composite_score"),
            "eligibility": strategy.get("auto_exec_line"),
            "eligible": bool(risk.get("auto_execute_eligible")),
            "placeable": bool(strategy.get("placeable")),
            "tradeable": bool(strategy.get("tradeable")),
            "failed_checks": list(strategy.get("block_reasons") or strategy.get("spread_block_reasons") or []),
            "risk_notes": list(strategy.get("risk_notes") or []),
            "vol_regime": strategy.get("vol_regime"),
            "direction": strategy.get("direction"),
            "leg_count": len([leg for leg in legs if leg.get("side") in {"call", "put"}]),
            "equity_legs": [leg for leg in legs if leg.get("side") not in {"call", "put"}],
            "stock_legs": risk.get("stock_legs") or [],
            "components": components,
            "iv": vol.get("iv"),
            "hv": vol.get("hv"),
            "iv_rank": vol.get("iv_rank"),
            "earnings": {
                "applicable": calendar.get("earnings_applicable"),
                "next_date": calendar.get("next_date"),
                "status": calendar.get("status"),
                "display": calendar.get("display"),
            },
            "quote_as_of": quote.as_of,
            "quote_source": quote.source,
            "quote_feed": (quote.quote_meta.feed if quote.quote_meta else None),
            "unmatched": unmatched,
            "recommended_expiry": chain_layer.get("expiry"),
        },
        "ledger_gamma": [
            row
            for row in ledger
            if GAMMA in str(row.get("key")) or "gamma" in str(row.get("key")).lower() or GAMMA in json.dumps(row.get("value"), default=str)
        ],
        "candidates": [row for row in ledger if row.get("kind") == "candidate"],
    }


async def main() -> None:
    only = set(sys.argv[1:])
    settings = get_settings()
    adapter = AlpacaAdapter(settings)
    rows = []
    with CSV_PATH.open() as handle:
        for record in csv.DictReader(handle):
            ticker = record["Ticker"].strip()
            expiry = record["Expiry"].strip()
            if only and ticker not in only:
                continue
            print(f"capture {ticker} {expiry}", flush=True)
            try:
                rows.append(await _one(adapter, settings, ticker, expiry))
            except Exception as exc:  # noqa: BLE001 — one ticker must not abort the sheet
                rows.append(
                    {
                        "ticker": ticker,
                        "expiry": expiry,
                        "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc().splitlines()[-4:],
                    }
                )
                print(f"  failed {ticker}: {exc}", flush=True)
            else:
                summary = rows[-1]["summary"]
                print(
                    f"  {summary['status']} {summary['strategy']} {summary['composite']} chain={rows[-1]['chain_count']}",
                    flush=True,
                )
    if only and OUT_PATH.exists():
        previous = json.loads(OUT_PATH.read_text())
        by_ticker = {row["ticker"]: row for row in previous.get("rows") or []}
        for row in rows:
            by_ticker[row["ticker"]] = row
        order = [record["Ticker"].strip() for record in csv.DictReader(CSV_PATH.open())]
        rows = [by_ticker[ticker] for ticker in order if ticker in by_ticker]
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "qa_minimum": QA_MINIMUM,
        "product_default_minimum": DEFAULT_AUTO_EXEC_THRESHOLD,
        "feed": adapter.feed,
        "rows": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, default=str))
    print(f"wrote {OUT_PATH} bytes={OUT_PATH.stat().st_size}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
