# Deep Scan analysis layers

Enumerated from the workspace PDFs. Nothing below is invented.

## THINK 10X / Section 2 (Full Document + Project APEX)

1. Trend � SuperTrend + EMA Stack (9/21/50/100/200)
2. Momentum � RSI (14) + MACD (12/26/9)
3. Volatility � Bollinger Band width + IV vs HV + IVR
4. Structure / Patterns � candlestick recognition
5. Levels � Pivot Points (PP, R1�R3, S1�S3) + support/resistance
6. Greeks � Delta, Theta, Vega, Gamma
7. Chain � OI, volume, bid/ask, put/call, unusual activity
8. Sentiment � news NLP + social + options flow
9. Fundamentals � P/E, EPS, earnings, revenue, analyst consensus
10. Strategy � final synthesis / playbook

## 10-layer technical list (Project APEX executive summary)

MACD, EMA, RSI, Bollinger Bands, Pivot Points, Support/Resistance, SuperTrend, Volume, Technical Candlestick Patterns

(Nine named studies; Volume is the layer the executive summary adds beyond Full Document page-1 list.)

## �3.5 scan progress order (Full Document)

Technical Analysis ? Candlestick Patterns ? MACD ? RSI (14) ? EMA Stack ? SuperTrend ? Bollinger Bands ? Pivot Points ? Support/Resistance ? Options Chain ? Greeks ? Volatility Engine ? Sentiment ? Fundamental ? Composite Score

## Additional documented pattern families (Project APEX �4)

Candlesticks: hammer, bullish/bearish engulfing, morning/evening star, dragonfly doji, piercing line, inverted hammer, bullish/bearish harami, shooting star, dark cloud cover, hanging man, three white soldiers, three black crows, rising three methods, spinning top, standard doji, inside bar.

Larger patterns: bull/bear flag, ascending/descending triangle, cup & handle, inverted cup & handle, H&S / inverted H&S, double top/bottom, rounding top/bottom.

## Implemented slider order

See `CONTRACT.md`. Union of the lists above as **one slide per named layer**, no compression, plus user-required Volume + Risk Review.

One deliberate exception: Options Chain and Greeks ship as the single `options_chain_greeks` layer.
The �3.5 progress list names them separately, but �5 is one section ("OPTIONS CHAIN ANALYSIS &
GREEKS ENGINE") and its rules are per-contract � a strike's spread/OI gates and its Delta/Theta,
Vega and Gamma verdicts are the same decision, so they are read on one screen: the chain ladder on
top, the �5 rule cards in a carousel beneath it.
