# Change 9 — condition coverage

`backend/tests/test_strategy_coverage_conditions.py` calls `strategy_decision` in `backend/app/services/strategy_engine.py` (the selector `scan_engine` uses). That function delegates to `recommend_strategy`. The test does not reimplement ranking.

72 scenarios. Every Best Match was an executable structure: none contained `NO TRADE`, `Wait for IV Crush`, or `Stand aside`. Five distinct names won.

Held constant on every call: composite 82, vol signal `fair`, RSI 50, technical score 85, one confirmed pattern, fresh data, 2% spread, spot 100, no sentiment, no catalyst, no delta/theta ratio, no back month, no structure allowlist. Varied: outlook (`bullish` / `bearish` / `neutral`), IV versus HV, and risk profile (`conservative` / `moderate` / `aggressive` / `custom`).

IV versus HV labels:

| Label | IV | HV |
|---|---:|---:|
| cheap | 0.18 | 0.40 |
| rich | 0.52 | 0.40 |
| extreme | 0.55 | 0.30 |
| matched | 0.25 | 0.25 |
| mild_cheap | 0.22 | 0.28 |
| mild_rich | 0.28 | 0.22 |

## Histogram

| Best Match | Wins |
|---|---:|
| Short Iron Condor | 24 |
| Bear Put Spread | 16 |
| Long Straddle | 16 |
| Married Put | 13 |
| Bull Call Spread | 3 |

## Inputs that produced each win

### Short Iron Condor (24)

Every rich and extreme pair, all three outlooks, all four profiles.

- bullish, rich (IV 0.52 / HV 0.40), conservative, moderate, aggressive, custom
- bullish, extreme (IV 0.55 / HV 0.30), conservative, moderate, aggressive, custom
- bearish, rich (IV 0.52 / HV 0.40), conservative, moderate, aggressive, custom
- bearish, extreme (IV 0.55 / HV 0.30), conservative, moderate, aggressive, custom
- neutral, rich (IV 0.52 / HV 0.40), conservative, moderate, aggressive, custom
- neutral, extreme (IV 0.55 / HV 0.30), conservative, moderate, aggressive, custom

### Bear Put Spread (16)

Bearish outlook only, when IV was not rich enough to clear the rich gap. Profile did not change the winner.

- bearish, cheap (IV 0.18 / HV 0.40), conservative, moderate, aggressive, custom
- bearish, matched (IV 0.25 / HV 0.25), conservative, moderate, aggressive, custom
- bearish, mild_cheap (IV 0.22 / HV 0.28), conservative, moderate, aggressive, custom
- bearish, mild_rich (IV 0.28 / HV 0.22), conservative, moderate, aggressive, custom

### Long Straddle (16)

Neutral outlook only, on the same four IV pairs as Bear Put Spread. Profile did not change the winner.

- neutral, cheap (IV 0.18 / HV 0.40), conservative, moderate, aggressive, custom
- neutral, matched (IV 0.25 / HV 0.25), conservative, moderate, aggressive, custom
- neutral, mild_cheap (IV 0.22 / HV 0.28), conservative, moderate, aggressive, custom
- neutral, mild_rich (IV 0.28 / HV 0.22), conservative, moderate, aggressive, custom

### Married Put (13)

- bullish, cheap (IV 0.18 / HV 0.40), conservative
- bullish, matched (IV 0.25 / HV 0.25), conservative, moderate, aggressive, custom
- bullish, mild_cheap (IV 0.22 / HV 0.28), conservative, moderate, aggressive, custom
- bullish, mild_rich (IV 0.28 / HV 0.22), conservative, moderate, aggressive, custom

### Bull Call Spread (3)

- bullish, cheap (IV 0.18 / HV 0.40), moderate
- bullish, cheap (IV 0.18 / HV 0.40), aggressive
- bullish, cheap (IV 0.18 / HV 0.40), custom

`pytest tests/test_strategy_coverage_conditions.py`: 73 passed (72 scenario tests plus a count check that the grid has at least 30 cases).
