# Change 12 Phase 3 status

Written before the four worktrees branched from `change12/base`. Subagents skip an item marked DONE and only verify it. They do not reimplement it.

The last recorded full backend suite, from the Phase 3 closeout note, was **1659 passed, 59 skipped, 0 failed**. This status file does not claim a new suite run.

## (a) Narrative check on all card text — DONE

`build_strategy_layer` sends why-it-fits, how-to-use, risk notes, the summary, the status line, and the outlook through `check_narrative`. Risk Review copies that status line as `auto_exec_line`. A rejected token falls back to the guard result. Rejections are logged by `narrative_guard`.

Tests already in `backend/tests/test_change12_phase3.py`: `test_generated_card_text_passes_the_ledger_check`, `test_invented_card_number_is_rejected_and_logged`.

**3A verifies** every text path, including an injected fake number and an AAPL card with zero unmatched tokens. 3A does not edit `strategy_engine.py`. If a sentence is still unguarded, list the file and the sentence under Requests for other owners.

## (b) One volatility rule — DONE

`volatility_intel._iv_hv_signal` calls `assess_vol_regime`. The band is ±5 vol points. There is no 10-point rich/cheap band. Inversion remains front IV at least 1.25 times back IV. IV rank is the tie-break inside `assess_vol_regime`.

Test already present: `test_five_point_band_replaces_the_ten_point_band`.

**3B verifies** IV 30.31% versus HV 20.38% is rich on both the volatility layer and the card, and verifies the ±5 boundaries. Do not change the band.

## (c) Event-vega penalty in ranking — DONE

`_apply_event_vega_penalty` subtracts the measured long-leg IV premium, in vol points, before rank, and records `event_vega_penalty` on the ledger. If the premium cannot be measured, no number is invented and nothing is subtracted.

Tests already present: `test_event_vega_penalty_changes_the_first_name`, `test_event_vega_penalty_is_on_the_score_ledger`.

**3B verifies** MSFT, TSLA, VZ, META, and HD rank lower when only the long leg spans earnings, and that the penalty is visible in the score breakdown. Add that test if it is missing. Do not invent the IV premium.

## (d) Phase 1 fixes — code DONE, frontend suite NOT green

Done in code and recorded in `docs/changes/change-12/integration-phase-1-fixes.md`:

- A priced quote with no timestamp is not fresh on the order path (`executability.quote_problem`).
- `contracts.canAutoExecute` delegates to `executability.can_auto_execute`.
- `skip_quote_check` is not a parameter of `execute_market_fill`.
- The 59 skipped backend tests are listed in that file. The skip count matches the Phase 1 baseline.
- Alpaca in this checkout is the paper Trading API, options feed `indicative`. Algo Trader Plus is $99/month and was not purchased.

Frontend `npm test` on 5 October 2026: **301 passed, 1 failed**. The failure is `src/pages/DeepScan.order.test.tsx` › `shows Place Trade below the saved minimum`. The screen shows `score 39.0` and `minimum 40.0`. The test still expects `score 39` and `minimum 40`. The assertion was not weakened.

**3C** fixes that frontend assertion to the shared one-decimal formatter, re-runs the full frontend suite, and verifies the three order-path items. 3C does not reopen the 300-second cap or the spread cap.

## Not done — leave these to 3D and the merge

- Gate-by-gate Gamma Trampoline explanation for JPM, GS, C, JNJ, UNH, BAC, WFC, MS, BLK, and PLD.
- Sub-score distribution and the calibration proposal. Weights stay unchanged.
- QA replay regression green on the merged tree.
- Before/after table for the 50 QA rows and the Part E PASS/FAIL table.
- Final `REPORT.md`. A draft may exist. It is not the final report.

## Do not revert

The phase3 WIP commit feeds Gamma Trampoline from data the scan already has: back-chain ATM IV when the vol layer has no back IV, average volume as ADV, and an estimated earnings date kept as estimated instead of erased by a second estimate. The eight-report history gate still fails closed when history is absent. Do not invent those eight moves. Do not revert this wiring.
