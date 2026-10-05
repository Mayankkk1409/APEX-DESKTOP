# Change 9 Part B — Strategy coverage

The selector is `strategy_decision` / `select_strategy` in `backend/app/services/strategy_engine.py`. Ranking is `_rank_candidates` and `order_candidates_for_risk_profile` in `backend/app/services/strategy_recommendation.py`. Names come from `STRATEGY_REGISTRY` in `backend/app/strategies/registry.py`.

Weights were not changed. Nothing was added to the matrix to force a name to appear.

## Real executable names

The registry has 100 entries. Two are advisory stand-ins with no legs:

- NO TRADE — Insufficient Conviction
- NO TRADE — Wait for IV Crush

`real_strategy_count()` is 98. Those 98 have legs. Thirteen of them are undefined-risk or marked not tradeable, so the ranker never makes them Best Match. The other 85 are defined-risk and tradeable. The §9.1 matrix only scores a short playbook, so most of those 85 stay at score 0.

## Fixture

188 scenarios. The test is `backend/tests/test_strategy_coverage.py`.

180 of them are the grid:

| Factor | Values |
|---|---|
| Outlook | strong bull, mild bull, neutral, mild bear, strong bear |
| IV versus HV | cheap (HV − IV > 0.10, vol signal `buy_premium`), near (IV = HV, `fair`), rich (IV − HV > 0.10, `sell_premium`) |
| DTE bucket | 0–7, 8–21, 22–60, 61–180 |
| Risk profile | conservative, moderate, aggressive |

Strong outlook uses a technical score of 90 and an RSI outside 40–60. Mild outlook uses a technical score of 65 and an RSI inside 40–60. Neutral uses score 60 and RSI 50. Composite is 78 on every row, so the bonus, not the base score, decides the order.

DTE is not a score. Buckets 0–7 and 8–21 set `back_month_available` false. Buckets 22–60 and 61–180 set it true. The two buckets that share that flag select the same name. A weekly-only or LEAPS label does not win just because the bucket changed.

Eight more scenarios turn on gates the grid leaves off:

- Strong bull, cheap IV, Δ/Θ = 12, moderate and aggressive → APEX Benchmark Greeks Strategy
- The same tape, conservative → Married Put (the profile moves the hedge in front of the benchmark)
- Mild bull, IV near HV, sentiment 70, moderate → APEX Benchmark Greeks Strategy
- Neutral, rich IV, strict APEX Strategy eligibility and an active catalyst, each profile → APEX Strategy
- Strong bull, cheap IV, Δ/Θ = 12, and that same eligibility → APEX Strategy (the +12 bonus outranks the benchmark)

Every scenario asserts the label is a defined-risk, tradeable registry name, that it does not contain NO TRADE, Wait for IV Crush, or Stand aside, and that it is the name the matrix bonuses predict.

## Distinct winners in the fixtures

12 names won at least once:

| Best Match | When it wins |
|---|---|
| Bull Call Spread | Strong bull, cheap IV, moderate or aggressive, and Δ/Θ is not at least 10 |
| APEX Benchmark Greeks Strategy | Strong bull, cheap IV, Δ/Θ ≥ 10, moderate or aggressive. Also mild bull with sentiment above 60 when no higher bonus is present |
| Married Put | Any bullish tape whose higher bonuses are absent, and the conservative profile whenever a bullish hedge is eligible |
| Bull Put Spread (credit) | Strong bull, rich IV (RSI is outside 40–60, so the iron condor is not eligible) |
| Short Iron Condor | Rich IV and RSI 40–60, unless aggressive pulls a later diagonal in front of it |
| Diagonal Spread (bullish) | Mild bull, rich IV, a back month, aggressive |
| Long Straddle | Neutral and cheap IV (moderate or aggressive). Neutral and near IV with no back month (directional fallback) |
| Calendar Spread | Neutral, IV near HV, back month. Also conservative on neutral cheap IV when a back month exists |
| Bear Put Spread | Strong bear and cheap IV (moderate or aggressive). Also the bearish fallback when the matrix adds no candidate |
| Bear Call Spread (credit) | Strong bear, rich IV |
| Diagonal Spread (bearish) | Bearish tape with a back month when the debit or credit vertical is not the top bonus, and the aggressive profile when an iron condor ranks ahead of the diagonal |
| APEX Strategy | Catalyst active and the strict eligibility check passes. Bonus +12 |

## Strategies that never ranked first

### Excluded — advisory (2)

NO TRADE — Insufficient Conviction. NO TRADE — Wait for IV Crush. They have no legs. The selector does not return them.

### Excluded — undefined risk or not tradeable (13)

Naked Call, Naked Put, Short Straddle, Short Strangle, Short Guts, Ratio Spread, Call Ratio Spread, Put Ratio Spread, 1x2 Ratio Spread, 2x1 Ratio Spread, Jade Lizard, Reverse Jade Lizard, Covered Put.

`_rank_candidates` skips the undefined-risk set. The registry pass then drops every `risk_type == "undefined"` name, including Short Guts and Covered Put. This is the existing exclusion, not a missed bonus.

### Unreachable — not scored by the §9.1 matrix (73)

These are defined-risk and tradeable. They are attached as ineligible misses with score 0. The matrix never adds them, so they cannot rank first. DTE does not create a path to the LEAPS, butterfly, or weekly names.

