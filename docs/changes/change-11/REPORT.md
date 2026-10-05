# Change 11 v2

Finished all four parts. The European Black-Scholes simulation does **not** contradict the approved scenario text. There is no American pricer. The card says so.

Full backend suite: **1480 passed, 59 skipped**.

## Brainstorm

Two knowledge-base entries cover the APEX Benchmark Greeks Strategy: `apex_benchmark_greeks_buy` (Rule 1) and `apex_benchmark_greeks_sell` (Rule 2). The registry stays at 100 names. Gamma Trampoline™ is the earnings label for the existing four-leg structure, not a 101st strategy. The same four legs without the earnings gates stay a double calendar.

A failed gate marks that strategy ineligible and names the gate and the value. The best match stays another real structure. It is not replaced with NO TRADE or Wait for IV Crush.

Every threshold is a setting with the stated default. Rule 1's 1.0% theta cap and the spot-scaled ratio do not replace the older 1.5% cap or the older delta/theta helper used by other long-premium names.

Directional alignment uses the pillars already on the scan:

- Technical direction is the existing synthesized trend (SuperTrend, MACD histogram, and the EMA stack). The scan publishes it as bullish, bearish, or neutral.
- Sentiment score is the existing 0–100 pillar. Clearly bullish means that score is at least 65 and the bias text contains "bull". Clearly bearish means the score is at or below 40. Those two lines are the existing actionable bullish line and the existing Bearish band.
- Mild bullish is a bullish trend that is not that clear pair. Mild bearish is the bearish equivalent. Neutral is neither.
- Rule 1 needs the clear pair. Rule 2 uses neutral for an iron condor, mild bullish for a bull put credit spread, and mild bearish for a bear call credit spread. A clear directional pair is not a Rule 2 structure.

HV20 is the existing 20-day close-to-close historical volatility, annualized with sqrt(252). It is not the 30-day HV series.

## Research and Analysis

An arbitrary premium set contradicted the scenarios: a flat outcome lost money, and net gamma before the event was slightly positive. A Black-Scholes-consistent chain does not. The shipped fixture is front IV 55%, back IV 36%, post-event IV 28% (the pre-event 30-day average in this fixture), 7 and 21 calendar days, spot 100. Expected move is the front at-the-money straddle, about 6.08. Nearest strikes are 106 and 94. Net debit is about 0.617 per share, $61.72 per unit. That run is the one behind the tables below.

Loss on that grid never exceeds the debit. With rate 0 and carry 0, a European option is worth at least its intrinsic value, so closing all four legs by the front expiry cannot lose more than the debit. The card confirms that on the price grid before the scenario text is shown. If a live chain ever breaks that bound by more than $0.01, `scenario_conflict` is set and the scenario sentences are left off that card.

Probability of profit uses the event-variance method stated on the card: the front at-the-money straddle is the expected move, the terminal price is lognormal with that move as one standard deviation, and the probability is the mass between the two model breakevens.

Earnings-move history is not invented. The gate reads `earnings_move_history` when a caller supplies it. If the eight reports are absent, the gate fails closed.

Order routing is the Change 10 path. Two or more option legs go as one combo limit at the net mid. A rejection is not split into separate market orders. Stock fills before a short call.

## Phased Checklist

1. Part A — Rule 1 and Rule 2 gates, structures, hand ratio, credit math, and ranking. Tests passed before Part B was treated as done.
2. Part B — Gamma Trampoline™ gates, four-leg fixture, simulation, sensitivity, classifier, and one combo order. Tests passed before the master sheet.
3. Part C — Knowledge-base validator, payoff grids, and this file's sibling `CORRECTIONS.md`. Version 11.2.
4. Part D — Full backend suite, including the purpose-built ranking scenarios.

## Execute

Knowledge base version 11.2. Validator runs at API startup.

Rule 1 card text is applied when the built structure is one long option. Rule 2 card text is applied when that structure won because the Rule 2 gates passed. Gamma Trampoline™ card text is applied only under that name.

### APEX Benchmark Greeks Strategy

Summary, verbatim:

The APEX Benchmark Greeks Strategy is a rules-based framework that uses an option's Greeks to decide when to buy options for directional exposure and when to sell options for premium income. Rule 1 buys options only when they offer strong directional exposure for little time decay. Rule 2 sells options only when implied volatility is elevated, momentum is neutral, and the short strike is far from the current price, always with a protective wing so risk is defined.

Rule 1 why it fits, verbatim:

High delta gives the option meaningful participation in the stock's move, while its daily time decay is small relative to its price. Implied volatility is below the stock's recent realized volatility, so you are not overpaying for the option.

Rule 1 ratio, verbatim:

The ratio compares what a 1% move in your favor earns against what one day of time decay costs. A ratio above 10 means a 1% favorable move earns more than ten days of decay.

