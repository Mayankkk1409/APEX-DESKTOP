# Change 12 plan (Step 0)

Branch: `change12/base`. Step 0 only. Phase 1 has not started. No defects were fixed.

Report path for later work: `docs/changes/change-12/REPORT.md`. Spec: `docs/changes/change-12/SPEC.md`.

## QA inputs

`APEX_QA_Test_Report.docx` and `APEX_QA_Test_Results.csv` were in the repository root (untracked). They were moved to:

- `docs/qa/APEX_QA_Test_Report.docx`
- `docs/qa/APEX_QA_Test_Results.csv`

No QA rows were added or rewritten. The spec's counts and examples are the written claims; this plan does not invent additional rows from those files.

## Frozen contracts

Module: `backend/app/contracts.py`.

Created in Step 0 as typed dataclasses and stubs. The app does not import it. `canAutoExecute` raises `NotImplementedError`. `ledger.record` drops the entry. `ledger.get` returns `[]`.

**Sole owner for the rest of Change 12: subagent 2B.** Every other subagent may import the types and must not edit this file.

Phase 1 does not put behavior in this module.

- 1C builds `QuoteMeta` and `EarningsInfo` in the quote and earnings modules it owns.
- 1D implements the live eligibility function in `backend/app/services/executability.py` (new, 1D-owned) with the same signature as `canAutoExecute(scan, userSettings) -> {eligible, reasons[]}`. Strategy slide, Risk Review, Acknowledge, Place Trade, scheduled/background fills, and the direct order API all call that one function. It must agree with `ExecutabilityVerdict`.
- 2B implements `record` / `get` in `backend/app/services/evidence_ledger.py` (new, 2B-owned) using `LedgerEntry`. 2A calls that API from the strategy engine. 2B does not reimplement `canAutoExecute`.

## Rules for every subagent

- Edit only files listed under that subagent for that phase.
- A file has one owner inside a phase. Files marked as a handoff are owned by the Phase 1 agent until that phase has merged, then by the Phase 2 agent. They are never edited by two agents at once.
- Do not edit `backend/app/config.py` except 1A. Do not edit `backend/app/main.py` except 2B. Do not edit `backend/app/contracts.py` except 2B.
- Do not change composite weights (`backend/app/analysis/composite_score.py` stays untouched). C6 is a written distribution and a proposed calibration in the report.
- Do not loosen spread, OI, or staleness thresholds. Do not buy a data plan.
- Do not add strategy quotas or randomness.
- New tests live next to the owner. Do not edit another owner's tests.

## Phase 1 file ownership

### 1A — Auth and session (A2)

Silent refresh before access-token expiry. Refresh token is an httpOnly Secure SameSite cookie. Access token stays in memory only. No token in localStorage. A failed refresh logs out. A successful refresh keeps the in-progress scan (symbol, expiry, captured bars, recommendation) in the session store.

- `backend/app/routers/auth.py` (cookie is already httponly; Secure is currently production-only; SameSite is `lax`)
- `backend/app/security.py`
- `backend/app/schemas/auth.py`
- `backend/app/models/user.py`
- `backend/app/deps.py`
- `backend/app/config.py` (sole owner of this file for the whole change)
- `frontend/src/api.ts` (in-memory access token today; 401 clears it)
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Login.test.tsx`
- `frontend/src/components/LogoutButton.tsx`
- `frontend/src/store.ts`
- `frontend/vite.config.ts` (dev proxy must send cookies)
- `backend/tests/test_integration_auth.py`
- `backend/tests/test_security.py`
- New tests for silent refresh, reload, and mid-scan expiry may be added under `backend/tests/` and `frontend/src/` by 1A only

Do not edit `frontend/src/pages/DeepScan.tsx` (1D). Preserve the scan by not clearing `store.ts` when refresh succeeds. Read current auth-library docs before changing cookie flags. Leave `api.search` callable so 1B can wrap it without editing this file.

### 1B — Search and shared score formatting (C7, C8, A4.6)

Search order is exact symbol, then prefix, then name. `MS` returns Morgan Stanley with exact tickers first. Debounce and cache so results return within 300 ms. One-decimal composites go through `formatCompositeScore`.

- `backend/app/services/symbol_catalog.py` (`search_instruments` is what both adapters call)
- `backend/tests/test_symbol_catalog.py`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Dashboard.brokerage.test.tsx`
- `frontend/src/pages/Dashboard.paper-brokerage.test.tsx`
- `frontend/src/lib/scoreFormat.ts`
- `frontend/src/lib/scoreFormat.test.ts`
- `frontend/src/components/ApexScoreScan.tsx`
- New `frontend/src/lib/symbolSearch.ts` for debounce and cache, if needed

