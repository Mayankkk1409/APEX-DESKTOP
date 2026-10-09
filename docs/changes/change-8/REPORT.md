# Change 8 — Always recommend the structure the legs actually are

Every scan keeps one real, executable strategy. Score, IV versus HV, earnings proximity, and spread width are warnings beside that recommendation. They do not rename it, hide it, or replace it.

## Root cause

### A and B — Bull put and long call labeled as a veto

`recommend_strategy` in `backend/app/services/strategy_recommendation.py` returned `NO TRADE — Wait for IV Crush` from the IV gate, and `NO TRADE — Insufficient Conviction` from earnings, a wide spread combined with that gate, stale quotes combined with that gate, or an empty matrix. `strategy_decision` in `backend/app/services/strategy_engine.py` rewrote the insufficient-conviction label to the all-caps form.

`build_strategy_layer` then kept that veto as `selected_strategy`, `what_is_this`, `why_recommended`, and `how_to_execute` (including “Stand aside” and “Extreme IV overhang”) while still building legs from `leg_structure`. The AAPL legs were already a bull put credit spread. The MSFT leg was already a long call. The card title did not describe those legs.

A composite at or below 50 took a second path in `build_strategy_layer` and replaced the ranked name with “Not tradeable in current situation” and empty legs.

### C — IV versus HV

`extreme_iv_overhang` is true only when both readings are real and IV is above 1.35× HV. 0.2334 / 0.224578 is about 1.04, and 0.2549 / 0.216802 is about 1.18, so that function does not fire for those pairs. The card still showed the crush title because an earlier gate had already replaced the name, and `_vol_citation` printed the raw fractions (`IV 0.2334 versus HV 0.224578`) instead of percentages.

Even a true reading above 1.35× HV used to replace the Best Match. It is now only a risk note. IV and HV on the strategy card are percentages to two decimals (23.34%, 22.46%).

### D — Evaluation count

`_attach_registry_evaluation` returned `len(STRATEGY_REGISTRY)`, which is 100 and includes two advisory entries with no legs (`no_trade_insufficient_conviction`, `no_trade_wait_iv_crush`). Those names were also appended as ranked misses. `strategies_evaluated` is now `real_strategy_count()` (98). Advisory entries are skipped and are not candidates.

### E — 66 versus a saved minimum of 40

`allows_auto_execution` already uses `composite >= auto_exec_threshold`. It never compared the numbers as strings. It returned false first because `is_defined_risk_strategy` rejected any name containing the veto label, so a score of 66 never reached the comparison with 40. The risk-review payload then set `defined_risk` false, and the order panel did not arm acknowledgement.

The displayed name is now the real structure. Defined-risk and `composite >= threshold` arm acknowledgement when the global toggle is on. The card line is `Composite score 66 · Your auto-execute minimum 40 · Auto-execute eligible`. Toggle off still shows the structure and an enabled Place Trade, with the note “Auto-execution is off.” Below the saved minimum, Place Trade stays enabled and the note is `Manual confirmation required (score X vs. your auto-execute minimum Y).` A pre-trade validation failure keeps the structure name and states the check that failed.

## Labels for the two examples

- AAPL sell 322.5 put / buy 320 put: **Bull Put Spread (credit)**. Credit $0.44, max profit $44, max loss $206, breakeven 322.06.
- MSFT buy 515 call: **Long Call**. Debit $11.07, max loss $1107, max profit Unlimited, breakeven 526.07.

The name comes from the legs when they match a registry structure (`structure_name_from_legs`). Playbook text is used when that name already has it. A single long call has no playbook essay, so “How to execute” is the factual line from the leg (`Buy the 515 call, expiring …`).

## How 66 versus 40 is decided

`allows_auto_execution` and the frontend `autoSubmitArms` both use numeric `>=` against the saved minimum. 66 >= 40 is eligible when the structure is defined-risk. Acknowledgement auto-submits only when the global toggle is also on. The toggle does not change the recommended name.

## Files

- `backend/app/services/strategy_recommendation.py` — one real Best Match; IV, earnings, spread, and stale quotes are `risk_notes`; evaluation count excludes advisory entries.
- `backend/app/services/strategy_engine.py` — label from the legs; percent IV/HV; no score band that blanks the structure; validation names the failed check.
- `backend/app/services/scan_engine.py` — auto-submit uses the displayed name and the saved minimum.
- `backend/app/services/options_analysis.py` — an advisory label is not a chain selection; a supplied real strategy still highlights a contract.
- `frontend/src/components/StrategyScan.tsx` — structure, payoff, risk notes, eligibility line.
- `frontend/src/pages/DeepScan.tsx` — eligibility line and Acknowledge versus Place Trade.
- `frontend/src/lib/riskReview.ts` — `>=` placement, toggle-off note, eligibility line.
- `frontend/src/lib/strategyDisplay.ts` — dropped the veto label helper.
- Tests listed below.

The encyclopedia registry still contains the two advisory display names so the 100-entry catalog stays intact. They are not ranked, not counted, and not returned as the Best Match.

## Tests

- `backend/tests/test_strategy_engine.py` — AAPL bull put payoff and label; MSFT long call with Unlimited max profit; IV 0.2334/0.224578 does not retitle the structure; score below the minimum keeps the structure. Full file passed.
- `backend/tests/test_auto_execution_threshold.py` — 66 >= 40 arms; below the minimum does not; veto phrases absent from `backend/app/services` and `frontend/src` (tests excluded).
- `backend/tests/test_apex_upgrade.py`, `tests/test_structure_payoff.py` (evaluated count 98), `tests/test_strategy_registry_validation.py`, `tests/test_options_analysis.py`, `tests/test_integration_scan.py` — 165 passed together with the two files above.
- `tests/test_iron_condor_msft_regression.py`, `tests/test_platform_trade_card_invariants.py`, `tests/test_all_100_strategies.py` — 632 passed, 15 skipped.
- Frontend vitest: `scanSlides.test.tsx`, `riskReview.test.ts`, `strategyDisplay.test.ts`, `optionsChain.test.ts`, `OptionsChainGreeks.test.tsx` — 60 passed.

This session had no browser runner, so the Deep Scan card was not clicked in a live window. The strategy slide and the risk-review placement helper were covered by the vitest render tests.
