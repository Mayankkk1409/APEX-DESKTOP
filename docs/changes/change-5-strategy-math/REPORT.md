# Change 5 — Strategy payoff on the recommendation

## What a recommendation shows

The strategy layer returns one Best Match with:

- **Name** — `selected_strategy`
- **Outlook** — playbook bias when the name is in the existing matrix (`bullish`, `bearish`, or `neutral`); otherwise the scan direction
- **Legs** — chain contracts chosen by the existing builders, with mids from bid/ask
- **Why it fits** — `why_it_fits` (also written into `why_recommended` on a tradeable match). It cites composite, technical score, volatility regime, and IV versus HV only when those values are already on the scan
- **Net debit/credit** — sum of leg mids
- **Max profit, max loss, breakevens** — closed form when the legs match a documented structure below
- **Unlimited** — `max_profit` or `max_loss` stays null and `max_profit_unlimited_allowed` / `max_loss_unlimited_allowed` is set. The strategy card prints Unlimited. Undefined-risk names do not get a scanned stand-in for the unbounded side

Money inside the closed form uses `Decimal`, quantized to cents before the JSON numbers are stored.

## Formulas applied

From `backend/app/strategies/payoffs/core.py`, recomputed in `backend/app/strategies/structure_math.py` from leg mids:

| Structure | Max loss | Max profit | Breakeven |
| --- | --- | --- | --- |
| Debit vertical (call) | net debit × multiplier | (width − debit) × multiplier | long strike + debit |
| Debit vertical (put) | net debit × multiplier | (width − debit) × multiplier | long strike − debit |
| Credit vertical (put) | (width − credit) × multiplier | credit × multiplier | short strike − credit |
| Credit vertical (call) | (width − credit) × multiplier | credit × multiplier | short strike + credit |
| Short iron condor | (wider wing − credit) × multiplier | credit × multiplier | short put − credit, short call + credit |
| Long iron condor | net debit × multiplier | (wider wing − debit) × multiplier | long put + debit, long call − debit |
| Long call | premium × multiplier | Unlimited | strike + premium |
| Long put | premium × multiplier | (strike − premium) × multiplier | strike − premium |

A quote is applied only when the legs match that geometry. Equity overlays are left on their existing handlers.

## Tests

`backend/tests/test_structure_payoff.py`

- Bull call: debit 2.00, max loss 200, max profit 300, breakeven 102. Grid P&L stays within $0.01
- Short iron condor: credit 1.80, max profit 180, max loss 320, breakevens 93.20 and 106.80. Grid P&L stays within $0.01
- Chain-built bull call: max loss equals net debit × multiplier
- Naked call: max loss is null with `max_loss_unlimited_allowed`

## Strategy types without this closed form

These keep their existing payoff handlers. Names are the registry display names.

- Naked Call, Naked Put, Wheel Strategy (`payoff_short_option`)
- Long Straddle, Long Straddle LEAPS, Synthetic Straddle, Long Straddle (pre-earnings), Gamma Scalping, Earnings Straddle (`payoff_long_straddle`)
- Long Strangle (`payoff_long_strangle`)
- Short Straddle, Short Guts (`payoff_short_straddle`)
- Short Strangle (`payoff_short_strangle`)
- Long Guts (`payoff_long_guts`)
- Strip (`payoff_strip`)
- Strap (`payoff_strap`)
- Short Iron Butterfly (variant), Iron Butterfly (`payoff_iron_butterfly`)
- Long Iron Butterfly (`payoff_long_iron_butterfly`)
- Calendar Spread, Calendar Put Spread, Calendar Call Spread, Diagonal Spread (bullish), Diagonal Spread (bearish), Reverse Calendar, Diagonal Call Spread (`payoff_calendar_spread`)
- Double Calendar, Double Diagonal, Calendar Straddle (`payoff_double_calendar`)
- Long Call Butterfly, Long Put Butterfly (`payoff_butterfly`)
- Short Call Butterfly, Short Put Butterfly (`payoff_short_butterfly`)
- Broken Wing Butterfly, Skip Strike Butterfly (`payoff_broken_wing_butterfly`)
- Condor Spread (call), Condor Spread (put) (`payoff_condor_spread`)
- Christmas Tree Spread (`payoff_christmas_tree`)
- Ratio Spread, Call Ratio Spread, Put Ratio Spread, 1x2 Ratio Spread, 2x1 Ratio Spread (`payoff_multi_leg_scan`)
- Back Ratio Spread, Call Backspread, Put Backspread (`payoff_backspread`)
- Jade Lizard, Reverse Jade Lizard (`payoff_jade_lizard`)
- Covered Call, Stock + Short Call (`payoff_covered_call`)
- Covered Put (`payoff_covered_put`)
- Married Put (`payoff_long_option`, equity required)
- Leveraged Covered Call (`payoff_leveraged_covered_call`)
- Protective Collar, Collar (`payoff_collar`)
- Stock + Long Put (`payoff_protective_put`)
- Synthetic Long Stock, Synthetic Call, Long Combo (`payoff_synthetic_long`)
- Synthetic Short Stock, Synthetic Put, Short Combo (`payoff_synthetic_short`)
- Conversion, Reversal (`payoff_conversion`)
- Box Spread (`payoff_box_spread`)
- Jelly Roll (`payoff_jelly_roll`)
- Risk Reversal, Volatility Skew Trade (`payoff_risk_reversal`)
- Dispersion Trade (`payoff_dispersion`)
- APEX Strategy (`payoff_apex_strategy`)
- Poor Man's Covered Call (`payoff_pmcc`)
- NO TRADE — Insufficient Conviction, NO TRADE — Wait for IV Crush (no payoff ref)
