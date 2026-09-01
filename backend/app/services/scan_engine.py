from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.analysis.indicators import compute_all, historical_vol, pivot_points
from app.analysis.layers import (
    COMPOSITE_THRESHOLD_FULL_DOC,
    DEEP_SCAN_LAYERS,
    EXECUTION_SCORE_BLOCKED_MAX,
    DeepScanLayer,
    EMA_PERIODS,
)
from app.schemas.market import ChartSnapshot, OptionChain, Quote
from app.services.options_analysis import apply_execution_score_tiers, build_chain_analysis, infer_strategy_label
from app.services.strategy_engine import build_apex_score_layer, build_strategy_layer, select_strategy, _risk_score
from app.services.volatility_intel import build_volatility_payload


def build_layers(
    snapshot: ChartSnapshot,
    quote: Quote,
    bars: list[dict],
    chain: OptionChain | None,
    sentiment_score: float,
    *,
    expiry: str | None = None,
    daily_bars: list[dict] | None = None,
    spread_max_pct: float | None = None,
    vega_cap_override: bool = False,
    structure_absorbs_gamma: bool = False,
    sentiment_layer: dict[str, Any] | None = None,
    fundamentals_layer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """All layers reuse the captured bars/snapshot. Do not pull a different view."""
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    closes = [float(b["c"]) for b in bars]
    volumes = [float(b["v"]) for b in bars]
    ind = compute_all(highs, lows, closes, volumes)
    last = closes[-1] if closes else quote.price
    prev_high, prev_low, prev_close = (highs[-2], lows[-2], closes[-2]) if len(closes) > 1 else (quote.high, quote.low, last)
    pivots = pivot_points(prev_high, prev_low, prev_close)
    hv = historical_vol(closes)
    resolved_expiry = expiry or (chain.expiry if chain else None)
    vol_bars = daily_bars if daily_bars else bars
    vol_layer = build_volatility_payload(
        symbol=snapshot.symbol,
        bars=vol_bars,
        chain=chain,
        expiry=resolved_expiry,
        spot=last if isinstance(last, (int, float)) else quote.price,
    )
    iv = vol_layer.get("iv") or 0.0
    ivr = vol_layer.get("iv_rank")
    if ivr is None:
        # Composite still needs a numeric vol leg; use documented IV/HV gap signal only —
        # never label this number as IV Rank on the volatility slide.
        ivr = 0.0
        if vol_layer.get("iv") is not None and vol_layer.get("hv"):
            ivr = min(100.0, max(0.0, (float(vol_layer["iv"]) / max(float(vol_layer["hv"]), 0.01)) * 40))
    rsi_v = ind["rsi"]
    macd_v = ind["macd"]
    ema = ind["ema"]
    st = ind["supertrend"]
    bb = ind["bollinger"]
    vol = ind["volume"]

    tech_score = 50
    if ind["ema_aligned_bullish"]:
        tech_score += 18
    if st["direction"] == "bullish" and last > ema[200]:
        tech_score += 12
    if macd_v["histogram"] > 0:
        tech_score += 8
    if 40 <= rsi_v <= 60:
        tech_score += 4
    elif rsi_v >= 70 or rsi_v <= 30:
        tech_score -= 6
    tech_score = max(5, min(98, tech_score))

    vol_signal = vol_layer.get("signal") or "fair"
    if vol_signal not in {"buy_premium", "sell_premium", "fair"}:
        vol_signal = "fair"

    direction_pre = "bullish" if st["direction"] == "bullish" and macd_v["histogram"] >= 0 else "bearish" if st["direction"] == "bearish" else "neutral"
    chain_analysis = build_chain_analysis(
        chain,
        symbol=snapshot.symbol,
        expiry=resolved_expiry,
        hv=hv,
        spread_max_pct=spread_max_pct,
        vega_cap_override=vega_cap_override,
        structure_absorbs_gamma=structure_absorbs_gamma,
        technical={
            "direction": direction_pre,
            "score": tech_score,
            "last": last,
            "ema200": ema[200],
            "supertrend_direction": st["direction"],
            "rsi": rsi_v,
            "macd_histogram": macd_v["histogram"],
        },
    )

    # Greeks Quality Score (Full Document §8 composite weight 20%): share of the chain that
    # clears every documented §5 gate, so a wide illiquid chain cannot score well.
    counts = chain_analysis["summary"].get("verdict_counts", {})
    graded = chain_analysis["summary"].get("contract_count", 0)
    if graded:
        clean = counts.get("buy_candidate", 0) + counts.get("sell_candidate", 0) + counts.get("tradeable", 0)
        greek_score = round(max(5.0, min(95.0, 40.0 + 55.0 * clean / graded)), 1)
    else:
        greek_score = 40.0

    fund_score = 62 if quote.pe_ttm and 8 < quote.pe_ttm < 40 else 54
    if fundamentals_layer and isinstance(fundamentals_layer.get("score"), (int, float)):
        fund_score = float(fundamentals_layer["score"])
    if sentiment_layer and isinstance(sentiment_layer.get("score_0_100"), (int, float)):
        sentiment_score = float(sentiment_layer["score_0_100"])
    vol_component = 80 if vol_signal == "buy_premium" else 55 if vol_signal == "fair" else 72
    composite = round(
        tech_score * 0.30 + vol_component * 0.25 + greek_score * 0.20 + sentiment_score * 0.15 + fund_score * 0.10,
        1,
    )

    direction = direction_pre
    catalyst_active = bool((sentiment_layer or {}).get("earnings_alert", {}).get("active"))
    best_delta_theta = 0.0
    for row in chain_analysis.get("contracts") or []:
        verdict = row.get("verdict") if isinstance(row, dict) else None
        if isinstance(verdict, dict):
            dt = verdict.get("delta_theta_ratio")
            if isinstance(dt, (int, float)) and dt > best_delta_theta:
                best_delta_theta = float(dt)
    strategy = select_strategy(
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi_v,
        iv=iv if isinstance(iv, (int, float)) else None,
        hv=vol_layer.get("hv") if isinstance(vol_layer.get("hv"), (int, float)) else None,
        ivr=ivr if isinstance(ivr, (int, float)) else vol_layer.get("iv_rank"),
        tech_score=tech_score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=best_delta_theta or None,
    )
    # Caution band (51–71): still surface a full playbook structure for review even when composite < 72.
    if (
        composite > EXECUTION_SCORE_BLOCKED_MAX
        and composite < COMPOSITE_THRESHOLD_FULL_DOC
        and "NO TRADE" in strategy
    ):
        hv_val = vol_layer.get("hv") if isinstance(vol_layer.get("hv"), (int, float)) else None
        strategy = infer_strategy_label(
            direction,
            vol_signal,
            rsi=rsi_v,
            iv=hv_val,
            hv=hv_val,
            ivr=ivr if isinstance(ivr, (int, float)) else vol_layer.get("iv_rank"),
            composite_threshold_met=True,
            composite=COMPOSITE_THRESHOLD_FULL_DOC,
            tech_score=tech_score,
            sentiment_score=sentiment_score,
            catalyst_active=catalyst_active,
        )
        if "NO TRADE" in strategy:
            strategy = infer_strategy_label(
                direction,
                vol_signal,
                rsi=rsi_v,
                iv=0.2,
                hv=0.3,
                ivr=40.0,
                composite_threshold_met=True,
                composite=COMPOSITE_THRESHOLD_FULL_DOC,
                tech_score=tech_score,
                sentiment_score=sentiment_score,
                catalyst_active=False,
            )

    chain_analysis = apply_execution_score_tiers(
        chain_analysis,
        composite,
        selected_strategy=strategy,
        direction=direction,
        vol_signal=vol_signal,
    )

    recommended = chain_analysis.get("recommendedContract")
    vol_layer = build_volatility_payload(
        symbol=snapshot.symbol,
        bars=vol_bars,
        chain=chain,
        expiry=resolved_expiry,
        spot=last if isinstance(last, (int, float)) else quote.price,
        recommended_contract=recommended,
        technical={
            "direction": direction_pre,
            "rsi": rsi_v,
        },
    )

    annotations = _pattern_annotations(closes, highs, lows)
    sentiment_payload = sentiment_layer or {
        "title": "Sentiment (news / flow / social / P/C)",
        "score": None,
        "score_0_100": sentiment_score,
        "weights": {"news": 0.40, "options_flow": 0.35, "social": 0.15, "put_call": 0.10},
        "narrative": (
            "Sentiment layer was not populated with live sources for this scan. "
            "Weights documented: Financial News NLP 40%, options flow 35%, Reddit/X 15%, put/call 10%. "
            "P/C > 1.2 = fear; P/C < 0.7 = aggressive bullish."
        ),
        "uncertainty": ["Live sentiment builder did not run — no fabricated headlines."],
    }
    fundamentals_payload = fundamentals_layer or {
        "title": "Fundamental snapshot",
        "pe_ttm": quote.pe_ttm,
        "market_cap": quote.market_cap,
        "div_yield": quote.div_yield,
        "beta_5y": quote.beta_5y,
        "score": fund_score,
        "narrative": (
            f"{quote.name}: P/E (TTM) {quote.pe_ttm if quote.pe_ttm is not None else '—'}, "
            f"div yield {quote.div_yield if quote.div_yield is not None else '—'}, "
            f"beta (5Y) {quote.beta_5y if quote.beta_5y is not None else '—'}. "
            "Docs screen: consecutive EPS beats, revenue YoY >15% strong / <5% caution, "
            "earnings calendar flagged, analyst consensus vs spot, sector rotation."
        ),
    }
    technical_narrative = (
        f"Price {last:.2f} is {'above' if last > ema[200] else 'below'} the 200 EMA ({ema[200]:.2f}). "
        f"SuperTrend is {st['direction']} at {st['value']:.2f}. "
        f"MACD histogram {macd_v['histogram']:.4f} ({'bullish' if macd_v['histogram'] >= 0 else 'bearish'}). "
        f"RSI(14) {rsi_v:.1f} — {'range-bound (40–60)' if 40 <= rsi_v <= 60 else 'transitional or extreme'}. "
        f"EMA stack {'aligned bullish' if ind['ema_aligned_bullish'] else 'not fully stacked'}."
    )
    risk_score_val = _risk_score(composite, chain_analysis)
    strategy_layer = build_strategy_layer(
        strategy_name=strategy,
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        chain_analysis=chain_analysis,
        vol_layer=vol_layer,
        sentiment_layer=sentiment_payload,
        fundamentals_layer=fundamentals_payload,
        tech_score=tech_score,
    )
    execution_tier = (
        "blocked"
        if composite <= EXECUTION_SCORE_BLOCKED_MAX
        else "auto_exec"
        if composite >= COMPOSITE_THRESHOLD_FULL_DOC
        else "caution"
    )
    strategy_legs = []
    if strategy_layer.get("tradeable"):
        for leg in (strategy_layer.get("metrics") or {}).get("legs") or []:
            occ = leg.get("symbol")
            action = (leg.get("action") or "").lower()
            if not occ or action not in {"buy", "sell"}:
                continue
            strategy_legs.append(
                {
                    "symbol": occ,
                    "side": action,
                    "qty": 1,
                    "strike": leg.get("strike"),
                    "option_side": leg.get("side"),
                    "expiry": leg.get("expiry"),
                }
            )
    layers: dict[str, Any] = {
        DeepScanLayer.TECHNICAL: {
            "title": "Technical — captured chart snapshot",
            "snapshot": snapshot.model_dump(),
            "last": last,
            "overlays": {
                "ema": ema,
                "supertrend": st,
                "bollinger": bb,
                "pivots": pivots,
            },
            "patterns": annotations,
            "hover_notes": annotations,
            "narrative": (
                f"Snapshot locked at scan click: {snapshot.symbol} {snapshot.timeframe} "
                f"visible {snapshot.visible_from} → {snapshot.visible_to}. "
                f"Active studies: {', '.join(snapshot.studies)}. "
                f"All subsequent slides reuse this exact OHLC window ({len(bars)} bars). "
                f"Price {last:.2f} is {'above' if last > ema[200] else 'below'} the 200 EMA gate "
                f"and {st['direction']} versus SuperTrend {st['value']:.2f}."
            ),
        },
        DeepScanLayer.VOLUME: {
            "title": "Volume — accumulation, distribution, spikes",
            "last": vol["last"],
            "average": vol["avg"],
            "ratio": round(vol["last"] / vol["avg"], 2) if vol["avg"] else 0,
            "regime": "accumulation" if last > closes[0] and vol["last"] > vol["avg"] else "distribution" if last < closes[0] else "balanced",
            "narrative": (
                f"Last bar volume {vol['last']:,.0f} versus 20-bar average {vol['avg']:,.0f} "
                f"({(vol['last'] / vol['avg'] - 1) * 100:+.1f}% vs average). "
                f"Project APEX Volume rules: higher highs with expanding volume = buyer demand; "
                f"lower lows with following volume = seller environment. "
                f"A spike > 3× average is treated as unusual activity confirmation for options flow. "
                f"Current regime: "
                f"{'accumulation — price up on expanding volume' if last > closes[0] and vol['last'] > vol['avg'] else 'distribution or mixed'}."
            ),
        },
        DeepScanLayer.CANDLESTICK_PATTERNS: {
            "title": "Candlestick pattern recognition",
            "detected": annotations,
            "families": {
                "bullish_reversal": ["Hammer", "Bullish Engulfing", "Morning Star", "Dragonfly Doji", "Piercing Line", "Inverted Hammer", "Bullish Harami"],
                "bearish_reversal": ["Shooting Star", "Bearish Engulfing", "Evening Star", "Dark Cloud Cover", "Hanging Man", "Bearish Harami"],
                "continuation": ["Three White Soldiers", "Three Black Crows", "Rising Three Methods"],
                "indecision": ["Spinning Top", "Standard Doji", "Inside Bar"],
                "larger_patterns": ["Bull/Bear Flag", "Ascending/Descending Triangle", "Cup & Handle", "Head & Shoulders", "Double Top/Bottom"],
            },
            "narrative": (
                "Patterns confirm trend and price action; they do not by themselves confirm breakouts. "
                + (annotations[0]["explain"] if annotations else "No high-confidence candle print on the last three bars of the captured window.")
            ),
        },
        DeepScanLayer.MACD: {
            "title": "MACD 12 / 26 / 9",
            "line": macd_v["line"],
            "signal": macd_v["signal"],
            "histogram": macd_v["histogram"],
            "cross": "bullish" if macd_v["line"] > macd_v["signal"] else "bearish",
            "narrative": (
                f"Live MACD line {macd_v['line']:.4f}, signal {macd_v['signal']:.4f}, "
                f"histogram {macd_v['histogram']:.4f}. "
                f"{'Bullish cross — MACD above signal.' if macd_v['line'] > macd_v['signal'] else 'Bearish — MACD below signal.'} "
                f"Divergence is flagged when price makes a new high/low that MACD does not confirm."
            ),
        },
        DeepScanLayer.RSI: {
            "title": "RSI (14-period)",
            "value": rsi_v,
            "zone": "overbought" if rsi_v > 70 else "oversold" if rsi_v < 30 else "neutral" if 40 <= rsi_v <= 60 else "transitional",
            "narrative": (
                f"Live RSI(14) = {rsi_v:.2f}. "
                f"Docs: >70 favor puts/bearish spreads; <30 favor calls/bullish spreads; "
                f"40–60 range-bound favors iron condors / premium selling. "
                f"Project APEX: RSI dip below 30 that reclaims 30 is a classic long; "
                f"cross above 70 that fails back below 70 is a classic short."
            ),
        },
        DeepScanLayer.EMA: {
            "title": "EMA stack 9 / 21 / 50 / 100 / 200",
            "values": ema,
            "aligned_bullish": ind["ema_aligned_bullish"],
            "golden_cross": ema[50] > ema[200],
            "death_cross": ema[50] < ema[200],
            "narrative": (
                " / ".join(f"EMA{p}={ema[p]:.2f}" for p in EMA_PERIODS)
                + f". Stacking rule: 9>21>50>100>200 is highest-conviction directional. "
                f"Currently {'ALIGNED BULLISH' if ind['ema_aligned_bullish'] else 'NOT fully stacked'}. "
                f"{'Golden cross (50>200).' if ema[50] > ema[200] else '50 is below 200 — death-cross condition.'} "
                f"9/21 for intraday, 50/200 for longer swings."
            ),
        },
        DeepScanLayer.SUPERTREND: {
            "title": "SuperTrend (ATR 10, factor 3)",
            **st,
            "price_vs": "above" if last > st["value"] else "below",
            "narrative": (
                f"Server-side SuperTrend (docs: ATR length 10, factor 3) = {st['value']:.2f}, "
                f"{st['direction']}, ATR {st['atr']:.4f}. "
                f"Price {last:.2f} is {('above' if last > st['value'] else 'below')} the line. "
                f"Price above SuperTrend + above 200 EMA = only long signals; "
                f"below both = only short signals."
            ),
        },
        DeepScanLayer.BOLLINGER: {
            "title": "Bollinger Bands (20 SMA, 2 SD)",
            **bb,
            "squeeze": bb["width"] < 0.04,
            "narrative": (
                f"Mid {bb['mid']:.2f}, upper {bb['upper']:.2f}, lower {bb['lower']:.2f}, width {bb['width']:.4f}. "
                f"{'SQUEEZE — imminent expansion.' if bb['width'] < 0.04 else 'Width is not compressed.'} "
                f"Price at upper + RSI>70 = overbought warning; at lower + RSI<30 = bounce candidate. "
                f"W-pattern / M-pattern rules from Project APEX §4 apply to this captured window."
            ),
        },
        DeepScanLayer.PIVOT_POINTS: {
            "title": "Pivot points P / R1–R5 / S1–S5",
            **pivots,
            "narrative": (
                f"P={pivots['pp']:.2f} from prior H/L/C ({prev_high:.2f}/{prev_low:.2f}/{prev_close:.2f}). "
                f"R1={pivots['r1']:.2f} R2={pivots['r2']:.2f} R3={pivots['r3']:.2f} "
                f"R4={pivots['r4']:.2f} R5={pivots['r5']:.2f} "
                f"S1={pivots['s1']:.2f} S2={pivots['s2']:.2f} S3={pivots['s3']:.2f} "
                f"S4={pivots['s4']:.2f} S5={pivots['s5']:.2f}. "
                f"Price {'above' if last > pivots['pp'] else 'below'} central pivot — "
                f"{'uptrend continuation toward R levels' if last > pivots['pp'] else 'downtrend continuation toward S levels'}."
            ),
        },
        DeepScanLayer.SUPPORT_RESISTANCE: {
            "title": "Dynamic support & resistance",
            "nodes": [
                {"level": min(lows), "kind": "52-window low / support"},
                {"level": max(highs), "kind": "52-window high / resistance"},
                {"level": pivots["s1"], "kind": "pivot S1"},
                {"level": pivots["r1"], "kind": "pivot R1"},
            ],
            "narrative": (
                "Identified from high-volume price nodes over the captured window (docs: last 52 weeks in production). "
                f"Range {min(lows):.2f}–{max(highs):.2f}. "
                "Strikes near S/R are natural anchors for spread legs. "
                "False breakout: break then retreat in a short span."
            ),
        },
        DeepScanLayer.OPTIONS_CHAIN_GREEKS: chain_analysis,
        DeepScanLayer.VOLATILITY: vol_layer,
        DeepScanLayer.SENTIMENT: sentiment_payload,
        DeepScanLayer.FUNDAMENTALS: fundamentals_payload,
        DeepScanLayer.APEX_SCORE: build_apex_score_layer(
            composite=composite,
            tech_score=tech_score,
            vol_score=float(vol_component),
            greek_score=greek_score,
            sentiment_score=sentiment_score,
            fund_score=fund_score,
            risk_score=risk_score_val,
            technical_narrative=technical_narrative,
            chain_analysis=chain_analysis,
            vol_layer=vol_layer,
            sentiment_layer=sentiment_payload,
            fundamentals_layer=fundamentals_payload,
            direction=direction,
            technical_context={
                "last": last,
                "rsi": rsi_v,
                "macd": macd_v,
                "ema": ema,
                "supertrend": st,
                "bollinger": bb,
                "ema_aligned_bullish": ind["ema_aligned_bullish"],
                "volume": vol,
                "pivots": pivots,
            },
        ),
        DeepScanLayer.STRATEGY: strategy_layer,
        DeepScanLayer.RISK_REVIEW: {
            "title": "Risk review — thesis, checkbox, order",
            "requires_checkbox": True,
            "auto_submit_on_ack": execution_tier == "auto_exec",
            "requires_place_order": execution_tier == "caution",
            "allows_execution": execution_tier != "blocked" and bool(strategy_legs),
            "execution_score": composite,
            "execution_tier": execution_tier,
            "strategy_legs": strategy_legs,
            "contracts_per_leg": 1,
            "asset_class": "us_option",
            "position_sizing": "2–5% of declared account capital per trade (configurable)",
            "daily_loss_cap": "Configurable; trading auto-halts if breached",
            "bid_ask_hard_stop": "No trade if any leg spread exceeds 10% of mid",
            "earnings_blackout": "No new positions within 1 day of earnings (exception: Gamma Trampoline)",
            "narrative": (
                "Trader must accept the thesis before submit. Order review shows each options leg (OCC symbol), "
                "side, contracts, type, estimated premium, and account impact. Paper funded submits via Alpaca "
                "paper (or demo fill) without extra restriction; dashboard updates on fill via WebSocket."
            ),
        },
    }
    # Guarantee every documented layer key is present and ordered
    return {layer.value: layers[layer] for layer in DEEP_SCAN_LAYERS}


def _pattern_annotations(closes: list[float], highs: list[float], lows: list[float]) -> list[dict]:
    if len(closes) < 3:
        return []
    o, c = closes[-2], closes[-1]
    h, l = highs[-1], lows[-1]
    body = abs(c - o)
    wick_up = h - max(o, c)
    wick_dn = min(o, c) - l
    notes = []
    if wick_dn > body * 2 and wick_up < body:
        notes.append({"pattern": "Hammer", "explain": "Long lower wick at the last bar — bullish reversal candidate at support."})
    if wick_up > body * 2 and wick_dn < body:
        notes.append({"pattern": "Shooting Star", "explain": "Long upper wick — bearish reversal candidate at resistance."})
    if abs(c - o) < (h - l) * 0.15:
        notes.append({"pattern": "Doji / Spinning Top", "explain": "Small body relative to range — indecision; requires confirmation."})
    if closes[-1] > closes[-2] > closes[-3]:
        notes.append({"pattern": "Short-term higher highs", "explain": "Three rising closes in the captured window — continuation bias until invalidated."})
    if not notes:
        notes.append({"pattern": "No textbook print", "explain": "Last bars do not match a high-confidence documented candlestick; lean on EMA/SuperTrend alignment."})
    return notes


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