Do not edit `backend/app/routers/market.py` or `backend/app/adapters/alpaca.py` (1C). The `/market/search` route already delegates to `adapter.search`, which calls `search_instruments`. Do not edit `frontend/src/api.ts` (1A). Do not edit Risk Review, Deep Scan, or `StrategyScan.tsx` (1D). Those screens must call `formatCompositeScore`; 1D makes that call.

### 1C — Data integrity (B1, B2, B3, B4, C6c, C6d)

`QuoteMeta` on quotes: provider, feed (`indicative` | `opra` | `other`), quotedAt, receivedAt, bid, ask, sizes, isStale, staleReason. Staleness is market-hours aware. Outside regular hours, label last close and do not fail only because the session is closed. Delayed feed is labeled delayed. Cite current Alpaca docs for the Basic indicative feed versus OPRA, and report upgrade cost. Do not buy a plan. Prefer a liquid strike before calling the name non-executable.

Earnings use `EarningsInfo`. Missing is `unknown`, never none. `confirmed` requires an IR source. `estimated` is a provider date and the UI shows est. Cross-check two sources. Conflict or a missing date is unverified, with an event-risk penalty when expiry could contain a typical report date. Verify GS, C, JNJ, UNH on their own IR pages. Do not change a date that is already correct. SPY and QQQ are ETFs and must not fail with "Earnings date is unconfirmed."

Flag inverted skew and bad quotes (bid > ask, IV outside the chain range) for the ledger. 1C writes the flags onto the chain payload. 2B records them. 1C does not edit the ledger module.

- `backend/app/adapters/alpaca.py` (feed is already `indicative` on paper and `opra` when `alpaca_trading_mode == live`)
- `backend/app/adapters/demo.py` (quote metadata only; search already delegates)
- `backend/app/adapters/base.py`
- `backend/app/services/live_quotes.py`
- `backend/app/services/volatility_intel.py` (feed, timestamps, explicit IV-rank data gap; do not relabel an HV proxy as IV rank)
- `backend/app/services/options_analysis.py`
- `backend/app/services/fundamentals_layer.py`
- `backend/app/services/catalyst_calendar.py`
- `backend/app/analysis/options_rules.py` (market-hours staleness; do not loosen caps)
- `backend/app/schemas/market.py`
- `backend/app/routers/market.py`
- `frontend/src/components/FundamentalsScan.tsx`
- `frontend/src/components/volatility/CatalystCalendar.tsx`
- New `frontend/src/lib/quoteMeta.ts` for feed and timestamp display
- `backend/tests/test_live_quotes.py`
- `backend/tests/test_options_analysis.py`
- `backend/tests/test_options_rules.py`
- `backend/tests/test_sentiment_fundamentals.py`
- `backend/tests/test_volatility.py`

Security type for the ETF skip comes from the existing `asset_class` on quotes and `symbol_catalog` (`us_etf`). Do not edit `symbol_catalog.py` (1B).

### 1D — Execution and Risk Review (A1, A3, A4.1–A4.5)

One eligibility function. Both screens use it. Composite at or above the user minimum is not enough: `executable` must be true and pre-trade validation must pass. Re-check quote freshness and spread at submission. Log every block. Stale or suspect quote: refetch once; if still stale, neither path can place it, and the screen shows "Quote not current" plus the timestamp. Wide spread turns auto-execute off; manual Place Trade requires a confirmation that states spread, threshold, and slippage dollars. Non-executable candidates do not outrank executable ones. If none are executable, still show the best strategy and why it cannot be placed. Disable Acknowledge when the trade is not placeable, and show the reason before click.

Options orders are marketable limits from the live bid/ask, with the limit and quote time shown. Demo fill uses the same server validation as Alpaca paper. Remove filler about paper-funded Alpaca or demo fill, OCC boilerplate, and raw `us_option`. Stock leg is required on the card, Risk Review, order, and confirmation. If shares are already held, say "Uses 100 of your N shares" and label the structure a protective put, not a married put. Leg count must match the template.

A4.6 (one decimal) is 1B's formatter. 1D calls it and does not edit `scoreFormat.ts`.

