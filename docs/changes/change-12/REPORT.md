# Change 12 final report

Branch `change12/base`. Phase 3 merges are `ff10a2862bc4e6bc7809a75be2aacec60e8de84a` (3B), `0e688db12171241a2d18e0e8fb749b0c2cd22153` (3A), and `f40d772ff0d1082c6990526014f43cedc53cc90e` (3D). `change12/3C` was already merged at `359057d`. The comparison minimum on the QA sheet is **50**. The product default in `backend/app/analysis/layers.py` is still **85**. Composite weights were not changed.

The 50-name capture is `backend/tests/fixtures/change12_qa_replay.json`, captured `2026-10-05T22:51:27Z`, options feed `indicative`. This report does not invent quotes, chains, or the eight historical earnings moves.

## Five stages

### Brainstorm

The QA sheet had two failures that looked like one. A card could say NOT EXECUTABLE and auto-execute eligible at the same time, and Gamma Trampoline was never selected. The first is an eligibility conjunction. The second is a set of gates that were not all being fed measured inputs. A missing earnings flag, a missing back-week IV, and a missing ADV made gates read as missing even when the scan already had the date, the back chain, and the average volume. The eight-report earnings history is a closed gate. Score spread on the sheet pointed at pillars that barely move, not at the weights.

### Research and analysis

Read `SPEC.md`, `PLAN.md`, the Phase 1 and Phase 2 integration notes, the agent notes, `docs/qa/APEX_QA_Test_Results.csv` (50 rows), and the replay fixture. The live regime rule is `assess_vol_regime`: IV versus HV outside ±5 vol points, IV rank only as the tie-break, inversion only when front IV is at least 1.25 times back IV. Alpaca in this checkout is paper Trading API Basic. The options feed is indicative. Algo Trader Plus is $99/month and was not purchased. Sources are in the last section.

### Phased checklist

1. Route card text through `check_narrative`, with ledger fallback and a rejection log.
2. One ±5 vol-point rule on the volatility layer and on the options vol signal.
3. Subtract a measured long-leg event-vega penalty before rank, and show that measured row on the APEX score slide.
4. Order paths treat a priced quote with no timestamp as not fresh. `canAutoExecute` delegates. `skip_quote_check` is gone.
5. Feed Gamma Trampoline the earnings flag, back-chain IV, and ADV. Do not invent the eight historical moves.
6. Replay the 50 QA names. Report sub-score spread and a calibration proposal. Do not change weights.
7. Mark each Part E criterion from the capture, the scripts, and the suites.

### Execute

The code changes are the defect list below. The capture script reads Alpaca chains and the existing fundamentals and sentiment builders. No chain was filled in by hand. `explain_change12_gamma.py` and `report_change12_subscores.py` were run on this merged tree against the existing fixture.

### Test and verify

Backend command, from `backend/`, unrestricted permissions:

`/Users/Mayank/Desktop/APEX DESKTOP/backend/.venv/bin/python -m pytest -q --tb=line`

| When | Result |
| --- | --- |
| After the 3C merge (already on this branch) | 1717 passed, 59 skipped, 0 failed |
| Re-run after the 3B merge, before any further merge | 1 failed, 1721 passed, 59 skipped |
| Same tree after recording the short-delta cap the Bull Put how-to already prints | 1722 passed, 59 skipped, 0 failed |
| After merging `change12/3A` | 1727 passed, 59 skipped, 0 failed |
| After merging `change12/3D` | 1735 passed, 59 skipped, 0 failed |
| After the integration edits in this commit | **1735 passed, 59 skipped, 0 failed** |

The skip count is the Phase 1 baseline. Frontend `npm test` was not re-run in this session. The 3C note already on this branch records **302 passed, 0 failed** on 5 October 2026.

`tests/test_session_refresh.py::test_two_hour_session_refreshes_without_logout` is the simulated session. It is not a wall-clock two-hour run. `test_reload_restores_session_from_cookie_on_every_screen` is the reload check.

## Defects

