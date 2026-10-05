# Master sheet verification

Authoritative list: `backend/app/strategies/registry.py` (100 display names). The repo has no xlsx, csv, or pptx master sheet. `docs/APEX_Options_Platform_Full_Document.txt` §9.1 is a short eligibility matrix, not this catalog.

Checked each name against the registry, the legs `build_registry_metrics` actually builds, the playbook or leg sentence shown as “What is this” / “How to execute”, and the payoff. Verticals, long call, long put, and iron condors use the closed form in `structure_math.py` (debit or credit, wing width, breakeven). Calendars, diagonals, butterflies, and ratios are marked not-applicable: there is no single expiry formula, and the card does not print a finite max profit for that side. Unlimited profit or loss is the word Unlimited, not a dollar figure.

| | Count |
|---|---:|
| Strategies on the sheet | 100 |
| Verified with no remaining defect | 100 |
| Defects fixed in this pass | 12 |
| Still open | 0 |

Fixed in this pass: long and reverse iron condors (they were short condors and showed a negative max profit), the wide iron condor, double diagonal, jelly roll, long and short guts, broken-wing and skip-strike butterflies, the christmas tree (unlimited upside loss, no invented max profit), the 2x1 ratio (unlimited profit, loss not labeled unlimited), and the volatility skew trade (buy the put, sell the call). A neutral strategy picked against a directional tape no longer describes every name as an iron-condor premium sale. Call and put condor max profit uses the narrower wing, not the distance between the short strikes. Equal wings were already the same number.