- `backend/app/services/executability.py` (new; the shared function)
- `backend/app/services/fills.py` (choke point for paper, demo, and `expiry_close`)
- `backend/app/services/orders.py`
- `backend/app/services/stock_leg.py`
- `backend/app/services/occ_symbol.py`
- `backend/app/services/expiry_close.py` (background path; validation still lives in `fills.py`)
- `backend/app/routers/portfolio.py` (`place_order` and the other submit path)
- `backend/app/routers/scan.py`
- `backend/app/services/scan_engine.py` (eligibility copy and the filler block around the order instructions)
- `backend/app/services/strategy_engine.py` (**Phase 1 owner.** Executability rank only. Do not change regime, vega, DTE windows, or sentiment weights.)
- `frontend/src/lib/riskReview.ts`
- `frontend/src/lib/riskReview.test.ts`
- `frontend/src/components/RiskReviewLegs.tsx`
- `frontend/src/components/RiskReviewOrderActions.tsx`
- `frontend/src/pages/DeepScan.tsx`
- `frontend/src/pages/DeepScan.order.test.tsx`
- `frontend/src/components/StrategyScan.tsx` (**Phase 1 owner.** Not-executable copy.)
- `frontend/src/components/scanSlides.test.tsx`
- `frontend/src/components/OrderConfirmationCertificate.tsx`
- `frontend/src/components/OrderConfirmationCertificate.test.tsx`
- `frontend/src/components/CertificateLegList.tsx`
- `frontend/src/lib/certificateLegs.ts`
- `frontend/src/lib/certificateLegs.test.ts`
- `frontend/src/lib/orderTicket.ts`
- `frontend/src/lib/orderFormat.ts`
- `frontend/src/lib/orderFormat.test.ts`
- `frontend/src/types.ts` (sole owner; scan and order eligibility fields)
- `backend/tests/test_orders.py`
- `backend/tests/test_options_execution.py`
- `backend/tests/test_stock_leg.py`
- `backend/tests/test_auto_execution_threshold.py`
- `backend/tests/test_card_filter_gates.py`
- `backend/tests/test_expiry_close.py`
- `backend/tests/test_strategy_engine.py` (**Phase 1 owner** for executability-rank cases)
- `backend/tests/test_integration_scan.py`

Quote freshness fields come from 1C. 1D reads them and does not edit 1C's files.

## Phase 2 file ownership

Phase 2 starts after Phase 1 has merged. 2A receives `strategy_engine.py`, `StrategyScan.tsx`, and `test_strategy_engine.py` from 1D and must keep the executability ranking 1D added.

### 2A — Strategy logic (C2, C3, C4, C5, C6b, and the fit half of C1)

One regime rule. IV versus HV is primary (more than 5 vol points below, within ±5, more than 5 above). Inversion is front IV at least 1.25 times back IV. IV rank is the tie-break. Show both inputs and the verdict. Long vega in a sell-premium regime is penalized, with a reason, unless inversion justifies it. Event-vega penalty when earnings fall after the short expiry and before the long expiry; name the leg and the date. Each strategy has a DTE window from the knowledge base (2C). Outside the window, use the nearest compliant expiry and say so, or penalize with the reason. Sentiment conflicts name the value, the weight, and why direction won. A margin below a threshold in `gate_config.py` labels the outlook low conviction. Do not add that threshold to `config.py`. Rich-IV alternatives (including a collar) are evaluated, and the card says why the winner ranked first. IV rank never renders a dash without a reason. Missing IV rank stays a data defect (1C sets the gap; 2A shows the reason).

Unreachable strategies, including Gamma Trampoline on the ten catalyst names, are fixed by gate fit. No quotas and no randomness. 2A calls `evidence_ledger.record` at each gate, candidate, score component, and rank. 2B owns the ledger implementation.

C6 (score compression) is a report only. Do not edit `backend/app/analysis/composite_score.py`.

- `backend/app/services/strategy_engine.py` (Phase 2 owner)
- `backend/app/services/strategy_recommendation.py` (`format_iv_rank`, `vol_regime_phrase`)
- `backend/app/analysis/gate_config.py` (`classify_vol_regime` lives here today)
- `backend/app/services/benchmark_greeks.py`
- `backend/app/services/apex_strategy.py`
- `backend/app/services/sentiment_layer.py`
- `backend/app/workers/sentiment.py`
- `backend/app/strategies/metrics_builder.py`
- `backend/app/strategies/chain_utils.py`
- `backend/app/strategies/expiry_utils.py`
- `frontend/src/components/StrategyScan.tsx` (Phase 2 owner)
- `frontend/src/components/volatility/VolAnalysisCards.tsx`
- New `frontend/src/lib/regime.ts` if the card needs types 1D does not own in `types.ts`
- `backend/tests/test_strategy_engine.py` (Phase 2 owner)
- `backend/tests/test_strategy_gate_fix.py`
- `backend/tests/test_change11.py`
- `backend/tests/test_change11_master_sheet.py`
- `backend/tests/test_apex_four_legs.py`
- `backend/tests/test_apex_upgrade.py`
- `backend/tests/test_strategy_coverage.py`
- `backend/tests/test_strategy_coverage_conditions.py`
- `backend/tests/test_mislabeled_structures.py`
- `backend/tests/test_synthetic_structures.py`
- `backend/tests/test_leaps_deep_itm_construction.py`
- `backend/tests/test_platform_trade_card_invariants.py`

