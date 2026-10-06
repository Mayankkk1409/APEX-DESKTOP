# Change 12 — agent 3D

Branch: `change12/3D` from `change12/base` at `8e58381d7942dcedaf68db65f8d4ab46ce287b05`.
Worktree: `/Users/Mayank/Desktop/APEX-change12-3D`.
Production code was not edited. `REPORT.md` and `phase3-status.md` were not edited. Weights were not changed. No chain was fabricated. The eight historical earnings moves were not invented.

## What the scripts check

`backend/scripts/explain_change12_gamma.py` reads the evaluation ledger on the QA fixture for JPM, GS, C, JNJ, UNH, BAC, WFC, MS, BLK, and PLD. Each Gamma Trampoline™ gate is printed with the measured value and the threshold taken from that ledger sentence. A missing front-week IV or IV rank is labeled `data_defect` ("not a strategy verdict"). A missing eight-report history is `fail_closed` and the script says the moves were not invented. If a snapshot has no ledger rows, or the ticker is absent, the script says so. It does not fill a gate the ledger did not record.

On this fixture every one of the ten has a candidate row and was not selected (score 0.0). The history gate fails closed on all ten. IV rank is present on all ten (100, or 97.1 on MS), so none of these ten is a data defect.

| Ticker | Best match | Window | IV rank | Front/back | ADV | Structure | Open interest | Spread | History |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| JPM | Calendar Spread | 8, inside 5–10 | 100, above 70 | 1.64, at least 1.25 | 19,163,627, above 5,000,000 | listed | absent | absent | absent, not invented |
| GS | Collar | 8, inside 5–10 | 100, above 70 | 1.11, below 1.25 | 3,391,601, not above 5,000,000 | listed | 27, not above 1,000 | 99.8% of mid, not below 8% | absent, not invented |
| C | Bear Call Spread (credit) | 8, inside 5–10 | 100, above 70 | 1.24, below 1.25 | 25,296,259, above 5,000,000 | listed | 124, not above 1,000 | 166.7% of mid, not below 8% | absent, not invented |
| JNJ | Short Iron Condor | 8, inside 5–10 | 100, above 70 | 1.09, below 1.25 | 6,429,776, above 5,000,000 | listed | absent | absent | absent, not invented |
| UNH | Collar | 8, inside 5–10 | 100, above 70 | 1.10, below 1.25 | 2,988,379, not above 5,000,000 | listed | 87, not above 1,000 | 38.5% of mid, not below 8% | absent, not invented |
| BAC | Short Iron Condor | 9, inside 5–10 | 100, above 70 | 1.07, below 1.25 | 63,916,242, above 5,000,000 | listed | 31, not above 1,000 | 133.3% of mid, not below 8% | absent, not invented |
| WFC | Bear Call Spread (credit) | 9, inside 5–10 | 100, above 70 | 1.03, below 1.25 | 45,188,941, above 5,000,000 | not listed | absent | absent | absent, not invented |
| MS | Collar | 9, inside 5–10 | 97.1, above 70 | 1.01, below 1.25 | 11,268,646, above 5,000,000 | not listed | absent | absent | absent, not invented |
| BLK | Collar | 9, inside 5–10 | 100, above 70 | 1.07, below 1.25 | 684,063, not above 5,000,000 | listed | absent | 123.7% of mid, not below 8% | absent, not invented |
| PLD | Collar | 10, inside 5–10 | 100, above 70 | 1.30, at least 1.25 | 2,953,478, not above 5,000,000 | listed | 853, not above 1,000 | absent | absent, not invented |

`backend/scripts/report_change12_subscores.py` reads the same fixture (or another captured JSON path) and the 50 tickers in `docs/qa/APEX_QA_Test_Results.csv`. It reports technical, volatility, Greeks (`options`), sentiment, and fundamental. A missing pillar is printed as absent and is left out of the mean. Weights are read from `APEX_COMPOSITE_WEIGHTS` and are not written.

Captured distribution (population stdev, n=50, absent=0 on every pillar):

| Pillar | Mean | Population stdev | Min | Max | Distinct at 1 decimal |
| --- | --- | --- | --- | --- | --- |
| technical | 73.59 | 4.86 | 63.00 | 81.00 | 40 |
| volatility | 72.30 | 3.29 | 55.00 | 80.00 | 3 |
| greeks | 40.75 | 1.72 | 40.00 | 47.80 | 15 |
| sentiment | 54.97 | 12.96 | 22.60 | 76.70 | 50 |
| fundamental | 74.68 | 12.28 | 40.30 | 95.00 | 45 |

Proposal, printed by the script and not applied: leave the weights as they are (technicals 30%, volatility 25%, options 20%, sentiment 15%, fundamentals 10%, risk 0% advisory). Technical, volatility, and Greeks are compressed on this capture (stdev under 5, and volatility has only three distinct one-decimal values). Recalibrate those scorers before any weight change.

