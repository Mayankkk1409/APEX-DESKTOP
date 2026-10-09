# QA Remediation + Evidence-Grounded Strategy Engine (No Fabrication)

Continues Changes 1-11. Report path docs/changes/change-12/REPORT.md.

Input: QA run of 5 October 2026, 50 scans, 50 tickers, 12 sectors, files docs/qa/APEX_QA_Test_Report.docx and docs/qa/APEX_QA_Test_Results.csv.

A1. Risk Review shows Auto-execute eligible for trades validation will block. 27 of 50 scans NOT EXECUTABLE on strategy slide (stale quote or wide spread) but Risk Review says Auto-execute eligible. Example JPM expiry 2026-10-16 composite 62.9 vs minimum 50. Acknowledge then validation stops the order. Backstop works. Screen must not promise eligibility.
Confirm validation is server-side on Acknowledge, Place Trade, scheduled/background, and direct API. Re-check quote freshness and spread at submission. Log every block. A bypass is HIGH severity.
Eligibility = composite >= user minimum AND executable == true AND pre-trade validation passed, via one shared function used by both screens. Stale/missing/suspect quote: refetch once; if still stale, neither path can place it; show Quote not current and timestamp. Wide spread: auto-execute off; manual Place Trade only after confirmation stating spread, threshold, and slippage dollars. Non-executable candidates must not outrank executable ones. If none executable, still show best strategy and why it cannot be placed. Risk Review plain reason example: Composite 62.9, Your minimum 50, Not auto-executable: quote 17 min old.
Tests: replay 27 QA cases; no auto-execute eligible while failing executability; blocked message matches the reason shown before click; quote stale between scan and click is caught; score above/below/equal; stale then refreshed; wide spread; no executable candidate.

A2. Session expires mid-use; refresh logs out. Three forced logouts in about 75 minutes (Invalid access token). Reload logs out. Silent refresh before expiry. httpOnly Secure SameSite cookie for refresh token. Never localStorage for tokens. Preserve in-progress scan through re-auth. Read current auth library docs. Tests: 2-hour session, reload every screen, expired access token mid-scan.

A3. Married Put order review omits stock leg (AMD, AAPL showed only the put). Enforce stock leg on card, Risk Review, order, confirmation. If shares already held, say Uses 100 of your N shares. Leg-completeness validator fails if leg count differs from template.

A4. Live AAPL Risk Review: NOT EXECUTABLE stale/suspect quote, then Risk Review BUY 1 AAPL261030P00320000 put 320 exp 2026-10-30 market est premium 4.02 debit 402, composite 59 vs minimum 50, Auto-execute eligible. Acknowledge then Strategy layer is not tradeable. Fixes: disable Acknowledge when not tradeable and show reason before click; never market orders on options, use marketable limit from live bid/ask and show limit and quote time; demo fill must run the same server validation as Alpaca paper; remove filler sentences about paper funded Alpaca or demo fill, OCC symbol boilerplate, and raw us_option; if shares already held, label protective put not married put; composite one decimal.

B1. 46 of 50 NOT EXECUTABLE: 35 stale/suspect, 11 wide spread (SBUX 106 percent of mid, RTX 47, LLY 39, XOM 31). Verify Alpaca Basic plan indicative feed vs OPRA. Cite current Alpaca docs. Log provider, feed, quote time, receipt time, bid, ask, size. Staleness market-hours aware: outside regular hours label last close, do not fail solely for hours. Delayed feed labeled delayed. Do not loosen thresholds. Do not buy a data plan. Report upgrade cost for a team decision. Prefer liquid strikes before declaring non-executable.

B2. Missing earnings is a data gap, never none. NVDA AMD GOOGL showed no date. Alphabet Q3 2026 reported by MarketBeat as 28 October 2026 after close, before a 30 Oct expiry. Cross-check two sources. Conflict or missing: earnings date unverified, and event-risk penalty if expiry could contain a typical report date.