| Defect | Root cause | Fix | Tests | Result |
| --- | --- | --- | --- | --- |
| Card sentences could cite numbers that were not on the ledger | Generated why-it-fits, how-to-use, risk notes, summary, status line, and outlook were returned without `check_narrative` | `_guard_strategy_card` (`strategy_engine.py:3182`) records the figures it prints, then accepts the text or falls back to the knowledge-base template plus ledger fact lines. Rejections are logged by `narrative_guard.py:287` | `tests/test_change12_phase3.py`, `tests/test_change12_3a.py` | An injected `999.9` is dropped. The replay's stored `unmatched` lists are empty |
| Remaining card fields were still the pre-guard strings | `equity_note`, `selection_rationale`, `hard_block_reasons`, `spread_block_reasons`, and `block_reason` were copied after the guard. `scan_engine.py` rewrote `why_it_fits` after the guard, and appended the missing-equity risk note after the guard | Those fields now call `_guard_card_text`. The restored composite sentence is checked at `scan_engine.py:1067`. The missing-equity note is checked at `scan_engine.py:628`. Holdings counts the note already prints are stored in `stock_leg.py` before the check | Existing card and stock-leg tests | Unmatched tokens fall back to the ledger-filled template. No quote was invented to make a sentence pass |
| Bull Put how-to cited 0.20 and the fallback dragged in `IV Crush` | The playbook sentence `Δ ≤ 0.20` was not on the ledger, so the guard replaced the card with every ledger fact line, including `IV Crush Short Iron Condor` | `strategy_engine.py:3896` records `rule2_short_delta_max()` when the how-to prints that cap | `test_aapl_bull_put_legs_keep_structure_name_and_payoff` | The assertion `IV Crush` not in the payload passes. The test was not weakened |
| Options vol signal used a 10-point band | `options_analysis.py` compared ATM IV minus HV with `iv_hv_rich_pts` (0.10). A 9.93-point gap stayed fair while the card, via `assess_vol_regime`, was rich | `options_analysis.py:421` calls `assess_vol_regime`. The vega-cap check at `options_analysis.py:474` still uses the 10-point constant and was not changed | Regime tests, `tests/test_options_analysis.py` | The ±5 band was not widened |
| Volatility layer used a separate 10-point label | `_iv_hv_signal` in `volatility_intel.py` | That function calls `assess_vol_regime`. The band constant is `IV_MISMATCH_VOL_POINTS` = 5 | `tests/test_change12_phase3.py`, `tests/test_change12_3b.py` | IV 30.31% versus HV 20.38% is rich |
| A long leg over earnings did not change rank, and the score slide hid the penalty | The penalty was a note after the sort. The APEX score slide did not read the ledger row | `_apply_event_vega_penalty` (`strategy_recommendation.py:640`) subtracts the measured long-leg IV premium, in vol points, before rank, and records `event_vega_penalty`. If the premium cannot be measured, nothing is subtracted. `_show_measured_event_vega` (`scan_engine.py:874`) appends that measured row to the risk section of the score slide. Weights stay the same | `tests/test_change12_phase3.py`, `tests/test_change12_3b.py` | A measured premium changes rank. An unmeasured premium is not shown |
| A price with no timestamp was fresh on the order path | `quote_problem` treated a missing `as_of` as not an age failure | `quote_problem` (`executability.py:139`) returns `Quote not current. Quoted unknown time.` The 300-second cap is unchanged | `tests/test_change12_phase3.py`, `tests/test_executability.py` | Pass |
| `contracts.canAutoExecute` did not share the order decision | Stub | `contracts.py:77` returns `executability.can_auto_execute` | `test_can_auto_execute_contract_delegates` | Pass |
| `skip_quote_check` could skip submission validation | Parameter on `execute_market_fill` | The parameter is gone. The quote check always runs | `test_order_path_cannot_skip_the_quote_check` | Pass |
| Gamma Trampoline was told the earnings date was missing when the calendar had one | The scan built the strategy input without the flag it had already computed | `scan_engine.py:394` passes `earnings_date_confirmed` | Replay ledger: JPM `Catalyst window 8 calendar days is inside 5 to 10` | The window gate is measured |
| Back-week IV was missing | Term structure did not read the back chain | `_atm_iv` (`apex_strategy.py:362`) reads the listed call nearest the spot. No IV is invented | Replay ledger | JPM front/back 1.64. GS 1.11. C 1.24, which stays below 1.25 |
| ADV was missing | The builder read a vol-layer field the quote never filled | `scan_engine.py:385` copies `quote.avg_volume` when ADV is absent | Replay ledger | JPM 19,163,627. BLK 684,063 |
| GOOGL's calendar date was wiped when a second estimate disagreed | Any disagreement cleared the date | `fundamentals_layer.py:597` keeps the stored calendar estimate when there is no company-IR confirmation | Replay row | `next_date` `2026-10-28`, display `2026-10-28 est.` |
| ETF earnings cards could crash, and a missing date could be stored as none | A factor-card name error, and a missing date rendered as the word none | `_build_factor_cards` (`fundamentals_layer.py:972`) uses the symbol it was given. SPY and QQQ have `earnings_applicable` false | Replay rows | No earnings field on the 50 rows is the string `none` |

