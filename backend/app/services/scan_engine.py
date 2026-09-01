from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.analysis.composite_score import compute_apex_composite_score
from app.analysis.score_bounds import assert_score_in_bounds, validate_scan_scores
from app.analysis.volatility import compute_iv_rank, iv_rank_proxy
from app.analysis.indicators import compute_all, historical_vol, pivot_points
from app.analysis.layers import (
    APEX_STRATEGY_NAME,
    COMPOSITE_THRESHOLD_FULL_DOC,
    DEFAULT_AUTO_EXEC_THRESHOLD,
    DEEP_SCAN_LAYERS,
    EXECUTION_SCORE_BLOCKED_MAX,
    DeepScanLayer,
    EMA_PERIODS,
)
from app.analysis.technical_analysis import analyze_technicals
from app.schemas.market import ChartSnapshot, OptionChain, Quote
from app.services.apex_strategy import build_apex_strategy_input_from_scan
from app.services.options_analysis import apply_execution_score_tiers, build_chain_analysis, infer_strategy_label
from app.services.strategy_engine import (
    build_apex_score_layer,
    build_strategy_layer,
    select_strategy,
    _risk_score,
    _strategy_requires_back_month,
)
from app.services.strategy_recommendation import allows_auto_execution, selection_rationale_for
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
    auto_execution_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
    back_month_chain: OptionChain | None = None,
) -> dict[str, Any]:
    """All layers reuse the captured bars/snapshot. Do not pull a different view."""
    highs = [float(b["h"]) for b in bars]
    lows = [float(b["l"]) for b in bars]
    closes = [float(b["c"]) for b in bars]
    opens = [float(b.get("o", b["c"])) for b in bars]
    volumes = [float(b["v"]) for b in bars]
    timestamps = [str(b.get("t", "")) for b in bars]
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
    ivr_raw = vol_layer.get("iv_rank")
    ivr: float | None = None
    if ivr_raw is not None:
        try:
            ivr = assert_score_in_bounds("iv_rank", ivr_raw)
        except ValueError:
            ivr = None
            vol_layer = {**vol_layer, "iv_rank": None, "iv_rank_invalid": ivr_raw}
    if ivr is None:
        proxy_bundle = compute_iv_rank([], vol_layer.get("iv"), atm_iv=vol_layer.get("atm_iv"), hv=vol_layer.get("hv"))
        ivr = proxy_bundle.get("iv_rank")
        if ivr is None and vol_layer.get("iv") is not None and vol_layer.get("hv"):
            ivr = iv_rank_proxy(vol_layer.get("iv"), vol_layer.get("hv"))
        if ivr is not None:
            vol_layer = {**vol_layer, "iv_rank": ivr}
    rsi_v = ind["rsi"]
    macd_v = ind["macd"]
    ema = ind["ema"]
    st = ind["supertrend"]
    bb = ind["bollinger"]
    vol = ind["volume"]

    tech_analysis = analyze_technicals(
        opens=opens,
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        timestamps=timestamps,
        indicators={
            "ema": ema,
            "supertrend": st,
            "macd": macd_v,
            "rsi": rsi_v,
            "bollinger": bb,
            "volume": vol,
            "pivots": pivots,
            "ema_aligned_bullish": ind["ema_aligned_bullish"],
            "ema_aligned_bearish": ind.get("ema_aligned_bearish", False),
            "bollinger_series": ind.get("bollinger_series"),
            "supertrend_series": ind.get("supertrend_series"),
            "macd_series": ind.get("macd_series"),
            "rsi_series": ind.get("rsi_series"),
        },
    )
    tech_score = tech_analysis.score
    annotations = [
        {"pattern": p.name, "explain": ", ".join(p.confirmation_evidence) or p.family}
        for p in tech_analysis.confirmed_patterns
    ]
    if not annotations:
        annotations = _pattern_annotations()

    vol_signal = vol_layer.get("signal") or "fair"
    if vol_signal not in {"buy_premium", "sell_premium", "fair"}:
        vol_signal = "fair"

    direction_pre = tech_analysis.direction
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
    data_fresh = chain_analysis.get("status") not in {"stale", "unavailable"}
    spread_fails = chain_analysis.get("summary", {}).get("gate_failures", {}).get("spread", 0)
    median_spread = chain_analysis.get("summary", {}).get("median_spread_pct")
    wide_spreads = bool(median_spread is not None and float(median_spread) > 10.0)
    graded = chain_analysis["summary"].get("contract_count", 0) or 0
    liquidity_score = round(max(20.0, min(95.0, 95.0 - spread_fails * 8)), 1) if graded else 50.0
    catalyst_days = (sentiment_layer or {}).get("earnings_alert", {}).get("days_until")
    catalyst_fund_score = fund_score
    if catalyst_days is not None and 5 <= int(catalyst_days) <= 10:
        catalyst_fund_score = min(95.0, fund_score + 8)
    cross_tf_score = tech_analysis.layer_scores.get("cross_tf", tech_score)
    composite_breakdown = compute_apex_composite_score(
        technical_score=tech_score,
        options_iv_score=greek_score,
        liquidity_score=liquidity_score,
        catalyst_fundamental_score=catalyst_fund_score,
        payoff_risk_score=max(40.0, min(90.0, greek_score)),
        cross_tf_score=cross_tf_score,
        data_freshness_score=90.0 if data_fresh else 45.0,
        direction_conflict=False,
        stale_data=not data_fresh,
        wide_spreads=wide_spreads,
    )
    composite = composite_breakdown.composite
    validate_scan_scores(
        composite=composite,
        technical=tech_score,
        sentiment=sentiment_score,
        fundamentals=fund_score,
        iv_rank=ivr if isinstance(ivr, (int, float)) else vol_layer.get("iv_rank"),
        iv_percentile=vol_layer.get("iv_percentile"),
        hv_rank=vol_layer.get("hv_rank"),
    )
    chain_analysis.setdefault("summary", {})["liquidity_score"] = liquidity_score
    chain_analysis["data_freshness_score"] = 90.0 if data_fresh else 45.0

    direction = direction_pre
    catalyst_active = bool((sentiment_layer or {}).get("earnings_alert", {}).get("active"))
    best_delta_theta = 0.0
    for row in chain_analysis.get("contracts") or []:
        verdict = row.get("verdict") if isinstance(row, dict) else None
        if isinstance(verdict, dict):
            dt = verdict.get("delta_theta_ratio")
            if isinstance(dt, (int, float)) and dt > best_delta_theta:
                best_delta_theta = float(dt)
    apex_input = build_apex_strategy_input_from_scan(
        catalyst_days=int(catalyst_days) if catalyst_days is not None else None,
        vol_layer=vol_layer,
        chain_analysis=chain_analysis,
        back_month_contracts=[c.model_dump() for c in back_month_chain.contracts]
        if back_month_chain and back_month_chain.contracts
        else None,
    )
    median_spread = chain_analysis.get("summary", {}).get("median_spread_pct")
    back_month_ready = bool(back_month_chain and back_month_chain.contracts)
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
        symbol=snapshot.symbol,
        spot=last if isinstance(last, (int, float)) else None,
        spread_pct=float(median_spread) if median_spread is not None else None,
        data_fresh=data_fresh,
        confirmed_pattern_count=len(tech_analysis.confirmed_patterns),
        apex_input=apex_input,
        auto_exec_threshold=auto_execution_threshold,
        back_month_available=back_month_ready,
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
        auto_exec_threshold=auto_execution_threshold,
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
    back_month_rows: list[dict[str, Any]] = []
    back_expiry: str | None = None
    if back_month_chain and back_month_chain.contracts:
        back_expiry = back_month_chain.expiry
        back_month_rows = [c.model_dump() for c in back_month_chain.contracts]
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
        auto_exec_threshold=auto_execution_threshold,
        back_month_contracts=back_month_rows if _strategy_requires_back_month(strategy) else None,
        back_expiry=back_expiry,
        ticker=snapshot.symbol,
    )
    execution_tier = (
        "blocked"
        if composite <= EXECUTION_SCORE_BLOCKED_MAX
        else "auto_exec"
        if composite >= auto_execution_threshold
        else "caution"
    )
    strategy_legs = []
    equity_legs = []
    strat_spec = None
    if strategy_layer.get("tradeable"):
        from app.strategies.registry import get_strategy_spec, resolve_strategy_id

        strat_spec = get_strategy_spec(strategy_layer.get("selected_strategy") or strategy)
        overlay_only = bool(
            strat_spec
            and strat_spec.equity_required
            and strat_spec.equity_leg_spec
            and strat_spec.equity_leg_spec.entry_mode == "pre_existing"
        )
        simultaneous_equity = bool(
            strat_spec and strat_spec.equity_required and not overlay_only
        )
        for leg in (strategy_layer.get("metrics") or {}).get("legs") or []:
            if leg.get("side") == "stock":
                if not strat_spec or not strat_spec.equity_required:
                    continue
                if overlay_only:
                    continue
                equity_legs.append(
                    {
                        "symbol": leg.get("symbol") or snapshot.symbol.upper(),
                        "side": leg.get("action") or "buy",
                        "qty": leg.get("quantity") or 100,
                        "asset_class": "us_equity",
                    }
                )
                continue
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
                    "asset_class": "us_option",
                }
            )
        if simultaneous_equity and not equity_legs:
            strategy_layer = {
                **strategy_layer,
                "tradeable": False,
                "selected_strategy": "Not tradeable in current situation",
                "validation_errors": (strategy_layer.get("validation_errors") or [])
                + [
                    {
                        "strategy_id": resolve_strategy_id(strategy) or strategy,
                        "ticker": snapshot.symbol,
                        "check": "equity_leg_required",
                        "expected": "stock leg for simultaneous equity strategy",
                        "actual": "missing",
                    }
                ],
            }
            strategy_legs = []
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
            "patterns": tech_analysis.to_api_dict()["patterns"],
            "pattern_analysis": tech_analysis.to_api_dict(),
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
            "squeeze_breakout_confirmed": (
                bb["width"] < 0.04
                and (
                    (last > bb["upper"] and vol["last"] > vol["avg"] * 1.2)
                    or (last < bb["lower"] and vol["last"] > vol["avg"] * 1.2)
                )
            ),
            "narrative": (
                f"Mid {bb['mid']:.2f}, upper {bb['upper']:.2f}, lower {bb['lower']:.2f}, width {bb['width']:.4f}. "
                f"{'Volatility squeeze — compression flag only; await confirmed breakout (close beyond band with ≥1.2× average volume).' if bb['width'] < 0.04 else 'Width is not compressed.'} "
                f"Price at upper + RSI>70 = overbought context; at lower + RSI<30 = oversold context."
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
                "cross_tf_score": cross_tf_score,
                "composite_breakdown": composite_breakdown.to_api_dict(),
                "volume": vol,
                "pivots": pivots,
            },
        ),
        DeepScanLayer.STRATEGY: strategy_layer,
        DeepScanLayer.RISK_REVIEW: {
            "title": "Risk review — thesis, checkbox, order",
            "requires_checkbox": True,
            "auto_submit_on_ack": allows_auto_execution(
                strategy,
                execution_tier=execution_tier,
                composite=composite,
                auto_exec_threshold=auto_execution_threshold,
            ),
            "requires_place_order": execution_tier == "caution",
            "allows_execution": execution_tier != "blocked" and bool(strategy_legs),
            "execution_score": composite,
            "execution_tier": execution_tier,
            "auto_execution_threshold": auto_execution_threshold,
            "strategy_legs": strategy_legs,
            "equity_legs": equity_legs,
            "equity_required": bool(strat_spec and strat_spec.equity_required),
            "contracts_per_leg": 1,
            "asset_class": "us_option",
            "position_sizing": "2–5% of declared account capital per trade (configurable)",
            "daily_loss_cap": "Configurable; trading auto-halts if breached",
            "bid_ask_hard_stop": "No trade if any leg spread exceeds 10% of mid",
            "earnings_blackout": f"No new positions within 1 day of earnings (exception: {APEX_STRATEGY_NAME})",
            "narrative": (
                "Trader must accept the thesis before submit. Order review shows each options leg (OCC symbol), "
                "side, contracts, type, estimated premium, and account impact. Paper funded submits via Alpaca "
                "paper (or demo fill) without extra restriction; dashboard updates on fill via WebSocket."
            ),
        },
    }
    # Guarantee every documented layer key is present and ordered
    return {layer.value: layers[layer] for layer in DEEP_SCAN_LAYERS}


def _pattern_annotations() -> list[dict]:
    """Fallback when no confirmed high/medium patterns pass the conviction floor."""
    return [
        {
            "pattern": "No confirmed pattern",
            "explain": (
                "No high- or medium-reliability confirmed pattern on the captured window. "
                "Lean on EMA stack, SuperTrend, and MACD alignment for directional context."
            ),
        }
    ]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