B3. Five names flagged reporting 2026-10-13. JPM IR schedules Q3 2026 for Tuesday 13 October 2026 about 6:45 a.m. ET. Verify GS, C, JNJ, UNH on their own IR pages. Do not fix a correct date.

B4. Index ETFs have no earnings. Classify security type. SPY QQQ must not fail with Earnings date is unconfirmed.

C1. Only 5 strategy types in 50 scans: Diagonal bearish 20, Diagonal bullish 14, Bull Put 6, Married Put 5, Bear Call 5. Gamma Trampoline window met by JPM GS C JNJ UNH (13 Oct), BAC WFC MS BLK (14 Oct), PLD (15 Oct) and selected zero times. Evaluation ledger for every strategy: eligibility per gate with value and threshold, candidates, score components, rank. API and debug view. Explain each of the 10 tickers gate by gate. Missing IV rank is a data defect. Fix unreachable strategies by correct fit, never quotas or randomness.

C2. 27 of 34 diagonals chosen in sell premium. Matrix: IV much below HV is more than 5 vol points below; IV near HV within plus or minus 5; IV much above HV more than 5 above; inversion front >= 1.25 times back. Score vega sign against regime. Long vega in sell premium gets a penalty and a reason unless inversion justifies it.

C3. MSFT TSLA VZ META HD: earnings after short expiry but before long expiry. Event-vega penalty from the long leg IV premium over normal IV. Warning names which leg spans the event and the date.

C4. AMD 0 DTE protective put while how-to says 30-45 DTE. Each strategy has a DTE window. Outside it, use nearest compliant expiry and say so, or penalize with the reason. Never silently contradict. IV rank never shows a dash without a reason.

C5. Sentiment vs direction conflicts (JPM 73 bearish structure, etc.). Why it fits names the conflict, value, weight, and why direction won. Margin below a configurable threshold labels outlook low conviction.

C6. Scores compressed: mean 52.9, stdev 6.6, 34 of 50 between 45 and 55. Report sub-score distributions. Propose calibration. Do NOT change weights without approval.

C6b. AAPL card said fair at IV rank 43.2 while 30-day ATM IV 30.31 vs HV 20.38 (9.93 points, about 1.49x). One regime rule combining IV vs HV (primary) and IV rank, with a tie-break. Show both inputs and the verdict. Structure must match. Evaluate rich-IV alternatives such as a collar and say why the winner ranked first.

C6c. OTM 320 put IV 27.40 vs ATM 30.31 is inverted put skew. Flag inverted skew and bad quotes (bid > ask, IV outside chain range) in the ledger.

C6d. Earnings status confirmed (IR source) or estimated (provider). Show est. when estimated. Apple Oct 29 was an estimate as of mid-September 2026 (The Mac Observer, 13 Sep 2026), not a confirmed company date.

C7. Search: exact symbol, then prefix, then name. MS should return Morgan Stanley. Exact tickers first. Results within 300 ms via debounce and cache.

C8. One decimal composite everywhere via the shared formatter.

D1. Every Change 7 strategy plus APEX Benchmark Greeks and Gamma Trampoline (Change 11 v2) has required fields including DTE window and greek signs. Validator fails the build on gaps.

D2. Evidence ledger: every card value records inputs, source, feed, timestamp, function. Models may write text only from ledger values. Post-generation validator rejects unmatched numbers, percents, dates, tickers and falls back to the KB template. Log rejections. High/low/rich/cheap claims must cite ledger value and threshold.

D3. At least 5 hand-verified scenarios per strategy with recorded chains. Payoff within 0.01. Ledger complete.

D4. QA replay regression for the 50 cases: A1 gating, leg counts, regime consistency, earnings, zero unmatched narrative numbers.

Part E acceptance after re-run: zero NOT EXECUTABLE plus auto-execute eligible; zero forced logouts in 2 hours and reload keeps session; stock legs shown; quotes show feed and timestamp; GOOGL earnings 28 Oct 2026 verified and unknown is never none; ledger explains the 10 Trampoline tickers; unreachable strategies fixed without quotas; zero unmatched numbers; full suite green; nothing outside scope changed.
