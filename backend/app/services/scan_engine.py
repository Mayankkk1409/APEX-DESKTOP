from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.analysis.composite_score import compute_apex_composite_score
from app.analysis.score_bounds import assert_score_in_bounds, validate_scan_scores
from app.analysis.volatility import compute_iv_rank, iv_rank_proxy
from app.analysis.indicators import compute_all, historical_vol, pivot_points
from app.analysis.layers import (
    APEX_STRATEGY_NAME,
    DEFAULT_AUTO_EXEC_THRESHOLD,
    DEEP_SCAN_LAYERS,
    EXECUTION_SCORE_BLOCKED_MAX,
    DeepScanLayer,
    EMA_PERIODS,
)
from app.analysis.technical_analysis import analyze_technicals
from app.schemas.market import ChartSnapshot, OptionChain, Quote
from app.services.apex_strategy import build_apex_strategy_input_from_scan
from app.services.options_analysis import apply_execution_score_tiers, build_chain_analysis
from app.services.strategy_engine import (
    build_apex_score_layer,
    build_strategy_layer,
    strategy_decision,
    _risk_score,
    _strategy_requires_back_month,
)
from app.services.executability import CLOSE_SCORE_GAP
from app.services.strategy_recommendation import is_defined_risk_strategy
from app.analysis.options_rules import daily_theta_per_share, delta_theta_ratio
from app.services.volatility_intel import build_volatility_payload


def _recommended_contract_delta_theta(chain_analysis: dict[str, Any]) -> float | None:
    """Delta/theta of the contract the card would buy, not the best ratio on the chain."""
    recommended = chain_analysis.get("recommendedContract") or {}
    if not isinstance(recommended, dict):
        return None
    target = recommended.get("contract_id") or recommended.get("symbol")
    strike = recommended.get("strike")
    side = recommended.get("side")
    for row in chain_analysis.get("contracts") or []:
        if not isinstance(row, dict):
            continue
        symbol_match = bool(target) and row.get("symbol") == target
        strike_match = False
        if side and strike is not None and row.get("side") == side and row.get("strike") is not None:
            strike_match = abs(float(row["strike"]) - float(strike)) < 0.01
        if not symbol_match and not strike_match:
            continue
        verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
        ratio = verdict.get("delta_theta_ratio") if isinstance(verdict, dict) else None
        if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
            return float(ratio)
        bid, ask = row.get("bid"), row.get("ask")
        mid = None
        if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
            mid = (float(bid) + float(ask)) / 2.0
        theta = daily_theta_per_share(row.get("theta"), mid=mid, multiplier=row.get("multiplier") or 100)
        return delta_theta_ratio(row.get("delta"), theta)
    return None