Rule 1 how to use, verbatim:

Buy the option with a limit order near the mid-price. Size the position so that the full premium is an amount you can afford to lose. Consider taking profits at a predefined target, and exit or re-evaluate if the trend or sentiment alignment breaks. Close or roll before the final 21 days, when time decay accelerates.

Rule 1 key risks, verbatim:

The full premium can be lost if the stock does not move in the expected direction before expiration. A drop in implied volatility reduces the option's value even when the stock price is unchanged.

Rule 1 risk math: long call max loss is premium × multiplier × contracts, max profit unlimited, breakeven strike + premium. Long put max loss is the same premium amount, max profit is (strike − premium) × multiplier × contracts, breakeven strike − premium.

Rule 2 why it fits, verbatim:

Implied volatility is high relative to its past year, so option premiums are rich. Momentum is neutral, which suggests the stock is less likely to make a strong directional move. The short strike sits well outside the current price, and the long wing caps the maximum loss.

Rule 2 probability, verbatim:

A short-strike delta of 0.20 or less roughly corresponds to an 80% or greater chance that strike expires out of the money, under standard pricing assumptions. The app shows the model-calculated probability of profit for the entire position, which is the figure to rely on.

Rule 2 how to use, verbatim:

Enter with a limit order near the mid-price for the net credit. A common management approach is to close the position once about 50% of the maximum profit has been captured, and to close it if the loss reaches about 2 times the credit received or the position reaches 21 days to expiration, whichever comes first. Watch for early-assignment risk on short calls ahead of ex-dividend dates.

Rule 2 key risks, verbatim:

A sharp move through the short strike can produce a loss up to the stated maximum. High implied volatility can rise further before it falls. Early assignment of a short option is possible, especially before ex-dividend dates.

Rule 2 risk math: credit-spread max profit is net credit × multiplier × contracts, max loss is (width − net credit) × multiplier × contracts, breakeven is the short put strike minus the credit or the short call strike plus the credit. Iron condor max profit is net credit × multiplier × contracts, max loss uses the wider wing the same way, and the breakevens are the short put strike minus the net credit and the short call strike plus the net credit. A missing wing does not become a naked short.

Settings, defaults: Rule 1 delta 0.55, DTE 30–90, theta percent 0.010, ratio above 10, spread under 8% of mid, sentiment 65 and 40. Rule 2 IV rank above 50, RSI 40–60, short delta 0.20, DTE 30–45, wing width 3% of spot, spread under 10% of mid, credit at least 20% of the wing width.

### Gamma Trampoline™

Title uses the trademark. Summary, verbatim:

The Gamma Trampoline is APEX's earnings volatility strategy, built on a double calendar structure. It sells front-week options while their implied volatility is inflated ahead of earnings, and buys the same strikes in a later expiration that keep more of their value once the announcement passes. It profits when the post-earnings move stays within or near the expected range and front-week volatility collapses. The maximum loss is limited to the net debit paid when all legs are closed together by the front-week expiration.

Problem, Greeks, scenarios A/B/C, and how to use are the approved paragraphs in `backend/app/strategies/knowledge_base.py` (`GAMMA_PROBLEM`, `GAMMA_GREEKS`, `GAMMA_SCENARIOS`, `GAMMA_HOW`). They are not paraphrased here.

Classifier: Gamma Trampoline™ only when every earnings gate passes. Otherwise the structure is a double calendar.

### Simulation at the default post-event IV (28%)

Priced with European Black-Scholes. Spot 100, strikes 94 and 106, expected move about 6.08, debit $61.72. Net gamma before the event about −0.0042. After the front expiry the remaining long strangle gamma is positive (about 0.080 at the spot under the same IV).

| Move, in expected-move units | P&L |
| --- | ---: |
| −2.0 | −35.63 |
| −1.5 | 22.20 |
| −1.0 (near strike B) | 142.68 |
| −0.5 | 43.76 |
| 0 | 14.44 |
| +0.5 | 59.17 |
| +1.0 (near strike A) | 169.11 |
| +1.5 | 50.46 |
| +2.0 | −14.48 |

Profit is highest near strikes A and B. The flat outcome is a profit. Both two-expected-move outcomes lose. Neither loss exceeds the $61.72 debit. Model breakevens at this IV: 90.01 and 111.27. Grid max profit: 172.89. Model probability of profit about 91.9% by the event-variance method. That figure is the model output for this fixture, not a performance claim.

### Sensitivity of the post-event IV assumption

The default assumption is 28%. The other two rows are 50% and 150% of that default. Max loss stays the debit on all three.