Long Call, Long Put, Long Call LEAPS, Long Put LEAPS, Deep ITM Call, Deep ITM Put, At-The-Money Call, Call Debit Spread, Put Debit Spread, Call Credit Spread, Put Credit Spread, Wide Bull Call Spread, Wide Bear Put Spread, Long Strangle, Long Guts, Strip, Strap, Long Straddle LEAPS, Short Iron Butterfly (variant), Calendar Put Spread, Calendar Call Spread, Double Calendar, Double Diagonal, Reverse Calendar, Calendar Straddle, Diagonal Call Spread, Long Call Butterfly, Long Put Butterfly, Iron Butterfly, Long Iron Condor, Broken Wing Butterfly, Skip Strike Butterfly, Iron Condor (wide), Condor Spread (call), Condor Spread (put), Reverse Iron Condor, Long Iron Butterfly, Short Call Butterfly, Short Put Butterfly, Christmas Tree Spread, Back Ratio Spread, Call Backspread, Put Backspread, Covered Call, Leveraged Covered Call, Protective Collar, Stock + Short Call, Stock + Long Put, Collar, Synthetic Long Stock, Synthetic Short Stock, Synthetic Call, Synthetic Put, Conversion, Reversal, Box Spread, Jelly Roll, Long Combo, Short Combo, Risk Reversal, Synthetic Straddle, Long Straddle (pre-earnings), IV Crush Short Iron Condor, Volatility Skew Trade, VIX Call Hedge, Dispersion Trade, Gamma Scalping, Vega Neutral Spread, Theta Harvest Iron Condor, Earnings Straddle, Iron Condor (monthly), Wheel Strategy, Poor Man's Covered Call.

Married Call is a display alias of APEX Benchmark Greeks Strategy. The ranker does not emit it as its own label.

### Defect that was overwriting a matrix winner

A one-leg long put is the option shape of both Married Put (stock already held) and Long Put. A one-leg long call is the shape of both APEX Benchmark Greeks Strategy and Long Call. `build_strategy_layer` was replacing the matrix name with that generic shape whenever the leg counts matched.

On a bullish, fair-IV tape the matrix selects Married Put. Live scans on the process from before this fix showed Long Put. A bullish benchmark tape showed Long Call. The label now stays on the matrix name. `test_shared_one_leg_shape_does_not_replace_the_matrix_name` covers both collisions.

No other matrix winner was being replaced. Verticals, the iron condor, the straddle, and the calendars already agreed with their built legs.

## Live scans

`GET http://127.0.0.1:8000/health` returned `market_adapter: alpaca`. Scans were `POST /scan` for one expiry in each of DTE 8–21, 22–60, and 61–180 when the chain had one.

34 scans completed. Each reported `strategies_evaluated` 98. None of the labels contained NO TRADE.

The API process reloaded while the batch was running, after the label fix. Rows through AAPL at 25 DTE are from the old process (Long Put and Long Call are the overwrite above). From AAPL at 74 DTE onward the labels are the matrix names. JPM, XOM, KO, and WMT were not scanned. The volume filled while the result file was written, after AMD at 9 DTE, so the batch stopped. The 46 scan rows stored in this pass were deleted. `apex.db` is still about 191MB until a `VACUUM` can run; the volume did not have room for that copy.

| Symbol | DTE | Selected strategy | strategies_evaluated | NO TRADE |
|---|---:|---|---:|---|
| SPY | 8 | Long Put | 98 | no |
| SPY | 25 | Long Put | 98 | no |
| SPY | 74 | Long Put | 98 | no |
| QQQ | 8 | Long Put | 98 | no |
| QQQ | 25 | Bull Put Spread (credit) | 98 | no |
| QQQ | 74 | Long Put | 98 | no |
| IWM | 8 | Long Put | 98 | no |
| IWM | 25 | Long Put | 98 | no |
| IWM | 74 | Diagonal Spread (bullish) | 98 | no |
| DIA | 11 | Diagonal Spread (bullish) | 98 | no |
| DIA | 25 | Long Put | 98 | no |
| DIA | 74 | Long Put | 98 | no |
| AAPL | 9 | Long Call | 98 | no |
| AAPL | 25 | Long Call | 98 | no |
| AAPL | 74 | APEX Benchmark Greeks Strategy | 98 | no |
| MSFT | 9 | APEX Benchmark Greeks Strategy | 98 | no |
| MSFT | 25 | APEX Benchmark Greeks Strategy | 98 | no |
| MSFT | 74 | Diagonal Spread (bullish) | 98 | no |
| NVDA | 9 | APEX Benchmark Greeks Strategy | 98 | no |
| NVDA | 25 | APEX Benchmark Greeks Strategy | 98 | no |
| NVDA | 74 | APEX Benchmark Greeks Strategy | 98 | no |
| AMZN | 9 | Married Put | 98 | no |
| AMZN | 25 | APEX Benchmark Greeks Strategy | 98 | no |
| AMZN | 74 | APEX Benchmark Greeks Strategy | 98 | no |
| GOOGL | 9 | Bull Put Spread (credit) | 98 | no |
| GOOGL | 25 | Bull Put Spread (credit) | 98 | no |
| GOOGL | 74 | Married Put | 98 | no |
| META | 9 | Diagonal Spread (bearish) | 98 | no |
| META | 25 | Diagonal Spread (bearish) | 98 | no |
| META | 74 | Diagonal Spread (bearish) | 98 | no |
| TSLA | 9 | Married Put | 98 | no |
| TSLA | 25 | Married Put | 98 | no |
| TSLA | 74 | Married Put | 98 | no |
| AMD | 9 | Bull Put Spread (credit) | 98 | no |

After the reload, one bullish book is not stuck on a single name: AAPL, MSFT, NVDA, and AMZN take APEX Benchmark Greeks Strategy, MSFT’s longer expiry takes a bullish diagonal, AMZN’s near expiry and TSLA take Married Put, and GOOGL and AMD take a bull put credit. META’s bearish tape takes Diagonal Spread (bearish) at every sampled DTE. The suite does not treat any of those winners as a failure.

## Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_strategy_coverage.py -q --tb=line -p no:cacheprovider
```

192 passed.