def _benchmark_rule_context(
    chain_analysis: dict[str, Any],
    *,
    direction: str,
    sentiment_score: float | None,
    sentiment_bias: str | None,
    spot: float | None,
    hv20: float | None,
    iv: float | None,
    iv_rank: float | None,
    rsi: float | None,
) -> dict[str, Any]:
    """Rule 1 and Rule 2 inputs from the scan's existing pillars and the live chain.

    HV20 is the 20-day close-to-close historical volatility already computed with sqrt(252).
    """
    from datetime import date

    contracts = [row for row in (chain_analysis.get("contracts") or []) if isinstance(row, dict)]
    recommended = chain_analysis.get("recommendedContract") if isinstance(chain_analysis.get("recommendedContract"), dict) else {}
    target = recommended.get("contract_id") or recommended.get("symbol")
    strike = recommended.get("strike")
    side = recommended.get("side")
    chosen: dict[str, Any] | None = None
    for row in contracts:
        symbol_match = bool(target) and row.get("symbol") == target
        strike_match = False
        if side and strike is not None and row.get("side") == side and row.get("strike") is not None:
            try:
                strike_match = abs(float(row["strike"]) - float(strike)) < 0.01
            except (TypeError, ValueError):
                strike_match = False
        if symbol_match or strike_match:
            chosen = row
            break
    bid = ask = mid = delta = theta = contract_iv = dte = None
    if chosen is not None:
        bid, ask = chosen.get("bid"), chosen.get("ask")
        if (
            isinstance(bid, (int, float))
            and isinstance(ask, (int, float))
            and not isinstance(bid, bool)
            and not isinstance(ask, bool)
            and bid > 0
            and ask > 0
        ):
            mid = (float(bid) + float(ask)) / 2.0
        if isinstance(chosen.get("delta"), (int, float)) and not isinstance(chosen.get("delta"), bool):
            delta = float(chosen["delta"])
        theta = daily_theta_per_share(chosen.get("theta"), mid=mid, multiplier=chosen.get("multiplier") or 100)
        raw_contract_iv = chosen.get("iv")
        if isinstance(raw_contract_iv, (int, float)) and not isinstance(raw_contract_iv, bool):
            contract_iv = float(raw_contract_iv)
        expiry = chosen.get("expiry") or chain_analysis.get("expiry")
        if isinstance(expiry, str) and len(expiry) >= 10:
            try:
                dte = (date.fromisoformat(expiry[:10]) - date.today()).days
            except ValueError:
                dte = None
    return {
        "technical_direction": direction,
        "sentiment_score": sentiment_score,
        "sentiment_bias": sentiment_bias,
        "delta": delta,
        "spot": spot,
        "theta_per_share": theta,
        "mid": mid,
        "dte": dte,
        "rule2_dte": dte,
        "contract_iv": contract_iv if contract_iv is not None else iv,
        "hv20": hv20,
        "bid": bid,
        "ask": ask,
        "iv_rank": iv_rank,
        "rsi": rsi,
        "contracts": contracts,
    }


