# Change 12 — agent 2B

Branch: `change12/2B`. Base: `51dbcf9c24269a242ce892b5d8fa375c1360886f`.

Spec C1.1 and D2. Frozen `LedgerEntry` field names and types were not changed. `canAutoExecute` still raises. The stub `ledger.record` / `ledger.get` still drop entries and return `[]`. The live store is `app.services.evidence_ledger`.

## What landed

- Evaluation rows for one scan: each gate stores pass or fail, the measured value, and the threshold; candidates, score components, and final rank (rank is a `score` row because the frozen kinds have no rank type).
- Evidence rows: every card value stores inputs, source, feed, timestamp, and function name. A value with empty inputs or a blank timestamp is refused.
- `record_chain_flags` copies `inverted_put_skew`, `crossed_market`, and `iv_outside_chain_range` when they are already on the payload. It does not recompute them and does not call `chain_quote_flags`.
- Debug read: `GET /api/ledger/{scan_id}` (authenticated). JSON only. No new visual page, because `App.tsx` is not owned here.
- `check_narrative` extracts numbers, percentages, dates, and tickers. A token that is not a ledger value within display rounding rejects the text. `high`, `low`, `rich`, and `cheap` must cite a ledger value and a ledger threshold in the same sentence. The fallback is the knowledge-base template with `{key}` slots filled, keeping only sentences that pass the same check, plus ledger facts. Every rejection is logged.

## Tests

Command: `backend/.venv/bin/python -m pytest -q --tb=line` from `backend/`.

**1544 passed, 59 skipped, 0 failed.** Integration baseline was 1530 passed, 59 skipped, 0 failed. The extra 14 are `test_evidence_ledger.py` and `test_narrative_guard.py`.

Covered: an injected `99.9 percent` is rejected and logged, and the fallback passes the same check; a narrative whose numbers, date, and ticker are on the ledger passes; every recorded card value has provenance; quote flags are copied, not recomputed.

## Requests for other owners

**2A** (`strategy_engine.py` and the explanation writer):

- Call `record_gate`, `record_candidate`, `record_score`, `record_rank`, and `record_card_value` at each gate, candidate, score component, rank, and card number. Do not use `app.contracts.ledger` (it still drops the entry).
- Before showing generated explanation text, call `check_narrative(text, scan_id=..., strategy_id=...)`. If `accepted` is false, show `result.text`.
- Put `high` / `low` / `rich` / `cheap` in the same sentence as the measured ledger value and the threshold. A later sentence does not count.
- Call `record_chain_flags(scan_id, payload)` with the options layer 1C already filled. Do not recompute the three flags.
- A clock time such as `14:00` is a number. Cite it only when that number is a ledger value. `Oct 16, 2026` matches a ledger date of `2026-10-16`.
- Do not call `contracts.canAutoExecute`.

**2C:** knowledge-base sentences may use `{key}` placeholders. The fallback substitutes those keys. A template sentence whose numbers are not on the ledger is left out of the fallback.

**1C:** no change. The copied flag fields are `code`, `value`, `threshold`, `source`, `feed`, `timestamp`, and when present `symbol`, `strike`, `side`, `detail`.