## Before / after QA

Before is `docs/qa/APEX_QA_Test_Results.csv`. After is the capture at user minimum 50. Score is the score-layer composite, one decimal. Eligibility is the stored `eligible` flag: true only when the capture marked the conjunction. A NOT EXECUTABLE row is not eligible. Failed check is the first stored `failed_checks` string. AMD and NFLX have an empty `failed_checks` list; their eligibility line says `quote not current`, and the risk notes cited below are the ones that name the quote or the spread. A dash means that list was empty and the row was not blocked.

| # | Ticker | Before status | Before strategy | Before score | Before eligibility | After status | After strategy | After score | After eligibility | After failed check |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | MSFT | BEST MATCH | Diagonal Spread (bullish) | 61.8 | Auto-execute eligible | BEST MATCH | Collar | 61.5 | eligible | — |
| 2 | NVDA | BEST MATCH | Diagonal Spread (bullish) | 70.6 | Auto-execute eligible | BEST MATCH | Short Iron Condor | 60.5 | eligible | — |
| 3 | AMD | NOT EXECUTABLE | Married Put | 54.6 | Auto-execute eligible | NOT EXECUTABLE | Married Put | 54.6 | not eligible | quote not current; Stale or suspect quote; Bid/ask spread is 63.0% of mid |
| 4 | JPM | NOT EXECUTABLE | Diagonal Spread (bearish) | 62.9 | Auto-execute eligible | BEST MATCH | Calendar Spread | 53.0 | eligible | — |
| 5 | GS | NOT EXECUTABLE | Diagonal Spread (bullish) | 50.5 | Auto-execute eligible | BEST MATCH | Collar | 50.7 | eligible | — |
| 6 | BAC | NOT EXECUTABLE | Diagonal Spread (bearish) | 51.9 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 52.1 | not eligible | bid/ask spread is 17.3% of mid, not below 10% |
| 7 | WFC | NOT EXECUTABLE | Bear Call Spread | 50.2 | Auto-execute eligible | NOT EXECUTABLE | Bear Call Spread (credit) | 50.2 | not eligible | bid/ask spread is 34.9% of mid, not below 10% |
| 8 | MS | BEST MATCH | Diagonal Spread (bullish) | 53.5 | Auto-execute eligible | BEST MATCH | Collar | 53.5 | eligible | — |
| 9 | C | NOT EXECUTABLE | Bear Call Spread | 48.8 | Manual confirmation | NOT EXECUTABLE | Bear Call Spread (credit) | 48.8 | not eligible | bid/ask spread is 27.5% of mid, not below 10% |
| 10 | JNJ | NOT EXECUTABLE | Diagonal Spread (bearish) | 51.0 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 51.0 | not eligible | bid/ask spread is 23.5% of mid, not below 10% |
| 11 | UNH | NOT EXECUTABLE | Bull Put Spread | 62.2 | Auto-execute eligible | BEST MATCH | Collar | 52.7 | eligible | — |
| 12 | NFLX | NOT EXECUTABLE | Diagonal Spread (bearish) | 56.6 | Auto-execute eligible | NOT EXECUTABLE | Diagonal Spread (bearish) | 60.6 | not eligible | quote not current; Stale or suspect quote |
| 13 | TSLA | NOT EXECUTABLE | Diagonal Spread (bullish) | 58.2 | Auto-execute eligible | BEST MATCH | Short Iron Condor | 58.3 | eligible | — |
| 14 | KO | BEST MATCH | Married Put | 49.7 | Manual confirmation | BEST MATCH | Married Put | 50.0 | eligible | — |
| 15 | GE | NOT EXECUTABLE | Diagonal Spread (bearish) | 48.2 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 48.3 | not eligible | bid/ask spread is 22.8% of mid, not below 10% |
| 16 | IBM | NOT EXECUTABLE | Diagonal Spread (bearish) | 49.7 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 49.8 | not eligible | bid/ask spread is 13.2% of mid, not below 10% |
| 17 | VZ | NOT EXECUTABLE | Diagonal Spread (bullish) | 48.4 | Manual confirmation | BEST MATCH | Collar | 48.4 | eligible | — |
| 18 | T | NOT EXECUTABLE | Diagonal Spread (bearish) | 49.6 | Manual confirmation | BEST MATCH | Short Iron Condor | 49.7 | eligible | — |
| 19 | GOOGL | NOT EXECUTABLE | Bull Put Spread | 61.5 | Auto-execute eligible | BEST MATCH | Collar | 65.9 | eligible | — |
| 20 | META | NOT EXECUTABLE | Diagonal Spread (bearish) | 63.1 | Auto-execute eligible | BEST MATCH | Short Iron Condor | 61.1 | eligible | — |
| 21 | AAPL | NOT EXECUTABLE | Married Put | 65.5 | Auto-execute eligible | BEST MATCH | Collar | 63.5 | eligible | — |
| 22 | AMZN | NOT EXECUTABLE | Diagonal Spread (bullish) | 62.1 | Auto-execute eligible | BEST MATCH | Bull Put Spread (credit) | 62.2 | eligible | — |
| 23 | XOM | NOT EXECUTABLE | Bull Put Spread | 45.1 | Manual confirmation | BEST MATCH | Collar | 45.1 | eligible | — |
| 24 | CVX | NOT EXECUTABLE | Bull Put Spread | 52.7 | Auto-execute eligible | BEST MATCH | Collar | 52.7 | eligible | — |
| 25 | LLY | NOT EXECUTABLE | Bull Put Spread | 48.8 | Manual confirmation | BEST MATCH | Collar | 48.8 | eligible | — |
| 26 | PFE | NOT EXECUTABLE | Bear Call Spread | 46.4 | Manual confirmation | NOT EXECUTABLE | Bear Call Spread (credit) | 46.4 | not eligible | bid/ask spread is 10.5% of mid, not below 10% |
| 27 | MRK | NOT EXECUTABLE | Diagonal Spread (bearish) | 46.0 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 46.0 | not eligible | bid/ask spread is 23.5% of mid, not below 10% |
| 28 | ABBV | NOT EXECUTABLE | Diagonal Spread (bullish) | 48.7 | Manual confirmation | BEST MATCH | Collar | 48.7 | eligible | — |
| 29 | V | NOT EXECUTABLE | Diagonal Spread (bullish) | 50.2 | Auto-execute eligible | BEST MATCH | Collar | 50.2 | eligible | — |
| 30 | MA | NOT EXECUTABLE | Diagonal Spread (bearish) | 50.5 | Auto-execute eligible | BEST MATCH | Diagonal Spread (bearish) | 50.5 | eligible | — |
| 31 | AXP | NOT EXECUTABLE | Diagonal Spread (bearish) | 50.7 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 50.7 | not eligible | bid/ask spread is 34.0% of mid, not below 10% |
| 32 | BLK | NOT EXECUTABLE | Diagonal Spread (bullish) | 50.7 | Auto-execute eligible | BEST MATCH | Collar | 50.7 | eligible | — |
| 33 | PEP | NOT EXECUTABLE | Diagonal Spread (bearish) | 46.8 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 46.8 | not eligible | bid/ask spread is 20.1% of mid, not below 10% |
| 34 | PG | NOT EXECUTABLE | Diagonal Spread (bearish) | 43.9 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 43.9 | not eligible | bid/ask spread is 92.8% of mid, not below 10% |
| 35 | MCD | NOT EXECUTABLE | Bear Call Spread | 52.5 | Auto-execute eligible | BEST MATCH | Diagonal Spread (bearish) | 52.5 | eligible | — |
| 36 | SBUX | NOT EXECUTABLE | Bull Put Spread | 46.7 | Manual confirmation | BEST MATCH | Collar | 46.7 | eligible | — |
| 37 | CAT | NOT EXECUTABLE | Diagonal Spread (bullish) | 45.2 | Manual confirmation | BEST MATCH | Collar | 49.3 | eligible | — |
| 38 | BA | NOT EXECUTABLE | Diagonal Spread (bearish) | 50.6 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 48.6 | not eligible | bid/ask spread is 16.5% of mid, not below 10% |
| 39 | HON | NOT EXECUTABLE | Diagonal Spread (bearish) | 47.5 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 47.5 | not eligible | bid/ask spread is 72.5% of mid, not below 10% |
| 40 | UPS | NOT EXECUTABLE | Diagonal Spread (bearish) | 48.6 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 48.6 | not eligible | bid/ask spread is 23.9% of mid, not below 10% |
| 41 | LMT | NOT EXECUTABLE | Diagonal Spread (bearish) | 51.0 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 51.0 | not eligible | bid/ask spread is 60.5% of mid, not below 10% |
| 42 | RTX | NOT EXECUTABLE | Bear Call Spread | 52.3 | Auto-execute eligible | NOT EXECUTABLE | Bear Call Spread (credit) | 52.3 | not eligible | bid/ask spread is 47.4% of mid, not below 10% |
| 43 | COP | NOT EXECUTABLE | Diagonal Spread (bullish) | 51.6 | Auto-execute eligible | BEST MATCH | Collar | 51.6 | eligible | — |
| 44 | NEE | NOT EXECUTABLE | Diagonal Spread (bearish) | 46.2 | Manual confirmation | NOT EXECUTABLE | Short Iron Condor | 46.2 | not eligible | bid/ask spread is 19.2% of mid, not below 10% |
| 45 | SPY | NOT EXECUTABLE | Married Put | 66.3 | Auto-execute eligible | BEST MATCH | Married Put | 66.1 | eligible | — |
| 46 | QQQ | NOT EXECUTABLE | Married Put | 63.7 | Auto-execute eligible | BEST MATCH | Married Put | 63.7 | eligible | — |
| 47 | DIS | NOT EXECUTABLE | Diagonal Spread (bullish) | 56.4 | Auto-execute eligible | BEST MATCH | Collar | 56.4 | eligible | — |
| 48 | PLD | NOT EXECUTABLE | Diagonal Spread (bullish) | 48.8 | Manual confirmation | BEST MATCH | Collar | 48.8 | eligible | — |
| 49 | NEM | NOT EXECUTABLE | Diagonal Spread (bearish) | 60.9 | Auto-execute eligible | NOT EXECUTABLE | Short Iron Condor | 60.9 | not eligible | bid/ask spread is 19.4% of mid, not below 10% |
| 50 | HD | NOT EXECUTABLE | Diagonal Spread (bearish) | 43.7 | Manual confirmation | NOT EXECUTABLE | Bear Call Spread (credit) | 47.9 | not eligible | bid/ask spread is 43.4% of mid, not below 10% |

