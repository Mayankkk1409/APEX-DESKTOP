"""Combined options-chain + Greeks analysis (Full Document §5).

Produces everything the combined screen renders: the evaluated chain rows for the table,
chain-wide structure metrics, and the analysis cards. Card prose is assembled from the
live values and the gate results computed in :mod:`app.analysis.options_rules` — when a
datum is absent the card says so instead of asserting a signal the data cannot support.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable, Literal

from app.analysis.layers import COMPOSITE_THRESHOLD_FULL_DOC, EXECUTION_SCORE_BLOCKED_MAX
from app.analysis.options_rules import (
    ChainContext,
    ContractVerdict,
    DEFAULT_THRESHOLDS,
    RuleThresholds,
    build_uoa_reference,
    evaluate_chain,
)
from app.schemas.market import OptionChain, OptionContract
from app.services.strategy_engine import select_strategy

RecommendedContract = dict[str, Any]

#: Human labels for every degradation state. The UI shows these verbatim.
STATUS_LABELS: dict[str, str] = {
    "live": "Live vendor chain",
    "vendor_quotes_model_greeks": "Live vendor quotes · model-computed Greeks",
    "simulated": "SIMULATED CHAIN — not live market data",
    "no_entitlement": "Options data not entitled on this account",
    "no_keys": "Configure Alpaca keys in .env",
    "unsupported_underlying": "Underlying has no listed chain on this vendor",
    "empty": "Vendor returned no contracts for this expiry",
    "unavailable": "Options chain unavailable",
}

TRUSTWORTHY_STATUSES = {"live", "vendor_quotes_model_greeks"}


def _f(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x:,.{digits}f}"


def _i(x: float | int | None) -> str:
    return "—" if x is None else f"{int(x):,}"


def _p(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def _mean(values: Iterable[float]) -> float | None:
    seq = [v for v in values]
    return sum(seq) / len(seq) if seq else None


def _median(values: Iterable[float]) -> float | None:
    seq = sorted(values)
    if not seq:
        return None
    n = len(seq)
    return seq[n // 2] if n % 2 else (seq[n // 2 - 1] + seq[n // 2]) / 2.0


def days_to_expiry(expiry: str, today: date | None = None) -> int | None:
    try:
        exp = date.fromisoformat(expiry)
    except (TypeError, ValueError):
        return None
    return (exp - (today or datetime.now(timezone.utc).date())).days


def strategy_selection_bucket(
    selected_strategy: str,
    direction: str = "neutral",
    vol_signal: str = "fair",
) -> tuple[Literal["buy", "sell"] | None, Literal["call", "put"] | None]:
    """Map the strategy playbook label to the §5 bucket and optional side filter."""
    if "NO TRADE" in selected_strategy:
        return None, None
    if "Iron Condor" in selected_strategy:
        return "sell", None
    if "Bull Call" in selected_strategy:
        return "buy", "call"
    if "Bear Put" in selected_strategy:
        return "buy", "put"
    if "Gamma Trampoline" in selected_strategy:
        return "buy", "put" if direction == "bearish" else "call"
    if "Benchmark Greeks" in selected_strategy:
        return "buy", "put" if direction == "bearish" else "call"
    if "Married Call" in selected_strategy:
        return "buy", "call"
    if "Married Put" in selected_strategy:
        return "buy", "put"
    if "Bull Put" in selected_strategy:
        return "sell", "put"
    if "Bear Call" in selected_strategy:
        return "sell", "call"
    if "Straddle" in selected_strategy:
        return "buy", None
    if "Diagonal" in selected_strategy:
        return "buy", "call" if "bullish" in selected_strategy.lower() else "put"
    if "Calendar" in selected_strategy:
        return "sell", None
    if vol_signal == "sell_premium":
        return "sell", None
    if vol_signal == "buy_premium" and direction == "bearish":
        return "buy", "put"
    if direction == "bearish":
        return "buy", "put"
    if direction == "bullish":
        return "buy", "call"
    return "buy", None


def infer_strategy_label(
    direction: str,
    vol_signal: str,
    *,
    rsi: float | None = None,
    iv: float | None = None,
    hv: float | None = None,
    ivr: float | None = None,
    composite_threshold_met: bool = False,
    composite: float = 72.0,
    tech_score: float | None = None,
    sentiment_score: float | None = None,
    catalyst_active: bool = False,
) -> str:
    """Mirror scan_engine strategy selection so standalone analysis can pick the same contract."""
    if not composite_threshold_met:
        return "NO TRADE — Insufficient Conviction"
    return select_strategy(
        composite=composite if composite_threshold_met else 0,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi,
        iv=iv,
        hv=hv,
        ivr=ivr,
        tech_score=tech_score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
    )


def pick_recommended_contract(
    verdicts: list[ContractVerdict],
    contracts: list[OptionContract],
    ctx: ChainContext,
    *,
    selected_strategy: str,
    direction: str = "neutral",
    vol_signal: str = "fair",
) -> RecommendedContract | None:
    """Pick the single contract the strategy layer would express, ranked by buy/sell score."""
    bucket, side = strategy_selection_bucket(selected_strategy, direction, vol_signal)
    if bucket is None:
        return None

    by_symbol = {c.symbol: c for c in contracts}
    wanted_verdict = "buy_candidate" if bucket == "buy" else "sell_candidate"
    scored: list[tuple[float, ContractVerdict]] = []
    for v in verdicts:
        if v.verdict != wanted_verdict:
            continue
        if side is not None and v.side != side:
            continue
        score = v.buy_score if bucket == "buy" else v.sell_score
        if score is None:
            continue
        scored.append((score, v))

    if not scored:
        fallback_verdicts = ("buy_candidate", "sell_candidate", "tradeable") if bucket == "buy" else ("sell_candidate", "tradeable")
        for v in verdicts:
            if v.verdict not in fallback_verdicts or v.hard_reject:
                continue
            if side is not None and v.side != side:
                continue
            score = v.buy_score if bucket == "buy" else v.sell_score
            if score is None:
                ratio = v.delta_theta_ratio or 0.0
                score = ratio if bucket == "buy" else max(0.0, 10.0 - ratio)
            scored.append((score, v))

    if not scored:
        return None

    _, best = max(scored, key=lambda item: item[0])
    occ = by_symbol.get(best.symbol)
    return {
        "symbol": ctx.symbol,
        "expiry": ctx.expiry,
        "strike": best.strike,
        "side": best.side,
        "contract_id": best.symbol if occ else None,
    }


def apply_recommended_contract(
    payload: dict[str, Any],
    *,
    selected_strategy: str,
    direction: str = "neutral",
    vol_signal: str = "fair",
) -> dict[str, Any]:
    contracts = payload.get("contracts") or []
    if not contracts:
        payload["recommendedContract"] = None
        return payload

    verdicts = [ContractVerdict.model_validate(row["verdict"]) for row in contracts if row.get("verdict")]
    if not verdicts:
        payload["recommendedContract"] = None
        return payload

    ctx = ChainContext(
        symbol=payload["symbol"],
        expiry=payload.get("expiry") or "",
        dte=int(payload.get("dte") or 0),
        spot=payload.get("spot"),
        atm_strike=payload.get("atm_strike"),
        catalyst_environment=bool(payload.get("vega_cap", {}).get("catalyst_environment")),
        catalyst_reason=str(payload.get("vega_cap", {}).get("reason") or ""),
        vega_cap_override=bool(payload.get("vega_cap", {}).get("override_granted")),
        structure_absorbs_gamma=bool(payload.get("vega_cap", {}).get("structure_absorbs_gamma")),
        thresholds=DEFAULT_THRESHOLDS.with_spread_cap(payload.get("thresholds", {}).get("spread_max_pct_of_mid")),
        atm_iv=payload.get("summary", {}).get("atm_iv"),
        hv=payload.get("summary", {}).get("hv"),
        iv_rank=payload.get("summary", {}).get("iv_rank_proxy"),
    )
    option_contracts = [OptionContract.model_validate({k: v for k, v in row.items() if k != "verdict"}) for row in contracts]
    recommended = pick_recommended_contract(
        verdicts,
        option_contracts,
        ctx,
        selected_strategy=selected_strategy,
        direction=direction,
        vol_signal=vol_signal,
    )
    payload["recommendedContract"] = recommended
    if recommended:
        occ = recommended.get("contract_id")
        focus = next((v for v in verdicts if v.symbol == occ), None)
        contract = next((c for c in option_contracts if c.symbol == occ), None)
        if focus and contract:
            payload["cards"] = _refocus_cards_on_contract(payload["cards"], focus, contract, ctx)
            payload["narrative"] = payload["cards"][0]["body"] if payload["cards"] else payload.get("narrative", "")
    return payload


INFEASIBLE_SCENARIO_MSG = (
    "APEX analysis has detected a not feasible or not tradeable scenario."
)


def execution_tier(score: float | None) -> str:
    """Map composite score to chain / risk-review execution bands."""
    if score is None or score <= EXECUTION_SCORE_BLOCKED_MAX:
        return "blocked"
    if score >= COMPOSITE_THRESHOLD_FULL_DOC:
        return "auto_exec"
    return "caution"


def apply_execution_score_tiers(
    payload: dict[str, Any],
    composite_score: float,
    *,
    selected_strategy: str,
    direction: str = "neutral",
    vol_signal: str = "fair",
) -> dict[str, Any]:
    """Apply §8 score bands: block below 50, highlight 50–72, auto-exec above 72."""
    tier = execution_tier(composite_score)
    payload["execution_score"] = composite_score
    payload["execution_tier"] = tier

    if tier == "blocked":
        payload["recommendedContract"] = None
        cards = [c for c in payload.get("cards", []) if c.get("id") != "chain-infeasible"]
        payload["cards"] = [
            {
                "id": "chain-infeasible",
                "title": "Scenario not tradeable",
                "verdict": f"Score {composite_score:.1f}/100",
                "bias": "bearish",
                "body": INFEASIBLE_SCENARIO_MSG,
            },
            *cards,
        ]
        payload["narrative"] = INFEASIBLE_SCENARIO_MSG
        return payload

    strategy = selected_strategy
    if tier == "caution" and "NO TRADE" in selected_strategy:
        strategy = infer_strategy_label(direction, vol_signal, composite_threshold_met=True)

    return apply_recommended_contract(
        payload,
        selected_strategy=strategy,
        direction=direction,
        vol_signal=vol_signal,
    )


def build_chain_analysis(
    chain: OptionChain | None,
    *,
    symbol: str,
    expiry: str | None,
    technical: dict[str, Any] | None = None,
    hv: float | None = None,
    spread_max_pct: float | None = None,
    vega_cap_override: bool = False,
    structure_absorbs_gamma: bool = False,
    today: date | None = None,
    selected_strategy: str | None = None,
    direction: str | None = None,
    vol_signal: str | None = None,
) -> dict[str, Any]:
    """Evaluate a chain and build the combined options + Greeks payload."""
    thresholds = DEFAULT_THRESHOLDS.with_spread_cap(spread_max_pct)
    today = today or datetime.now(timezone.utc).date()

    if chain is None or not chain.contracts:
        return _empty_payload(chain, symbol, expiry, thresholds, today)

    contracts = [c for c in chain.contracts if c.strike > 0]
    if not contracts:
        return _empty_payload(chain, symbol, expiry, thresholds, today)

    spot = chain.spot
    dte = chain.dte if chain.dte is not None else days_to_expiry(chain.expiry, today)
    dte = 0 if dte is None else max(dte, 0)
    atm_strike = _atm_strike(contracts, spot)
    atm_iv = _atm_iv(contracts, atm_strike)
    iv_rank = _iv_rank_proxy(atm_iv, hv)
    catalyst, catalyst_reason = _catalyst_environment(atm_iv, hv, iv_rank, thresholds)
    uoa_reference, uoa_basis = build_uoa_reference(contracts)

    ctx = ChainContext(
        symbol=chain.symbol or symbol.upper(),
        expiry=chain.expiry,
        dte=dte,
        spot=spot,
        atm_strike=atm_strike,
        catalyst_environment=catalyst,
        catalyst_reason=catalyst_reason,
        vega_cap_override=vega_cap_override,
        structure_absorbs_gamma=structure_absorbs_gamma,
        thresholds=thresholds,
        uoa_reference=uoa_reference,
        uoa_basis=uoa_basis,
        atm_iv=atm_iv,
        hv=hv,
        iv_rank=iv_rank,
    )

    verdicts = evaluate_chain(contracts, ctx)
    by_symbol = {v.symbol: v for v in verdicts}
    rows = [_row(c, by_symbol.get(c.symbol)) for c in contracts]
    summary = _summary(contracts, verdicts, ctx, chain)
    provenance = _provenance(chain, contracts)
    cards = _cards(contracts, verdicts, ctx, chain, summary, provenance, technical or {})

    payload = {
        "title": "Options chain & Greeks engine",
        "symbol": ctx.symbol,
        "expiry": chain.expiry,
        "expiry_valid": chain.expiry_valid,
        "dte": dte,
        "spot": spot,
        "spot_source": chain.spot_source,
        "atm_strike": atm_strike,
        "data_source": provenance,
        "thresholds": _thresholds_payload(thresholds),
        "vega_cap": {
            "catalyst_environment": catalyst,
            "reason": catalyst_reason,
            "override_granted": vega_cap_override,
            "structure_absorbs_gamma": structure_absorbs_gamma,
            "blocks_long_premium": catalyst and not (vega_cap_override or structure_absorbs_gamma),
        },
        "contracts": rows,
        "summary": summary,
        "cards": cards,
        "narrative": cards[0]["body"] if cards else "",
        "recommendedContract": None,
    }

    tech = technical or {}
    resolved_direction = direction or str(tech.get("direction") or "neutral")
    resolved_vol = vol_signal or "fair"
    if atm_iv and hv:
        gap = atm_iv - hv
        if gap > thresholds.iv_hv_rich_pts:
            resolved_vol = "sell_premium"
        elif gap < -thresholds.iv_hv_rich_pts:
            resolved_vol = "buy_premium"
    strategy = selected_strategy or infer_strategy_label(
        resolved_direction,
        resolved_vol,
        rsi=tech.get("rsi"),
        iv=atm_iv,
        hv=hv,
        ivr=iv_rank,
        composite_threshold_met=True,
    )
    return apply_recommended_contract(
        payload,
        selected_strategy=strategy,
        direction=resolved_direction,
        vol_signal=resolved_vol,
    )


# ──────────────────────────────────────────────────────────────────────────────
# chain structure
# ──────────────────────────────────────────────────────────────────────────────


def _atm_strike(contracts: list[OptionContract], spot: float | None) -> float | None:
    if spot is None or spot <= 0:
        return None
    return min({c.strike for c in contracts}, key=lambda s: abs(s - spot), default=None)


def _atm_iv(contracts: list[OptionContract], atm_strike: float | None) -> float | None:
    if atm_strike is None:
        return None
    ivs = [c.iv for c in contracts if c.iv is not None and abs(c.strike - atm_strike) < 1e-9]
    return _mean(ivs)


def _iv_rank_proxy(atm_iv: float | None, hv: float | None) -> float | None:
    """IV vs realised vol scaled into a 0-100 band.

    Documented IVR needs a 52-week IV history, which this feed does not provide. This is an
    explicit proxy and every card that uses it says so.
    """
    if atm_iv is None or not hv or hv <= 0:
        return None
    return round(min(100.0, max(0.0, (atm_iv / hv) * 40.0)), 1)


def _catalyst_environment(
    atm_iv: float | None, hv: float | None, iv_rank: float | None, t: RuleThresholds
) -> tuple[bool, str]:
    """§5.3 / §6.1: is this a catalyst environment that arms the Vega cap?"""
    if atm_iv is None:
        return False, "ATM implied volatility is unavailable, so a catalyst environment cannot be established"
    if hv and atm_iv - hv >= t.iv_hv_rich_pts:
        return True, (
            f"ATM IV {atm_iv * 100:.1f}% is {(atm_iv - hv) * 100:.1f} points above realised volatility "
            f"{hv * 100:.1f}% — options are pricing an event the underlying has not yet delivered"
        )
    if iv_rank is not None and iv_rank > t.ivr_catalyst:
        return True, f"IV rank proxy {iv_rank:.0f} is above the {t.ivr_catalyst:.0f} caution line"
    if hv:
        return False, (
            f"ATM IV {atm_iv * 100:.1f}% against realised {hv * 100:.1f}% is inside the "
            f"{t.iv_hv_rich_pts * 100:.0f}-point event band"
        )
    return False, f"ATM IV is {atm_iv * 100:.1f}% but realised volatility is unavailable for comparison"


def _row(contract: OptionContract, verdict: ContractVerdict | None) -> dict[str, Any]:
    row = contract.model_dump()
    row["verdict"] = verdict.model_dump() if verdict else None
    return row


def _summary(
    contracts: list[OptionContract],
    verdicts: list[ContractVerdict],
    ctx: ChainContext,
    chain: OptionChain,
) -> dict[str, Any]:
    calls = [c for c in contracts if c.side == "call"]
    puts = [c for c in contracts if c.side == "put"]
    call_oi = sum(c.open_interest or 0 for c in calls)
    put_oi = sum(c.open_interest or 0 for c in puts)
    call_vol = sum(c.volume or 0 for c in calls)
    put_vol = sum(c.volume or 0 for c in puts)
    spreads = [v.spread_pct_of_mid for v in verdicts if v.spread_pct_of_mid is not None]

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1

    gate_fail: dict[str, int] = {}
    gate_unknown: dict[str, int] = {}
    for v in verdicts:
        for g in v.gates:
            if g.status == "fail":
                gate_fail[g.id] = gate_fail.get(g.id, 0) + 1
            elif g.status == "unknown":
                gate_unknown[g.id] = gate_unknown.get(g.id, 0) + 1

    buys = sorted(
        [v for v in verdicts if v.verdict == "buy_candidate" and v.buy_score is not None],
        key=lambda v: v.buy_score or 0,
        reverse=True,
    )[:5]
    sells = sorted(
        [v for v in verdicts if v.verdict == "sell_candidate" and v.sell_score is not None],
        key=lambda v: v.sell_score or 0,
        reverse=True,
    )[:5]
    ratio_ranked = sorted(
        [v for v in verdicts if v.delta_theta_ratio is not None and not v.hard_reject],
        key=lambda v: v.delta_theta_ratio or 0,
        reverse=True,
    )
    uoa = [v for v in verdicts if "uoa" in v.flags]

    return {
        "contract_count": len(contracts),
        "call_count": len(calls),
        "put_count": len(puts),
        "single_sided": not calls or not puts,
        "strike_count": len({c.strike for c in contracts}),
        "strike_range": [min(c.strike for c in contracts), max(c.strike for c in contracts)],
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "call_volume": call_vol,
        "put_volume": put_vol,
        # A ratio is only claimed when both sides are actually listed. A single-sided chain
        # would otherwise report 0.0 and read as an aggressive directional signal.
        "put_call_oi_ratio": round(put_oi / call_oi, 3) if calls and puts and call_oi else None,
        "put_call_volume_ratio": round(put_vol / call_vol, 3) if calls and puts and call_vol else None,
        "delta_weighted_call_flow": _delta_flow(calls),
        "delta_weighted_put_flow": _delta_flow(puts),
        "atm_iv": ctx.atm_iv,
        "hv": ctx.hv,
        "iv_rank_proxy": ctx.iv_rank,
        "iv_skew_25d": _skew_25_delta(contracts),
        "max_pain": _max_pain(contracts),
        "call_oi_walls": _walls(calls),
        "put_oi_walls": _walls(puts),
        "median_spread_pct": _median(spreads),
        "mean_spread_pct": _mean(spreads),
        "widest_spread_pct": max(spreads) if spreads else None,
        "tightest_spread_pct": min(spreads) if spreads else None,
        "verdict_counts": counts,
        "gate_failures": gate_fail,
        "gate_unknown": gate_unknown,
        "hard_rejects": [v.model_dump() for v in verdicts if v.hard_reject],
        "top_buy_candidates": [v.model_dump() for v in buys],
        "top_sell_candidates": [v.model_dump() for v in sells],
        "best_delta_theta": [v.model_dump() for v in ratio_ranked[:5]],
        "worst_delta_theta": [v.model_dump() for v in ratio_ranked[-5:][::-1]],
        "unusual_activity": [v.model_dump() for v in uoa],
        "vega_cap_blocked": [v.symbol for v in verdicts if "vega_cap_blocked" in v.flags],
        "gamma_flagged": [v.symbol for v in verdicts if "gamma_risk_7dte" in v.flags],
        "greeks_available": sum(1 for c in contracts if c.delta is not None),
        "quotes_two_sided": sum(1 for c in contracts if c.bid is not None and c.ask is not None),
        "feed": chain.feed,
    }


def _delta_flow(side: list[OptionContract]) -> float | None:
    weighted = [(c.volume or 0) * abs(c.delta) for c in side if c.delta is not None]
    return round(sum(weighted), 1) if weighted else None


def _skew_25_delta(contracts: list[OptionContract]) -> float | None:
    """25-delta put IV minus 25-delta call IV. Positive = downside is bid up."""

    def nearest(side: str) -> float | None:
        pool = [c for c in contracts if c.side == side and c.delta is not None and c.iv is not None]
        if not pool:
            return None
        return min(pool, key=lambda c: abs(abs(c.delta) - 0.25)).iv

    put_iv, call_iv = nearest("put"), nearest("call")
    if put_iv is None or call_iv is None:
        return None
    return round(put_iv - call_iv, 4)


def _max_pain(contracts: list[OptionContract]) -> dict[str, Any] | None:
    """Strike where total intrinsic value owed to option holders is smallest."""
    strikes = sorted({c.strike for c in contracts})
    priced = [c for c in contracts if c.open_interest]
    if len(strikes) < 3 or not priced:
        return None
    best: tuple[float, float] | None = None
    for settle in strikes:
        pain = 0.0
        for c in priced:
            oi = c.open_interest or 0
            if c.side == "call":
                pain += max(0.0, settle - c.strike) * oi
            else:
                pain += max(0.0, c.strike - settle) * oi
        if best is None or pain < best[1]:
            best = (settle, pain)
    if best is None:
        return None
    return {"strike": best[0], "intrinsic_owed": round(best[1], 2)}


def _walls(side: list[OptionContract]) -> list[dict[str, Any]]:
    ranked = sorted([c for c in side if c.open_interest], key=lambda c: c.open_interest or 0, reverse=True)[:3]
    return [{"strike": c.strike, "open_interest": c.open_interest, "volume": c.volume} for c in ranked]


def _provenance(chain: OptionChain, contracts: list[OptionContract]) -> dict[str, Any]:
    vendor_greeks = sum(1 for c in contracts if c.greeks_source == "vendor")
    model_greeks = sum(1 for c in contracts if c.greeks_source == "model")
    missing_greeks = sum(1 for c in contracts if c.greeks_source == "unavailable")
    caveats: list[str] = list(chain.notes)
    if model_greeks:
        caveats.append(
            f"{model_greeks} of {len(contracts)} contracts carry locally computed Black-Scholes Greeks, "
            "not vendor-published Greeks. They are marked MODEL in the chain table."
        )
    if missing_greeks:
        caveats.append(f"{missing_greeks} contracts have no Greeks at all and are not graded on Greek rules.")
    if chain.status == "simulated":
        caveats.append(
            "This chain is generated by the internal simulator so the screen stays navigable without an "
            "options entitlement. Do not trade from these numbers."
        )
    if not chain.expiry_valid:
        caveats.append(f"Expiry {chain.expiry} is not a live, non-expired expiration as of server time.")
    return {
        "status": chain.status,
        "label": STATUS_LABELS.get(chain.status, chain.status),
        "is_live": chain.status in TRUSTWORTHY_STATUSES,
        "source": chain.source,
        "feed": chain.feed,
        "greeks_source": chain.greeks_source,
        "as_of": chain.as_of,
        "vendor_greeks": vendor_greeks,
        "model_greeks": model_greeks,
        "missing_greeks": missing_greeks,
        "caveats": caveats,
    }


def _thresholds_payload(t: RuleThresholds) -> dict[str, Any]:
    return {
        "buy_delta_min": t.buy_delta_min,
        "sell_delta_max": t.sell_delta_max,
        "rule1_delta_min": t.rule1_delta_min,
        "rule1_theta_max": t.rule1_theta_max,
        "rule2_delta_max": t.rule2_delta_max,
        "delta_theta_buy_min": t.delta_theta_buy_min,
        "delta_theta_sell_max": t.delta_theta_sell_max,
        "spread_max_pct_of_mid": t.spread_max_pct_of_mid,
        "spread_max_pct_illiquid": t.spread_max_pct_illiquid,
        "min_open_interest": t.min_open_interest,
        "volume_oi_min_ratio": t.volume_oi_min_ratio,
        "uoa_volume_multiple": t.uoa_volume_multiple,
        "gamma_dte_flag": t.gamma_dte_flag,
    }


def _empty_payload(
    chain: OptionChain | None,
    symbol: str,
    expiry: str | None,
    thresholds: RuleThresholds,
    today: date,
) -> dict[str, Any]:
    status = chain.status if chain else "unavailable"
    label = STATUS_LABELS.get(status, status)
    notes = list(chain.notes) if chain else []
    exp = (chain.expiry if chain else expiry) or "—"
    dte = days_to_expiry(exp, today)
    if status == "no_keys":
        body = (
            f"Configure Alpaca keys in .env to load a live {symbol.upper()} options chain. "
            "Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (names only in .env.example — never commit values), "
            "then restart the backend (`uvicorn` / docker compose). "
            "APEX will not invent a Black-Scholes ladder when credentials are missing."
        )
    else:
        body = (
            f"No option contracts are available for {symbol.upper()} {exp}, so every §5 rule below is unevaluated. "
            f"Reported state: {label}. "
            + (" ".join(notes) if notes else "")
            + " No Delta, Theta, Vega, Gamma, spread, open-interest or volume verdict is shown because APEX will not "
            "synthesise chain values it does not have. Pick a different expiry from the dashboard expiry picker, or "
            "select an underlying with a listed options chain, and re-run the scan."
        )
    caveats = list(notes)
    if chain and not chain.expiry_valid:
        caveats.append(f"Expiry {exp} is not a live, non-expired expiration as of server time.")
    return {
        "title": "Options chain & Greeks engine",
        "symbol": symbol.upper(),
        "expiry": chain.expiry if chain else expiry,
        "expiry_valid": chain.expiry_valid if chain else False,
        "dte": dte,
        "spot": chain.spot if chain else None,
        "spot_source": chain.spot_source if chain else None,
        "atm_strike": None,
        "data_source": {
            "status": status,
            "label": label,
            "is_live": False,
            "source": chain.source if chain else "unavailable",
            "feed": chain.feed if chain else "indicative",
            "greeks_source": "unavailable",
            "as_of": chain.as_of if chain else None,
            "vendor_greeks": 0,
            "model_greeks": 0,
            "missing_greeks": 0,
            "caveats": caveats,
        },
        "thresholds": _thresholds_payload(thresholds),
        "vega_cap": {
            "catalyst_environment": False,
            "reason": "no chain to evaluate",
            "override_granted": False,
            "structure_absorbs_gamma": False,
            "blocks_long_premium": False,
        },
        "contracts": [],
        "summary": {
            "contract_count": 0,
            "call_count": 0,
            "put_count": 0,
            "single_sided": True,
            "verdict_counts": {},
            "gate_failures": {},
            "gate_unknown": {},
            "hard_rejects": [],
            "top_buy_candidates": [],
            "top_sell_candidates": [],
            "best_delta_theta": [],
            "worst_delta_theta": [],
            "unusual_activity": [],
            "vega_cap_blocked": [],
            "gamma_flagged": [],
        },
        "cards": [
            {
                "id": "chain-unavailable",
                "title": "Chain unavailable — no analysis claimed",
                "verdict": label,
                "bias": "neutral",
                "body": body,
            }
        ],
        "narrative": body,
        "recommendedContract": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# cards
# ──────────────────────────────────────────────────────────────────────────────


def _refocus_cards_on_contract(
    cards: list[dict[str, str]],
    focus: ContractVerdict,
    contract: OptionContract,
    ctx: ChainContext,
) -> list[dict[str, str]]:
    """Replace chain-wide Greek cards with analysis of the recommended contract."""
    replace_ids = {
        "greeks-delta",
        "greeks-theta",
        "greeks-delta-theta",
        "greeks-vega",
        "greeks-gamma",
        "candidates-buy",
        "candidates-sell",
    }
    focused = _contract_focus_cards(focus, contract, ctx)
    out: list[dict[str, str]] = []
    inserted = False
    for card in cards:
        if card["id"] in replace_ids:
            if not inserted:
                out.extend(focused)
                inserted = True
            continue
        out.append(card)
    return out


def _contract_focus_cards(
    focus: ContractVerdict,
    contract: OptionContract,
    ctx: ChainContext,
) -> list[dict[str, str]]:
    """Carousel cards centred on one evaluated contract rather than the ATM strike."""
    t = ctx.thresholds
    label = f"{focus.strike:g} {focus.side}"
    mid_txt = _f(focus.mid)
    ratio_txt = _f(focus.delta_theta_ratio, 2)
    delta_txt = _f(focus.itm_probability_proxy, 2)
    spread_txt = _p(focus.spread_pct_of_mid)
    bias = {
        "buy_candidate": "bullish",
        "sell_candidate": "bearish",
        "tradeable": "neutral",
        "screened_out": "bearish",
        "rejected": "bearish",
        "insufficient_data": "neutral",
    }.get(focus.verdict, "neutral")

    return [
        _card(
            "greeks-delta",
            f"Delta — {label}",
            f"Delta {delta_txt}",
            bias,
            f"This analysis follows the recommended {ctx.symbol} {ctx.expiry} {label} contract selected by the §5 "
            f"strategy scoring engine (verdict {focus.verdict.replace('_', ' ')})."
            + (
                " ATM cannot be located because the underlying reference price is unavailable."
                if ctx.spot is None
                else ""
            ),
            f"Delta {_f(contract.delta, 4)} implies roughly {(focus.itm_probability_proxy or 0) * 100:.0f}% of the next $1 "
            f"move passes into premium and ~{(focus.itm_probability_proxy or 0) * 100:.0f}% P(ITM). "
            f"Documented buy floor is {t.buy_delta_min:.2f}; short-leg ceiling is {t.sell_delta_max:.2f}.",
            focus.reasoning,
        ),
        _card(
            "greeks-theta",
            f"Theta — {label}",
            f"daily bleed {_p(focus.theta_pct_of_mid)} of mid",
            bias,
            f"Daily Theta {_f(contract.theta, 4)} on a {mid_txt} mid is {_p(focus.theta_pct_of_mid)} of premium per calendar day.",
            (
                f"At that bleed rate the position loses its whole premium in about {1 / focus.theta_pct_of_mid:.0f} days "
                f"if the underlying never moves."
                if focus.theta_pct_of_mid
                else "Theta as a share of premium is unavailable because the mid or Theta is missing."
            ),
            focus.reasoning,
        ),
        _card(
            "greeks-delta-theta",
            f"APEX Delta/Theta — {label}",
            f"ratio {ratio_txt}",
            "bullish" if (focus.delta_theta_ratio or 0) > t.delta_theta_buy_min else "bearish" if (focus.delta_theta_ratio or 99) < t.delta_theta_sell_max else "neutral",
            f"The APEX Delta/Theta ratio for {label} is {ratio_txt}. Exceptional buying value begins above {t.delta_theta_buy_min:g}; "
            f"efficient selling candidates fall below {t.delta_theta_sell_max:g}.",
            focus.reasoning,
        ),
        _card(
            "greeks-vega",
            f"Vega — {label}",
            f"Vega {_f(contract.vega, 4)}",
            "bearish" if "vega_cap_blocked" in focus.flags else bias,
            f"Vega {_f(contract.vega, 4)} per IV point is {_p(focus.vega_pct_of_mid)} of the {mid_txt} mid. "
            f"Catalyst environment: {'yes' if ctx.catalyst_environment else 'no'} — {ctx.catalyst_reason}."
            + (
                " Short legs are unaffected: selling premium here is short Vega, and the same crush the cap is "
                "protecting buyers from is what pays a seller."
                if ctx.catalyst_environment
                else ""
            ),
            focus.reasoning,
        ),
        _card(
            "greeks-gamma",
            f"Gamma — {label}",
            f"shift {_f(focus.gamma_delta_shift_1pct, 4)} / 1%",
            bias,
            f"Gamma {_f(contract.gamma, 4)} reprices Delta by {_f(contract.gamma, 4)} per $1 in the underlying"
            + (
                f" — a 1% move shifts Delta by {focus.gamma_delta_shift_1pct:+.4f}."
                if focus.gamma_delta_shift_1pct is not None
                else "."
            ),
            f"This expiry is {ctx.dte} days out, so the {t.gamma_dte_flag}-day window is "
            + (
                f"OPEN and this contract carries the flag."
                if ctx.dte <= t.gamma_dte_flag
                else "closed — convexity is present but is not yet the dominant risk."
            ),
            focus.reasoning,
        ),
        _card(
            "candidates-buy" if focus.verdict == "buy_candidate" else "candidates-sell",
            f"Recommended contract — {label}",
            focus.verdict.replace("_", " "),
            bias,
            f"Recommended leg: {ctx.symbol} {ctx.expiry} {label} (contract {focus.symbol}). "
            f"Mid {mid_txt}, spread {spread_txt}, breakeven {_f(focus.breakeven)}, "
            f"buy score {_f(focus.buy_score, 1)}/100, sell score {_f(focus.sell_score, 1)}/100.",
            focus.reasoning,
        ),
    ]


def _card(id: str, title: str, verdict: str, bias: str, *parts: str) -> dict[str, str]:
    return {"id": id, "title": title, "verdict": verdict, "bias": bias, "body": " ".join(p for p in parts if p)}


def _elasticity(v: ContractVerdict, spot: float | None) -> float | None:
    """Option elasticity (lambda): percentage the premium moves per 1% of the underlying.

    This, not raw Delta, is what "directional leverage" means — a 0.99-delta LEAP is a stock
    substitute with roughly 1x leverage, while a 0.55-delta near-dated call can be 15x.
    """
    if spot is None or spot <= 0 or v.mid is None or v.mid <= 0 or v.itm_probability_proxy is None:
        return None
    return v.itm_probability_proxy * spot / v.mid


def _describe(v: dict[str, Any] | ContractVerdict) -> str:
    d = v if isinstance(v, dict) else v.model_dump()
    return f"{d['strike']:g} {d['side']}"


def _cards(
    contracts: list[OptionContract],
    verdicts: list[ContractVerdict],
    ctx: ChainContext,
    chain: OptionChain,
    s: dict[str, Any],
    prov: dict[str, Any],
    technical: dict[str, Any],
) -> list[dict[str, str]]:
    t = ctx.thresholds
    sym = ctx.symbol
    spot_txt = _f(ctx.spot)
    out: list[dict[str, str]] = []

    # 1 ─ provenance
    out.append(
        _card(
            "chain-provenance",
            "Data provenance & chain integrity",
            prov["label"],
            "neutral",
            f"This screen evaluates {s['contract_count']} contracts on the {sym} {chain.expiry} expiry "
            f"({ctx.dte} days to expiration), the same expiry selected in the dashboard expiry picker and carried "
            f"into this scan session. Underlying reference {spot_txt}"
            + (f" sourced from {chain.spot_source}." if chain.spot_source else " (source not reported).")
            + f" Chain state is {prov['label']} from {prov['source']} on the {chain.feed} feed"
            + (f", as of {chain.as_of}." if chain.as_of else "."),
            f"Greek provenance is split {prov['vendor_greeks']} vendor-published / {prov['model_greeks']} "
            f"model-computed / {prov['missing_greeks']} unavailable. "
            + (
                "Every Greek below is vendor-published, so Delta, Gamma, Theta and Vega are the market's own numbers."
                if prov["model_greeks"] == 0 and prov["missing_greeks"] == 0
                else "Model-computed Greeks are Black-Scholes values derived from the mid, the strike, time to expiry "
                "and solved implied volatility; they are not vendor marks. "
                + (
                    "Every contract on this chain is model-computed, which is what the header badge states."
                    if prov["vendor_greeks"] == 0
                    else "The model-computed contracts are badged MODEL in the chain table so they can be told apart "
                    "from the vendor-published ones."
                )
            ),
            f"Two-sided quotes exist on {s['quotes_two_sided']} of {s['contract_count']} contracts and "
            f"{s['greeks_available']} carry a Delta. "
            + (
                "Coverage is complete, so no rule below is running on a partial chain."
                if s["quotes_two_sided"] == s["contract_count"] and s["greeks_available"] == s["contract_count"]
                else f"{s['contract_count'] - s['quotes_two_sided']} contracts have an incomplete quote and "
                f"{s['contract_count'] - s['greeks_available']} have no Delta; those are graded "
                "'insufficient data' rather than passed or failed."
            ),
            (" ".join(prov["caveats"]) if prov["caveats"] else "No integrity caveats on this chain."),
            "" if prov["is_live"] else "TREAT EVERY NUMBER BELOW AS NON-EXECUTABLE until a live entitled chain is loaded.",
        )
    )

    # 2 ─ spread quality
    rejects = s["hard_rejects"]
    reject_names = ", ".join(_describe(r) + f" ({_p(r['spread_pct_of_mid'])})" for r in rejects[:8] if r.get("spread_pct_of_mid") is not None)
    out.append(
        _card(
            "chain-spread",
            "Spread quality & execution cost (§5.5 hard reject)",
            f"{len(rejects)} of {s['contract_count']} hard-rejected",
            "bearish" if len(rejects) > s["contract_count"] * 0.4 else "neutral",
            f"§5.5 hard-rejects any option whose bid/ask spread exceeds {_p(t.spread_max_pct_of_mid, 0)} of mid — wide "
            "spreads are a hidden cost that destroys edge before the thesis is even tested. The threshold is "
            f"configurable and the documented ceiling for illiquid names is {_p(t.spread_max_pct_illiquid, 0)}; this run "
            f"used {_p(t.spread_max_pct_of_mid, 0)}.",
            f"Across this expiry the median spread is {_p(s['median_spread_pct'])} of mid and the mean is "
            f"{_p(s['mean_spread_pct'])}, ranging from {_p(s['tightest_spread_pct'])} at the tightest to "
            f"{_p(s['widest_spread_pct'])} at the widest. "
            + (
                f"{len(rejects)} contracts breach the cap and are marked REJECTED in the table"
                + (f": {reject_names}." if reject_names else ".")
                if rejects
                else "No contract on this expiry breaches the cap, so execution friction is not the binding constraint here."
            ),
            (
                f"Practically: crossing a {_p(s['median_spread_pct'])} spread once costs "
                f"{_p((s['median_spread_pct'] or 0) / 2)} of premium, and a round trip that pays the offer on entry and "
                f"hits the bid on exit costs the full {_p(s['median_spread_pct'])}. That is the hurdle the thesis has to "
                "clear before the position makes a cent."
                if s["median_spread_pct"] is not None
                else "No spread percentiles are computable because too few contracts publish both sides of the market."
            ),
            f"Spread failures by gate count: {s['gate_failures'].get('spread', 0)} spread, "
            f"{s['gate_failures'].get('open_interest', 0)} open interest, "
            f"{s['gate_failures'].get('volume_oi', 0)} volume/OI.",
        )
    )

    # 3 ─ liquidity / open interest gate
    oi_fail = s["gate_failures"].get("open_interest", 0)
    out.append(
        _card(
            "chain-liquidity",
            "Liquidity — open interest gate (§5.6)",
            f"{oi_fail} strikes below {t.min_open_interest} OI",
            "bearish" if oi_fail > s["contract_count"] * 0.5 else "neutral",
            f"§5.6 sets a floor of {t.min_open_interest} contracts of open interest per strike. Below that, the exit is a "
            "negotiation rather than a fill and the mark can gap on a single print.",
            f"This expiry carries {_i(s['call_open_interest'])} call OI against {_i(s['put_open_interest'])} put OI "
            f"(put/call OI ratio {_f(s['put_call_oi_ratio'], 3)}) spread across {s['strike_count']} strikes from "
            f"{_f(s['strike_range'][0])} to {_f(s['strike_range'][1])}. "
            f"{oi_fail} of {s['contract_count']} contracts fail the {t.min_open_interest} floor"
            + (
                f" and {s['gate_unknown'].get('open_interest', 0)} do not publish open interest at all."
                if s["gate_unknown"].get("open_interest")
                else "."
            ),
            "Heaviest resting interest sits at "
            + (
                "call strikes "
                + ", ".join(f"{w['strike']:g} ({_i(w['open_interest'])})" for w in s["call_oi_walls"])
                if s["call_oi_walls"]
                else "no rankable call strike"
            )
            + " and "
            + (
                "put strikes "
                + ", ".join(f"{w['strike']:g} ({_i(w['open_interest'])})" for w in s["put_oi_walls"])
                if s["put_oi_walls"]
                else "no rankable put strike"
            )
            + ". Those are the strikes with a real book behind them, which is where spread legs belong.",
            f"With spot at {spot_txt}, the tradeable band on this expiry is therefore narrower than the printed strike "
            "range: strikes that fail the OI floor are shown but should not carry size.",
        )
    )

    # 4 ─ volume & turnover, UOA
    uoa = s["unusual_activity"]
    vol_fail = s["gate_failures"].get("volume_oi", 0)
    out.append(
        _card(
            "chain-volume",
            "Volume, turnover & unusual options activity (§5.6)",
            f"{len(uoa)} UOA flag{'s' if len(uoa) != 1 else ''}",
            "bullish" if (s["put_call_volume_ratio"] or 1) < 0.7 else "bearish" if (s["put_call_volume_ratio"] or 1) > 1.2 else "neutral",
            f"§5.6 requires same-day volume above {_p(t.volume_oi_min_ratio, 0)} of open interest — stale OI with no "
            f"turnover is a book that is not being worked — and flags unusual options activity when volume exceeds "
            f"{t.uoa_volume_multiple:g}x the average.",
            f"Today {_i(s['call_volume'])} calls and {_i(s['put_volume'])} puts traded on this expiry, a put/call volume "
            f"ratio of {_f(s['put_call_volume_ratio'], 3)}. Documented reading: above 1.2 is fear, below 0.7 is "
            "aggressive bullish positioning. "
            + (
                f"At {_f(s['put_call_volume_ratio'], 3)} this expiry reads "
                + (
                    "as fear/hedging demand."
                    if (s["put_call_volume_ratio"] or 1) > 1.2
                    else "as aggressive call-side positioning."
                    if (s["put_call_volume_ratio"] or 1) < 0.7
                    else "as neither extreme — positioning is balanced and carries no directional claim."
                )
                if s["put_call_volume_ratio"] is not None
                else "The ratio is not computable because one side published no volume."
            ),
            f"Delta-weighted flow is {_f(s['delta_weighted_call_flow'], 1)} on calls against "
            f"{_f(s['delta_weighted_put_flow'], 1)} on puts, which weights each contract's volume by its own directional "
            "sensitivity rather than counting a far-OTM lottery ticket the same as an ITM strike.",
            f"{vol_fail} contracts fail the turnover gate. "
            + (
                "UNUSUAL OPTIONS ACTIVITY on "
                + "; ".join(
                    f"{_describe(u)} — {next((g['observed'] for g in u['gates'] if g['id'] == 'uoa'), 'no detail')}"
                    for u in uoa[:6]
                )
                + f". Baseline used: {ctx.uoa_basis}."
                if uoa
                else f"No strike prints {t.uoa_volume_multiple:g}x its baseline, so no UOA claim is made. Baseline used: {ctx.uoa_basis}."
            ),
        )
    )

    # 5 ─ Delta
    buy_bucket = [v for v in verdicts if v.itm_probability_proxy is not None and v.itm_probability_proxy >= t.buy_delta_min]
    sell_bucket = [v for v in verdicts if v.itm_probability_proxy is not None and v.itm_probability_proxy <= t.sell_delta_max]
    out.append(
        _card(
            "greeks-delta",
            "Delta — directional leverage & probability proxy (§5.1)",
            f"{len(buy_bucket)} buy-band / {len(sell_bucket)} short-leg-band",
            "neutral",
            f"§5.1 targets Delta >= {t.buy_delta_min:.2f} when buying (high directional leverage and a higher ITM "
            f"probability) and Delta <= {t.sell_delta_max:.2f} on short legs (high probability of expiring OTM). Delta "
            f"doubles as a probability proxy: a {t.sell_delta_max:.2f}-delta short put carries roughly a "
            f"{t.sell_delta_max * 100:.0f}% chance of finishing ITM.",
            f"On this chain {len(buy_bucket)} contracts sit in the buy band and {len(sell_bucket)} in the short-leg band "
            f"out of {s['greeks_available']} contracts that publish a Delta. "
            + (
                f"ATM is the {_f(ctx.atm_strike)} strike against spot {spot_txt}, so strikes below it on the call side and "
                "above it on the put side are the in-the-money half of the ladder."
                if ctx.atm_strike is not None
                else "ATM cannot be located because the underlying reference price is unavailable."
            ),
            (
                # Ranked by elasticity, not by raw Delta. A 0.99-delta strike has the highest
                # P(ITM) on the board and almost the *least* leverage — it is a stock substitute.
                # Elasticity (|Delta| x spot / premium) is the percentage the option moves for a
                # 1% move in the underlying, which is what "directional leverage" means.
                "Best directional leverage inside the buy band, ranked by elasticity (percentage the premium moves "
                "per 1% of underlying, which is what leverage actually measures — the deepest-ITM strike has the "
                "highest P(ITM) and the least leverage): "
                + "; ".join(
                    f"{_describe(v)} Delta {v.itm_probability_proxy:.2f} (~{(v.itm_probability_proxy or 0) * 100:.0f}% "
                    f"P(ITM)) moves {_elasticity(v, ctx.spot):.1f}x the underlying in percentage terms"
                    for v in sorted(buy_bucket, key=lambda v: _elasticity(v, ctx.spot) or 0.0, reverse=True)[:5]
                    if _elasticity(v, ctx.spot) is not None
                )
                + "."
                if buy_bucket and ctx.spot
                else f"No strike on this expiry reaches the {t.buy_delta_min:.2f} Delta floor, so there is no documented "
                "directional-leverage buy here at all — a long here would be paying for a low-probability outcome."
                if not buy_bucket
                else f"{len(buy_bucket)} strikes clear the Delta floor, but elasticity cannot be ranked without an "
                "underlying reference price."
            ),
            (
                "Lowest-assignment-risk short legs: "
                + "; ".join(
                    f"{_describe(v)} Delta {v.itm_probability_proxy:.2f} (~{(v.itm_probability_proxy or 0) * 100:.0f}% P(ITM))"
                    for v in sorted(sell_bucket, key=lambda v: v.itm_probability_proxy or 0)[:5]
                )
                + "."
                if sell_bucket
                else "No strike sits at or below the short-leg Delta ceiling."
            ),
        )
    )

    # 6 ─ Theta
    theta_pcts = [v.theta_pct_of_mid for v in verdicts if v.theta_pct_of_mid is not None]
    med_theta = _median(theta_pcts)
    out.append(
        _card(
            "greeks-theta",
            "Theta — decay economics (§5.2)",
            f"median daily bleed {_p(med_theta)} of premium",
            "bearish" if (med_theta or 0) > 0.05 else "neutral",
            "§5.2: buyers want low Theta relative to Delta so the option retains value longer per premium dollar; "
            "sellers want high Theta because decay works in their favour every day.",
            (
                f"Median daily decay on this expiry is {_p(med_theta)} of mid, which means a median-priced contract "
                f"loses its entire premium to time in about {1 / med_theta:.0f} calendar days if the underlying never "
                f"moves. At {ctx.dte} DTE that clock is "
                + ("the dominant term in the P&L." if ctx.dte <= 14 else "material but not yet dominant.")
                if med_theta
                else "Daily decay as a share of premium is not computable — Theta or the mid is missing across this expiry."
            ),
            (
                "Fastest bleeders (worst for buyers, best for sellers): "
                + "; ".join(
                    f"{_describe(v)} {_p(v.theta_pct_of_mid)}/day"
                    for v in sorted(
                        [v for v in verdicts if v.theta_pct_of_mid is not None], key=lambda v: v.theta_pct_of_mid or 0, reverse=True
                    )[:5]
                )
                + "."
                if theta_pcts
                else ""
            ),
            (
                "Slowest bleeders (best for buyers): "
                + "; ".join(
                    f"{_describe(v)} {_p(v.theta_pct_of_mid)}/day"
                    for v in sorted([v for v in verdicts if v.theta_pct_of_mid is not None], key=lambda v: v.theta_pct_of_mid or 0)[:5]
                )
                + "."
                if theta_pcts
                else ""
            ),
        )
    )

    # 7 ─ Delta/Theta ratio
    best = s["best_delta_theta"]
    worst = s["worst_delta_theta"]
    exceptional = [v for v in verdicts if (v.delta_theta_ratio or 0) > t.delta_theta_buy_min and not v.hard_reject]
    efficient = [v for v in verdicts if v.delta_theta_ratio is not None and v.delta_theta_ratio < t.delta_theta_sell_max and not v.hard_reject]
    out.append(
        _card(
            "greeks-delta-theta",
            "APEX Delta/Theta ratio ranking (§5.2)",
            f"{len(exceptional)} > {t.delta_theta_buy_min:g} · {len(efficient)} < {t.delta_theta_sell_max:g}",
            "bullish" if exceptional else "bearish" if efficient else "neutral",
            f"The APEX Delta/Theta ratio divides |Delta| by absolute daily Theta. A ratio above "
            f"{t.delta_theta_buy_min:g} is exceptional buying value — each unit of decay buys many units of directional "
            f"exposure. A ratio below {t.delta_theta_sell_max:g} is an efficient selling candidate because decay "
            "dominates the directional payoff.",
            (
                "Top ranked by ratio: "
                + "; ".join(f"{_describe(v)} ratio {v['delta_theta_ratio']:.2f}" for v in best)
                + "."
                if best
                else "No contract on this expiry publishes both a Delta and a non-zero Theta, so the ratio is unavailable "
                "chain-wide and no buying-value claim is made."
            ),
            (
                f"{len(exceptional)} contracts clear the {t.delta_theta_buy_min:g} exceptional-buying line"
                + (
                    ": " + ", ".join(f"{_describe(v)} ({v.delta_theta_ratio:.2f})" for v in sorted(exceptional, key=lambda v: v.delta_theta_ratio or 0, reverse=True)[:5]) + "."
                    if exceptional
                    else ", so nothing on this expiry is priced as exceptional buying value. Buying here pays full retail "
                    "for time."
                )
            ),
            (
                f"{len(efficient)} contracts fall below the {t.delta_theta_sell_max:g} efficient-selling line"
                + (
                    ": " + ", ".join(f"{_describe(v)} ({v.delta_theta_ratio:.2f})" for v in sorted(efficient, key=lambda v: v.delta_theta_ratio or 0)[:5]) + ". Those are the strikes where a premium seller is best paid per unit of directional risk taken."
                    if efficient
                    else ", so there is no standout premium-selling strike on this expiry either."
                )
            ),
            (
                "Weakest ratios: " + "; ".join(f"{_describe(v)} ratio {v['delta_theta_ratio']:.2f}" for v in worst) + "."
                if worst
                else ""
            ),
        )
    )

    # 8 ─ Vega
    vega_pcts = [v.vega_pct_of_mid for v in verdicts if v.vega_pct_of_mid is not None]
    med_vega = _median(vega_pcts)
    blocked = s["vega_cap_blocked"]
    out.append(
        _card(
            "greeks-vega",
            "Vega — IV sensitivity & the Vega cap (§5.3)",
            "cap ARMED" if ctx.catalyst_environment else "cap inactive",
            "bearish" if ctx.catalyst_environment else "neutral",
            "Vega measures sensitivity to a 1-point change in implied volatility. Pre-catalyst, high Vega is dangerous "
            "for buyers because a post-event IV crush can erase premium even when the underlying moves the right way. "
            "§5.3 therefore applies a Vega cap: long Vega positions in catalyst environments require an explicit "
            "override or a Gamma Trampoline structure.",
            f"Catalyst assessment: {ctx.catalyst_reason}. The cap is "
            + ("ARMED" if ctx.catalyst_environment else "not armed")
            + f" on this scan. Override is {'GRANTED' if ctx.vega_cap_override else 'not granted'} and Gamma Trampoline "
            f"structure is {'selected' if ctx.structure_absorbs_gamma else 'not selected'}"
            + (
                f", so long premium is blocked on all {len(blocked)} strikes carrying Vega until one of those two "
                "conditions is satisfied. Short legs are unaffected: selling premium here is short Vega, and the same "
                "crush the cap is protecting buyers from is what pays a seller."
                if blocked
                else ", so no long-premium candidate is blocked by the cap on this run."
            ),
            (
                f"Median Vega exposure is {_p(med_vega)} of premium per IV point, so a 10-point IV crush costs roughly "
                f"{_p(min((med_vega or 0) * 10, 1.0))} of the median contract's value on this expiry independent of "
                "direction."
                if med_vega
                else "Vega as a share of premium is not computable across this expiry."
            ),
            (
                "Most IV-exposed strikes: "
                + "; ".join(
                    f"{_describe(v)} {_p(v.vega_pct_of_mid)} of mid per IV point"
                    for v in sorted([v for v in verdicts if v.vega_pct_of_mid is not None], key=lambda v: v.vega_pct_of_mid or 0, reverse=True)[:5]
                )
                + "."
                if vega_pcts
                else ""
            ),
        )
    )

    # 9 ─ Gamma
    gamma_flagged = s["gamma_flagged"]
    out.append(
        _card(
            "greeks-gamma",
            "Gamma — convexity & the 7-DTE flag (§5.4)",
            f"{ctx.dte} DTE · {len(gamma_flagged)} flagged",
            "bearish" if gamma_flagged else "neutral",
            f"Gamma is the rate of change of Delta per $1 move and it accelerates rapidly near expiration. §5.4 flags "
            f"high-Gamma risk for positions within {t.gamma_dte_flag} days of expiration unless the structure accounts "
            "for it (Gamma Trampoline).",
            f"This expiry is {ctx.dte} days out, so the {t.gamma_dte_flag}-day window is "
            + (
                f"OPEN and {len(gamma_flagged)} contracts carry the flag."
                if ctx.dte <= t.gamma_dte_flag
                else "closed — convexity is present but is not yet the dominant risk."
            )
            + (
                " Gamma Trampoline structure is selected, which is the documented exception, so the flag is satisfied structurally."
                if ctx.structure_absorbs_gamma
                else ""
            ),
            (
                "Highest convexity on the ladder: "
                + "; ".join(
                    f"{_describe(v)} Delta shifts {v.gamma_delta_shift_1pct:+.4f} per 1% move in the underlying"
                    for v in sorted(
                        [v for v in verdicts if v.gamma_delta_shift_1pct is not None],
                        key=lambda v: abs(v.gamma_delta_shift_1pct or 0),
                        reverse=True,
                    )[:5]
                )
                + f". With spot at {spot_txt}, a 1% move is {_f((ctx.spot or 0) * 0.01)}."
                if any(v.gamma_delta_shift_1pct is not None for v in verdicts)
                else "Gamma is unavailable across this expiry, so convexity cannot be quantified."
            ),
            "Practically: short premium inside the Gamma window can lose faster than Theta collects, and long premium "
            "needs the move immediately rather than eventually.",
        )
    )

    # 10 ─ IV / skew
    skew = s["iv_skew_25d"]
    out.append(
        _card(
            "chain-iv",
            "Implied volatility level, skew & rank",
            f"ATM IV {_p(ctx.atm_iv)}",
            "bearish" if skew is not None and skew > 0.02 else "bullish" if skew is not None and skew < -0.02 else "neutral",
            (
                f"ATM implied volatility on the {_f(ctx.atm_strike)} strike is {_p(ctx.atm_iv)}"
                + (
                    f" against realised (historical) volatility of {_p(ctx.hv)} on the captured window — a gap of "
                    f"{_f(((ctx.atm_iv or 0) - (ctx.hv or 0)) * 100)} points."
                    if ctx.atm_iv is not None and ctx.hv
                    else " and realised volatility is unavailable for comparison, so no rich/cheap verdict is claimed."
                )
                if ctx.atm_iv is not None
                else "ATM implied volatility is unavailable on this chain, so no IV verdict is claimed."
            ),
            (
                f"Documented framework: IV below HV by more than 10 points means options are cheap and buying premium is "
                f"favoured; within 5 points is fair value and defined-risk spreads apply; above HV by more than 10 points "
                f"means options are rich and selling premium is favoured. Current gap of "
                f"{_f(((ctx.atm_iv or 0) - (ctx.hv or 0)) * 100)} points therefore reads as "
                + (
                    "RICH — sell premium."
                    if (ctx.atm_iv or 0) - (ctx.hv or 0) > 0.10
                    else "CHEAP — buy premium."
                    if (ctx.atm_iv or 0) - (ctx.hv or 0) < -0.10
                    else "FAIR VALUE — defined-risk spreads and diagonals rather than naked directional premium."
                )
                if ctx.atm_iv is not None and ctx.hv
                else ""
            ),
            (
                f"IV rank proxy is {ctx.iv_rank:.0f} on a 0-100 scale (bands: below 25 cheap, 25-50 moderate, 50-75 rich, "
                f"above 75 elevated caution — investigate the catalyst). This is a proxy scaled from the IV/HV ratio, not "
                "a true 52-week IV rank, because this feed does not publish an IV history."
                if ctx.iv_rank is not None
                else "An IV rank cannot be derived: it requires either a published IV history or a realised-volatility "
                "reference, and neither is available here."
            ),
            (
                f"25-delta skew is {_f(skew * 100)} points ({_p(skew)}) of put IV over call IV, so "
                + (
                    "downside protection is being bid up relative to upside calls — the market is paying for hedges."
                    if skew > 0.02
                    else "call IV is bid over put IV, an unusual configuration that points at upside speculation or a squeeze bid."
                    if skew < -0.02
                    else "the wings are priced symmetrically and the skew carries no directional message."
                )
                if skew is not None
                else "25-delta skew is not computable because one wing lacks either a Delta or an IV."
            ),
        )
    )

    # 11 ─ OI positioning / max pain
    mp = s["max_pain"]
    out.append(
        _card(
            "chain-positioning",
            "Open interest structure & positioning",
            f"max pain {_f(mp['strike']) if mp else '—'}",
            "neutral",
            f"Open interest maps where positions already live, which is where dealer hedging and pinning pressure "
            f"concentrate. This expiry holds {_i(s['call_open_interest'])} call OI and {_i(s['put_open_interest'])} put "
            f"OI, a put/call OI ratio of {_f(s['put_call_oi_ratio'], 3)}.",
            (
                f"Max pain — the settlement strike that minimises total intrinsic value owed to option holders — sits at "
                f"{_f(mp['strike'])}, {_f(abs((ctx.spot or mp['strike']) - mp['strike']))} "
                f"({_p(abs((ctx.spot or mp['strike']) - mp['strike']) / (ctx.spot or 1))}) from spot {spot_txt}. "
                + (
                    "Spot is close enough to max pain that pinning into expiry is a live risk for both sides."
                    if ctx.spot and abs(ctx.spot - mp["strike"]) / ctx.spot < 0.01
                    else "Spot is far enough from max pain that pinning is not the dominant force."
                )
                if mp and ctx.spot
                else "Max pain is not computable on this expiry — it needs open interest across at least three strikes."
            ),
            (
                "Call OI walls at "
                + ", ".join(f"{w['strike']:g} ({_i(w['open_interest'])} open, {_i(w['volume'])} traded)" for w in s["call_oi_walls"])
                + " act as overhead supply where dealers are short calls and sell into strength."
                if s["call_oi_walls"]
                else "No call-side OI wall is rankable."
            ),
            (
                "Put OI walls at "
                + ", ".join(f"{w['strike']:g} ({_i(w['open_interest'])} open, {_i(w['volume'])} traded)" for w in s["put_oi_walls"])
                + " act as demand shelves where dealers are short puts and buy into weakness."
                if s["put_oi_walls"]
                else "No put-side OI wall is rankable."
            ),
            "These strikes are the documented natural anchors for spread legs — they are where a resting order has a book "
            "to fill against.",
        )
    )

    # 12 ─ chain vs technical
    out.append(_technical_confirmation_card(s, ctx, technical))

    # 13 ─ buy candidates
    buys = s["top_buy_candidates"]
    out.append(
        _card(
            "candidates-buy",
            "Ranked buy candidates",
            f"{len(buys)} qualified",
            "bullish" if buys else "neutral",
            f"A buy candidate must clear every liquidity gate (spread inside {_p(t.spread_max_pct_of_mid, 0)} of mid, OI "
            f"at or above {t.min_open_interest}, turnover above {_p(t.volume_oi_min_ratio, 0)} of OI), carry Delta at or "
            f"above {t.buy_delta_min:.2f}, post a Delta/Theta ratio above {t.delta_theta_buy_min:g}, and not be blocked "
            "by the Vega cap.",
            (
                " ".join(
                    f"#{n}: {_describe(v)} — Delta {_f(v['itm_probability_proxy'], 2)}, ratio "
                    f"{_f(v['delta_theta_ratio'], 2)}, spread {_p(v['spread_pct_of_mid'])}, mid {_f(v['mid'])}, "
                    f"breakeven {_f(v['breakeven'])}, score {_f(v['buy_score'], 1)}/100. {v['reasoning']}"
                    for n, v in enumerate(buys, start=1)
                )
                if buys
                else f"Nothing on the {chain.expiry} expiry qualifies. That is a finding, not a gap: with "
                f"{s['gate_failures'].get('spread', 0)} spread rejects, {s['gate_failures'].get('open_interest', 0)} OI "
                f"failures and {len([v for v in verdicts if (v.itm_probability_proxy or 0) >= t.buy_delta_min])} strikes "
                f"in the Delta buy band, the documented conditions for paying premium on this expiry are not present. "
                "APEX does not lower the gates to produce a trade."
            ),
        )
    )

    # 14 ─ sell candidates
    sells = s["top_sell_candidates"]
    out.append(
        _card(
            "candidates-sell",
            "Ranked short-leg candidates",
            f"{len(sells)} qualified",
            "bearish" if sells else "neutral",
            f"A short-leg candidate must clear the same liquidity gates, carry |Delta| at or below "
            f"{t.sell_delta_max:.2f} (roughly a {t.sell_delta_max * 100:.0f}% chance of finishing ITM), and post a "
            f"Delta/Theta ratio below {t.delta_theta_sell_max:g} so decay dominates the directional payoff.",
            (
                " ".join(
                    f"#{n}: {_describe(v)} — Delta {_f(v['itm_probability_proxy'], 2)} (~"
                    f"{(v['itm_probability_proxy'] or 0) * 100:.0f}% P(ITM)), ratio {_f(v['delta_theta_ratio'], 2)}, "
                    f"daily decay {_p(v['theta_pct_of_mid'])} of a {_f(v['mid'])} mid, spread "
                    f"{_p(v['spread_pct_of_mid'])}, score {_f(v['sell_score'], 1)}/100. {v['reasoning']}"
                    for n, v in enumerate(sells, start=1)
                )
                if sells
                else "No strike on this expiry combines a low enough Delta with a low enough Delta/Theta ratio to be an "
                "efficient short leg. Selling here would be collecting premium without the documented probability edge."
            ),
        )
    )

    # 15 ─ execution gate summary
    counts = s["verdict_counts"]
    out.append(
        _card(
            "chain-gates",
            "Execution gate summary — what would change the verdict",
            f"{counts.get('rejected', 0)} rejected · {counts.get('screened_out', 0)} screened · "
            f"{counts.get('buy_candidate', 0)} buy · {counts.get('sell_candidate', 0)} sell",
            "neutral",
            f"Of {s['contract_count']} contracts on this expiry: {counts.get('rejected', 0)} hard-rejected on spread, "
            f"{counts.get('screened_out', 0)} screened out by the OI or turnover gates, "
            f"{counts.get('insufficient_data', 0)} ungradeable for missing data, {counts.get('tradeable', 0)} liquid but "
            f"with no directional fit, {counts.get('buy_candidate', 0)} buy candidates and "
            f"{counts.get('sell_candidate', 0)} short-leg candidates.",
            f"Gate failure tally — spread: {s['gate_failures'].get('spread', 0)}, open interest: "
            f"{s['gate_failures'].get('open_interest', 0)}, volume/OI: {s['gate_failures'].get('volume_oi', 0)}, "
            f"Vega cap: {s['gate_failures'].get('vega_cap', 0)}. Unknown (data missing) — spread: "
            f"{s['gate_unknown'].get('spread', 0)}, open interest: {s['gate_unknown'].get('open_interest', 0)}, "
            f"Delta: {s['gate_unknown'].get('delta', 0)}, Delta/Theta: {s['gate_unknown'].get('delta_theta', 0)}.",
            (
                f"The binding constraint on this expiry is the {max(s['gate_failures'], key=lambda k: s['gate_failures'][k])} "
                f"gate ({max(s['gate_failures'].values())} failures). Relieving it is what would change the verdict: "
                if s["gate_failures"]
                else "No gate is the binding constraint — every documented filter is clearing on this expiry. "
            )
            + (
                f"a wider expiry with more resting interest, or the {_p(t.spread_max_pct_illiquid, 0)} illiquid-name "
                f"spread ceiling instead of {_p(t.spread_max_pct_of_mid, 0)}, would re-admit some of the rejected strikes "
                "— at a knowingly higher execution cost."
            ),
            "Every threshold above is documented in Full Document §5; the spread cap is the only one intended to be "
            "user-configurable.",
        )
    )

    return out


def _technical_confirmation_card(
    s: dict[str, Any], ctx: ChainContext, technical: dict[str, Any]
) -> dict[str, str]:
    """Does the chain agree with the technical screen the trader just left?"""
    direction = str(technical.get("direction") or "unknown")
    last = technical.get("last")
    ema200 = technical.get("ema200")
    st_dir = technical.get("supertrend_direction")
    rsi = technical.get("rsi")
    macd_hist = technical.get("macd_histogram")
    tech_score = technical.get("score")

    call_flow = s.get("delta_weighted_call_flow")
    put_flow = s.get("delta_weighted_put_flow")
    if call_flow is None or put_flow is None:
        chain_bias = "unknown"
    elif call_flow > put_flow * 1.2:
        chain_bias = "bullish"
    elif put_flow > call_flow * 1.2:
        chain_bias = "bearish"
    else:
        chain_bias = "neutral"

    if direction == "unknown" or chain_bias == "unknown":
        agreement = (
            "Agreement cannot be scored: "
            + ("the technical read was not carried into this layer. " if direction == "unknown" else "")
            + ("delta-weighted flow is not computable on this chain. " if chain_bias == "unknown" else "")
        )
        bias = "neutral"
    elif direction == chain_bias:
        agreement = (
            f"CONFIRMATION: the technical screen read {direction} and delta-weighted option flow is also {chain_bias}. "
            "Two independent layers pointing the same way is the documented condition for sizing a directional idea "
            "rather than a probe."
        )
        bias = direction if direction in {"bullish", "bearish"} else "neutral"
    elif chain_bias == "neutral" or direction == "neutral":
        agreement = (
            f"PARTIAL: the technical screen read {direction} while the chain reads {chain_bias}. One layer is "
            "directional and the other is not, so the chain neither confirms nor contradicts — it declines to vote."
        )
        bias = "neutral"
    else:
        agreement = (
            f"CONTRADICTION: the technical screen read {direction} but delta-weighted option flow is {chain_bias}. "
            "Positioning is leaning against the chart. Either the chart is early and flow has not rotated, or the "
            "options market knows something the price series has not yet printed. Size down until they agree."
        )
        bias = "neutral"

    return _card(
        "chain-vs-technical",
        "Chain versus the technical read",
        f"chain {chain_bias} vs technical {direction}",
        bias,
        f"The previous screen locked a technical read on the captured window: direction {direction}"
        + (f", composite technical score {tech_score}" if tech_score is not None else "")
        + (f", last {_f(last)}" if last is not None else "")
        + (f" against EMA200 {_f(ema200)}" if ema200 is not None else "")
        + (f", SuperTrend {st_dir}" if st_dir else "")
        + (f", RSI {_f(rsi)}" if rsi is not None else "")
        + (f", MACD histogram {_f(macd_hist, 4)}" if macd_hist is not None else "")
        + ".",
        f"The chain's own vote is delta-weighted flow of {_f(call_flow, 1)} on calls against {_f(put_flow, 1)} on puts "
        f"and a put/call volume ratio of {_f(s.get('put_call_volume_ratio'), 3)}, which reads {chain_bias}. "
        f"Open interest is positioned {_f(s.get('put_call_oi_ratio'), 3)} put/call, and max pain sits at "
        f"{_f((s.get('max_pain') or {}).get('strike'))}.",
        agreement,
        (
            f"Implied volatility adds context: ATM IV {_p(ctx.atm_iv)} against realised {_p(ctx.hv)} means the chain is "
            + (
                "pricing more movement than the underlying has been delivering, so a directional buyer is paying up for the move."
                if ctx.atm_iv is not None and ctx.hv and ctx.atm_iv > ctx.hv
                else "pricing less movement than the underlying has been delivering, so directional premium is relatively cheap."
                if ctx.atm_iv is not None and ctx.hv
                else "unavailable for that comparison."
            )
            if ctx.atm_iv is not None
            else "Implied volatility is unavailable, so no IV context is added to the agreement read."
        ),
    )
