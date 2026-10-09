# Change 12 — agent 2B

Branch: `change12/2B`. Worktree: `/Users/Mayank/Desktop/APEX-change12-2B`. Base: `change12/base` at `51dbcf9c24269a242ce892b5d8fa375c1360886f`.

Spec C1.1 and D2. `LedgerEntry` field names and types were not changed. `canAutoExecute` still raises. The stub `ledger.record` / `ledger.get` still drop the entry and return `[]`. The live store is `app.services.evidence_ledger`. The only edit in `backend/app/contracts.py` is the module docstring, so other agents do not call the stub by mistake.

## Stage 1 — Brainstorm

Approaches considered:

- Put `record` / `get` on the frozen `Ledger` class. Rejected as the place the behavior lives. The class stays the type source. A new module holds the rows.
- Add a scans table for the ledger. Rejected. Models are not owned here. Rows are kept per scan id in the process.
- Recompute inverted skew, crossed markets, and IV-outside-range from bid, ask, and IV. Rejected. 1C already writes `ledger_flags`. This agent copies those three codes.
- Ask a language model to judge the explanation. Rejected. The check compares tokens to stored values. It does not price, score, or invent a date.

## Stage 2 — Research

- `LedgerKind` is `value`, `gate`, `candidate`, or `score`. Rank has no kind, so the final rank is a `score` row whose component is `rank`.
- `chain_quote_flags` in `backend/app/analysis/options_rules.py` already emits `inverted_put_skew`, `crossed_market`, and `iv_outside_chain_range` with `value`, `threshold`, `source`, `feed`, and `timestamp`. This agent does not import that function.
- Knowledge-base text comes from `entry_for`. Placeholders `{key}` are filled from ledger keys. Sentences that still fail the token check are left out.
- Composite display is one decimal, half up. A whole number matches only a stored whole number. `30.31` may appear as `30.3`. `30.35` may appear as `30.4`. `99.9` does not match either.
- `App.tsx` is not owned here, so the debug view is `GET /api/ledger/{scan_id}` and not a new page.

## Stage 3 — Checklist

- [x] Every strategy can store pass or fail per gate, with the measured value and the threshold
- [x] Candidates, score components, and final rank are stored per scan id
- [x] Every card value stores inputs, source, feed, timestamp, and function name
- [x] Empty inputs or a blank timestamp are refused
- [x] The three 1C flags are copied when present and ignored when absent, even if bid is above ask
- [x] `99.9 percent` is rejected, logged, and replaced by a fallback that passes the same check
- [x] A narrative whose numbers, date, and ticker are on the ledger passes
- [x] `high`, `low`, `rich`, and `cheap` must cite a ledger value and threshold in the same sentence
- [x] Authenticated JSON debug read
- [x] Full backend suite green
- [x] Spread, open-interest, and staleness thresholds unchanged
- [x] No order is placed and no score weight is changed

## Stage 4 — Execution

- `backend/app/services/evidence_ledger.py` — `record`, `get`, `record_gate`, `record_candidate`, `record_score`, `record_rank`, `record_card_value`, `record_chain_flags`, `evaluation`.
- `backend/app/services/narrative_guard.py` — `check_narrative`. Rejection log. Knowledge-base fallback.
- `backend/app/routers/ledger.py` — `GET /api/ledger/{scan_id}`.
- `backend/app/main.py` — includes that router.
- `backend/app/contracts.py` — docstring only.

`strategy_engine.py` was not edited. 2A inserts the `record` calls and passes explanation text through `check_narrative`.

## Stage 5 — Testing

Command, from `backend/` in this worktree, using the main checkout's virtualenv:

`python -m pytest -q --tb=line`

Result: **1544 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). Integration baseline was 1530 passed, 59 skipped, 0 failed. The 14 new tests are the difference.

| Test | What it checks |
| --- | --- |
| `test_ledger_entry_fields_stay_frozen` | Field order unchanged; the stub still returns `[]` |
| `test_scan_stores_gates_candidates_scores_and_rank` | Pass/fail, measured, threshold, candidate, score, rank, per scan |
| `test_card_values_keep_provenance_and_scans_stay_separate` | inputs, source, feed, timestamp, fn |
| `test_card_value_without_provenance_is_rejected` | Empty inputs or a blank timestamp |
| `test_chain_flags_are_copied_and_not_recomputed` | Three codes copied; bid above ask with no flags records nothing |
| `test_debug_route_returns_the_scan_ledger` | 401 without a token; JSON gates for the scan id |
| `test_hallucinated_percent_is_rejected_and_logged` | `99.9 percent` rejected; fallback passes a second check |
| `test_narrative_whose_figures_are_on_the_ledger_passes` | `62.9`, `Oct 16, 2026`, `30.3`, `1,500`, `AAPL` |
| `test_display_rounding_accepts_one_decimal_and_rejects_the_other_way` | `30.31` as `30.3`; `30.35` as `30.4`, not `30.3` |
| `test_qualitative_claim_cites_ledger_value_and_threshold` | high, low, rich, cheap |
| `test_unknown_ticker_is_rejected` | `ZZZZ` |

## Requests for other owners

**2A** (`strategy_engine.py` and the explanation writer):

- Call `record_gate`, `record_candidate`, `record_score`, `record_rank`, and `record_card_value` at each gate, candidate, score component, rank, and card number. Do not use `app.contracts.ledger`. It still drops the entry.
- Before the card shows generated explanation text, call `check_narrative(text, scan_id=..., strategy_id=...)`. When `accepted` is false, show `result.text`.
- Put `high`, `low`, `rich`, or `cheap` in the same sentence as the measured ledger value and the threshold. A later sentence does not count.
- Call `record_chain_flags(scan_id, payload)` with the options layer 1C already filled. Do not recompute the three flags.
- A clock time such as `14:00` is a number. Cite it only when that number is a ledger value. `Oct 16, 2026` matches a ledger date of `2026-10-16`.
- Do not call `contracts.canAutoExecute`.

**2C:** knowledge-base sentences may use `{key}` placeholders. The fallback substitutes those keys. A template sentence whose numbers are not on the ledger is left out of the fallback.

**1C:** no change. Copied flag fields are `code`, `value`, `threshold`, `source`, `feed`, `timestamp`, and when present `symbol`, `strike`, `side`, `detail`.
