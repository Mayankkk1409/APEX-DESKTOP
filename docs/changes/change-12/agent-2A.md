# Change 12 — agent 2A

Branch: `change12/2A` from `change12/base` at `51dbcf9c24269a242ce892b5d8fa375c1360886f`.
Worktree: `/Users/Mayank/Desktop/APEX-change12-2A`.
Spec: C2, C3, C4, C5, C6b.
Contracts file was not edited. Frontend files were not edited. Composite weights were not changed.

## Root causes

- `backend/app/analysis/gate_config.py:213` (base). `classify_vol_regime` sold premium only when IV rank was above 50 and IV was not below HV, and it bought premium whenever IV was merely below HV. A 9.93-point rich gap with IV rank 43.2 returned `fair`. There was no ±5 point rule, no stated verdict, and no inversion test.
- `backend/app/services/strategy_recommendation.py:238` (base). `vol_regime_phrase` returned that same rank-first label whenever IV rank was present, so the card could say fair while 30-day ATM IV was 30.31% and HV was 20.38%.
- `backend/app/services/strategy_recommendation.py:426` (base). Candidate ranking treated IV as cheap only when HV exceeded IV by more than 10 points, treated a `sell_premium` signal or IV rank above 50 as rich even when IV was below HV, and applied no long-vega penalty.
- `backend/app/services/strategy_recommendation.py:225` (base). `format_iv_rank` returned a bare em dash for a missing rank, with no reason.
- `backend/app/services/strategy_engine.py` (base `build_strategy_layer`). The fit text did not name a sentiment conflict, an event-spanning long leg, or a DTE window miss. A user expiry outside the how-to window was left in place with no penalty sentence.
- `backend/app/contracts.py:82`. `ledger.record` drops the entry. The engine calls it. Persistence is not implemented here.

## Changes

One assessment, `assess_vol_regime` in `gate_config.py`, is what `classify_vol_regime`, `vol_regime_phrase`, candidate ranking, and `build_strategy_layer` use.

- Primary test: IV minus HV. More than 5 points below is buy premium (`IV much below HV`). Within ±5 is fair (`IV near HV` in the verdict; the card label stays the word `fair`). More than 5 points above is sell premium. The card label for that case is `IV much above HV` unless IV rank is the tie-break, in which case the short label is shown.
- `classify_vol_regime` still returns exactly `sell premium`, `buy premium`, or `fair`. `volatility_intel.py` maps those three strings and is owned by 1C.
- IV rank is the tie-break only when the primary band is near and rank is outside 30–50, or when primary and rank are opposite extremes. Rank 43.2 does not override a 9.93-point rich gap. AAPL 30.31% versus 20.38% is rich.
- Front IV at least 1.25 times back IV is inversion, its own condition (`term_structure_inversion`, using the existing settings default 1.25). It does not by itself flip the IV-versus-HV label.
- The verdict states both inputs, the ratio, the rank, the inversion condition, and the rule sentence. Those strings are placed on `vol_regime` and `why_it_fits`.
- A long-vega name in a sell-premium regime loses `VEGA_LONG_IN_RICH_PENALTY` (6 points) and gets a `Long-vega penalty:` note. A diagonal, calendar, or APEX Strategy / Gamma Trampoline is exempt when the term structure is inverted. The aggressive profile does not pull a penalized long-vega name ahead of income.
- When the short expiry is before earnings and a long expiry is after, `why_it_fits` names the long leg, the short leg, the earnings date, and the long-leg IV premium over HV in vol points. HV is the normal IV used for that premium. The sentence is not added when a short leg also expires on or after the event. The point value is stated on the card. It is not subtracted from the rank score, because `strategy_decision` selects the name before the legs exist.
- DTE windows are read from a knowledge-base `dte_window` or `dte_min`/`dte_max` when 2C adds them, otherwise from how-to text, otherwise from the playbook. Married Put / Protective Put uses the playbook line "30–45 DTE". If contracts exist on a listed expiry inside the window, the candidate is rebuilt on the expiry nearest the window midpoint and `why_it_fits` says which expiry it uses. If no contract sits inside the window, the card states a DTE penalty, the how-to range, and the nearest listed date. It does not invent a quote. AMD at 0 DTE with only a same-day contract takes that penalty path.
- A sentiment conflict names the score, the 15% sentiment weight, the 30% technical weight, and why the technical direction prevailed. Outlook appends `, low conviction` when `direction_margin` is below `DIRECTION_CONVICTION_MARGIN` (8). The margin is technical score × 0.30 minus sentiment score × 0.15. Pillar weights are unchanged.
- In a rich regime with an earnings context, a Collar is scored against an eligible Married Put or Long Put. The risk note says which name ranked first and both scores. The collar replaces the winner only when the current winner is that long-put hedge and the collar scores higher.
- Every gate, candidate, score, and the rank call `ledger.record` through `record_ledger`. The stub drops them.
- Missing IV rank on strategy text is `IV rank unavailable: {reason}`, using `iv_rank_gap` when the vol layer has one.