### Strategy distribution (after)

| Strategy | Count |
| --- | --- |
| Collar | 18 |
| Short Iron Condor | 18 |
| Bear Call Spread (credit) | 5 |
| Married Put | 4 |
| Diagonal Spread (bearish) | 3 |
| Calendar Spread | 1 |
| Bull Put Spread (credit) | 1 |
| Gamma Trampoline | 0 |

Composite on this capture: mean 52.50, population stdev 5.76, min 43.9, max 66.1. Status counts: 29 BEST MATCH, 21 NOT EXECUTABLE. Zero of the 21 NOT EXECUTABLE rows have `eligible` true.

Nineteen of those 21 store a bid/ask failed check above 10% of mid. AMD and NFLX are blocked because the eligibility line says the quote is not current. The 10% cap was not raised.

## Gamma Trampoline, gate by gate

`backend/scripts/explain_change12_gamma.py` read the ledger on the fixture. Every one of the ten has a candidate row, score 0.0, and was not selected. The history gate is `fail_closed` on all ten. The script says the eight moves were not invented. IV rank is present on all ten (100, or 97.1 on MS), so none of these ten is a missing-IV-rank data defect. The 1.25 inversion minimum was not lowered. C at 1.24 fails that gate.

| Ticker | Best match | Window | IV rank | Front/back | ADV | Structure | Open interest | Spread | History |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| JPM | Calendar Spread | 8, inside 5–10 | 100, above 70 | 1.64, at least 1.25 | 19,163,627, above 5,000,000 | listed | absent | absent | fail closed, not invented |
| GS | Collar | 8, inside | 100, above 70 | 1.11, below 1.25 | 3,391,601, not above 5,000,000 | listed | 27, not above 1,000 | 99.8% of mid | fail closed |
| C | Bear Call Spread (credit) | 8, inside | 100, above 70 | 1.24, below 1.25 | 25,296,259, above 5,000,000 | listed | 124, not above 1,000 | 166.7% of mid | fail closed |
| JNJ | Short Iron Condor | 8, inside | 100, above 70 | 1.09, below 1.25 | 6,429,776, above 5,000,000 | listed | absent | absent | fail closed |
| UNH | Collar | 8, inside | 100, above 70 | 1.10, below 1.25 | 2,988,379, not above 5,000,000 | listed | 87, not above 1,000 | 38.5% of mid | fail closed |
| BAC | Short Iron Condor | 9, inside | 100, above 70 | 1.07, below 1.25 | 63,916,242, above 5,000,000 | listed | 31, not above 1,000 | 133.3% of mid | fail closed |
| WFC | Bear Call Spread (credit) | 9, inside | 100, above 70 | 1.03, below 1.25 | 45,188,941, above 5,000,000 | not listed | absent | absent | fail closed |
| MS | Collar | 9, inside | 97.1, above 70 | 1.01, below 1.25 | 11,268,646, above 5,000,000 | not listed | absent | absent | fail closed |
| BLK | Collar | 9, inside | 100, above 70 | 1.07, below 1.25 | 684,063, not above 5,000,000 | listed | absent | 123.7% of mid | fail closed |
| PLD | Collar | 10, inside | 100, above 70 | 1.30, at least 1.25 | 2,953,478, not above 5,000,000 | listed | 853, not above 1,000 | absent | fail closed |

