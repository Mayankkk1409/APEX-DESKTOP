"""APEX strategy playbook selection and payoff metrics (Full Document §8–§10)."""

from __future__ import annotations

from typing import Any, Literal

from app.analysis.layers import COMPOSITE_THRESHOLD_FULL_DOC, EXECUTION_SCORE_BLOCKED_MAX

NOT_TRADEABLE_COPY = "Not tradeable in current situation"


def _execution_tier(composite: float) -> str:
    if composite <= EXECUTION_SCORE_BLOCKED_MAX:
        return "blocked"
    if composite >= COMPOSITE_THRESHOLD_FULL_DOC:
        return "auto_exec"
    return "caution"

StrategyName = str

PLAYBOOK: dict[str, dict[str, str]] = {
    "Short Iron Condor": {
        "summary": "Sell OTM put spread and OTM call spread to collect premium when IV is rich and price is range-bound.",
        "execution": (
            "Sell one OTM put below support, buy a further OTM put for protection. "
            "Sell one OTM call above resistance, buy a further OTM call for protection. "
            "Target 30–45 DTE; manage at 50% max profit or if price breaches a short strike."
        ),
    },
    "Bull Call Spread": {
        "summary": "Debit spread that profits from a moderate rise with capped risk.",
        "execution": (
            "Buy a call near the money (Δ ≈ 0.55 per §9.2 Rule 1). "
            "Sell a higher-strike call in the same expiry to reduce cost. "
            "Size so max loss fits the 2–5% account risk budget."
        ),
    },
    "Bear Put Spread": {
        "summary": "Debit spread that profits from a moderate decline with capped risk.",
        "execution": (
            "Buy a put near the money. Sell a lower-strike put in the same expiry. "
            "Confirm bid/ask spread < 8% of mid on both legs before entry."
        ),
    },
    "Bull Put Spread (credit)": {
        "summary": "Credit spread expressing mild bullish bias when premium is elevated.",
        "execution": (
            "Sell an OTM put (Δ ≤ 0.20). Buy a further OTM put for defined risk. "
            "Collect credit; max profit if both expire worthless."
        ),
    },
    "Bear Call Spread (credit)": {
        "summary": "Credit spread expressing mild bearish bias when premium is elevated.",
        "execution": (
            "Sell an OTM call (Δ ≤ 0.20). Buy a further OTM call for defined risk."
        ),
    },
    "Gamma Trampoline™": {
        "summary": "APEX proprietary catalyst structure: wide OTM strikes across front and back expirations.",
        "execution": (
            "Step 1 — Buy back-week OTM call (Strike A) and OTM put (Strike B). "
            "Step 2 — Sell front-week call and put at the same strikes to subsidize long gamma. "
            "Front expiry should be the day after the catalyst; back expiry ~2 weeks later."
        ),
    },
    "APEX Benchmark Greeks Strategy": {
        "summary": "Proprietary long-premium expression when Δ is high, Θ is low, and IV < HV (§9.2 Rule 1).",
        "execution": (
            "Buy the recommended contract with Δ ≥ 0.55 and daily Θ < 0.05. "
            "APEX Δ/Θ ratio must exceed 10; spread < 8% of mid. "
            "Hold through the directional thesis; exit on SuperTrend flip or composite drop below 72."
        ),
    },
    "Married Put": {
        "summary": "Protective put paired with stock — insurance on a bullish core position.",
        "execution": (
            "Own (or plan to own) shares. Buy a put slightly OTM at 30–45 DTE. "
            "Strike near pivot support; roll before expiry if thesis intact."
        ),
    },
    "Married Call": {
        "summary": "Long stock plus long call — leveraged upside participation with defined premium cost.",
        "execution": (
            "Own shares (or pair with simultaneous stock entry). Buy a call near Δ 0.55. "
            "Acts as synthetic leverage while retaining dividend and voting rights on stock."
        ),
    },
    "Diagonal Spread (bullish)": {
        "summary": "Long back-month call, short nearer-term OTM call — bullish bias with time spread.",
        "execution": "Buy longer-dated call; sell shorter-dated higher-strike call against it.",
    },
    "Diagonal Spread (bearish)": {
        "summary": "Long back-month put, short nearer-term OTM put — bearish bias with time spread.",
        "execution": "Buy longer-dated put; sell shorter-dated lower-strike put against it.",
    },
    "Calendar Spread": {
        "summary": "Sell front-month, buy back-month at the same strike when IV is fair and direction is neutral.",
        "execution": "Sell near-term option at ATM; buy same-strike back-month. Profit from theta differential.",
    },
    "Long Straddle": {
        "summary": "Long ATM call and put when IV is cheap and a large move is expected.",
        "execution": "Buy ATM call and ATM put same expiry. Exit on expansion or time stop.",
    },
    "NO TRADE — Insufficient Conviction": {
        "summary": "Composite score below the 72 execution threshold — monitor only.",
        "execution": "No new positions. Re-run scan when technical alignment and IV regime improve.",
    },
    "NO TRADE — Wait for IV Crush": {
        "summary": "Extreme IV overhang — edge is destroyed by premium crush risk.",
        "execution": "Stand aside until front-month IV normalizes toward HV.",
    },
}


def _mid(contract: dict[str, Any]) -> float | None:
    bid, ask = contract.get("bid"), contract.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    last = contract.get("last")
    return float(last) if last is not None else None


def _pick_strike(contracts: list[dict[str, Any]], side: Literal["call", "put"], spot: float, delta_target: float) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike")]
    if not pool:
        return None
    if side == "call":
        pool.sort(key=lambda c: abs((c.get("delta") or 0) - delta_target))
    else:
        pool.sort(key=lambda c: abs((c.get("delta") or 0) + delta_target))
    return pool[0]