def build_layers(
    snapshot: ChartSnapshot,
    quote: Quote,
    bars: list[dict],
    chain: OptionChain | None,
    sentiment_score: float | None,
    *,
    expiry: str | None = None,
    daily_bars: list[dict] | None = None,
    spread_max_pct: float | None = None,
    vega_cap_override: bool = False,
    structure_absorbs_gamma: bool = False,
    sentiment_layer: dict[str, Any] | None = None,
    fundamentals_layer: dict[str, Any] | None = None,
    auto_execution_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
    risk_profile: str = "moderate",
    back_month_chain: OptionChain | None = None,
    shares_held: int = 0,
    shares_encumbered: int = 0,
    shares_short: int = 0,
    share_avg_cost: float | None = None,
    stock_ask: float | None = None,
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
    raw_iv = vol_layer.get("iv")
    iv = raw_iv if isinstance(raw_iv, (int, float)) and not isinstance(raw_iv, bool) else None
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
    if vol_signal not in {"buy_premium", "sell_premium", "fair", "between_bands"}:
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
    vol_component = 80 if vol_signal == "buy_premium" else 72 if vol_signal == "sell_premium" else 55
    data_fresh = chain_analysis.get("status") not in {"stale", "unavailable"}
    spread_fails = chain_analysis.get("summary", {}).get("gate_failures", {}).get("spread", 0)
    median_spread = chain_analysis.get("summary", {}).get("median_spread_pct")
    # median_spread_pct is a fraction of mid (0.10 == 10%).
    wide_spreads = bool(median_spread is not None and float(median_spread) > 0.10)
    from app.analysis.gate_config import earnings_before_expiry as earnings_inside_window

    earnings_alert_early = (sentiment_layer or {}).get("earnings_alert") or {}
    earnings_cal_early = (fundamentals_layer or {}).get("earnings_calendar") if isinstance(fundamentals_layer, dict) else None
    earnings_next_early = None
    if isinstance(earnings_cal_early, dict):
        earnings_next_early = earnings_cal_early.get("next_date")
    if not earnings_next_early:
        earnings_next_early = earnings_alert_early.get("next_date")
    latest_expiry = resolved_expiry
    if back_month_chain and getattr(back_month_chain, "expiry", None):
        back_exp = str(back_month_chain.expiry)
        if latest_expiry is None or back_exp > str(latest_expiry):
            latest_expiry = back_exp
    earnings_inside, _earnings_note = earnings_inside_window(
        earnings_next_early,
        latest_expiry,
        confirmed=bool(earnings_next_early),
    )
    graded = chain_analysis["summary"].get("contract_count", 0) or 0
    liquidity_score = round(max(20.0, min(95.0, 95.0 - spread_fails * 8)), 1) if graded else 50.0
    earnings_alert = (sentiment_layer or {}).get("earnings_alert") or {}
    catalyst_days = earnings_alert.get("days_until")
    if catalyst_days is None:
        catalyst_days = earnings_alert.get("dte")
    cross_tf_score = tech_analysis.layer_scores.get("cross_tf", tech_score)
    composite_breakdown = compute_apex_composite_score(
        technical_score=tech_score,
        volatility_score=float(vol_component),
        options_score=greek_score,
        sentiment_score=sentiment_score,
        fundamental_score=fund_score,
        direction_conflict=False,
        stale_data=not data_fresh,
        wide_spreads=wide_spreads,
        earnings_before_expiry=earnings_inside,
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
    earnings_calendar = (fundamentals_layer or {}).get("earnings_calendar") if isinstance(fundamentals_layer, dict) else None
    earnings_next = None
    if isinstance(earnings_calendar, dict):
        earnings_next = earnings_calendar.get("next_date")
    if not earnings_next:
        earnings_next = earnings_alert.get("next_date")
    earnings_date_confirmed = bool(earnings_next)
    if not earnings_date_confirmed:
        catalyst_days = None
    elif catalyst_days is None and isinstance(earnings_calendar, dict):
        catalyst_days = earnings_calendar.get("dte")
        if catalyst_days is None:
            catalyst_days = earnings_calendar.get("days_until")
    best_delta_theta = _recommended_contract_delta_theta(chain_analysis)
    apex_input = build_apex_strategy_input_from_scan(
        catalyst_days=int(catalyst_days) if catalyst_days is not None else None,
        vol_layer=vol_layer,
        chain_analysis=chain_analysis,
        back_month_contracts=[c.model_dump() for c in back_month_chain.contracts]
        if back_month_chain and back_month_chain.contracts
        else None,
    )
    back_month_ready = bool(back_month_chain and back_month_chain.contracts)
    spread_pct_points = float(median_spread) * 100.0 if median_spread is not None else None
    raw_hv = vol_layer.get("hv")
    rule_context = _benchmark_rule_context(
        chain_analysis,
        direction=direction,
        sentiment_score=sentiment_score,
        sentiment_bias=(sentiment_layer or {}).get("bias") if isinstance(sentiment_layer, dict) else None,
        spot=last if isinstance(last, (int, float)) else None,
        hv20=hv,
        iv=iv,
        iv_rank=ivr if isinstance(ivr, (int, float)) else vol_layer.get("iv_rank"),
        rsi=rsi_v,
    )
    decision = strategy_decision(
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi_v,
        iv=iv,
        hv=raw_hv if isinstance(raw_hv, (int, float)) and not isinstance(raw_hv, bool) else None,
        ivr=ivr if isinstance(ivr, (int, float)) else vol_layer.get("iv_rank"),
        tech_score=tech_score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=best_delta_theta or None,
        symbol=snapshot.symbol,
        spot=last if isinstance(last, (int, float)) else None,
        spread_pct=spread_pct_points,
        data_fresh=data_fresh,
        confirmed_pattern_count=len(tech_analysis.confirmed_patterns),
        apex_input=apex_input,
        auto_exec_threshold=auto_execution_threshold,
        back_month_available=back_month_ready,
        catalyst_days=int(catalyst_days) if catalyst_days is not None else None,
        earnings_date_confirmed=earnings_date_confirmed if earnings_next or earnings_alert or earnings_calendar else None,
        risk_profile=risk_profile,
        rule_context=rule_context,
        sentiment_bias=(sentiment_layer or {}).get("bias") if isinstance(sentiment_layer, dict) else None,
    )
    strategy = decision.best_match

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
    structure_for_legs = decision.leg_structure or strategy
    chain_analysis = {
        **chain_analysis,
        "shares_held": int(shares_held or 0),
        "shares_encumbered": int(shares_encumbered or 0),
        "shares_short": int(shares_short or 0),
        "share_avg_cost": share_avg_cost,
        "stock_ask": stock_ask,
    }
    # The playbook builder still blanks legs at or below the old blocked band. Ask for the
    # structure above that band, then restore the real score. 72 is not a second gate.
    layer_composite = composite if composite > EXECUTION_SCORE_BLOCKED_MAX else float(EXECUTION_SCORE_BLOCKED_MAX + 1)
    strategy_layer = build_strategy_layer(
        strategy_name=strategy,
        composite=layer_composite,
        direction=direction,
        vol_signal=vol_signal,
        chain_analysis=chain_analysis,
        vol_layer=vol_layer,
        sentiment_layer=sentiment_payload,
        fundamentals_layer=fundamentals_payload,
        tech_score=tech_score,
        auto_exec_threshold=auto_execution_threshold,
        back_month_contracts=back_month_rows if _strategy_requires_back_month(structure_for_legs) else None,
        back_expiry=back_expiry,
        ticker=snapshot.symbol,
        gate_reason=decision.gate_reason,
        leg_structure=decision.leg_structure,
        strategies_evaluated=decision.strategies_evaluated,
        risk_notes=list(decision.risk_notes),
        benchmark_rule=(
            "rule2"
            if any(
                "APEX Benchmark Greeks Strategy Rule 2" in note
                for note in next(
                    (row.gate_notes for row in decision.candidates if row.name == strategy and row.eligible),
                    [],
                )
            )
            else None
        ),
    )
    if layer_composite != composite:
        _restore_scored_strategy_layer(strategy_layer, composite, auto_execution_threshold)
    strategy, strategy_layer = _promote_close_executable(
        strategy,
        strategy_layer,
        decision,
        build=lambda name: _scored_strategy_layer(
            name,
            composite=composite,
            layer_composite=layer_composite,
            direction=direction,
            vol_signal=vol_signal,
            chain_analysis=chain_analysis,
            vol_layer=vol_layer,
            sentiment_layer=sentiment_payload,
            fundamentals_layer=fundamentals_payload,
            tech_score=tech_score,
            auto_execution_threshold=auto_execution_threshold,
            back_month_rows=back_month_rows,
            back_expiry=back_expiry,
            ticker=snapshot.symbol,
            gate_reason=decision.gate_reason,
            leg_structure=decision.leg_structure,
            strategies_evaluated=decision.strategies_evaluated,
            risk_notes=list(decision.risk_notes),
            candidates=decision.candidates,
        ),
    )
    execution_tier = "auto_exec" if composite >= auto_execution_threshold else "caution"
    strategy_legs = []
    equity_legs = []
    strat_spec = None
    if strategy_layer.get("tradeable"):
        from app.services.stock_leg import build_order_ticket
        from app.strategies.registry import get_strategy_spec, resolve_strategy_id

        strat_spec = get_strategy_spec(strategy_layer.get("selected_strategy") or strategy)
        strategy_legs, equity_legs = build_order_ticket(
            strategy_layer.get("metrics") or {},
            tradeable=True,
            equity_required=bool(strat_spec and strat_spec.equity_required),
            ticker=snapshot.symbol,
        )
        covered_by_holdings = bool((strategy_layer.get("metrics") or {}).get("equity_covered_by_holdings"))
        if strat_spec and strat_spec.equity_required and not equity_legs and not covered_by_holdings:
            equity_error = {
                "strategy_id": resolve_strategy_id(strategy) or strategy,
                "ticker": snapshot.symbol,
                "check": "equity_leg_required",
                "expected": "stock leg for simultaneous equity strategy",
                "actual": "missing",
            }
            strategy_layer = {
                **strategy_layer,
                "tradeable": False,
                "validation_errors": (strategy_layer.get("validation_errors") or []) + [equity_error],
                "risk_notes": list(strategy_layer.get("risk_notes") or [])
                + ["Pre-trade check equity_leg_required: expected stock leg for simultaneous equity strategy; actual missing."],
            }
            strategy_legs = []
    defined_risk = is_defined_risk_strategy(str(strategy_layer.get("selected_strategy") or strategy))
    auto_submit_on_ack = bool(strategy_layer.get("auto_execute_eligible"))
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
            "defined_risk": defined_risk,
            "auto_submit_on_ack": auto_submit_on_ack,
            "requires_place_order": not auto_submit_on_ack,
            "allows_execution": bool(strategy_legs),
            "execution_score": composite,
            "execution_tier": execution_tier,
            "auto_execution_threshold": auto_execution_threshold,
            "risk_profile": risk_profile,
            "strategy_legs": strategy_legs,
            "equity_legs": equity_legs,
            "equity_required": bool(strat_spec and strat_spec.equity_required),
            "equity_note": strategy_layer.get("equity_note"),
            "block_reason": (
                strategy_layer.get("block_reason")
                if strategy_layer.get("placeable") is False
                else (None if strategy_legs else _order_block_reason(strategy_layer))
            ),
            "contracts_per_leg": 1,
            "asset_class": "us_option",
            "position_sizing": "2–5% of declared account capital per trade (configurable)",
            "daily_loss_cap": "Configurable; trading auto-halts if breached",
            "bid_ask_hard_stop": "Reject a leg when its bid/ask spread exceeds 10% of mid",
            "earnings_blackout": f"No new positions within 1 day of earnings (exception: {APEX_STRATEGY_NAME})",
            "narrative": (
                "Review each leg, the quantity, the order type, the limit price, the estimated cost or credit, "
                "and the account impact before submitting. Broker fees are not on this quote."
            ),
            "auto_execute_eligible": auto_submit_on_ack,
            "auto_exec_line": strategy_layer.get("auto_exec_line"),
            "auto_exec_reasons": strategy_layer.get("auto_exec_reasons") or [],
            "executable": bool(strategy_layer.get("placeable")) and not bool(strategy_layer.get("auto_exec_blocked")),
            "placeable": bool(strategy_layer.get("placeable")),
            "spread_confirmation_required": bool(strategy_layer.get("spread_block_reasons"))
            and bool(strategy_layer.get("placeable")),
            "spread_block_reasons": strategy_layer.get("spread_block_reasons") or [],
            "quote_not_current": bool(strategy_layer.get("quote_not_current")),
            "quote_as_of": strategy_layer.get("quote_as_of"),
            "structure_label": strategy_layer.get("structure_label"),
            "stock_legs": _stock_context_rows(strategy_layer.get("metrics") or {}, snapshot.symbol),
        },
    }
    # Guarantee every documented layer key is present and ordered
    return {layer.value: layers[layer] for layer in DEEP_SCAN_LAYERS}