JPM passes the window, IV rank, inversion, ADV, and the listed four-leg structure. It still fails history, open interest, and spread. WFC and MS do not have the same strikes listed on a back expiry about two weeks later. Open interest and spread of "absent" means the chosen contracts did not all carry the field on this indicative chain. Those values were not filled in.

## Part E

1. **PASS.** Zero of 50 rows have status NOT EXECUTABLE and `eligible` true, and none of those rows have "auto-execute eligible" on the eligibility line. `tests/test_change12_qa_replay.py` asserts the same pair. The before sheet had that pair on most rows.
2. **PASS, simulated.** `tests/test_session_refresh.py::test_two_hour_session_refreshes_without_logout` runs eight expired access tokens. The access-token TTL default is 900 seconds, so the loop covers 8 × 900 = 7200 seconds. Each `/auth/me` with the expired token returns 401, refresh returns 200, and the new token reads `/auth/me`. `test_reload_restores_session_from_cookie_on_every_screen` restores the session from the cookie with no Authorization header. A wall-clock two-hour manual session was not run.
3. **PASS.** Married Put, Collar, and the other equity-required names in the capture include a stock leg or an equity leg. The replay asserts option-leg counts match the registry template, or option legs plus the equity leg match it. Zero of those names lack a stock leg.
4. **PASS.** All 50 equity quotes have `quote_as_of` and `quote_feed` (`other` on the stock quote). All 50 option chains have feed `indicative` and `chain_as_of`. AMD and NFLX still show a quote-not-current block. That block is not the session clock alone: the risk notes also say "Stale or suspect quote".
5. **PASS.** GOOGL `next_date` is `2026-10-28` and `display` is `2026-10-28 est.` The date matches 28 October 2026 and is labeled an estimate, not a confirmed company announcement. SPY and QQQ have `earnings_applicable` false. No stored earnings `next_date`, `status`, `display`, or `date_status` on the 50 rows is the string `none`.
6. **PASS.** The explain script printed a ledger gate for all ten Gamma Trampoline names. History fails closed on every name. The moves were not invented.
7. **PASS.** Gamma Trampoline stays unselected because the measured gates fail, including history fail-closed. No quota and no random choice was added. The distribution above is the capture count.
8. **PASS.** Every stored `unmatched` list on the 50 summaries is empty. The replay asserts `unmatched == []`.
9. **PASS** for the backend suite: 1735 passed, 59 skipped, 0 failed. Frontend was not re-run here. The merged 3C note records 302 passed, 0 failed.
10. **PASS.** This integration commit edits the vol signal, the narrative checks, the score-slide penalty row, and these two documents. Weights, the 300-second quote cap, the spread cap, and the ±5 band were not changed.