| Strategy | Present | Legs ok | Explanation ok | Math | Defect |
|---|---|---|---|---|---|
| Long Call | yes | yes | yes | ok |  |
| Long Put | yes | yes | yes | ok |  |
| Naked Call | yes | yes | yes | ok |  |
| Naked Put | yes | yes | yes | ok |  |
| APEX Benchmark Greeks Strategy | yes | yes | yes | ok |  |
| Long Call LEAPS | yes | yes | yes | ok | Was the front expiry. Now a call more than a year out. The long-call formula matches that leg. |
| Long Put LEAPS | yes | yes | yes | ok | Was the front expiry. Now a put more than a year out. The long-put formula matches that leg. |
| Deep ITM Call | yes | yes | yes | ok | Was tagged ATM and built at the money. Now tagged deep ITM, with the call strike at least 10% below spot. The long-call formula matches that leg. |
| Deep ITM Put | yes | yes | yes | ok | Was tagged ATM and built at the money. Now tagged deep ITM, with the put strike at least 10% above spot. The long-put formula matches that leg. |
| At-The-Money Call | yes | yes | yes | ok |  |
| Bull Call Spread | yes | yes | yes | ok |  |
| Bear Put Spread | yes | yes | yes | ok |  |
| Bull Put Spread (credit) | yes | yes | yes | ok |  |
| Bear Call Spread (credit) | yes | yes | yes | ok |  |
| Call Debit Spread | yes | yes | yes | ok |  |
| Put Debit Spread | yes | yes | yes | ok |  |
| Call Credit Spread | yes | yes | yes | ok |  |
| Put Credit Spread | yes | yes | yes | ok |  |
| Wide Bull Call Spread | yes | yes | yes | ok |  |
| Wide Bear Put Spread | yes | yes | yes | ok |  |
| Long Straddle | yes | yes | yes | ok |  |
| Long Strangle | yes | yes | yes | ok |  |
| Short Straddle | yes | yes | yes | ok |  |
| Short Strangle | yes | yes | yes | ok |  |
| Long Guts | yes | yes | yes | ok | Was an at-the-money straddle. Now an in-the-money call and an in-the-money put. |
| Short Guts | yes | yes | yes | ok | Was an at-the-money straddle. Now a short in-the-money call and put. |
| Strip | yes | yes | yes | ok |  |
| Strap | yes | yes | yes | ok |  |
| Long Straddle LEAPS | yes | yes | yes | ok | Was the front expiry. Now a call and a put more than a year out. Profit is Unlimited. |
| Short Iron Butterfly (variant) | yes | yes | yes | not-applicable |  |
| Calendar Spread | yes | yes | yes | not-applicable |  |
| Calendar Put Spread | yes | yes | yes | not-applicable |  |
| Calendar Call Spread | yes | yes | yes | not-applicable |  |
| Double Calendar | yes | yes | yes | not-applicable |  |
| Diagonal Spread (bullish) | yes | yes | yes | not-applicable |  |
| Diagonal Spread (bearish) | yes | yes | yes | not-applicable |  |
| Double Diagonal | yes | yes | yes | not-applicable | Was the same strikes as a double calendar. Now a back-month long call and put against nearer OTM shorts. |
| Reverse Calendar | yes | yes | yes | not-applicable |  |
| Calendar Straddle | yes | yes | yes | not-applicable |  |
| Diagonal Call Spread | yes | yes | yes | not-applicable |  |
| Long Call Butterfly | yes | yes | yes | not-applicable |  |
| Long Put Butterfly | yes | yes | yes | not-applicable |  |
| Iron Butterfly | yes | yes | yes | not-applicable |  |
| Short Iron Condor | yes | yes | yes | ok |  |
| Long Iron Condor | yes | yes | yes | ok | Was built as a short condor and showed a negative max profit. Now buys the body and sells the wings. |
| Broken Wing Butterfly | yes | yes | yes | not-applicable | Upper wing now skips a strike, so the wings are not equal. |
| Skip Strike Butterfly | yes | yes | yes | not-applicable | Upper wing now skips a strike. |
| Iron Condor (wide) | yes | yes | yes | ok | Wings now skip one strike instead of matching the tight condor. |
| Condor Spread (call) | yes | yes | yes | ok |  |
| Condor Spread (put) | yes | yes | yes | ok |  |
| Reverse Iron Condor | yes | yes | yes | ok | Was built as a short condor and showed a negative max profit. Now buys the body and sells the wings. |
| Long Iron Butterfly | yes | yes | yes | not-applicable |  |
| Short Call Butterfly | yes | yes | yes | not-applicable |  |
| Short Put Butterfly | yes | yes | yes | not-applicable |  |
| Christmas Tree Spread | yes | yes | yes | not-applicable | Net short one call. Max loss is Unlimited. No finite max profit is shown. |
| Ratio Spread | yes | yes | yes | not-applicable |  |
| Call Ratio Spread | yes | yes | yes | not-applicable |  |
| Put Ratio Spread | yes | yes | yes | not-applicable |  |
| Back Ratio Spread | yes | yes | yes | ok |  |
| Call Backspread | yes | yes | yes | ok |  |
| Put Backspread | yes | yes | yes | ok |  |
| 1x2 Ratio Spread | yes | yes | yes | not-applicable |  |
| 2x1 Ratio Spread | yes | yes | yes | not-applicable | Long 2, short 1. Profit is Unlimited. Loss is not labeled unlimited. |
| Jade Lizard | yes | yes | yes | ok |  |
| Reverse Jade Lizard | yes | yes | yes | ok |  |
| Covered Call | yes | yes | yes | ok |  |
| Covered Put | yes | yes | yes | ok |  |
| Married Put | yes | yes | yes | ok |  |
| Leveraged Covered Call | yes | yes | yes | ok |  |
| Protective Collar | yes | yes | yes | ok |  |
| Stock + Short Call | yes | yes | yes | ok |  |
| Stock + Long Put | yes | yes | yes | ok |  |
| Collar | yes | yes | yes | ok |  |
| Synthetic Long Stock | yes | yes | yes | ok |  |
| Synthetic Short Stock | yes | yes | yes | ok |  |
| Synthetic Call | yes | yes | yes | ok | Long stock plus a long put. Profit is Unlimited. Loss is the stock price minus the put strike, plus the put premium. |
| Synthetic Put | yes | yes | yes | ok | Short stock plus a long call. Profit is finite because the stock cannot trade below zero. The long call caps the upside loss. |
| Conversion | yes | yes | yes | ok |  |
| Reversal | yes | yes | yes | ok |  |
| Box Spread | yes | yes | yes | ok |  |
| Jelly Roll | yes | yes | yes | not-applicable | Was a double calendar. Now a long back-month synthetic against a short front-month synthetic. |
| Long Combo | yes | yes | yes | ok |  |
| Short Combo | yes | yes | yes | ok |  |
| Risk Reversal | yes | yes | yes | ok |  |
| Synthetic Straddle | yes | yes | yes | ok | Long stock plus two long puts at one strike. Profit is Unlimited. Loss at the strike is finite. |
| Long Straddle (pre-earnings) | yes | yes | yes | ok |  |
| IV Crush Short Iron Condor | yes | yes | yes | ok |  |
| Volatility Skew Trade | yes | yes | yes | ok | Now buys the OTM put and sells the OTM call. Profit is capped at a stock price of zero. Upside loss is Unlimited. |
| VIX Call Hedge | yes | yes | yes | ok |  |
| Dispersion Trade | yes | yes | yes | not-applicable | Infeasible on a single-name scan. It needs an index and a component, so no legs are built and it is not a Best Match. A second underlying is not invented. |
| APEX Strategy | yes | yes | yes | ok |  |
| Gamma Scalping | yes | yes | yes | ok |  |
| Vega Neutral Spread | yes | yes | yes | not-applicable | Same call strike is bought and sold across two expirations, with quantities set so the vegas offset. A same-expiry vertical is not built. No closed-form max profit. |
| Theta Harvest Iron Condor | yes | yes | yes | ok |  |
| Earnings Straddle | yes | yes | yes | ok |  |
| Iron Condor (monthly) | yes | yes | yes | ok |  |
| Wheel Strategy | yes | yes | yes | ok | Cash-secured short put. The covered-call stage is built only when the account already holds the shares. An unrelated spread is not labeled a wheel. |
| Poor Man's Covered Call | yes | yes | yes | not-applicable | Diagonal: long far-dated in-the-money call and short nearer out-of-the-money call. Payoff depends on the long leg, so no finite max profit is shown. |
| NO TRADE — Insufficient Conviction | yes | yes | yes | not-applicable |  |
| NO TRADE — Wait for IV Crush | yes | yes | yes | not-applicable |  |

Row check: 100 without an open defect, 0 still open. The previous tally of 8 was the three LEAPS names, the two deep ITM names, and the three synthetic names. Those builders already match the rows above.