def _layer_is_executable(layer: dict[str, Any]) -> bool:
    return bool(layer.get("placeable")) and not bool(layer.get("auto_exec_blocked")) and bool(layer.get("tradeable"))


def _scored_strategy_layer(name: str, **kwargs: Any) -> dict[str, Any]:
    composite = kwargs.pop("composite")
    layer_composite = kwargs.pop("layer_composite")
    threshold = kwargs.pop("auto_execution_threshold")
    back_month_rows = kwargs.pop("back_month_rows")
    candidates = kwargs.pop("candidates")
    benchmark = None
    if any(
        "APEX Benchmark Greeks Strategy Rule 2" in note
        for note in next((row.gate_notes for row in candidates if row.name == name and row.eligible), [])
    ):
        benchmark = "rule2"
    layer = build_strategy_layer(
        strategy_name=name,
        composite=layer_composite,
        auto_exec_threshold=threshold,
        back_month_contracts=back_month_rows if _strategy_requires_back_month(name) else None,
        benchmark_rule=benchmark,
        **kwargs,
    )
    if layer_composite != composite:
        _restore_scored_strategy_layer(layer, composite, threshold)
    return layer


def _promote_close_executable(
    strategy: str,
    layer: dict[str, Any],
    decision: Any,
    *,
    build: Any,
) -> tuple[str, dict[str, Any]]:
    """Prefer an executable candidate within CLOSE_SCORE_GAP of a blocked winner."""
    if _layer_is_executable(layer):
        return strategy, layer
    primary = next((row for row in decision.candidates if row.name == strategy), None)
    primary_score = float(primary.score) if primary is not None else float(layer.get("composite_score") or 0)
    best_name = None
    best_score: float | None = None
    best_layer = None
    for cand in decision.candidates:
        if cand.name == strategy or not cand.eligible or not cand.defined_risk:
            continue
        if primary_score - float(cand.score) > CLOSE_SCORE_GAP:
            continue
        alt = build(cand.name)
        if not _layer_is_executable(alt):
            continue
        if best_score is None or float(cand.score) > best_score:
            best_name = cand.name
            best_score = float(cand.score)
            best_layer = alt
    if best_layer is None or best_name is None:
        return strategy, layer
    return best_name, best_layer