## Tests

New: `backend/tests/test_change12_regime.py` and `backend/tests/test_change12_2a.py`.
The second file repeats the AAPL, near-band, missing-rank, AMD, sentiment, and collar cases, and adds the IV-rank tie-break, the inversion waiver, ledger kinds, and the five long-leg earnings names (MSFT, TSLA, VZ, META, HD).

- AAPL inputs 0.3031 versus 0.2038, rank 43.2, classify as rich. Card `vol_regime` is `IV much above HV`. Verdict shows 30.31%, 20.38%, and the rule.
- A 4.5-point gap (0.27 versus 0.225, rank 46.05) stays `fair`.
- Long leg spans earnings: event-vega sentence names the long put, both expiries, and the earnings date.
- AMD at 0 DTE on a Married Put does not pass the 30–45 DTE how-to silently. The note names 0 DTE, the window, and the nearest compliant expiry.
- Bullish sentiment 73 on a bearish structure names the conflict, the score, weight 15%, and low conviction.
- Missing IV rank is not the string `IV rank —`.
- A rich-IV hedge records a Collar and a rank ledger entry.

Updated expectations in 2A-owned tests:

- `test_strategy_coverage.py`: mild bear and mild bull, rich IV, back month, aggressive, now select Short Iron Condor. The long-vega diagonal is penalized and is not pulled ahead.
- `test_strategy_engine.py`: IV 0.20 versus HV 0.35 is buy premium, so a `sell_premium` signal does not make the iron condor eligible. Conservative selects Married Put; aggressive and moderate select Bull Call Spread. The iron-condor allowlist is checked on a rich pair (IV 0.40, HV 0.22).

## Results

Full backend suite, from `/Users/Mayank/Desktop/APEX-change12-2A/backend`, using the origin venv:

`1547 passed, 59 skipped, 0 failed`.

Phase 1 after integration was 1530 passed, 59 skipped, 0 failed. The two new files collect 17 tests. 1530 + 17 = 1547. Nothing failed and nothing new was skipped.

## Sources

- Spec C2–C5 and C6b, and PLAN.md Phase 2 section 2A.
- Frozen `VolRegime` and `Ledger` in `backend/app/contracts.py`.
- Existing weights in `APEX_COMPOSITE_WEIGHTS` (technicals 0.30, sentiment 0.15).
- Existing inversion setting `gamma_front_back_iv_ratio_min` default 1.25 in `config.py` (not edited).
- Playbook how-to for Married Put: "Buy a put slightly OTM at 30–45 DTE."
- 1D card tests that require the near band to display exactly `fair`, and that forbid `2026-10-30` in `risk_notes` when the earnings date is absent.

## Open questions

- The spec does not give a number for the long-vega penalty. 6 points is the configured amount. The aggressive reorder also refuses to promote a name that already carries the penalty note, which is what moves the two coverage cells off the diagonal.
- "Normal IV" for the event-vega premium is HV. If 1C later publishes a different normal-IV field, the penalty should use that field.
- The direction margin is the technical pillar contribution minus the sentiment pillar contribution. It is not a new weight. The low-conviction line is 8. A technical score of 55 and a sentiment score of 73 produce a margin of 5.55, which is below 8.
- A DTE miss with contracts already listed inside the window rebuilds the candidate onto the nearest compliant expiry and says so. A listed date with no contract is a stated penalty only. AMD 0 DTE is that second case in the tests.

## Requests for other owners

- **2B.** `contracts.ledger.record` still drops the entry and `get` returns `[]`. 2A calls `record` for the regime value, each gate, each candidate, each score, and the rank. Please persist those entries in `evidence_ledger.py`. Do not reimplement `canAutoExecute`.
- **Scan owner (`scan_engine.py`, 1D).** The event-vega point value is written on the card after legs are built. It does not change which name `strategy_decision` ranks first. Passing the short expiry, long expiry, long-leg IV, and earnings date into the decision would let the penalty affect rank. That file is not edited here.
- **2C.** Please put `dte_min` / `dte_max` (or `dte_window`) and `vega_sign` on each knowledge entry. The engine already reads those attributes when they exist. Until then it parses how-to text and the playbook. Married Put's 30–45 day window is the playbook sentence, not a knowledge-base field.
- **1C.** `volatility_intel._iv_hv_signal` (`volatility_intel.py:463`) still treats more than 10 points as rich or cheap and labels 6–10 points `between_bands`. The strategy card now uses 5 points. `classify_vol_regime` still returns `sell premium` / `buy premium` / `fair` because `_regime_signal` maps those exact words. The IV-versus-HV card body still says ">10 pts rich". That copy is in a 1C file and was not changed.
- **Frontend.** `VolatilityScan.tsx` `fmtNum` still renders a null IV rank as a bare dash. `ivHistoryHint` is often undefined, so the dash can appear with no reason. Strategy-card strings are on the existing API fields (`vol_regime`, `why_it_fits`, `outlook`, `risk_notes`). No frontend file was edited.