| Scale | Post-event IV | Grid max profit | Breakevens | Worst grid P&L |
| --- | ---: | ---: | --- | ---: |
| 0.50 | 14% | 54.23 | 93.05, 94.98, 104.70, 107.34 | −61.72 |
| 1.00 | 28% | 172.89 | 90.01, 111.27 | −61.72 |
| 1.50 | 42% | 312.32 | 86.47, 116.21 | −61.72 |

A deeper crush (half the default IV) lowers the modeled max profit. The payoff then crosses zero more than twice, so the scan reports four breakevens instead of two. A milder crush (1.5 times the default) raises the max profit and widens the two-breakeven interval. The approved scenarios are statements about the default assumption. They still hold there.

## Test and Verify

Part A: bullish fixture returns a long call, bearish fixture a long put. One fixture fails each Rule 1 gate alone (alignment, delta, DTE, theta percent, ratio, IV versus HV, spread) with that reason. Puts use absolute delta. Ratio 18.75 passes and 7.5 fails. Neutral builds an iron condor, mild bullish a bull put spread, mild bearish a bear call spread. Rejections cover IV rank 45, RSI 35, RSI 65, short delta 0.25, a 12% spread on one leg, and a credit below 20% of width. No naked short is returned. Credit-spread and condor dollars match the hand values, including a wider call wing and a 3-contract condor.

Part B: eligible fixture has four legs, one call strike and one put strike shared across the front expiry and the back expiry. One fixture fails each earnings gate with the stated reason, including a missing date and a missing eight-report history. The simulation assertions above are in `backend/tests/test_change11.py`. All four legs submit as one combo limit.

Part C: `validate_knowledge_base()` is clean. Every registry strategy has the required fields. Payoff checks cover three fixtures per strategy. Path: `docs/changes/change-11/CORRECTIONS.md`.

Part D: both strategies are evaluated on every recommendation. Rule 1 ranks first in five purpose-built scans. Gamma Trampoline™ ranks first in five earnings scans. Rule 2's iron condor ranks first in five neutral scans, and the two credit spreads rank first for mild bullish and mild bearish. Full suite: 1480 passed, 59 skipped.

### Files changed for this change, and why

- `backend/app/strategies/knowledge_base.py` — version 11.2, verbatim entries, reverse-calendar correction, startup validator.
- `backend/app/services/benchmark_greeks.py` — Rule 1 and Rule 2 evaluation. A failed wing is not a naked short.
- `backend/app/services/apex_strategy.py` — earnings gates and the classifier.
- `backend/app/config.py`, `backend/app/analysis/gate_config.py`, `.env.example` — named defaults only. No secrets.
- `backend/app/services/strategy_recommendation.py` — both strategies scored on every scan; a pass is inserted by score.
- `backend/app/services/strategy_engine.py` — card fields render the knowledge-base paragraphs; limit-at-mid is priced when the text says mid-price.
- `backend/app/services/scan_engine.py` — live scans pass chain delta, theta, HV20, RSI, IV rank, and the contracts into the rules.
- `backend/app/strategies/metrics_builder.py` — expected-move strikes, measured premium offset, Rule 1 long option, reverse-calendar sign.
- `backend/app/strategies/payoffs/core.py` — European double-calendar grid, event-variance probability, IV-crush sensitivity, reverse-calendar sign.
- `backend/app/main.py` — knowledge base must validate before the app serves.
- `backend/app/services/options_analysis.py` — Gamma Trampoline™ follows the same four-leg bucket as the registry structure.
- Tests listed in `backend/tests/test_change11.py`, `test_change11_master_sheet.py`, and the fixture updates in the existing apex, coverage, registry, card, and brokerage tests.

This change did not edit frontend UI, layout, CSS, or cosmetic copy. The working tree still contains frontend edits from earlier changes. They were not part of Change 11.

### Remaining limitations

- There is no American pricer. Max profit, breakevens, and the scenario checks use European Black-Scholes with rate 0 and carry 0, and the card says so. Early assignment is named in the risk notes and is not priced.
- A live scan has no earnings-move history unless the caller supplies `earnings_move_history`. The history gate then fails closed, so a live card is not labeled Gamma Trampoline™ on missing history.
- If a 30-day pre-event average is not supplied, the back-leg IV already on the chain is used and the note says a 30-day average was not supplied.
- The registry display name of the four-leg id remains "APEX Strategy". The trademark is the classifier label when the gates pass.
- `frontend/src/lib/strategyDisplay.ts` rewrites a Gamma Trampoline™ title to "APEX Strategy" before the card title renders. Body fields are not rewritten. This change did not edit that file. The title the user sees can therefore still say APEX Strategy while the body carries the trademark paragraphs.
- The 50% IV-crush row can show four breakevens. The default assumption shows two.
- No performance claim is made. The probability figure is the model output for the position, as the approved probability sentence says.
