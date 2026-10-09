# Change 12 — agent 3A

Branch: `change12/3A`. Worktree: `/Users/Mayank/Desktop/APEX-change12-3A`. Started from `change12/base` via `8e58381` (`phase3 WIP`).

Item (a) in `docs/changes/change-12/phase3-status.md` is marked DONE. It was verified. `narrative_guard.py` was not rewritten. Matching was not loosened. Score weights, the 300-second quote cap, and the spread cap were not changed.

## Root causes

The card used to return generated prose that had never been compared to the ledger. The check that closes that gap is already on this branch:

- `backend/app/services/narrative_guard.py:182` `check_narrative` extracts numbers, percentages, dates, and tickers. A token that is not on the ledger, or a `high` / `low` / `rich` / `cheap` claim that does not cite a ledger value and a ledger threshold in the same sentence, rejects the text.
- `backend/app/services/narrative_guard.py:287` `_remember` appends the rejection and logs `narrative rejected` with the unmatched tokens.
- `backend/app/services/narrative_guard.py:292` `_fallback` fills the knowledge-base title, summary, why-it-fits, how-to-use, and key-risks template from ledger keys, then keeps only sentences that themselves pass, then appends ledger fact lines that pass. If nothing remains, the text is the fixed rejection sentence at line 317.
- `backend/app/services/strategy_engine.py:3168` `_guard_card_text` is what `build_strategy_layer` uses. `_guard_strategy_card` at line 3182 sends why-it-fits, how-to-use, each risk note, the summary, the status line, and the narrative through that function. Outlook is sent at line 3916. The status line is `eligibility_sentence`, stored as `auto_exec_line` at line 3944.
- `backend/app/services/scan_engine.py:845` `build_layers` copies that status line onto the Risk Review layer as `auto_exec_line`.

On the AAPL Long Put card used in the proof (composite 59.0, expiry 2026-10-30, IV 30.31, HV 20.38), those fields were the strings passed to `check_narrative`, and each one came back with an empty unmatched list and an empty qualitative list. The build logged no rejection, so the displayed sentences are the generated ones, not a fallback.

## Changes

No production file was edited. `backend/app/services/narrative_guard.py` and `backend/tests/test_narrative_guard.py` are unchanged.

- `backend/tests/test_change12_3a.py` — proof for item (a).
- `docs/changes/change-12/agent-3A.md` — this note.

## Tests

`backend/tests/test_change12_3a.py`:

- `test_injected_fake_number_is_rejected_on_every_guarded_text_path` — `999.9` is injected into why-it-fits, how-to-use, the risk note, the summary, the Risk Review status line, the narrative, and the outlook. Each path logs a rejection, drops `999.9`, and returns the Long Put knowledge-base template plus the ledger fact `composite is 59`. The same figure injected through `build_strategy_layer(..., risk_notes=...)` does not appear on the AAPL card.
- `test_unmatched_percent_date_and_ticker_fall_back_on_every_path` — `99.9 percent`, `1999-01-01`, and `ZZZZ` take the same seven paths and the same fallback.
- `test_aapl_strategy_layer_card_has_zero_unmatched_tokens` — the AAPL strategy-layer card's why-it-fits, how-to-use, risk notes, summary, Risk Review line, narrative, and outlook are arguments to `check_narrative` and have zero unmatched tokens.

Existing `tests/test_narrative_guard.py` and `tests/test_change12_phase3.py` still pass. They were not edited.

## Results

Command, from `/Users/Mayank/Desktop/APEX-change12-3A/backend`, using `/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python` (this worktree has no `.venv`):

`python -m pytest -q --tb=line`

**1715 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py`). Exit code 0. Elapsed 1233.87s. The skip count matches the Phase 1 baseline and `phase3-status.md`.

`phase3-status.md` records an earlier full run of 1659 passed, 59 skipped, 0 failed, and says that file does not claim a new suite run. This run is the suite on `change12/3A` after the five tests in `test_change12_3a.py`. The suite was not run on `8e58381` before those tests were added.

## Sources

- `docs/changes/change-12/phase3-status.md` item (a).
- `docs/changes/change-12/SPEC.md` D4 (zero unmatched narrative numbers) and the strategy-card / Risk Review sentences in A1 and A4.
- `docs/changes/change-12/PLAN.md` section 2B (post-generation check, knowledge-base fallback, rejection log).
- `backend/app/services/narrative_guard.py` and the call sites in `backend/app/services/strategy_engine.py` (read, not edited).
- `backend/tests/test_narrative_guard.py` and `backend/tests/test_change12_phase3.py`.

## Open questions

- Knowledge-base templates on this branch do not use `{key}` placeholders. `_fill_placeholders` still substitutes them when a template has them. The fallback that the tests observe is the template sentences that pass, plus fact lines such as `composite is 59 from strategy_layer via build_strategy_layer.`
- `strategy_engine._guard_card_text` calls `check_narrative`, and if the full text fails it checks the text again with catalog sentences removed. When that remainder passes, line 3178 returns the original text, including whatever made the first check fail. The AAPL Long Put card did not take that branch (no rejection was logged). Whether a catalog sentence with a figure that is not on the ledger should stay on the card is a strategy-engine decision.
- The 56-test gap versus the recorded 1659 was not bisected. The skip count did not change.

## Requests for other owners

These sentences are still not passed through `check_narrative`. They were not edited here.

- `backend/app/services/strategy_engine.py` `build_strategy_layer` returns `equity_note` (line 3935), `selection_rationale` (line 3941), `hard_block_reasons` (line 3948), `spread_block_reasons` (line 3949), and `block_reason` (line 3950) from the pre-guard strings. The risk-note copies of the block sentences are guarded. The fields above stay the originals, so a fallback that replaces a risk note leaves the original on `spread_block_reasons` and `block_reason`. `auto_exec_reasons` (line 3946) is also returned without a check.
- `backend/app/services/strategy_engine.py` `_guard_card_text` (line 3178) can return the original text after `check_narrative` has rejected it, when the non-catalog remainder passes.
- `backend/app/services/strategy_recommendation.py` `selection_rationale_for` (line 882) builds a sentence with the technical score. That sentence is concatenated into why-it-fits before the guard, and it is also stored on `selection_rationale`, which the strategy slide renders on its own. A rejected why-it-fits does not replace this field.
- `backend/app/services/stock_leg.py` `plan_stock` (lines 215–229) writes the holdings note (`Uses N of your N shares`, cost basis in dollars). `apply_equity_holdings` (line 353) stores it as `equity_note`. The strategy card and Risk Review both show that note.
- `backend/app/services/scan_engine.py` `build_layers` (lines 625–626) appends `Pre-trade check equity_leg_required: ...` onto `risk_notes` after `build_strategy_layer` has already guarded the list.
- `backend/app/services/scan_engine.py` `_restore_scored_strategy_layer` (lines 1002–1005) rewrites `why_it_fits` and `why_recommended` after the guard when the real composite is restored. The new composite sentence is not checked.
- `backend/app/services/scan_engine.py` `build_layers` Risk Review `narrative` (lines 840–843) is a fixed sentence and is not passed through `check_narrative`. It has no figures. The eligibility sentence on that layer is the guarded `auto_exec_line` (line 845).
- `frontend/src/pages/DeepScan.tsx` risk-review render composes `Quote not current. Quoted {timestamp}` and the options-execution leg-count sentence. `frontend/src/lib/orderTicket.ts` `optionsLegBlockReason` returns `block_reason` before the guarded risk notes.