## Sources

- Alpaca, About Market Data API. Trading API Basic is free and is the default for paper and live accounts. Basic options coverage is the indicative feed. Basic historical data is limited to the latest 15 minutes. Algo Trader Plus is $99/month and includes the OPRA options feed: https://docs.alpaca.markets/us/docs/about-market-data-api
- Alpaca, historical option data. Indicative quotes are not OPRA quotes. Indicative trades are delayed 15 minutes. OPRA is the consolidated BBO and is only for subscribed users: https://docs.alpaca.markets/us/docs/historical-option-data
- Replay fixture `backend/tests/fixtures/change12_qa_replay.json`, captured 2026-10-05T22:51:27Z, feed `indicative`.
- `docs/qa/APEX_QA_Test_Results.csv` (50 rows).
- `backend/scripts/explain_change12_gamma.py` and `backend/scripts/report_change12_subscores.py`, run on this tree.
- `APEX_COMPOSITE_WEIGHTS` in `backend/app/analysis/layers.py`.
- This checkout: `alpaca_trading_mode` default `paper` (`config.py`). The Alpaca adapter uses feed `indicative` unless trading mode is live (`alpaca.py`). Algo Trader Plus was not purchased.

## Score calibration proposal

Weights were not changed. Technicals 30%, volatility 25%, options/Greeks 20%, sentiment 15%, fundamentals 10%. Risk stays advisory at 0%.