Do not edit `knowledge_base.py`, `registry.py`, or `validator.py` (2C). Read DTE windows and greek signs from them.

### 2B — Ledgers and anti-fabrication (C1.1, D2)

Evaluation ledger and evidence ledger. Every card number, percent, date, and ticker used in prose comes from a `LedgerEntry` (inputs, source, feed, timestamp, function). The post-generation check rejects unmatched numbers and falls back to the knowledge-base template. Log rejections. High, low, rich, and cheap claims cite the ledger value and the threshold. API and a debug view explain the ten Trampoline tickers gate by gate. C6c flags produced by 1C are recorded here.

- `backend/app/contracts.py` (sole owner; keep the frozen fields, implement ledger behavior only if it stays in this module — prefer `evidence_ledger.py` and leave the stub class as the type source)
- `backend/app/services/evidence_ledger.py` (new)
- `backend/app/services/narrative_guard.py` (new; post-generation number check)
- `backend/app/routers/ledger.py` (new; debug API)
- `backend/app/main.py` (sole owner; include the debug router)
- New debug view under `frontend/src/components/` or `frontend/src/pages/` created by 2B
- New `backend/tests/test_evidence_ledger.py` and `backend/tests/test_narrative_guard.py`

Do not edit `strategy_engine.py` (2A inserts the `record` calls). Do not edit `canAutoExecute` / `executability.py` (1D).

### 2C — Knowledge base and golden scenarios (D1, D3)

Every Change 7 strategy plus APEX Benchmark Greeks and Gamma Trampoline (Change 11 v2) has the required fields, including a DTE window and greek signs. The validator fails the build when a field is missing. At least five hand-verified scenarios per strategy, with the chain recorded. Payoff within 0.01. Ledger entries for those scenarios are complete.

- `backend/app/strategies/knowledge_base.py`
- `backend/app/strategies/registry.py`
- `backend/app/strategies/validator.py`
- `backend/app/strategies/payoffs/core.py`
- `backend/app/strategies/payoffs/helpers.py`
- `backend/app/strategies/structure_math.py`
- `backend/tests/test_strategy_registry_validation.py`
- `backend/tests/test_all_100_strategies.py`
- `backend/tests/test_strategy_explanations.py`
- `backend/tests/test_structure_payoff.py`
- New golden scenarios under `backend/tests/golden/`

D4 (replay of the 50 QA cases) is the acceptance pass after Phases 1 and 2. It is not a third phase of feature work. The replay test file is added by 2B only if it only asserts ledger and narrative checks; gating, leg counts, regime, and earnings assertions stay in the owners' tests (1D, 1A, 2A, 1C). One new file, `backend/tests/test_change12_qa_replay.py`, is owned by 2B and may only call the other owners' public functions. If that split is too tight, 2B owns the file and the other owners add fixtures in their own test modules that the replay imports.

## Merge order

Phase 1, after each subagent's branch is reviewed:

1. **1B** — formatter and search. No dependency.
2. **1C** — quote and earnings fields that 1D reads.
3. **1D** — eligibility, limits, stock legs, filler removal. Uses 1C payloads and 1B's formatter.
4. **1A** — session cookie and silent refresh, last, so order tests are not rewritten around auth in the middle of the phase.

Phase 2, after Phase 1 is merged:

1. **2B** — ledger API and narrative guard. 2A needs `record` / `get` to exist.
2. **2C** — required KB fields and golden scenarios. 2A reads DTE windows from the KB. Scenario tests are the payoff target; they may fail until 2A merges, and 2A is responsible for making them pass without weakening the 0.01 check.
3. **2A** — regime, vega, event-vega, DTE enforcement, sentiment, rich-IV alternatives, and ledger call sites. Must preserve 1D's executability ranking.

## Out of scope for every subagent

`backend/app/analysis/composite_score.py`, technical-analysis detectors, brokerage SnapTrade panels, portfolio P&L charts, and theme or settings pages, except where a file is listed above. C6 calibration is a proposal in the report, not a weight change.

## Baseline

Recorded on this branch before any Change 12 behavior change. Failures were not fixed.

Command: `backend/.venv/bin/python -m pytest -q --tb=line` from `backend/`, on `change12/base` at the pre-Change-12 product commit plus this Step 0 documentation (the suite does not import `app.contracts`).

Result: **1482 passed, 59 skipped, 0 failed**, 1 warning (`StarletteDeprecationWarning` in `tests/test_ws.py` about httpx and `starlette.testclient`), 20.07s. Exit code 0.