def _stock_context_rows(metrics: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for leg in metrics.get("legs") or []:
        if not isinstance(leg, dict) or leg.get("side") != "stock":
            continue
        rows.append(
            {
                "symbol": leg.get("symbol") or ticker,
                "side": leg.get("action") or "buy",
                "qty": leg.get("quantity") or leg.get("shares_used") or 0,
                "shares_used": leg.get("shares_used"),
                "already_held": bool(leg.get("already_held") or metrics.get("equity_covered_by_holdings")),
                "order_type": leg.get("order_type") or "market",
                "price": leg.get("mid"),
                "note": metrics.get("equity_note"),
            }
        )
    return rows


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


def _order_block_reason(strategy_layer: dict[str, Any]) -> str | None:
    """Why the order step has no option legs. A built contract is not this sentence."""
    metrics = strategy_layer.get("metrics") or {}
    handler = metrics.get("validation_error")
    if isinstance(handler, str) and handler.strip():
        return handler.strip()
    errors = strategy_layer.get("validation_errors") or []
    if errors and isinstance(errors[0], dict):
        first = errors[0]
        return (
            f"Pre-trade check {first.get('check')}: expected {first.get('expected')}; "
            f"actual {first.get('actual')}."
        )
    note = strategy_layer.get("equity_note")
    if isinstance(note, str) and note.strip():
        return note.strip()
    notes = [n for n in (strategy_layer.get("risk_notes") or []) if isinstance(n, str) and n.strip()]
    return notes[0] if notes else None


def _restore_scored_strategy_layer(layer: dict[str, Any], composite: float, threshold: float) -> None:
    """Put the real composite back after the playbook builder was asked above the old blocked band.

    The saved minimum only chooses auto-submit versus manual placement.
    """
    layer["composite_score"] = composite
    tier = "auto_exec" if composite >= threshold else "caution"
    layer["execution_tier"] = tier
    why = layer.get("why_recommended")
    if not isinstance(why, str) or not why.startswith("Composite "):
        return
    sentence = (
        f"Composite {composite:g}/100 meets your auto-execution threshold ({threshold:.0f})."
        if tier == "auto_exec"
        else (
            f"Composite {composite:g}/100 — manual review required below your auto-execution threshold "
            f"({threshold:.0f})."
        )
    )
    # "51.0" contains a decimal point; split on the sentence boundary instead.
    boundary = why.find(". ")
    layer["why_recommended"] = sentence + (why[boundary + 1 :] if boundary != -1 else "")
    fit = layer.get("why_it_fits")
    if isinstance(fit, str) and fit.startswith("Composite "):
        fit_dot = fit.find(".")
        layer["why_it_fits"] = sentence + (fit[fit_dot + 1 :] if fit_dot != -1 else "")