`backend/scripts/capture_change12_qa.py` now also stores the full `evaluation_ledger` and earnings `date_status`. The existing fixture was not recaptured. The explain script uses `evaluation_ledger` when that key is present, and otherwise the captured `ledger_gamma` and `candidates` rows.

## Tests

`backend/tests/test_change12_qa_replay.py` walks all 50 CSV tickers. A ticker with no snapshot, a capture error, or no summary is skipped with that reason. On a real snapshot it asserts:

- no `NOT EXECUTABLE` together with auto-execute eligible, on the boolean or on the eligibility line
- option leg count matches the registry template, or option legs plus the equity leg match it; equity-required names have a stock leg
- the stored regime is the same side of the ±5 rule as `assess_vol_regime` on the stored IV, HV, and IV rank (`IV_MISMATCH_VOL_POINTS` is 5; the rule text contains `±5`)
- an earnings field is never the string `none`; SPY and QQQ have `earnings_applicable` false; an estimated date shows `est.`; the five IR-confirmed names do not show `est.`
- unmatched narrative tokens are empty
- the ten catalyst names have a Gamma Trampoline™ ledger note that the earnings-move history is missing

`backend/tests/test_change12_3d_tools.py` checks the two scripts: a missing IV rank or IV ratio is a data defect, history is not filled in, an empty ledger says so, the fixture explanation covers all ten names, and an absent pillar is not replaced with a number.

No `pytest.mark.xfail` was added. The replay assertions passed on this tree. `change12/3A`, `change12/3B`, and `change12/3C` point at the same commit this branch started from, so there was no unmerged production failure to mark. Assertions were not loosened to pass.

## Results

Full backend suite, from `/Users/Mayank/Desktop/APEX-change12-3D/backend`, outside the sandbox:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

**1718 passed, 59 skipped, 0 failed, 0 xfailed, 0 xpassed.** One Starlette deprecation warning in `tests/test_ws.py`.

The 50 replay rows and the 8 tool tests are included in that pass count.

## Sources

- `docs/changes/change-12/SPEC.md` C1, C6, D4, and Part E items 1, 5, 6, and 8.
- `docs/changes/change-12/phase3-status.md` (the not-done list for 3D).
- `docs/qa/APEX_QA_Test_Results.csv` (50 tickers).
- `backend/tests/fixtures/change12_qa_replay.json`, captured 2026-10-05T22:51:27Z. Ledger gate notes and pillar scores are from that file.
- `APEX_COMPOSITE_WEIGHTS` in `backend/app/analysis/layers.py`.
- `IV_MISMATCH_VOL_POINTS` and `assess_vol_regime` in `backend/app/analysis/gate_config.py`.
- `IR_CONFIRMED` in `backend/app/services/fundamentals_layer.py` (JPM, GS, C, JNJ, UNH on 2026-10-13).
- Gamma gate sentences from `check_apex_strategy_eligibility` in `backend/app/services/apex_strategy.py`. Those sentences are read, not reimplemented.

## Open questions

- The current fixture has no `evaluation_ledger` key and no `date_status`. Fetch status is `live` even when the display carries `est.` The replay treats a populated date outside `IR_CONFIRMED` as estimated and requires `est.` A later capture will store `date_status` because the capture script now copies it.
- BAC's stored `vol_regime` is the short label `sell premium`. The ±5 assessment of the stored IV, HV, and IV rank is the sell side (5.89 vol points, display phrase `IV much above HV`, no tie-break on those three inputs). The replay accepts both strings as that sell side. The card field is `regime_view.display`, which is the short label only when `tie_break` is true, so the card may have used ATM IV or front/back IV that the summary does not store.
- NFLX in the fixture has `earnings_applicable` false, `next_date` null, and status `unavailable`. The catalog lists NFLX as an equity. The value is not the string `none`. The replay does not require a date for that row.
- Delta 0.15–0.25 and the premium-offset measurement are not gates in the current eligibility notes. The explain script does not add them.

## Requests for other owners

- **3A.** The replay asserts `unmatched == []` on the text the capture kept. If a later card sentence cites a number that is not on the ledger, that row fails here. Do not weaken this assertion.
- **3B.** Volatility (population stdev 3.29, three distinct one-decimal values) and Greeks (population stdev 1.72, 34 of 50 captured scores exactly 40.0, 15 distinct values at one decimal) are compressed. Leave `APEX_COMPOSITE_WEIGHTS` unchanged. If the card must say `IV much above HV` rather than `sell premium` for BAC's 5.89-point gap, that string is on the strategy layer.
- **3C.** No frontend file was edited here. The replay does not cover `DeepScan.order.test.tsx`.
- **Whoever next recaptures.** Run `backend/scripts/capture_change12_qa.py` so new rows include `evaluation_ledger` and `date_status`. Do not invent the eight earnings moves to turn the history gate green.