`report_change12_subscores.py` on this fixture (population stdev, n=50, absent=0 on every pillar):

| Pillar | Mean | Population stdev | Min | Max | Distinct at 1 decimal |
| --- | --- | --- | --- | --- | --- |
| Technical | 73.59 | 4.86 | 63.00 | 81.00 | 40 |
| Volatility | 72.30 | 3.29 | 55.00 | 80.00 | 3 |
| Greeks | 40.75 | 1.72 | 40.00 | 47.80 | 15 |
| Sentiment | 54.97 | 12.96 | 22.60 | 76.70 | 50 |
| Fundamental | 74.68 | 12.28 | 40.30 | 95.00 | 45 |

Volatility is 72.0 on 45 names, 80.0 on 4, and 55.0 on 1. Greeks are exactly 40.0 on 34 of 50 names. The script's proposal, not applied: leave the weights as they are. Technical, volatility, and Greeks are compressed on this capture (population stdev under 5, and volatility has three distinct one-decimal values). Recalibrate those scorers before any weight change.

## Remaining limitations

- The eight historical earnings moves are not in the data. Gamma Trampoline fails that gate closed on all ten names. Other measured failures (inversion, ADV, open interest, spread, missing back strikes) would still block these ten even if history appeared.
- The options feed is Alpaca indicative. Quotes are not OPRA quotes. Trades on that feed are delayed 15 minutes. Some chosen strikes have no open interest or no two-sided quote. Those gates say absent.
- For composites at or below the old blocked band, the playbook is built at 51 and `_restore_scored_strategy_layer` puts the real composite back on the score and on `why_it_fits`. The stored eligibility sentence on this capture still says `Composite 51.0` for those names, and the stored `eligible` flag follows that build. Eight BEST MATCH rows are below 50 and still stored as eligible: VZ 48.4, T 49.7, XOM 45.1, LLY 48.8, ABBV 48.7, SBUX 46.7, CAT 49.3, PLD 48.8. KO is 50.0, which meets minimum 50; its sentence still says 51.0. The table's eligibility column is that stored flag. NOT EXECUTABLE rows are not in this set: their flag is false.
- A rejected card sentence is replaced by the knowledge-base text plus ledger fact lines. That fallback can be long. It does not contain unmatched numbers.
- The QA comparison uses minimum 50 so it lines up with the sheet. The highest composite in this capture is 66.1, so a saved minimum of 85 would mark every row not eligible.
- The two-hour session result is the simulated test cited above. A wall-clock two-hour session was not run.
- Frontend vitest was not re-run in this session. The 3C result on this branch is 302 passed, 0 failed.
- The fixture has no `date_status` key. GOOGL's estimate is the `est.` suffix on `display`.

## Decisions needed from the team

1. **Data feed upgrade.** This app is on Alpaca paper Trading API Basic. The options feed is indicative. Indicative quotes are not OPRA quotes, and indicative trades are delayed 15 minutes. Algo Trader Plus is $99/month and is the Trading API plan that includes OPRA. It was not purchased. Whether to subscribe is a team decision. Cost and feed definitions: https://docs.alpaca.markets/us/docs/about-market-data-api and https://docs.alpaca.markets/us/docs/historical-option-data
2. **Score calibration.** Keep the current weights. Recalibrate the technical, volatility, and Greeks scorers so they are not compressed (volatility is 72.0 on 45 of 50 names; Greeks are 40.0 on 34 of 50) before any weight change is considered. Evidence is the table above. This report does not change weights.
