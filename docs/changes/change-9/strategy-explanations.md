# Change 9 — Strategy explanations and payoff numbers

The strategy card (`StrategyScan`) reads `what_is_this`, `why_it_fits`, `how_to_execute`, and the payoff fields on `metrics`. Those strings are built in `build_strategy_layer` (`backend/app/services/strategy_engine.py`). The numbers for a documented expiry payoff are recomputed from the legs in `quote_documented_structure` (`backend/app/strategies/structure_math.py`) and applied in `metrics_builder._finalize`.

## What was wrong

The playbook essay was chosen by the strategy title. A title such as Long Call, Bull Call Spread, or APEX Benchmark Greeks Strategy could supply “buy a call” copy while the legs were a different structure. A bull put credit spread must not be described as a long call.

Calendars, diagonals, butterflies, and ratios were also publishing a scanned or simplified max profit. That number is not a closed form. After the short expires, the result depends on the remaining long leg.

## What the card does now

Copy is written from the legs (action, side, strike, expiration). A title’s playbook line is kept only when it describes that same geometry. “NO TRADE” and “Stand aside” are not used as the definition.

Undefined-risk names still show Unlimited on the unbounded side. They do not get a finite stand-in.

## Verified closed forms

Applied only when the legs match the geometry. Money is per share times the contract multiplier (100).

| Structure | Max profit | Max loss | Breakeven |
| --- | --- | --- | --- |
| Bull put credit spread | credit × multiplier | (width − credit) × multiplier | short strike − credit |
| Bear call credit spread | credit × multiplier | (width − credit) × multiplier | short strike + credit |
| Bull call debit spread | (width − debit) × multiplier | debit × multiplier | long strike + debit |
| Bear put debit spread | (width − debit) × multiplier | debit × multiplier | long strike − debit |
| Short iron condor | credit × multiplier | (wider wing − credit) × multiplier | short put − credit, short call + credit |
| Long iron condor | (wider wing − debit) × multiplier | debit × multiplier | long put + debit, long call − debit |
| Long call | Unlimited | premium × multiplier | strike + premium |
| Long put | (strike − premium) × multiplier | premium × multiplier | strike − premium |

Registry names that use these formulas when the legs match:

- Long call family: Long Call, APEX Benchmark Greeks Strategy, Long Call LEAPS, Deep ITM Call, At-The-Money Call, VIX Call Hedge
- Long put family: Long Put, Long Put LEAPS, Deep ITM Put
- Debit verticals: Bull Call Spread, Call Debit Spread, Wide Bull Call Spread, Bear Put Spread, Put Debit Spread, Wide Bear Put Spread, Vega Neutral Spread (the built legs are a call debit vertical, so the bull-call formula is the one applied)
- Credit verticals: Bull Put Spread (credit), Put Credit Spread, Bear Call Spread (credit), Call Credit Spread
- Short iron condor family: Short Iron Condor, Iron Condor (wide), IV Crush Short Iron Condor, Theta Harvest Iron Condor, Iron Condor (monthly)
- Long iron condor family: Long Iron Condor, Reverse Iron Condor

Married Put is a long put on the option leg. Stock is assumed already held, so `quote_documented_structure` does not treat the whole position as a new closed form.

## No closed form

Calendars, diagonals, butterflies, and ratios. This pass did not invent an expiry formula for them. Max profit on the card is empty, not Unlimited and not a scanned dollar amount. The explanation states that the payoff depends on the remaining long leg.

- Calendars and diagonals: Calendar Spread, Calendar Put Spread, Calendar Call Spread, Double Calendar, Calendar Straddle, Reverse Calendar, Diagonal Spread (bullish), Diagonal Spread (bearish), Diagonal Call Spread, Double Diagonal, Jelly Roll, Poor Man's Covered Call
- Butterflies: Long Call Butterfly, Long Put Butterfly, Short Call Butterfly, Short Put Butterfly, Iron Butterfly, Long Iron Butterfly, Short Iron Butterfly (variant), Broken Wing Butterfly, Skip Strike Butterfly
- Ratios: Ratio Spread, Call Ratio Spread, Put Ratio Spread, 1x2 Ratio Spread, 2x1 Ratio Spread, Christmas Tree Spread

Back Ratio Spread, Call Backspread, and Put Backspread are also ratios. Their profit side is unlimited because the long quantity exceeds the short. That Unlimited flag is not a scanned dollar max profit. Their loss figure is not a verified closed form.

## Not given a new closed form

These names keep their existing handlers. This pass did not add a formula and did not mark them verified:

Naked Call, Naked Put, Wheel Strategy, Long Straddle, Long Strangle, Long Straddle LEAPS, Synthetic Straddle, Long Straddle (pre-earnings), Gamma Scalping, Earnings Straddle, Short Straddle, Short Strangle, Short Guts, Long Guts, Strip, Strap, Condor Spread (call), Condor Spread (put), Jade Lizard, Reverse Jade Lizard, Covered Call, Stock + Short Call, Covered Put, Leveraged Covered Call, Protective Collar, Collar, Stock + Long Put, Synthetic Long Stock, Synthetic Short Stock, Synthetic Call, Synthetic Put, Long Combo, Short Combo, Conversion, Reversal, Box Spread, Risk Reversal, Volatility Skew Trade, Dispersion Trade, APEX Strategy.

Naked calls and naked puts show Unlimited for max loss. APEX Strategy has no closed-form max profit; the remaining long legs are still open after the front expiration.

NO TRADE — Insufficient Conviction and NO TRADE — Wait for IV Crush are advisory catalog entries. They are not a Best Match and they are not a structure description.