def compute_strategy_metrics(
    strategy_name: str,
    *,
    spot: float | None,
    contracts: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
    contract_multiplier: int = 100,
) -> dict[str, Any]:
    """Return max loss, max profit, net debit/credit, breakevens for the named strategy."""
    empty = {
        "max_loss": None,
        "max_profit": None,
        "net_debit_credit": None,
        "net_type": None,
        "breakevens": [],
        "legs": [],
        "per_contract_multiplier": contract_multiplier,
    }
    if "NO TRADE" in strategy_name or not contracts:
        return empty

    atm = spot or (recommended or {}).get("strike")
    if atm is None:
        return empty

    rec_side = (recommended or {}).get("side")
    rec_strike = (recommended or {}).get("strike")

    def leg(action: str, c: dict[str, Any] | None) -> dict[str, Any] | None:
        if not c:
            return None
        m = _mid(c)
        return {
            "action": action,
            "side": c.get("side"),
            "strike": c.get("strike"),
            "expiry": c.get("expiry") or (recommended or {}).get("expiry"),
            "mid": m,
            "symbol": c.get("symbol"),
        }

    legs: list[dict[str, Any]] = []
    metrics = dict(empty)

    if "Iron Condor" in strategy_name:
        short_put = _pick_strike(contracts, "put", atm, 0.20)
        long_put = min(
            (c for c in contracts if c.get("side") == "put" and short_put and c.get("strike", 0) < short_put["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        short_call = _pick_strike(contracts, "call", atm, 0.20)
        long_call = min(
            (c for c in contracts if c.get("side") == "call" and short_call and c.get("strike", 0) > short_call["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        for action, c in [("sell", short_put), ("buy", long_put), ("sell", short_call), ("buy", long_call)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        credits = sum(l["mid"] or 0 for l in legs if l["action"] == "sell")
        debits = sum(l["mid"] or 0 for l in legs if l["action"] == "buy")
        net = credits - debits
        put_width = (short_put["strike"] - long_put["strike"]) if short_put and long_put else 0
        call_width = (long_call["strike"] - short_call["strike"]) if short_call and long_call else 0
        width = max(put_width, call_width)
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "credit" if net >= 0 else "debit",
                "max_profit": round(net * contract_multiplier, 2) if net > 0 else None,
                "max_loss": round((width - net) * contract_multiplier, 2) if width and net >= 0 else None,
                "breakevens": [
                    round(short_put["strike"] - net, 2) if short_put else None,
                    round(short_call["strike"] + net, 2) if short_call else None,
                ],
                "legs": legs,
            }
        )
        return metrics

    if "Bull Call" in strategy_name:
        long_c = next((c for c in contracts if c.get("side") == "call" and c.get("strike") == rec_strike), None) or _pick_strike(
            contracts, "call", atm, 0.55
        )
        short_c = min(
            (c for c in contracts if c.get("side") == "call" and long_c and c.get("strike", 0) > long_c["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        for action, c in [("buy", long_c), ("sell", short_c)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        debits = sum(l["mid"] or 0 for l in legs if l["action"] == "buy")
        credits = sum(l["mid"] or 0 for l in legs if l["action"] == "sell")
        net = debits - credits
        width = (short_c["strike"] - long_c["strike"]) if long_c and short_c else 0
        be = (long_c["strike"] + net) if long_c else None
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "debit",
                "max_loss": round(net * contract_multiplier, 2),
                "max_profit": round((width - net) * contract_multiplier, 2) if width else None,
                "breakevens": [round(be, 2)] if be else [],
                "legs": legs,
            }
        )
        return metrics

    if "Bear Put" in strategy_name and "Spread" in strategy_name:
        long_p = next((c for c in contracts if c.get("side") == "put" and c.get("strike") == rec_strike), None) or _pick_strike(
            contracts, "put", atm, 0.55
        )
        short_p = max(
            (c for c in contracts if c.get("side") == "put" and long_p and c.get("strike", 0) < long_p["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        for action, c in [("buy", long_p), ("sell", short_p)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        debits = sum(l["mid"] or 0 for l in legs if l["action"] == "buy")
        credits = sum(l["mid"] or 0 for l in legs if l["action"] == "sell")
        net = debits - credits
        width = (long_p["strike"] - short_p["strike"]) if long_p and short_p else 0
        be = (long_p["strike"] - net) if long_p else None
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "debit",
                "max_loss": round(net * contract_multiplier, 2),
                "max_profit": round((width - net) * contract_multiplier, 2) if width else None,
                "breakevens": [round(be, 2)] if be else [],
                "legs": legs,
            }
        )
        return metrics

    if "Married Put" in strategy_name:
        prot = _pick_strike(contracts, "put", atm, 0.30)
        lg = leg("buy", prot)
        if lg:
            legs.append(lg)
            prem = lg["mid"] or 0
            metrics.update(
                {
                    "net_debit_credit": round(prem, 2),
                    "net_type": "debit",
                    "max_loss": None,
                    "max_profit": None,
                    "breakevens": [round(atm - prem, 2)] if atm else [],
                    "legs": legs,
                }
            )
        return metrics

    if "Married Call" in strategy_name or "Benchmark Greeks" in strategy_name:
        focus = next(
            (c for c in contracts if c.get("side") == rec_side and c.get("strike") == rec_strike),
            _pick_strike(contracts, rec_side or "call", atm, 0.55),
        )
        lg = leg("buy", focus)
        if lg:
            legs.append(lg)
            prem = lg["mid"] or 0
            be = (focus["strike"] + prem) if focus.get("side") == "call" else (focus["strike"] - prem)
            metrics.update(
                {
                    "net_debit_credit": round(prem, 2),
                    "net_type": "debit",
                    "max_loss": round(prem * contract_multiplier, 2),
                    "max_profit": None,
                    "breakevens": [round(be, 2)],
                    "legs": legs,
                }
            )
        return metrics

    if "Gamma Trampoline" in strategy_name:
        call_a = _pick_strike(contracts, "call", atm, 0.25)
        put_b = _pick_strike(contracts, "put", atm, 0.25)
        for action, c in [("buy", call_a), ("buy", put_b)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        debits = sum(l["mid"] or 0 for l in legs)
        metrics.update(
            {
                "net_debit_credit": round(debits * 0.45, 2),
                "net_type": "debit",
                "max_loss": round(debits * 0.45 * contract_multiplier, 2),
                "max_profit": None,
                "breakevens": [round(atm, 2)],
                "legs": legs,
                "notes": "Front-week shorts subsidize ~50–70% of back-week longs per §10.2; net shown is estimated post-subsidy.",
            }
        )
        return metrics

    # Single-leg or calendar/diagonal fallback from recommended contract
    focus = next(
        (c for c in contracts if c.get("side") == rec_side and c.get("strike") == rec_strike),
        contracts[0] if contracts else None,
    )
    lg = leg("buy" if "credit" not in strategy_name.lower() else "sell", focus)
    if lg:
        legs.append(lg)
        prem = lg["mid"] or 0
        is_call = focus.get("side") == "call"
        be = (focus["strike"] + prem) if is_call and lg["action"] == "buy" else (focus["strike"] - prem)
        metrics.update(
            {
                "net_debit_credit": round(prem, 2),
                "net_type": "credit" if lg["action"] == "sell" else "debit",
                "max_loss": round(prem * contract_multiplier, 2) if lg["action"] == "buy" else None,
                "max_profit": round(prem * contract_multiplier, 2) if lg["action"] == "sell" else None,
                "breakevens": [round(be, 2)],
                "legs": legs,
            }
        )
    return metrics


def select_strategy(
    *,
    composite: float,
    direction: str,
    vol_signal: str,
    rsi: float | None = None,
    iv: float | None = None,
    hv: float | None = None,
    ivr: float | None = None,
    tech_score: float | None = None,
    sentiment_score: float | None = None,
    catalyst_active: bool = False,
    delta_theta_ratio: float | None = None,
) -> StrategyName:
    """Eligibility matrix from Full Document §9.1 — not a hardcoded iron condor."""
    if composite < COMPOSITE_THRESHOLD_FULL_DOC:
        return "NO TRADE — Insufficient Conviction"

    if iv and hv and iv > hv * 1.35:
        return "NO TRADE — Wait for IV Crush"

    rsi_v = rsi if rsi is not None else 50.0
    tech = tech_score or composite
    iv_cheap = iv is not None and hv is not None and (hv - iv) > 0.10
    iv_rich = vol_signal == "sell_premium" or (iv is not None and hv is not None and (iv - hv) > 0.10)

    if catalyst_active and ivr is not None and ivr > 70 and iv and hv and iv > hv:
        return "Gamma Trampoline™"

    if iv_cheap:
        if tech > 80 and direction == "bullish":
            if delta_theta_ratio and delta_theta_ratio >= 10:
                return "APEX Benchmark Greeks Strategy"
            return "Bull Call Spread"
        if tech > 80 and direction == "bearish":
            return "Bear Put Spread"
        if direction == "neutral":
            return "Long Straddle"
        if direction == "bullish" and sentiment_score and sentiment_score > 60:
            return "Married Call"
        if direction == "bullish":
            return "Married Put"

    if iv_rich:
        if 40 <= rsi_v <= 60:
            return "Short Iron Condor"
        if direction == "bullish":
            return "Bull Put Spread (credit)"
        if direction == "bearish":
            return "Bear Call Spread (credit)"

    if direction == "bullish":
        return "Diagonal Spread (bullish)"
    if direction == "bearish":
        return "Diagonal Spread (bearish)"
    return "Calendar Spread"


def _risk_score(composite: float, chain_analysis: dict[str, Any]) -> float:
    tier = chain_analysis.get("execution_tier")
    if tier == "blocked" or composite <= EXECUTION_SCORE_BLOCKED_MAX:
        return max(5.0, composite * 0.5)
    spread_fails = chain_analysis.get("summary", {}).get("gate_failures", {}).get("spread", 0)
    graded = chain_analysis.get("summary", {}).get("contract_count", 1) or 1
    liquidity_penalty = min(25.0, 25.0 * spread_fails / graded)
    base = composite if tier == "auto_exec" else composite * 0.85
    return round(max(5.0, min(98.0, base - liquidity_penalty)), 1)


def _apex_fmt(v: Any, digits: int = 2) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{float(v):.{digits}f}"
    return str(v)


def _apex_score_band(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "constructive"
    if score >= 50:
        return "mixed"
    return "weak"


def _apex_join_paragraphs(parts: list[str]) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _apex_section_payload(
    *,
    paragraphs: list[str],
    interpretation: str,
    breakdown: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "narrative": _apex_join_paragraphs(paragraphs),
        "paragraphs": [p.strip() for p in paragraphs if p and p.strip()],
        "interpretation": interpretation.strip(),
        "breakdown": breakdown,
    }


def _technicals_apex_section(
    *,
    tech_score: float,
    weight: float,
    direction: str,
    technical_narrative: str,
    technical_context: dict[str, Any] | None,
) -> dict[str, Any]:
    ctx = technical_context or {}
    last = ctx.get("last")
    rsi = ctx.get("rsi")
    macd = ctx.get("macd") or {}
    ema = ctx.get("ema") or {}
    st = ctx.get("supertrend") or {}
    bb = ctx.get("bollinger") or {}
    aligned = ctx.get("ema_aligned_bullish")
    hist = macd.get("histogram")
    st_dir = st.get("direction", "—")
    st_val = st.get("value")
    ema200 = ema.get(200)
    contribution = round(tech_score * weight, 1)
    band = _apex_score_band(tech_score)

    measured = (
        "The technical leg scores the captured chart snapshot against Project APEX §4 rules: "
        "EMA stack alignment (9/21/50/100/200), SuperTrend (ATR 10, factor 3), MACD 12/26/9 histogram, "
        "RSI(14) zone, and price versus the 200 EMA gate. Each confirmed signal adds conviction; "
        "extreme RSI or conflicting trend filters subtract."
    )
    if last is not None and ema200 is not None:
        measured += (
            f" On this scan, last price {_apex_fmt(last)} sits "
            f"{'above' if float(last) > float(ema200) else 'below'} the 200 EMA ({_apex_fmt(ema200)})."
        )

    score_meaning = (
        f"Technical score {tech_score}/100 is rated {band} for directional conviction. "
        f"Scores above 80 indicate stacked bullish or bearish alignment suitable for debit spreads and "
        f"directional premium buys; 50–65 reflects mixed or transitional structure where neutral "
        f"structures (iron condors, calendars) dominate eligibility; below 50 warns that trend filters "
        f"are fighting the tape."
    )

    drivers: list[str] = []
    if aligned:
        drivers.append("full EMA bullish stack (9>21>50>100>200)")
    else:
        drivers.append("EMA stack not fully aligned")
    if st_dir == "bullish" and last is not None and ema200 is not None and float(last) > float(ema200):
        drivers.append("SuperTrend bullish with price above 200 EMA")
    elif st_dir == "bearish":
        drivers.append(f"SuperTrend bearish at {_apex_fmt(st_val)}")
    if hist is not None:
        drivers.append(f"MACD histogram {_apex_fmt(hist, 4)} ({'positive' if hist >= 0 else 'negative'})")
    if rsi is not None:
        zone = (
            "overbought"
            if rsi > 70
            else "oversold"
            if rsi < 30
            else "range-bound"
            if 40 <= rsi <= 60
            else "transitional"
        )
        drivers.append(f"RSI {_apex_fmt(rsi, 1)} ({zone})")
    if bb.get("width") is not None:
        drivers.append(
            f"Bollinger width {_apex_fmt(bb.get('width'), 4)}"
            + (" — squeeze compression" if bb.get("width") < 0.04 else "")
        )

    drivers_para = (
        f"Key drivers on this scan: {technical_narrative} "
        f"Primary inputs contributing to the {tech_score} score: {', '.join(drivers)}. "
        f"Composite bias is {direction} — strategy eligibility in §9.1 keys off this directional label "
        f"together with volatility and Greeks quality."
    )

    weight_para = (
        f"Weighted contribution: {contribution} points of the composite ({int(weight * 100)}% weight). "
        f"Technicals carry the largest single weight in the Full Document §8 formula because price structure "
        f"and trend filters gate every downstream leg selection; a weak technical score cannot be offset "
        f"by rich IV or bullish flow alone when SuperTrend and the 200 EMA disagree."
    )

    if band == "strong" and direction == "bullish":
        action = (
            "Actionable view: trend structure supports call-side or bullish spread expressions when "
            "volatility and chain quality confirm. Wait for a SuperTrend flip or loss of EMA stack before "
            "adding contra-trend premium."
        )
    elif band == "strong" and direction == "bearish":
        action = (
            "Actionable view: bearish alignment favors put spreads or credit call structures when IV is "
            "rich. Avoid married-call or bull spread expressions until MACD and SuperTrend repair."
        )
    elif band == "mixed":
        action = (
            "Actionable view: technicals are not offering high-conviction direction — favor range structures "
            "(iron condors, calendars) or reduce size until RSI and MACD clarify."
        )
    else:
        action = (
            "Actionable view: technical score is a headwind for execution — defer new risk or use defined-risk "
            "structures only after composite clears 72 with improved alignment."
        )

    breakdown = [
        {
            "label": "Trend alignment",
            "value": direction,
            "note": "Bullish/bearish/neutral label from SuperTrend + MACD histogram",
        },
        {
            "label": "Raw technical score",
            "value": tech_score,
            "note": "Base 50 + EMA stack + SuperTrend/200 EMA + MACD + RSI adjustments (5–98)",
        },
        {
            "label": "RSI (14)",
            "value": rsi if rsi is not None else "—",
            "note": "40–60 favors premium selling; extremes penalize score",
        },
        {
            "label": "SuperTrend",
            "value": f"{st_dir} @ {_apex_fmt(st_val)}" if st_val is not None else st_dir,
            "note": "ATR 10, factor 3 on captured window",
        },
        {
            "label": "200 EMA",
            "value": ema200 if ema200 is not None else "—",
            "note": "Long-term trend gate per §4",
        },
        {
            "label": "Weighted contribution",
            "value": contribution,
            "note": f"{int(weight * 100)}% of composite",
        },
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "technicals",
        "title": "Technicals",
        "score": tech_score,
        "weight": weight,
        "weighted_contribution": contribution,
        **section_body,
    }


def _options_apex_section(
    *,
    greek_score: float,
    weight: float,
    chain_analysis: dict[str, Any],
) -> dict[str, Any]:
    summary = chain_analysis.get("summary") or {}
    counts = summary.get("verdict_counts") or {}
    graded = summary.get("contract_count", 0) or 0
    tradeable = counts.get("tradeable", 0)
    buy_c = counts.get("buy_candidate", 0)
    sell_c = counts.get("sell_candidate", 0)
    clean = buy_c + sell_c + tradeable
    tier = chain_analysis.get("execution_tier", "—")
    spread_fails = (summary.get("gate_failures") or {}).get("spread", 0)
    median_spread = summary.get("median_spread_pct")
    recommended = chain_analysis.get("recommendedContract")
    contribution = round(greek_score * weight, 1)
    band = _apex_score_band(greek_score)
    clean_pct = round(100.0 * clean / graded, 1) if graded else 0.0

    measured = (
        "The options leg is the Greeks Quality Score (Full Document §8, 20% weight): every contract on the "
        "selected expiry is graded against §5 gates — bid/ask spread vs mid, open interest, delta/theta ratio, "
        "vega cap, gamma risk on short DTE, and hard rejects for missing quotes. The score is the share of "
        "graded contracts that clear actionable verdicts (buy_candidate, sell_candidate, or tradeable), "
        "mapped to a 40–95 scale so an empty or toxic chain cannot masquerade as high quality."
    )
    if graded:
        measured += f" This scan graded {graded} contracts ({summary.get('call_count', '—')} calls, {summary.get('put_count', '—')} puts)."

    score_meaning = (
        f"Greeks Quality Score {greek_score}/100 ({band}): {clean} of {graded} contracts ({clean_pct}%) "
        f"passed actionable gates. Execution tier for the composite is {tier}. "
        f"A score below 65 usually means spread or liquidity failures dominate — not a Greek misread on a "
        f"single strike."
    )

    drivers_para = (
        f"Gate failures on spread: {spread_fails} contract(s). "
        f"Median bid/ask spread {_apex_fmt(median_spread, 1)}% of mid when quoted. "
        f"Verdict mix — buy candidates {buy_c}, sell candidates {sell_c}, tradeable {tradeable}, "
        f"rejected/screened {counts.get('rejected', 0) + counts.get('screened_out', 0)}. "
    )
    if recommended:
        drivers_para += (
            f"Recommended contract: {recommended.get('side', '—')} "
            f"{_apex_fmt(recommended.get('strike'))} exp {recommended.get('expiry', '—')}."
        )
    else:
        drivers_para += "No recommended contract — composite or gate stack blocked auto-selection."

    weight_para = (
        f"Weighted contribution: {contribution} points ({int(weight * 100)}% weight). "
        "Options quality is weighted second only to technicals because illiquid legs inflate slippage and "
        "invalidate modeled payoffs; §5 explicitly merges chain structure and Greek fitness on one screen."
    )

    if greek_score >= 75 and recommended:
        action = (
            "Actionable view: chain quality supports execution on the recommended leg — verify live spread "
            "before entry and size to 2–5% account risk. If spread widens beyond 10% of mid, re-run scan."
        )
    elif greek_score >= 55:
        action = (
            "Actionable view: partial chain quality — consider alternative strikes/DTE from top buy/sell "
            "candidate lists or reduce size until more contracts clear spread gates."
        )
    else:
        action = (
            "Actionable view: chain is not fit for automated execution — widen expiry search, avoid wide "
            "spreads, or wait for liquidity; do not force legs that failed §5 hard stops."
        )

    breakdown = [
        {"label": "Contracts graded", "value": graded, "note": "Full chain on selected expiry"},
        {"label": "Clean / actionable", "value": clean, "note": f"{clean_pct}% of graded"},
        {"label": "Buy candidates", "value": buy_c, "note": "Long premium / delta expressions"},
        {"label": "Sell candidates", "value": sell_c, "note": "Credit / short premium legs"},
        {"label": "Spread gate failures", "value": spread_fails, "note": "Hard stop >10% of mid"},
        {"label": "Execution tier", "value": tier, "note": "From composite score bands"},
        {"label": "Weighted contribution", "value": contribution, "note": f"{int(weight * 100)}% of composite"},
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "options",
        "title": "Options",
        "score": greek_score,
        "weight": weight,
        "weighted_contribution": contribution,
        **section_body,
    }


def _volatility_apex_section(
    *,
    vol_score: float,
    weight: float,
    vol_layer: dict[str, Any],
) -> dict[str, Any]:
    iv = vol_layer.get("iv")
    hv = vol_layer.get("hv")
    iv_rank = vol_layer.get("iv_rank")
    iv_pct = vol_layer.get("iv_percentile")
    signal = vol_layer.get("signal") or "fair"
    em = vol_layer.get("expected_move") or {}
    em_pct = em.get("percent")
    em_dollar = em.get("dollar")
    dte = vol_layer.get("dte")
    term = vol_layer.get("term_structure") or {}
    iv_vs_hv = vol_layer.get("iv_vs_hv") or {}
    contribution = round(vol_score * weight, 1)
    band = _apex_score_band(vol_score)
    layer_narrative = vol_layer.get("narrative")

    measured = (
        "The volatility leg scores whether implied volatility (IV) is cheap or rich versus realized "
        "historical volatility (HV), IV Rank / Percentile versus a rolling history, expected move at the "
        "scan expiry, and term-structure shape. Full Document §8 maps the vol signal to a component score: "
        "buy_premium ≈ 80 (IV cheap — favor long vol), sell_premium ≈ 72 (IV rich — favor credits), "
        "fair ≈ 55 (no strong vol edge)."
    )
    if iv is not None and hv is not None:
        measured += f" ATM / contract IV {_apex_fmt(iv, 3)} vs 30D HV {_apex_fmt(hv, 3)}."

    score_meaning = (
        f"Volatility component score {vol_score}/100 ({band}) with signal '{signal}'. "
        f"IV Rank {_apex_fmt(iv_rank, 1)} / percentile {_apex_fmt(iv_pct, 1)}. "
        f"This score does not predict direction — it tells you which strategy families §9.1 should prefer "
        f"(debit vs credit vs neutral)."
    )

    drivers_para = layer_narrative or (
        f"IV vs HV gap: {iv_vs_hv.get('label', '—')}. "
        f"Expected move ±{_apex_fmt(em_pct, 1)}% (${_apex_fmt(em_dollar)}) at {dte or '—'} DTE. "
        f"Term structure: {term.get('shape', '—')} — {term.get('detail', '')}"
    )

    weight_para = (
        f"Weighted contribution: {contribution} points ({int(weight * 100)}% weight — largest after "
        "technicals). Volatility regime often determines whether §9.1 selects iron condors versus bull "
        "call spreads; misalignment here is a common reason composite clears 72 but strategy still reads "
        "'NO TRADE — Wait for IV Crush' when IV >> HV."
    )

    if signal == "buy_premium":
        action = (
            "Actionable view: IV is relatively cheap — favor long premium, debit spreads, and structures "
            "that benefit from vol expansion; avoid naked short vol unless hedged."
        )
    elif signal == "sell_premium":
        action = (
            "Actionable view: IV is rich versus HV — favor credit spreads, iron condors, and short strangles "
            "with defined risk; be cautious adding long gamma unless catalyst justifies it."
        )
    else:
        action = (
            "Actionable view: vol edge is muted — let technicals and chain quality drive structure choice; "
            "avoid oversized vega bets."
        )

    breakdown = [
        {"label": "IV", "value": iv, "note": "ATM or recommended contract"},
        {"label": "HV (30D)", "value": hv, "note": "Realized on captured daily window"},
        {"label": "IV Rank", "value": iv_rank, "note": "0–100 vs IV history"},
        {"label": "IV Percentile", "value": iv_pct, "note": "Historical percentile"},
        {"label": "Signal", "value": signal, "note": "buy_premium / sell_premium / fair"},
        {"label": "Expected move", "value": f"±{_apex_fmt(em_pct, 1)}%", "note": f"${_apex_fmt(em_dollar)} at {dte or '—'} DTE"},
        {"label": "Weighted contribution", "value": contribution, "note": f"{int(weight * 100)}% of composite"},
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "volatility",
        "title": "Volatility",
        "score": vol_score,
        "weight": weight,
        "weighted_contribution": contribution,
        **section_body,
    }


def _sentiment_apex_section(
    *,
    sentiment_score: float,
    weight: float,
    sentiment_layer: dict[str, Any],
) -> dict[str, Any]:
    components = sentiment_layer.get("components") or {}
    news = components.get("news") or {}
    flow = components.get("options_flow") or {}
    social = components.get("social") or {}
    pc = components.get("put_call") or {}
    signed = sentiment_layer.get("score")
    score_0_100 = sentiment_layer.get("score_0_100", sentiment_score)
    bias = sentiment_layer.get("bias") or "—"
    band = sentiment_layer.get("band") or "—"
    earnings = sentiment_layer.get("earnings_alert") or {}
    weights_doc = sentiment_layer.get("weights") or {
        "news": 0.40,
        "options_flow": 0.35,
        "social": 0.15,
        "put_call": 0.10,
    }
    contribution = round(sentiment_score * weight, 1)
    qual_band = _apex_score_band(sentiment_score)
    layer_narrative = sentiment_layer.get("narrative")

    measured = (
        "Sentiment is a weighted blend of Financial News NLP (40%), options flow on the selected expiry "
        "(35%), social sentiment (15%), and put/call volume ratio (10%). Each component is scored on a "
        "signed scale then mapped to 0–100 for the composite formula. News uses lexicon scoring on live "
        "headlines; flow uses call/put volume, notional skew, and unusual activity flags; P/C > 1.2 reads "
        "as fear, < 0.7 as aggressive bullish positioning."
    )

    score_meaning = (
        f"Sentiment score {sentiment_score}/100 ({qual_band}) on the 0–100 execution scale; "
        f"signed composite {_apex_fmt(signed, 1)}, band '{band}', bias {bias}. "
        "This leg confirms or contradicts the technical direction — strong bullish tape with fearful "
        "sentiment can still justify contrarian structures but reduces composite conviction."
    )

    drivers_para = layer_narrative or (
        f"News: score {_apex_fmt(news.get('score'), 1)} from {news.get('count', 0)} articles "
        f"({news.get('status', '—')}). Flow: {_apex_fmt(flow.get('score'), 1)} "
        f"({flow.get('label', '—')}), call vol {flow.get('call_volume', '—')}, put vol {flow.get('put_volume', '—')}. "
        f"P/C ratio {_apex_fmt(pc.get('ratio'), 2)} → {pc.get('signal', '—')}."
    )
    if earnings.get("active"):
        drivers_para += f" Earnings catalyst flagged: {earnings.get('message', 'active window')}."

    weight_para = (
        f"Weighted contribution: {contribution} points ({int(weight * 100)}% weight). "
        "Sentiment is material but not dominant — it captures positioning and narrative risk that price "
        "may not have fully discounted, especially around flow spikes and headline clusters."
    )

    if sentiment_score >= 65 and "bull" in str(bias).lower():
        action = (
            "Actionable view: sentiment supports long-biased structures aligned with technicals; watch for "
            "crowded bullish flow as a reversal tell if composite is extreme without vol confirmation."
        )
    elif sentiment_score <= 45 or "bear" in str(bias).lower():
        action = (
            "Actionable view: sentiment is cautious or bearish — favor hedges, credit call structures, or "
            "reduced delta unless technicals strongly disagree and vol is cheap."
        )
    else:
        action = (
            "Actionable view: sentiment is neutral — do not let narrative override price; use as a tie-breaker "
            "between equally viable §9.1 structures."
        )

    breakdown = [
        {"label": "0–100 scale", "value": score_0_100, "note": "Composite formula input"},
        {"label": "Signed composite", "value": signed, "note": "−100 to +100 before mapping"},
        {"label": "Bias / band", "value": f"{bias} / {band}", "note": "Human-readable label"},
        {"label": "News NLP", "value": news.get("score"), "note": f"{int(weights_doc.get('news', 0.4) * 100)}% weight · {news.get('count', 0)} articles"},
        {"label": "Options flow", "value": flow.get("score"), "note": f"{int(weights_doc.get('options_flow', 0.35) * 100)}% weight"},
        {"label": "Put/call ratio", "value": pc.get("ratio"), "note": pc.get("signal") or pc.get("rule", "")},
        {"label": "Weighted contribution", "value": contribution, "note": f"{int(weight * 100)}% of composite"},
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "sentiment",
        "title": "Sentiment",
        "score": sentiment_score,
        "weight": weight,
        "weighted_contribution": contribution,
        **section_body,
    }


def _fundamentals_apex_section(
    *,
    fund_score: float,
    weight: float,
    fundamentals_layer: dict[str, Any],
) -> dict[str, Any]:
    revenue = fundamentals_layer.get("revenue") or {}
    eps = fundamentals_layer.get("eps_trend") or {}
    analyst = fundamentals_layer.get("analyst") or {}
    calendar = fundamentals_layer.get("earnings_calendar") or {}
    rotation = fundamentals_layer.get("sector_rotation") or {}
    health = fundamentals_layer.get("company_health") or {}
    name = fundamentals_layer.get("name") or fundamentals_layer.get("symbol") or "Issuer"
    contribution = round(fund_score * weight, 1)
    band = _apex_score_band(fund_score)
    rev_yoy = revenue.get("yoy_pct")
    beats = eps.get("consecutive_beats")
    trend = eps.get("trend")
    target = analyst.get("price_target") or health.get("analyst_target")
    upside = health.get("analyst_upside_pct")
    pe = health.get("pe_ttm")

    measured = (
        f"Fundamentals screen {name} for earnings quality, revenue growth, calendar risk, analyst consensus "
        "versus spot, and sector rotation versus SPY. Scoring emphasizes consecutive EPS beats, revenue YoY "
        "(>15% strong, <5% caution per docs), reasonable P/E band, and constructive analyst upside — not a "
        "full DCF, but a tradeability and tail-risk filter for options holding periods."
    )

    score_meaning = (
        f"Fundamental score {fund_score}/100 ({band}). Revenue YoY {_apex_fmt(rev_yoy, 1)}% "
        f"({revenue.get('signal', '—')}). EPS trend {trend or '—'} with {beats or 0} consecutive beats. "
        "This leg rarely drives the composite alone at 10% weight but flags earnings landmines and "
        "multiple compression risk."
    )

    drivers_para = (
        f"P/E (TTM) {_apex_fmt(pe, 1)}. Analyst target {_apex_fmt(target)} "
        f"({_apex_fmt(upside, 1)}% vs spot). Sector {rotation.get('sector', '—')}: "
        f"{rotation.get('flow', '—')} vs {rotation.get('benchmark', 'SPY')}. "
        f"Next earnings: {calendar.get('next_date', '—')} ({calendar.get('status', '—')})."
    )

    weight_para = (
        f"Weighted contribution: {contribution} points ({int(weight * 100)}% weight). "
        "Fundamentals act as a sanity check — strong tape into deteriorating estimates raises event risk; "
        "stable growth supports holding period for diagonal and married structures."
    )

    if fund_score >= 65 and rev_yoy is not None and float(rev_yoy) > 10:
        action = (
            "Actionable view: fundamentals support holding-period structures; still respect earnings "
            "blackout unless using Gamma Trampoline with explicit catalyst rules."
        )
    elif calendar.get("days_until") is not None and int(calendar.get("days_until", 99)) <= 7:
        action = (
            "Actionable view: earnings proximity elevates gap risk — reduce size, favor defined risk, or "
            "use catalyst-specific structures only."
        )
    else:
        action = (
            "Actionable view: fundamentals are mixed or neutral — size positions assuming binary headline "
            "risk and verify live estimates before entry."
        )

    breakdown = [
        {"label": "Layer score", "value": fundamentals_layer.get("score", fund_score), "note": "Screening score"},
        {"label": "Revenue YoY", "value": rev_yoy, "note": revenue.get("rule", ">15% strong")},
        {"label": "EPS trend", "value": trend, "note": f"{beats or 0} consecutive beats"},
        {"label": "P/E (TTM)", "value": pe, "note": "Valuation context"},
        {"label": "Analyst upside", "value": f"{_apex_fmt(upside, 1)}%", "note": f"Target {_apex_fmt(target)}"},
        {"label": "Sector rotation", "value": rotation.get("flow"), "note": rotation.get("etf", "—")},
        {"label": "Weighted contribution", "value": contribution, "note": f"{int(weight * 100)}% of composite"},
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "fundamentals",
        "title": "Fundamentals",
        "score": fund_score,
        "weight": weight,
        "weighted_contribution": contribution,
        **section_body,
    }


def _risk_apex_section(
    *,
    risk_score: float,
    composite: float,
    chain_analysis: dict[str, Any],
) -> dict[str, Any]:
    summary = chain_analysis.get("summary") or {}
    tier = chain_analysis.get("execution_tier", "—")
    spread_fails = (summary.get("gate_failures") or {}).get("spread", 0)
    vega_blocked = summary.get("vega_cap_blocked") or []
    gamma_flagged = summary.get("gamma_flagged") or []
    hard_rejects = len(summary.get("hard_rejects") or [])
    graded = summary.get("contract_count", 0) or 0
    band = _apex_score_band(risk_score)

    measured = (
        "Risk is advisory (0% composite weight) but gates execution: composite score maps to blocked (≤50), "
        "caution (51–72), or auto-exec (>72). Liquidity penalties subtract from a synthesis score when spread "
        "gates fail. Hard rules: reject legs wider than 10% of mid, vega cap blocks, 7-DTE gamma flags, "
        "position sizing 2–5% of capital, earnings blackout unless Gamma Trampoline is explicitly selected."
    )

    score_meaning = (
        f"Risk synthesis score {risk_score}/100 ({band}). Composite {composite}/100 → tier '{tier}'. "
        "This score summarizes whether the book should automate entry — not whether the trade idea is "
        "interesting on chart alone."
    )

    drivers_para = (
        f"Spread gate failures: {spread_fails} on {graded} graded contracts. "
        f"Hard rejects: {hard_rejects}. Vega cap blocked: {len(vega_blocked)} symbol(s). "
        f"7-DTE gamma flagged: {len(gamma_flagged)}. "
        f"Median spread {_apex_fmt(summary.get('median_spread_pct'), 1)}% of mid."
    )

    weight_para = (
        "Weighted contribution: 0 points (advisory). Risk does not inflate composite — it prevents false "
        "confidence when score is high but legs are untradeable. Always read risk alongside options and "
        "composite threshold status."
    )

    if tier == "auto_exec" and spread_fails == 0:
        action = (
            "Actionable view: execution band permits automated workflow — still confirm live quotes, "
            "accept thesis checkbox on risk review, and size within 2–5% capital at risk."
        )
    elif tier == "caution":
        action = (
            "Actionable view: composite is in the caution band — half size or manual confirmation; "
            "improve composite above 72 or clean spread failures before scaling."
        )
    else:
        action = (
            "Actionable view: blocked band — do not execute automated orders; remediate composite, liquidity, "
            "or structure choice before re-scanning."
        )

    breakdown = [
        {"label": "Composite", "value": composite, "note": f"Threshold ≥ {COMPOSITE_THRESHOLD_FULL_DOC}"},
        {"label": "Execution tier", "value": tier, "note": "blocked / caution / auto_exec"},
        {"label": "Risk synthesis", "value": risk_score, "note": "Liquidity-adjusted"},
        {"label": "Spread failures", "value": spread_fails, "note": "§5 gate"},
        {"label": "Vega cap blocks", "value": len(vega_blocked), "note": "Symbols blocked"},
        {"label": "Gamma 7-DTE flags", "value": len(gamma_flagged), "note": "Short DTE risk"},
    ]

    section_body = _apex_section_payload(
        paragraphs=[measured, score_meaning, drivers_para, weight_para],
        interpretation=action,
        breakdown=breakdown,
    )
    return {
        "id": "risk",
        "title": "Risk",
        "score": risk_score,
        "weight": 0.0,
        "weighted_contribution": 0.0,
        **section_body,
    }


def build_apex_score_layer(
    *,
    composite: float,
    tech_score: float,
    vol_score: float,
    greek_score: float,
    sentiment_score: float,
    fund_score: float,
    risk_score: float,
    technical_narrative: str,
    chain_analysis: dict[str, Any],
    vol_layer: dict[str, Any],
    sentiment_layer: dict[str, Any],
    fundamentals_layer: dict[str, Any],
    direction: str,
    technical_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    weights = {"technicals": 0.30, "volatility": 0.25, "options": 0.20, "sentiment": 0.15, "fundamentals": 0.10}
    sections = [
        _technicals_apex_section(
            tech_score=tech_score,
            weight=weights["technicals"],
            direction=direction,
            technical_narrative=technical_narrative,
            technical_context=technical_context,
        ),
        _options_apex_section(
            greek_score=greek_score,
            weight=weights["options"],
            chain_analysis=chain_analysis,
        ),
        _volatility_apex_section(
            vol_score=vol_score,
            weight=weights["volatility"],
            vol_layer=vol_layer,
        ),
        _sentiment_apex_section(
            sentiment_score=sentiment_score,
            weight=weights["sentiment"],
            sentiment_layer=sentiment_layer,
        ),
        _fundamentals_apex_section(
            fund_score=fund_score,
            weight=weights["fundamentals"],
            fundamentals_layer=fundamentals_layer,
        ),
        _risk_apex_section(
            risk_score=risk_score,
            composite=composite,
            chain_analysis=chain_analysis,
        ),
    ]

    tech_contrib = round(tech_score * weights["technicals"], 1)
    vol_contrib = round(vol_score * weights["volatility"], 1)
    opt_contrib = round(greek_score * weights["options"], 1)
    sent_contrib = round(sentiment_score * weights["sentiment"], 1)
    fund_contrib = round(fund_score * weights["fundamentals"], 1)
    clears = composite >= COMPOSITE_THRESHOLD_FULL_DOC

    synthesis_parts = [
        (
            f"APEX Composite Score {composite}/100 synthesizes five weighted pillars from the captured scan: "
            f"technicals {tech_score} ({tech_contrib} pts), volatility {vol_score} ({vol_contrib} pts), "
            f"options/Greeks {greek_score} ({opt_contrib} pts), sentiment {sentiment_score} ({sent_contrib} pts), "
            f"and fundamentals {fund_score} ({fund_contrib} pts). Risk is advisory and does not add points."
        ),
        (
            f"Full Document §8 execution threshold is ≥ {COMPOSITE_THRESHOLD_FULL_DOC}; Project APEX stretch "
            f"target is 85. Directional bias on this scan is {direction}. "
            f"Composite formula: 30% technical + 25% vol + 20% Greeks quality + 15% sentiment + 10% fundamentals."
        ),
    ]
    if clears:
        synthesis_parts.append(
            "Threshold met — composite clears the execution gate. Proceed to strategy selection (§9.1) "
            "and confirm chain recommended contract, risk tier, and live spreads before order entry."
        )
    else:
        synthesis_parts.append(
            "Below execution threshold — insufficient conviction for automated playbook selection. "
            "Monitor for improved alignment across technicals and vol, or reduced spread failures on the chain."
        )

    synthesis_interpretation = (
        "Hold execution until composite ≥ 72 with clean §5 gates unless operating manual half-size in the "
        "caution band with explicit risk acceptance."
        if not clears
        else "Execution permitted by score — complete risk review checkbox and size 2–5% account risk per structure."
    )

    return {
        "title": "APEX Composite Score",
        "composite_score": composite,
        "threshold_full_doc": COMPOSITE_THRESHOLD_FULL_DOC,
        "threshold_project_apex": 85,
        "weights": weights,
        "clears_threshold": clears,
        "sections": sections,
        "narrative": _apex_join_paragraphs(synthesis_parts),
        "paragraphs": [p.strip() for p in synthesis_parts if p.strip()],
        "interpretation": synthesis_interpretation,
    }


def build_strategy_layer(
    *,
    strategy_name: StrategyName,
    composite: float,
    direction: str,
    vol_signal: str,
    chain_analysis: dict[str, Any],
    vol_layer: dict[str, Any],
    sentiment_layer: dict[str, Any],
    fundamentals_layer: dict[str, Any],
    tech_score: float,
) -> dict[str, Any]:
    tier = _execution_tier(composite)
    empty_metrics = {
        "max_loss": None,
        "max_profit": None,
        "net_debit_credit": None,
        "net_type": None,
        "breakevens": [],
        "legs": [],
        "per_contract_multiplier": 100,
    }
    if tier == "blocked":
        return {
            "title": "Strategy",
            "tradeable": False,
            "execution_tier": tier,
            "selected_strategy": NOT_TRADEABLE_COPY,
            "composite_score": composite,
            "clears_threshold": False,
            "direction": direction,
            "vol_signal": vol_signal,
            "recommended_contract": None,
            "what_is_this": "",
            "why_recommended": (
                f"Composite score {composite}/100 is below the 51 minimum required for an actionable "
                "options structure on this scan."
            ),
            "how_to_execute": (
                "Review prior layers, improve composite above 50, and re-scan before considering execution. "
                "No legs or payoff metrics are shown while the setup is blocked."
            ),
            "metrics": empty_metrics,
            "narrative": (
                f"{NOT_TRADEABLE_COPY}. Composite {composite}/100 is in the blocked band (≤50). "
                "Improve conviction, liquidity, and structure fit before returning to strategy selection."
            ),
        }

    recommended = chain_analysis.get("recommendedContract")
    contracts = chain_analysis.get("contracts") or []
    metrics = compute_strategy_metrics(
        strategy_name,
        spot=chain_analysis.get("spot"),
        contracts=contracts,
        recommended=recommended,
    )
    playbook = PLAYBOOK.get(strategy_name, {"summary": "", "execution": ""})
    why_parts = [
        f"Composite {composite}/100 {'meets' if composite >= COMPOSITE_THRESHOLD_FULL_DOC else 'is below'} the 72 auto-execution gate.",
        f"Technical bias {direction} (score {tech_score}).",
        f"Volatility regime: {vol_signal} (IV rank {vol_layer.get('iv_rank', '—')}).",
    ]
    if sentiment_layer.get("bias"):
        why_parts.append(f"Sentiment {sentiment_layer.get('bias')} on 0–100 scale {sentiment_layer.get('score_0_100', '—')}.")
    if fundamentals_layer.get("score") is not None:
        why_parts.append(f"Fundamentals score {fundamentals_layer.get('score')}.")

    return {
        "title": "Strategy playbook",
        "tradeable": True,
        "execution_tier": tier,
        "selected_strategy": strategy_name,
        "composite_score": composite,
        "clears_threshold": composite >= COMPOSITE_THRESHOLD_FULL_DOC,
        "direction": direction,
        "vol_signal": vol_signal,
        "recommended_contract": recommended,
        "what_is_this": playbook.get("summary", ""),
        "why_recommended": " ".join(why_parts),
        "how_to_execute": playbook.get("execution", ""),
        "metrics": metrics,
        "narrative": (
            f"Recommended: {strategy_name}. {playbook.get('summary', '')} "
            f"{playbook.get('execution', '')}"
        ),
    }
