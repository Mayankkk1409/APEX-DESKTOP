# Change 12 — agent 3B

Branch: `change12/3B` from `change12/base` at `8e58381d7942dcedaf68db65f8d4ab46ce287b05` (`phase3 WIP`).
Worktree: `/Users/Mayank/Desktop/APEX-change12-3B`.
Spec: C2, C3, C6b. Phase 3 status items (b) and (c).

Items (b) and (c) were already marked DONE. The existing phase 3 tests were not rewritten. The ±5 rule in `assess_vol_regime`, the volatility-layer signal, the card label, and the pre-rank subtraction were verified and left in place. Composite weights were not changed. The Gamma Trampoline gate notes from the phase 3 WIP commit were not reverted. `_guard_strategy_card` and `check_narrative` were not removed or bypassed.

## Root causes

- `backend/app/services/volatility_intel.py:330` (before this commit). `resolve_recommended_contract` still compared ATM IV minus HV with `DEFAULT_THRESHOLDS.iv_hv_rich_pts` (`options_rules.py:66`, value `0.10`). That is the 10-point band. A gap of 9.93 vol points, including IV 30.31% versus HV 20.38%, stayed `fair` on this fallback. `build_volatility_payload` already called `assess_vol_regime`.
- `backend/app/services/strategy_engine.py:1272` (before this commit). The volatility score-breakdown note still said `between bands`, the name of the removed 6-to-10-point band. The signal value itself already came from `assess_vol_regime`.
- `backend/app/services/strategy_recommendation.py:638` (before this commit, `_apply_event_vega_penalty`). The measured long-leg premium was subtracted from the score and stored as a gate note and a ledger sentence. The candidate had no score-breakdown row, and no test showed MSFT, TSLA, VZ, META, and HD leaving the top score with that row visible.
- `backend/app/analysis/gate_config.py:17` and `gate_config.py:283`. `IV_MISMATCH_VOL_POINTS` is `5.0`. `_primary_view` treats a gap of more than 5 as rich or cheap and a gap of exactly 5 as near. `gate_config.py:261` treats front IV of at least `gamma_front_back_iv_ratio_min()` (1.25) as inversion. IV rank breaks a disagreement inside `assess_vol_regime` (`gate_config.py:389`). These lines were already correct and were not edited.

## Changes

- `resolve_recommended_contract` now takes its rich, cheap, or fair signal from `assess_vol_regime`. The 10-point threshold is not used on that path.
- The volatility score-breakdown note names `IV much below HV / fair / IV much above HV`.
- `StrategyCandidate.score_breakdown` records the event-vega row. When the long-leg IV premium over normal IV can be measured, the row's `value` is that premium in vol points, and `score_before` / `score_after` show the subtraction that happens before rank. When the premium cannot be measured, `value` is null and the score is unchanged. No substitute number is written.
- The same row is copied onto the recommendation API and onto the ledger score inputs (`breakdown` and `points`).
- A candidate that is copied or replaced keeps its breakdown.

## Tests

New: `backend/tests/test_change12_3b.py`.

- One rule: the band constant is 5, the rule text does not say 10, inversion is true at 1.25 times and false at 1.249 times, and `resolve_recommended_contract` no longer mentions `iv_hv_rich_pts`.
- IV 30.31% versus HV 20.38% is `sell_premium` on `_iv_hv_signal`, `IV much above HV` on the card, and the desk card says more than 5 vol points. IV rank 43.2 does not break that rich gap.
- Exact boundaries: a displayed gap of 5.00 stays `fair` on the layer and the card. 5.01 is rich. −5.00 stays `fair`. −5.01 is cheap. A 1-point gap with IV rank 62 is the rank tie-break.
- MSFT, TSLA, VZ, META, and HD: earnings after the short expiry and before the long expiry. Long-leg IV is read from the contract passed in, not from a stored penalty. Each bullish diagonal is tied for the top score without the span, then drops by the measured premium and finishes strictly below the top score. The breakdown, the API payload, and the ledger `event_vega_penalty` row all show that premium.
- The same MSFT window with no long-leg IV and no normal IV does not change the score. The breakdown value is null and the note says the premium could not be measured.

## Results

Full backend suite, from `/Users/Mayank/Desktop/APEX-change12-3B/backend`, using `/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python`, outside the sandbox:

`pytest -q --tb=line`

**1715 passed, 59 skipped, 0 failed** in 780.13s.

The phase 3 status file recorded 1659 passed and 59 skipped before these worktrees, and it did not claim a suite run of the phase 3 WIP commit. This run includes that WIP plus the five tests in `test_change12_3b.py`. The skip count is still 59. Nothing failed.

## Sources

- Spec C2, C3, and C6b. Phase 3 status items (b) and (c).
- `IV_MISMATCH_VOL_POINTS = 5.0` in `backend/app/analysis/gate_config.py`.
- `gamma_front_back_iv_ratio_min` default 1.25 in `backend/app/config.py`.
- Existing phase 3 tests `test_five_point_band_replaces_the_ten_point_band`, `test_event_vega_penalty_changes_the_first_name`, and `test_event_vega_penalty_is_on_the_score_ledger`.
- QA dates already used for these five names in `backend/tests/test_change12_2a.py`.

## Open questions

- Normal IV is the `normal_iv` value on the event span. The scan passes HV. This commit does not invent a different normal IV.
- On a fair-vol bullish book the bullish diagonal ties Married Put for the top score, because both receive the same +2 bonus. The penalty drops the diagonal out of that tie. It does not by itself choose a new family when every eligible name is a time spread and all of them share one measured premium.
- The APEX Composite Score slide is built in `scan_engine.py`, which this agent does not edit. The rank breakdown is on the candidate and the ledger. It is not yet a row in that slide's volatility section.

## Requests for other owners

- **Options owner (`backend/app/services/options_analysis.py:418`).** When ATM IV and HV are both present, this path still sets the vol signal from `thresholds.iv_hv_rich_pts` (10 vol points). A 9.93-point gap stays fair there. Please call `assess_vol_regime` for that signal. The separate catalyst check at `options_analysis.py:475` also uses `iv_hv_rich_pts` to arm the vega cap. That file is outside this agent's file list.
- **Scan owner (`backend/app/services/scan_engine.py`).** `build_apex_score_layer` does not receive `StrategyCandidate.score_breakdown`. Please pass the measured event-vega row into the volatility section breakdown so the score slide shows the same points the rank ledger already stores. Do not change composite weights.
