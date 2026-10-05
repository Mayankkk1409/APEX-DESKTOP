# Change 11 v2 — master-sheet corrections

Knowledge base version: **11.2**.

Citations name the public education sources. No copyrighted pages are copied.

| Source | What was checked |
| --- | --- |
| OCC, *Characteristics and Risks of Standardized Options* | Long call and long put: max loss is the premium, long-call max profit is unlimited, long-put max profit is strike minus premium, breakevens are strike ± premium. |
| Options Industry Council (optionseducation.org) | Debit verticals, calendars, and the double-calendar debit. Max loss of a long calendar, held to the near expiry and closed together, is the net debit. |
| Cboe options strategy education | Credit vertical: max profit is the credit, max loss is width minus credit, breakeven is the short strike minus the credit (put) or plus the credit (call). Short iron condor uses the wider wing the same way, with two breakevens. |

## Logged changes

| Strategy | Field | Before | After | Reason | Reference |
| --- | --- | --- | --- | --- | --- |
| APEX Strategy | summary, execution, scenarios | Double-calendar playbook plus an older A/B/C story (moderate move, gap, flat result tied to back-week IV). | Registry name stays "APEX Strategy" and describes a double calendar. Gamma Trampoline™ is used only when the earnings gates pass, with the approved summary, problem, Greeks, scenarios, and how-to. | The old scenario prose conflicted with the approved A/B/C text. | OIC calendar education. The earnings label is the team's approved text. |
| APEX Benchmark Greeks Strategy | summary, how to use, risk | Proprietary long-premium line: delta at least 0.55, daily theta under 0.05, exit on a SuperTrend flip or a composite drop below 72. | Two entries. Rule 1 is one long call or one long put. Rule 2 is a defined-risk credit structure. Verbatim summary, why, how-to, ratio explanation, and key risks. | The old exit line and the absolute theta cap are not the approved rules. | OCC long-option identities. Cboe credit-spread and condor identities. |
| Rule 1 only | theta cap | 1.5% of premium (`theta_max_pct_per_day` 0.015) for long premium. | 1.0% of the mid (`rule1_theta_pct_per_day` 0.010) for this rule only. The 1.5% cap remains for other long-premium names. | Approved Rule 1 gate. | Named setting. Not a performance claim. |
| Rule 1 only | delta/theta ratio | `abs(delta) / abs(theta)`. | `(abs(delta) × spot × 0.01) / abs(theta per share)`. Must be above 10. The older ratio function is unchanged for other gates. | Approved definition: a 1% move versus one day of decay. Hand check: delta 0.60, spot 250, theta 0.08 → 18.75. Theta 0.20 → 7.5. | Named setting `rule1_delta_theta_ratio_min`. |
| Gamma Trampoline™ | earnings gates | Vol-point inversion, a 50% premium-offset hard gate, and a 0.15–0.25 delta band. | Calendar days 5–10 on a confirmed date, front IV rank above 70, front IV / back IV at least 1.25, at least 5 of the last 8 earnings moves smaller than the implied move, ADV above 5,000,000, open interest above 1000, spread under 8% of mid, both expiries listed. Offset is measured and shown, not gated. Strikes are spot ± the front ATM straddle. | Approved gates. A missing earnings date or a missing 8-report history fails closed. | OIC, for the debit cap. The gates are named settings. |
| Reverse Calendar | payoff grid and knowledge-base loss text | The standard calendar formula (short the near option, long the later option) was applied to legs that buy the near call and sell the later call. The shared calendar blurb said the loss was the debit. | The near expiry is valued as a long intrinsic leg and the later leg as a short European Black-Scholes leg. The knowledge-base row says the later short is uncovered after the near expiry, so the loss is not the debit. | The published grid was the sign-flip of the legs. | OCC short-call risk: once the long near call expires, the later short call is uncovered. |

## Checked, no field change

These identities already matched the sources above on at least three fixtures (different prices, widths, and contract counts), including stock legs where the template has stock. No wording change.

- Long call and long put, including the Rule 1 card math.
- Bull call and bear put debit verticals.
- Bull put and bear call credit spreads, and the short iron condor, including Rule 2.
- Long iron condor.
- Covered call, protective put, and collar, with the stock share count in the formula.
- Same-expiry butterflies, condors, straddles, and strangles: the expiry grid matches intrinsic value within $0.01.
- Standard calendars and diagonals: short the nearer expiry, long the later expiry, European Black-Scholes on the remaining leg.

The phrase "consistent edge through volume" was not in the knowledge base. The validator rejects it, along with "guaranteed" and "risk-free", except on the verbatim approved entries. The Rule 2 summary keeps the word "always" because that sentence is approved text ("always with a protective wing").
