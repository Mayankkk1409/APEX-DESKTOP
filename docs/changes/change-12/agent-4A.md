# Change 12 — agent 4A

Branch: `change12/4A`. Worktree: `/Users/Mayank/Desktop/APEX-change12-4A`. Started from `297104c` (`Ground the remaining Phase 3 card sentences on the ledger.`).

Scope: the trader card stopped reading like copy and started reading like the evidence ledger. The ledger still belongs on `GET /api/ledger` and in the rejection log. No ranking math, no composite weights, and no ±5 vol-point band was touched.

## What the user saw

On MDB and NFLX the card showed `Collar Collar.` followed by `Payoff is the model grid…` and then hundreds of rows such as `data_freshness is True from strategy_recommendation via recommend_strategy`, `collar:score is 0 …`, and one row per leg figure and per payoff-grid point `from strategy_layer via build_strategy_layer`.

## Root cause

`backend/app/services/narrative_guard.py` `_fallback` built the replacement text from three parts: the knowledge-base template (`title` + `summary` + `why_it_fits` + `how_to_use` + `key_risks`), then **every** ledger row rendered by `_fact_lines` as `{key} is {value} from {source} via {fn}.`

So a single rejected figure turned the whole scan ledger into card copy:

- `title` and `summary` both name the structure, and catalog summaries are built as `f"{name}. {formula}"`, which is where `Collar Collar.` came from.
- `_fact_lines` printed gate rows (`data_freshness is True …`), the zero score of every unselected candidate (`collar:score is 0 …`), and each recorded leg, metric, and payoff-grid number.

Reproduced before the fix on an MDB-like Collar layer seeded with the rows a scan records: the first risk note was 3.5 kB and contained `Collar\nCollar. Payoff is the model grid…` followed by the gate and score rows.

A second, smaller cause sat on the accepted path: the term-structure sentence prints `front IV 28.00% is 0.70x back IV 40.00% (threshold 1.25x)`, and that ratio was never recorded as a card figure. The guard rejected the real why-it-fits over `0.70`, and the old dump happened to re-supply the missing sentences, which is how `tests/test_change12_2a.py::test_long_leg_spans_earnings_names_the_leg_and_date` was passing — it was asserting on the dump.

## Changes

`backend/app/services/narrative_guard.py`

- Deleted `_fact_lines`. The ledger is never joined into prose.
- `_fallback` is now a short knowledge-base sentence for the **selected** strategy plus one headline figure sentence:
  - `_catalog_sentences` reads only the selected strategy's entry, fills `{key}` placeholders from the ledger, drops a sentence that is just the strategy's own name (so the structure is named once), and takes the first grounded sentence (`_FALLBACK_SENTENCE_CAP = 1`) from `why_it_fits`, then `summary`, then `key_risks`.
  - `_figure_sentence` prints only the card's headline figures from recorded `value` rows: `The composite is 58 with IV 42 percent and HV 33 percent.` Composite is one decimal with a trailing `.0` trimmed; IV and HV print as percents, converting a stored fraction such as `0.3031` to `30.3`.
  - Every kept sentence is re-checked against the ledger, so the fallback still has zero unmatched tokens. When nothing survives, the text is the existing one-line rejection sentence.
- Module docstring records that the ledger stays on `GET /api/ledger` and in the log.

`backend/app/services/strategy_engine.py` (card text and card figures only)

- `_narrative_line` replaces the inline `f"Recommended: {name}. {summary} {execution}"`. When the summary already opens with the structure name, the lead is dropped, so the narrative names the structure once.
- `build_strategy_layer` records `front_back_iv_ratio`, `front_iv`, and `back_iv` as card figures, because the term-structure sentence prints them. Nothing else about that sentence changed.

`frontend/src/components/StrategyScan.tsx` — not edited. It renders backend strings and structured metrics (legs, max profit, max loss, breakevens, payoff table); it does not print raw layer strings, so there was nothing to strip.

## Tests

`backend/tests/test_change12_card_copy.py` (new). Each test seeds the rows a scan records (`data_freshness`, `liquidity`, `spread_cap`, `earnings_blackout` gate values from `strategy_recommendation` / `recommend_strategy`, and a zero score for five candidate strategies), then forces the fallback with an ungrounded `999.9`.

- `test_card_copy_never_carries_the_evidence_ledger[MDB]` and `[NFLX]` — why-it-fits, how-to-use, what-is-this, the Risk Review line, the narrative, the outlook, and every risk note contain none of `from strategy_recommendation`, `via recommend_strategy`, `via build_strategy_layer`, `data_freshness is`, `:score is 0`, `payoff_grid`, `measured True`, or the injected figure. The ledger still holds those rows and the rejection is still logged.
- `test_fallback_is_short_and_names_the_strategy_once[MDB]` and `[NFLX]` — the fallback is at most three sentences, has no newline, names the selected strategy at most once, and passes `check_narrative` on re-check.
- `test_rejected_narrative_falls_back_to_the_selected_strategy_sentence` — the fallback carries a `why_it_fits` sentence from the selected strategy's knowledge-base entry and `The composite is 58 with IV 42 percent.`, and none of the dump markers.
- `test_fallback_without_a_strategy_does_not_quote_the_ledger` — with no `strategy_id`, the fallback still refuses to quote ledger rows.

All six fail on `297104c` with the old `_fallback` and pass after the change (verified by stashing the production diff).

No existing test was edited or weakened. `tests/test_change12_2a.py::test_long_leg_spans_earnings_names_the_leg_and_date` now passes on the real generated sentence instead of the dump, because the front/back IV ratio is recorded.

## Results

From `/Users/Mayank/Desktop/APEX-change12-4A/backend`, outside the sandbox, with `/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`:

**1741 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). Exit code 0. Elapsed 71.8s. Baseline on this branch was 1735 passed / 59 skipped; the six new tests account for the difference.

## Not verified in a browser

This worktree has no `frontend/node_modules`, and the only running backend on port 8000 is the main checkout, which is off limits for this task. The card payload was verified at the API boundary instead: `build_strategy_layer` was driven with MDB-like Collar and NFLX-like Long Call inputs and every user-facing string on the returned layer was asserted free of ledger text. The frontend was not changed.

## Sources

- `backend/app/services/narrative_guard.py`, `backend/app/services/strategy_engine.py`.
- `backend/app/strategies/knowledge_base.py` (`_template` builds `summary` as `f"{name}. {formula}"`).
- `backend/app/services/evidence_ledger.py` (`record_gate`, `record_score`, `record_card_value` provenance fields).
- `docs/changes/change-12/agent-3A.md` open question on the fallback's fact lines.
