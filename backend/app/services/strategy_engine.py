"""APEX strategy playbook selection and payoff metrics (Full Document §8–§10)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Literal

from app.analysis.layers import (
    APEX_COMPOSITE_WEIGHTS,
    APEX_STRATEGY_NAME,
    COMPOSITE_THRESHOLD_FULL_DOC,
    DEFAULT_AUTO_EXEC_THRESHOLD,
    EXECUTION_SCORE_BLOCKED_MAX,
)
from app.analysis.gate_config import (
    CREDIT_STRUCTURES,
    IV_MISMATCH_VOL_POINTS,
    LONG_VEGA_RICH_PENALTY,
    NOT_EXECUTABLE,
    PLAIN_LONG_PREMIUM,
    assess_vol_regime,
    direction_margin,
    direction_margin_min,
    earnings_before_expiry,
    entry_composite_min,
    theta_max_pct_per_day,
    exit_composite_min,
    hysteresis_action,
    iv_below_hv,
    mids_are_exact_double,
    rule1_theta_failures,
)
from app.analysis.options_rules import classify_quote_freshness, daily_theta_per_share
from app.services.executability import (
    can_auto_execute,
    eligibility_sentence,
    order_candidates_by_executability,
    quote_age_phrase,
    split_block_notes,
)
from app.services.strategy_recommendation import (
    DEFINED_RISK_PLAYBOOK,
    MarketSnapshot,
    StrategyRecommendation,
    TechnicalAnalysisResultRef,
    earnings_position_note,
    format_iv_rank_with_reason,
    format_vol_percent,
    is_defined_risk_strategy,
    recommend_strategy,
    record_ledger,
    selection_rationale_for,
    strategy_vega_sign,
)
from app.strategies.payoffs import apex_strategy_payoff, calendar_spread_payoff, long_straddle_payoff
from app.strategies.registry import STRATEGY_REGISTRY, get_strategy_spec, resolve_strategy_id
from app.strategies.validator import assert_strategy_handler, validate_strategy_output


def _execution_tier(
    composite: float,
    *,
    auto_exec_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
) -> str:
    if composite <= EXECUTION_SCORE_BLOCKED_MAX:
        return "blocked"
    if composite >= auto_exec_threshold:
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
    APEX_STRATEGY_NAME: {
        "summary": (
            "A double calendar sells the nearer call and put and buys the same strikes in the later expiration. "
            "Gamma Trampoline™ is that structure only when the earnings gates pass."
        ),
        "execution": (
            "Enter all four legs together as one limit at the net mid. "
            "Send the buys with the sells in that combo. A rejected combo does not leave a naked short."
        ),
    },
    "APEX Benchmark Greeks Strategy": {
        "summary": (
            "The APEX Benchmark Greeks Strategy is a rules-based framework that uses an option's Greeks to decide "
            "when to buy options for directional exposure and when to sell options for premium income."
        ),
        "execution": (
            "Rule 1 buys one call or one put when every buy gate passes. "
            "Rule 2 sells a defined-risk credit structure when every sell gate passes."
        ),
    },
    "Married Put": {
        "summary": "Protective put paired with stock — insurance on a bullish core position.",
        "execution": (
            "Own (or plan to own) shares. Buy a put slightly OTM at 30–45 DTE. "
            "Strike near pivot support; roll before expiry if thesis intact."
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


def _contract_at_strike(contracts: list[dict[str, Any]], side: str, strike: float) -> dict[str, Any] | None:
    return next(
        (c for c in contracts if c.get("side") == side and c.get("strike") is not None and abs(float(c["strike"]) - strike) < 0.01),
        None,
    )


def _nearest_strike_contract(contracts: list[dict[str, Any]], side: str, spot: float) -> dict[str, Any] | None:
    pool = [c for c in contracts if c.get("side") == side and c.get("strike")]
    if not pool:
        return None
    return min(pool, key=lambda c: abs(float(c["strike"]) - spot))


def _dte_from_expiry(expiry: str | None, *, today: date | None = None) -> int | None:
    if not expiry:
        return None
    try:
        exp = date.fromisoformat(expiry)
    except (TypeError, ValueError):
        return None
    ref = today or datetime.now(timezone.utc).date()
    return max((exp - ref).days, 0)


def _strategy_requires_back_month(strategy_name: str) -> bool:
    if APEX_STRATEGY_NAME in strategy_name:
        return True
    if "Double Calendar" in strategy_name or "Double Diagonal" in strategy_name:
        return True
    return "Calendar" in strategy_name or "Diagonal" in strategy_name


def compute_strategy_metrics(
    strategy_name: str,
    *,
    spot: float | None,
    contracts: list[dict[str, Any]],
    recommended: dict[str, Any] | None,
    back_month_contracts: list[dict[str, Any]] | None = None,
    front_expiry: str | None = None,
    back_expiry: str | None = None,
    iv: float | None = None,
    ticker: str = "",
    contract_multiplier: int = 100,
    shares_held: int = 0,
    shares_encumbered: int = 0,
    shares_short: int = 0,
    share_avg_cost: float | None = None,
    stock_ask: float | None = None,
    component_contracts: list[dict[str, Any]] | None = None,
    component_ticker: str | None = None,
    hv: float | None = None,
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
    spec_gate = get_strategy_spec(strategy_name)
    if not contracts or (spec_gate is not None and (spec_gate.risk_type == "advisory" or spec_gate.leg_count == 0)):
        return empty

    from app.services.stock_leg import multiplier_from_contracts
    from app.strategies.metrics_builder import from_display_name

    contract_multiplier = multiplier_from_contracts(contracts, explicit=contract_multiplier)
    registry_metrics = from_display_name(
        strategy_name,
        spot=spot or 0,
        contracts=contracts,
        back_month_contracts=back_month_contracts,
        front_expiry=front_expiry,
        back_expiry=back_expiry,
        iv=iv,
        ticker=ticker,
        contract_multiplier=contract_multiplier,
        recommended=recommended,
        shares_held=shares_held,
        shares_encumbered=shares_encumbered,
        shares_short=shares_short,
        share_avg_cost=share_avg_cost,
        stock_ask=stock_ask,
        component_contracts=component_contracts,
        component_ticker=component_ticker,
        hv=hv,
    )
    if registry_metrics is not None and registry_metrics.get("legs") is not None:
        if registry_metrics.get("validation_blocked"):
            return registry_metrics
        if len(registry_metrics.get("legs") or []) > 0 or get_strategy_spec(strategy_name) is None:
            spec = get_strategy_spec(strategy_name)
            if spec and spec.leg_count == 0:
                return empty
            if spec and spec.payoff_function_ref:
                return registry_metrics

    atm = spot or (recommended or {}).get("strike")
    if atm is None:
        return empty

    rec_side = (recommended or {}).get("side")
    rec_strike = (recommended or {}).get("strike")
    resolved_front_expiry = front_expiry or (recommended or {}).get("expiry")

    def leg(action: str, c: dict[str, Any] | None, *, expiry: str | None = None) -> dict[str, Any] | None:
        if not c:
            return None
        m = _mid(c)
        return {
            "action": action,
            "side": c.get("side"),
            "strike": c.get("strike"),
            "expiry": expiry or c.get("expiry") or resolved_front_expiry,
            "mid": m,
            "symbol": c.get("symbol"),
        }

    legs: list[dict[str, Any]] = []
    metrics = dict(empty)

    if "Iron Condor" in strategy_name:
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "short_iron_condor")
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
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "bull_call_spread")
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
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "bear_put_spread")
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

    if "Bull Put" in strategy_name and "credit" in strategy_name.lower():
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "bull_put_spread_credit")
        short_p = _pick_strike(contracts, "put", atm, 0.20)
        long_p = min(
            (c for c in contracts if c.get("side") == "put" and short_p and c.get("strike", 0) < short_p["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        for action, c in [("sell", short_p), ("buy", long_p)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        credits = sum(l["mid"] or 0 for l in legs if l["action"] == "sell")
        debits = sum(l["mid"] or 0 for l in legs if l["action"] == "buy")
        net = credits - debits
        width = (short_p["strike"] - long_p["strike"]) if short_p and long_p else 0
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "credit",
                "max_profit": round(net * contract_multiplier, 2),
                "max_loss": round((width - net) * contract_multiplier, 2) if width else None,
                "breakevens": [round(short_p["strike"] - net, 2)] if short_p else [],
                "legs": legs,
            }
        )
        return metrics

    if "Bear Call" in strategy_name and "credit" in strategy_name.lower():
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "bear_call_spread_credit")
        short_c = _pick_strike(contracts, "call", atm, 0.20)
        long_c = min(
            (c for c in contracts if c.get("side") == "call" and short_c and c.get("strike", 0) > short_c["strike"]),
            key=lambda c: c["strike"],
            default=None,
        )
        for action, c in [("sell", short_c), ("buy", long_c)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        credits = sum(l["mid"] or 0 for l in legs if l["action"] == "sell")
        debits = sum(l["mid"] or 0 for l in legs if l["action"] == "buy")
        net = credits - debits
        width = (long_c["strike"] - short_c["strike"]) if short_c and long_c else 0
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "credit",
                "max_profit": round(net * contract_multiplier, 2),
                "max_loss": round((width - net) * contract_multiplier, 2) if width else None,
                "breakevens": [round(short_c["strike"] + net, 2)] if short_c else [],
                "legs": legs,
            }
        )
        return metrics

    if "Long Straddle" in strategy_name:
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "long_straddle")
        call_c = _nearest_strike_contract(contracts, "call", float(atm))
        put_c = _nearest_strike_contract(contracts, "put", float(atm))
        strike = call_c["strike"] if call_c else (put_c["strike"] if put_c else atm)
        call_c = call_c or _contract_at_strike(contracts, "call", float(strike))
        put_c = put_c or _contract_at_strike(contracts, "put", float(strike))
        for action, c in [("buy", call_c), ("buy", put_c)]:
            lg = leg(action, c)
            if lg:
                legs.append(lg)
        call_mid = _mid(call_c) or 0
        put_mid = _mid(put_c) or 0
        net = call_mid + put_mid
        payoff = long_straddle_payoff(call_premium=call_mid, put_premium=put_mid, strike=float(strike), contract_multiplier=contract_multiplier)
        metrics.update(
            {
                "net_debit_credit": round(net, 2),
                "net_type": "debit",
                "max_loss": payoff["max_loss"],
                "max_profit": payoff["max_profit"],
                "breakevens": payoff["breakevens"],
                "legs": legs,
            }
        )
        return metrics

    if "Calendar" in strategy_name and "Double" not in strategy_name:
        sid = resolve_strategy_id(strategy_name) or "calendar_spread"
        assert_strategy_handler(strategy_name, sid)
        option_side: Literal["call", "put"] = "put" if "put" in strategy_name.lower() else (rec_side or "call")  # type: ignore[assignment]
        strike_val = rec_strike
        if strike_val is None:
            nearest = _nearest_strike_contract(contracts, option_side, float(atm))
            strike_val = nearest.get("strike") if nearest else atm
        strike_f = float(strike_val)
        front_c = _contract_at_strike(contracts, option_side, strike_f) or _nearest_strike_contract(contracts, option_side, strike_f)
        back_pool = back_month_contracts or []
        back_c = _contract_at_strike(back_pool, option_side, strike_f)
        if front_c:
            lg_front = leg("sell", front_c, expiry=resolved_front_expiry)
            if lg_front:
                legs.append(lg_front)
        if back_c and back_expiry:
            lg_back = leg("buy", back_c, expiry=back_expiry)
            if lg_back:
                legs.append(lg_back)
        legs = [lg for lg in legs if lg.get("symbol")]
        if len(legs) != 2:
            metrics.update({"legs": legs, "validation_blocked": True, "validation_error": "Calendar spread requires front-month sell and back-month buy at the same strike"})
            return metrics
        front_mid = legs[0].get("mid") or 0
        back_mid = legs[1].get("mid") or 0
        net_debit = back_mid - front_mid
        front_dte = _dte_from_expiry(resolved_front_expiry) or 30
        back_dte = _dte_from_expiry(back_expiry) or (front_dte + 30)
        vol = iv if iv and iv > 0 else 0.25
        payoff = calendar_spread_payoff(
            spot=float(atm),
            strike=strike_f,
            net_debit=net_debit,
            front_dte_days=front_dte,
            back_dte_days=back_dte,
            iv=vol,
            side=option_side,
            contract_multiplier=contract_multiplier,
        )
        metrics.update(
            {
                "net_debit_credit": round(net_debit, 2),
                "net_type": "debit",
                "max_loss": payoff["max_loss"],
                "max_profit": payoff["max_profit"],
                "breakevens": payoff["breakevens"],
                "legs": legs,
                "max_profit_iv_assumption_dependent": payoff.get("max_profit_iv_assumption_dependent", True),
                "payoff_notes": payoff.get("payoff_notes"),
            }
        )
        return metrics

    if "Diagonal" in strategy_name:
        sid = "diagonal_spread_bullish" if "bullish" in strategy_name.lower() else "diagonal_spread_bearish"
        assert_strategy_handler(strategy_name, sid)
        bullish = "bullish" in strategy_name.lower()
        option_side: Literal["call", "put"] = "call" if bullish else "put"
        back_pool = back_month_contracts or contracts
        long_c = _pick_strike(back_pool, option_side, float(atm), 0.55)
        if not long_c:
            long_c = _nearest_strike_contract(back_pool, option_side, float(atm))
        short_c = None
        if long_c:
            if bullish:
                short_c = min(
                    (c for c in contracts if c.get("side") == "call" and c.get("strike", 0) > long_c["strike"]),
                    key=lambda c: c["strike"],
                    default=None,
                )
            else:
                short_c = max(
                    (c for c in contracts if c.get("side") == "put" and c.get("strike", 0) < long_c["strike"]),
                    key=lambda c: c["strike"],
                    default=None,
                )
        if long_c:
            lg_long = leg("buy", long_c, expiry=back_expiry)
            if lg_long:
                legs.append(lg_long)
        if short_c:
            lg_short = leg("sell", short_c, expiry=resolved_front_expiry)
            if lg_short:
                legs.append(lg_short)
        legs = [lg for lg in legs if lg.get("symbol")]
        if len(legs) != 2:
            metrics.update({"legs": legs, "validation_blocked": True, "validation_error": "Diagonal spread requires long back-month and short front-month legs"})
            return metrics
        debits = sum(l.get("mid") or 0 for l in legs if l["action"] == "buy")
        credits = sum(l.get("mid") or 0 for l in legs if l["action"] == "sell")
        net_debit = debits - credits
        strike_f = float(long_c["strike"]) if long_c else float(atm)
        front_dte = _dte_from_expiry(resolved_front_expiry) or 30
        back_dte = _dte_from_expiry(back_expiry) or (front_dte + 30)
        vol = iv if iv and iv > 0 else 0.25
        payoff = calendar_spread_payoff(
            spot=float(atm),
            strike=strike_f,
            net_debit=net_debit,
            front_dte_days=front_dte,
            back_dte_days=back_dte,
            iv=vol,
            side=option_side,
            contract_multiplier=contract_multiplier,
        )
        metrics.update(
            {
                "net_debit_credit": round(net_debit, 2),
                "net_type": "debit" if net_debit >= 0 else "credit",
                "max_loss": payoff["max_loss"],
                "max_profit": payoff["max_profit"],
                "breakevens": payoff["breakevens"],
                "legs": legs,
                "max_profit_iv_assumption_dependent": True,
                "payoff_notes": payoff.get("payoff_notes"),
            }
        )
        return metrics

    if "Married Put" in strategy_name:
        assert_strategy_handler(strategy_name, resolve_strategy_id(strategy_name) or "married_put")
        prot = _pick_strike(contracts, "put", atm, 0.30)
        lg = leg("buy", prot)
        if lg:
            legs.append(lg)
            prem = lg["mid"] or 0
            metrics.update(
                {
                    "net_debit_credit": round(prem, 2),
                    "net_type": "debit",
                    "max_loss": round(prem * contract_multiplier, 2),
                    "max_profit": None,
                    "breakevens": [round(atm - prem, 2)] if atm else [],
                    "legs": legs,
                }
            )
        return metrics

    if APEX_STRATEGY_NAME in strategy_name or "APEX Strategy" in strategy_name:
        assert_strategy_handler(strategy_name, "apex_strategy")
        front_call = _pick_strike(contracts, "call", float(atm), 0.20)
        front_put = _pick_strike(contracts, "put", float(atm), 0.20)
        back_pool = back_month_contracts or []
        back_call = (
            _contract_at_strike(back_pool, "call", float(front_call["strike"]))
            if front_call and front_call.get("strike") is not None
            else None
        )
        back_put = (
            _contract_at_strike(back_pool, "put", float(front_put["strike"]))
            if front_put and front_put.get("strike") is not None
            else None
        )
        leg_plan: list[tuple[str, dict[str, Any] | None, str | None]] = [
            ("buy", back_call, back_expiry),
            ("buy", back_put, back_expiry),
            ("sell", front_call, resolved_front_expiry),
            ("sell", front_put, resolved_front_expiry),
        ]
        for action, contract, expiry in leg_plan:
            lg = leg(action, contract, expiry=expiry)
            if lg:
                legs.append(lg)
        legs = [lg for lg in legs if lg.get("symbol")]
        if len(legs) != 4:
            metrics.update(
                {
                    "legs": [],
                    "validation_blocked": True,
                    "validation_error": (
                        "APEX Strategy requires all four legs: buy the back-week call, buy the back-week put, "
                        "sell the front-week call, and sell the front-week put."
                    ),
                }
            )
            return metrics
        call_strike = float(front_call["strike"]) if front_call else float(atm)
        put_strike = float(front_put["strike"]) if front_put else float(atm)
        front_prem = sum(l.get("mid") or 0 for l in legs if l["action"] == "sell")
        back_prem = sum(l.get("mid") or 0 for l in legs if l["action"] == "buy")
        net_debit = back_prem - front_prem
        front_dte = _dte_from_expiry(resolved_front_expiry) or 7
        back_dte = _dte_from_expiry(back_expiry) or (front_dte + 14)
        vol = iv if iv and iv > 0 else 0.35
        payoff = apex_strategy_payoff(
            spot=float(atm),
            call_strike=call_strike,
            put_strike=put_strike,
            net_debit=net_debit,
            front_dte_days=front_dte,
            back_dte_days=back_dte,
            iv=vol,
            contract_multiplier=contract_multiplier,
        )
        metrics.update(
            {
                "net_debit_credit": round(net_debit, 2),
                "net_type": "debit" if net_debit >= 0 else "credit",
                "max_loss": payoff["max_loss"],
                "max_profit": payoff["max_profit"],
                "breakevens": payoff["breakevens"],
                "legs": legs,
                "max_profit_iv_assumption_dependent": payoff.get("max_profit_iv_assumption_dependent", True),
                "max_profit_unlimited_allowed": payoff.get("max_profit_unlimited_allowed", True),
                "payoff_notes": payoff.get("payoff_notes"),
                "front_premium_offset_pct": round(front_prem / back_prem, 4) if back_prem > 0 else None,
            }
        )
        return metrics

    # Registered strategies must not silently fall back to single-leg logic.
    spec = get_strategy_spec(strategy_name)
    if spec and spec.tradeable and spec.leg_count > 0:
        metrics.update(
            {
                "validation_blocked": True,
                "validation_error": f"No payoff handler implemented for registered strategy {strategy_name}",
                "legs": legs,
            }
        )
        return metrics

    # Unregistered legacy fallback — only for labels outside the encyclopedia registry.
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


def strategy_decision(
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
    symbol: str = "",
    spot: float | None = None,
    spread_pct: float | None = None,
    data_fresh: bool = True,
    confirmed_pattern_count: int = 0,
    auto_exec_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
    apex_input: Any = None,
    back_month_available: bool = False,
    catalyst_days: int | None = None,
    earnings_date_confirmed: bool | None = None,
    risk_profile: str = "moderate",
    structure_limits: frozenset[str] | None = None,
    rule_context: dict[str, Any] | None = None,
    sentiment_bias: str | None = None,
    executable_by_name: dict[str, bool] | None = None,
    event_span: dict[str, Any] | None = None,
) -> StrategyRecommendation:
    """One Best Match. Risk notes stay beside the structure and do not replace it."""
    from app.services.apex_strategy import ApexStrategyInput

    market = MarketSnapshot(
        symbol=symbol or "—",
        spot=spot,
        direction=direction if direction in {"bullish", "bearish", "neutral"} else "neutral",  # type: ignore[arg-type]
        data_fresh=data_fresh,
        spread_pct=spread_pct,
    )
    technical = TechnicalAnalysisResultRef(
        score=tech_score or composite,
        direction=direction,
        confirmed_pattern_count=confirmed_pattern_count,
    )
    rec = recommend_strategy(
        market=market,
        technical=technical,
        composite=composite,
        vol_signal=vol_signal,
        rsi=rsi,
        iv=iv,
        hv=hv,
        ivr=ivr,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=delta_theta_ratio,
        apex_input=apex_input if isinstance(apex_input, ApexStrategyInput) else None,
        auto_exec_threshold=auto_exec_threshold,
        back_month_available=back_month_available,
        catalyst_days=catalyst_days,
        earnings_date_confirmed=earnings_date_confirmed,
        risk_profile=risk_profile,
        structure_limits=structure_limits,
        rule_context=rule_context,
        sentiment_bias=sentiment_bias,
        event_span=event_span,
    )
    return _prefer_executable_match(rec, executable_by_name)


def _prefer_executable_match(
    rec: StrategyRecommendation,
    executable_by_name: dict[str, bool] | None,
) -> StrategyRecommendation:
    """A failing candidate does not stay ahead of an executable one with a close score.

    With no per-name flags the recommendation is unchanged. When every name fails,
    the best-ranked real strategy stays in place.
    """
    if not executable_by_name:
        return rec
    ordered = order_candidates_by_executability(rec.candidates, executable_by_name)
    rec.candidates = ordered
    viable = [c for c in ordered if c.defined_risk and c.eligible and executable_by_name.get(c.name, False)]
    if not viable:
        return rec
    winner = viable[0]
    if winner.name == rec.best_match:
        return rec
    current = next((c for c in ordered if c.name == rec.best_match), None)
    if current is not None and executable_by_name.get(current.name, False):
        return rec
    rec.best_match = winner.name
    rec.leg_structure = winner.name
    return rec


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
    symbol: str = "",
    spot: float | None = None,
    spread_pct: float | None = None,
    data_fresh: bool = True,
    confirmed_pattern_count: int = 0,
    auto_exec_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
    apex_input: Any = None,
    back_month_available: bool = False,
    catalyst_days: int | None = None,
    earnings_date_confirmed: bool | None = None,
    risk_profile: str = "moderate",
    structure_limits: frozenset[str] | None = None,
    rule_context: dict[str, Any] | None = None,
    sentiment_bias: str | None = None,
) -> StrategyName:
    """Eligibility matrix from Full Document §9.1 — deterministic rule-based selection."""
    return strategy_decision(
        composite=composite,
        direction=direction,
        vol_signal=vol_signal,
        rsi=rsi,
        iv=iv,
        hv=hv,
        ivr=ivr,
        tech_score=tech_score,
        sentiment_score=sentiment_score,
        catalyst_active=catalyst_active,
        delta_theta_ratio=delta_theta_ratio,
        symbol=symbol,
        spot=spot,
        spread_pct=spread_pct,
        data_fresh=data_fresh,
        confirmed_pattern_count=confirmed_pattern_count,
        auto_exec_threshold=auto_exec_threshold,
        apex_input=apex_input,
        back_month_available=back_month_available,
        catalyst_days=catalyst_days,
        earnings_date_confirmed=earnings_date_confirmed,
        risk_profile=risk_profile,
        structure_limits=structure_limits,
        rule_context=rule_context,
        sentiment_bias=sentiment_bias,
    ).best_match


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
    regime_view = assess_vol_regime(iv=iv, hv=hv, iv_rank=iv_rank, vol_signal=str(signal))
    signal_label = regime_view.display
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
    iv_pct = format_vol_percent(iv)
    hv_pct = format_vol_percent(hv)
    if iv_pct and hv_pct:
        measured += f" ATM / contract IV {iv_pct} vs 30D HV {hv_pct}."

    score_meaning = (
        f"Volatility component score {vol_score}/100 ({band}) with signal '{signal_label}'. "
        f"IV Rank {format_iv_rank_with_reason(iv_rank, vol_layer.get('iv_rank_gap') if isinstance(vol_layer.get('iv_rank_gap'), str) else None)} / percentile {_apex_fmt(iv_pct, 1)}. "
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
        "technicals). Volatility regime often determines whether the playbook prefers iron condors or debit spreads. "
        "IV versus HV is a scoring input and a risk note. It does not replace the recommended structure."
    )

    if regime_view.short == "buy premium":
        action = (
            "Actionable view: IV is relatively cheap — favor long premium, debit spreads, and structures "
            "that benefit from vol expansion; avoid naked short vol unless hedged."
        )
    elif regime_view.short == "sell premium":
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
        {
            "label": "IV Rank",
            "value": format_iv_rank_with_reason(
                iv_rank,
                vol_layer.get("iv_rank_gap") if isinstance(vol_layer.get("iv_rank_gap"), str) else None,
            ),
            "note": "0–100 vs IV history, or the reason the rank is missing",
        },
        {"label": "IV Percentile", "value": vol_layer.get("iv_percentile"), "note": "Historical percentile"},
        {"label": "Signal", "value": signal_label, "note": "IV much below HV / fair / IV much above HV"},
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
    sentiment_score: float | None,
    weight: float,
    sentiment_layer: dict[str, Any],
) -> dict[str, Any]:
    components = sentiment_layer.get("components") or {}
    news = components.get("news") or {}
    if sentiment_score is None:
        reason = news.get("error") or "Live news and options flow did not produce a score."
        section_body = _apex_section_payload(
            paragraphs=[
                "Sentiment is omitted from this composite. No neutral score is substituted when the live feed is empty.",
                str(reason),
            ],
            interpretation=(
                "Actionable view: ignore sentiment until a live score exists. Do not treat a missing read as neutral."
            ),
            breakdown=[
                {"label": "0–100 scale", "value": None, "note": "Unavailable"},
                {"label": "News source", "value": news.get("source"), "note": news.get("as_of") or news.get("status")},
            ],
        )
        return {
            "id": "sentiment",
            "title": "Sentiment",
            "score": None,
            "weight": 0.0,
            "weighted_contribution": 0.0,
            **section_body,
        }
    assert sentiment_score is not None
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
            "blackout unless using APEX Strategy with explicit catalyst rules."
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
        "position sizing 2–5% of capital, earnings blackout unless APEX Strategy is explicitly selected."
    )

    score_meaning = (
        f"Risk synthesis score {risk_score}/100 ({band}). Composite {float(composite):.1f}/100 → tier '{tier}'. "
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
    sentiment_score: float | None,
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
    weights = dict(APEX_COMPOSITE_WEIGHTS)
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

    applied = ((technical_context or {}).get("composite_breakdown") or {}).get("weights") or weights
    tech_contrib = round(tech_score * applied["technicals"], 1)
    opt_contrib = round(greek_score * applied["options"], 1)
    vol_contrib = round(vol_score * applied["volatility"], 1)
    sent_contrib = 0.0 if sentiment_score is None else round(sentiment_score * applied["sentiment"], 1)
    fund_contrib = round(fund_score * applied["fundamentals"], 1)
    sent_label = "unavailable (omitted)" if sentiment_score is None else f"{sentiment_score} ({sent_contrib} pts)"
    clears = composite >= COMPOSITE_THRESHOLD_FULL_DOC

    synthesis_parts = [
        (
            f"APEX Composite Score {float(composite):.1f}/100 synthesizes weighted pillars: "
            f"technicals {tech_score} ({tech_contrib} pts), volatility {vol_score} ({vol_contrib} pts), "
            f"Greeks quality {greek_score} ({opt_contrib} pts), sentiment {sent_label}, "
            f"fundamentals {fund_score} ({fund_contrib} pts). Risk is advisory and weighted 0."
        ),
        (
            f"Full Document §8 execution threshold is ≥ {COMPOSITE_THRESHOLD_FULL_DOC}; auto-exec default "
            f"threshold is {DEFAULT_AUTO_EXEC_THRESHOLD}. Directional bias on this scan is {direction}. "
            f"Composite formula: 30% technicals + 25% volatility + 20% Greeks quality + 15% sentiment "
            f"+ 10% fundamentals."
        ),
    ]
    if clears:
        synthesis_parts.append(
            "Composite is recorded. The saved auto-execution minimum decides acknowledgement versus "
            "manual placement. Confirm the recommended structure and live spreads before order entry."
        )
    else:
        synthesis_parts.append(
            "Composite is recorded for review. The recommended structure on the strategy slide stays visible; "
            "the saved auto-execution minimum decides acknowledgement versus manual placement."
        )

    synthesis_interpretation = (
        "The saved auto-execution minimum decides acknowledgement versus manual placement. "
        "The recommended structure stays visible either way."
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


def _anchor_from_metrics_legs(
    metrics: dict[str, Any],
    recommended: dict[str, Any] | None,
    symbol: str,
) -> dict[str, Any] | None:
    """Single source of truth: primary option leg from metrics drives anchor display."""
    option_legs = [leg for leg in (metrics.get("legs") or []) if leg.get("side") in {"call", "put"}]
    if not option_legs:
        return recommended
    primary = option_legs[0]
    base = dict(recommended or {})
    return {
        **base,
        "symbol": symbol,
        "strike": primary.get("strike"),
        "side": primary.get("side"),
        "expiry": primary.get("expiry"),
        "contract_id": primary.get("symbol"),
    }


def _scan_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _same_expiry(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_exp = left.get("expiry")
    right_exp = right.get("expiry")
    if not left_exp or not right_exp:
        return True
    return str(left_exp) == str(right_exp)


def _strike(leg: dict[str, Any]) -> float | None:
    raw = leg.get("strike")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _structure_label(strategy_name: str, metrics: dict[str, Any]) -> str:
    """Shares already held make a long put a protective put. The registry name stays Married Put."""
    if strategy_name != "Married Put":
        return strategy_name
    covered = bool(metrics.get("equity_covered_by_holdings"))
    for leg in metrics.get("legs") or []:
        if isinstance(leg, dict) and leg.get("side") == "stock" and (leg.get("already_held") or covered):
            return "Protective Put"
    return strategy_name


def structure_name_from_legs(legs: list[dict[str, Any]] | None) -> str | None:
    """Map built option legs to an existing registry display name."""
    rows = [leg for leg in (legs or []) if isinstance(leg, dict)]
    stock = [leg for leg in rows if leg.get("side") == "stock"]
    opts = [leg for leg in rows if leg.get("side") in {"call", "put"}]
    if len(stock) == 1 and len(opts) == 1:
        opt = opts[0]
        if opt.get("action") == "buy" and opt.get("side") == "put":
            return "Married Put"
    if len(opts) == 1:
        opt = opts[0]
        action = str(opt.get("action") or "").lower()
        side = opt.get("side")
        if action == "buy" and side == "call":
            return "Long Call"
        if action == "buy" and side == "put":
            return "Long Put"
        if action == "sell" and side == "call":
            return "Naked Call"
        if action == "sell" and side == "put":
            return "Naked Put"
        return None
    if len(opts) == 2 and _same_expiry(opts[0], opts[1]):
        return _two_leg_name(opts[0], opts[1])
    if len(opts) == 4 and len({str(leg.get("expiry") or "") for leg in opts}) <= 1:
        return _iron_condor_name(opts)
    return None


def _two_leg_name(left: dict[str, Any], right: dict[str, Any]) -> str | None:
    if left.get("side") != right.get("side"):
        left_strike = _strike(left)
        right_strike = _strike(right)
        if (
            left.get("action") == right.get("action") == "buy"
            and left_strike is not None
            and right_strike is not None
            and abs(left_strike - right_strike) < 0.01
        ):
            return "Long Straddle"
        return None
    sell = left if left.get("action") == "sell" else right if right.get("action") == "sell" else None
    buy = left if left.get("action") == "buy" else right if right.get("action") == "buy" else None
    if sell is None or buy is None:
        return None
    sell_strike = _strike(sell)
    buy_strike = _strike(buy)
    if sell_strike is None or buy_strike is None or abs(sell_strike - buy_strike) < 0.01:
        return None
    side = left.get("side")
    if side == "put" and sell_strike > buy_strike:
        return "Bull Put Spread (credit)"
    if side == "put" and sell_strike < buy_strike:
        return "Bear Put Spread"
    if side == "call" and buy_strike < sell_strike:
        return "Bull Call Spread"
    if side == "call" and sell_strike < buy_strike:
        return "Bear Call Spread (credit)"
    return None


def _iron_condor_name(opts: list[dict[str, Any]]) -> str | None:
    puts = [leg for leg in opts if leg.get("side") == "put"]
    calls = [leg for leg in opts if leg.get("side") == "call"]
    if len(puts) != 2 or len(calls) != 2:
        return None
    put_name = _two_leg_name(puts[0], puts[1])
    call_name = _two_leg_name(calls[0], calls[1])
    if put_name == "Bull Put Spread (credit)" and call_name == "Bear Call Spread (credit)":
        return "Short Iron Condor"
    return None


def factual_structure_copy(legs: list[dict[str, Any]] | None) -> str:
    """Short description from the legs: action, strike, side, and expiry."""
    rows = [leg for leg in (legs or []) if isinstance(leg, dict)]
    stock = [leg for leg in rows if leg.get("side") == "stock"]
    opts = [leg for leg in rows if leg.get("side") in {"call", "put"}]
    if not stock and not opts:
        return "Option legs were not resolved for this scan."
    bits: list[str] = []
    for leg in stock:
        action = str(leg.get("action") or "trade").capitalize()
        shares = leg.get("quantity") or 100
        held = " already held" if leg.get("already_held") else ""
        bits.append(f"{action} {shares:g} shares{held}")
    for leg in opts:
        action = str(leg.get("action") or "trade").capitalize()
        strike = _strike(leg)
        side = leg.get("side")
        qty = leg.get("quantity") or 1
        under = leg.get("underlying")
        under_txt = f" on {under}" if under else ""
        noun = f"the {side}" if strike is None else f"the {float(strike):g} {side}"
        if qty != 1:
            bits.append(f"{action} {qty:g} of {noun}{under_txt}")
        else:
            bits.append(f"{action} {noun}{under_txt}")
    if len(bits) == 1:
        sentence = bits[0]
    elif len(bits) == 2:
        sentence = f"{bits[0]} and {bits[1]}"
    else:
        sentence = ", ".join(bits[:-1]) + f", and {bits[-1]}"
    expiries: list[str] = []
    for leg in opts:
        exp = leg.get("expiry")
        if exp and str(exp) not in expiries:
            expiries.append(str(exp))
    if len(expiries) == 1:
        sentence += f", expiring {expiries[0]}"
    elif len(expiries) > 1:
        sentence += f", expiring {expiries[0]} and {expiries[1]}"
    return sentence + "."


_REMAINING_LONG_LEG = (
    "Payoff depends on the remaining long leg. No closed-form max profit is shown."
)


def classify_legs(legs: list[dict[str, Any]] | None) -> str | None:
    """Leg geometry the card must describe. Independent of the strategy title."""
    rows = [leg for leg in (legs or []) if isinstance(leg, dict)]
    stock = [leg for leg in rows if leg.get("side") == "stock"]
    opts = [leg for leg in rows if leg.get("side") in {"call", "put"}]
    if stock and opts:
        return "equity_overlay"
    if not opts:
        return None
    expiries = {str(leg.get("expiry")) for leg in opts if leg.get("expiry")}
    if len(expiries) > 1:
        sides = {leg.get("side") for leg in opts}
        if len(opts) == 2 and len(sides) == 1:
            strikes = {_strike(leg) for leg in opts}
            strikes.discard(None)
            if len(strikes) == 1:
                return "calendar"
            return "diagonal"
        return "multi_expiry"
    quantities: list[float] = []
    for leg in opts:
        raw = leg.get("quantity") if leg.get("quantity") is not None else 1
        try:
            quantities.append(float(raw))
        except (TypeError, ValueError):
            quantities.append(1.0)
    if any(qty != 1 for qty in quantities):
        return "ratio"
    if len(opts) == 1:
        action = str(opts[0].get("action") or "").lower()
        side = opts[0].get("side")
        if action == "buy" and side == "call":
            return "long_call"
        if action == "buy" and side == "put":
            return "long_put"
        if action == "sell" and side == "call":
            return "short_call"
        if action == "sell" and side == "put":
            return "short_put"
        return None
    if len(opts) == 2:
        named = _two_leg_name(opts[0], opts[1])
        return {
            "Bull Put Spread (credit)": "bull_put_credit",
            "Bear Put Spread": "bear_put_debit",
            "Bull Call Spread": "bull_call_debit",
            "Bear Call Spread (credit)": "bear_call_credit",
            "Long Straddle": "long_straddle",
        }.get(named or "")
    if len(opts) == 3:
        return "butterfly"
    if len(opts) == 4:
        named = _iron_condor_name(opts)
        if named == "Short Iron Condor":
            short_put = _strike(next(leg for leg in opts if leg.get("side") == "put" and leg.get("action") == "sell"))
            short_call = _strike(next(leg for leg in opts if leg.get("side") == "call" and leg.get("action") == "sell"))
            # Shared short strike is an iron butterfly, not a condor with a body.
            if short_put is not None and short_call is not None and abs(short_put - short_call) < 0.01:
                return "butterfly"
            return "short_iron_condor"
        puts = [leg for leg in opts if leg.get("side") == "put"]
        calls = [leg for leg in opts if leg.get("side") == "call"]
        if len(puts) == 2 and len(calls) == 2:
            put_name = _two_leg_name(puts[0], puts[1])
            call_name = _two_leg_name(calls[0], calls[1])
            if put_name == "Bear Put Spread" and call_name == "Bull Call Spread":
                return "long_iron_condor"
        return "four_leg"
    return None


def _copy_conflicts(text: str, family: str | None) -> bool:
    """True when playbook prose describes a different structure than the legs."""
    lowered = text.lower()
    if "no " + "trade" in lowered or "stand " + "aside" in lowered:
        return True
    if not family:
        return False
    describes_long_call = any(
        phrase in lowered
        for phrase in (
            "long call",
            "buy a call",
            "buy the recommended contract",
            "debit spread that profits from a moderate rise",
        )
    )
    if family == "bull_put_credit" and (describes_long_call or ("call" in lowered and "put" not in lowered)):
        return True
    if family == "bear_put_debit" and describes_long_call:
        return True
    if family == "long_put" and describes_long_call:
        return True
    if family == "bear_call_credit" and "bull put" in lowered:
        return True
    if family == "long_call" and ("bull put" in lowered or "credit spread expressing mild bullish" in lowered):
        return True
    return False


def _grounded_copy(family: str | None, legs: list[dict[str, Any]] | None) -> tuple[str, str] | None:
    """Definition, use, and management written from the legs."""
    if not family:
        return None
    factual = factual_structure_copy(legs)
    if family == "bull_put_credit":
        return (
            "A bull put credit spread sells a higher-strike put and buys a lower-strike put in the same expiration. "
            "It is used for a mild bullish outlook. Maximum profit is the credit times the contract multiplier. "
            "Maximum loss is the strike width minus the credit, times the multiplier. "
            "The breakeven is the short strike minus the credit.",
            f"{factual} The short put is the higher strike and the long put is the lower strike. "
            "Close or roll if the underlying trades through the short strike before expiration.",
        )
    if family == "bull_call_debit":
        return (
            "A bull call debit spread buys a lower-strike call and sells a higher-strike call in the same expiration. "
            "It is used for a moderate rise with capped risk. Maximum loss is the debit times the contract multiplier. "
            "Maximum profit is the strike width minus the debit, times the multiplier. "
            "The breakeven is the long strike plus the debit.",
            f"{factual} Close the spread if the directional thesis fails before expiration.",
        )
    if family == "bear_put_debit":
        return (
            "A bear put debit spread buys a higher-strike put and sells a lower-strike put in the same expiration. "
            "It is used for a moderate decline with capped risk. Maximum loss is the debit times the contract multiplier. "
            "Maximum profit is the strike width minus the debit, times the multiplier. "
            "The breakeven is the long strike minus the debit.",
            f"{factual} Close the spread if the directional thesis fails before expiration.",
        )
    if family == "bear_call_credit":
        return (
            "A bear call credit spread sells a lower-strike call and buys a higher-strike call in the same expiration. "
            "It is used for a mild bearish outlook. Maximum profit is the credit times the contract multiplier. "
            "Maximum loss is the strike width minus the credit, times the multiplier. "
            "The breakeven is the short strike plus the credit.",
            f"{factual} The short call is the lower strike and the long call is the higher strike. "
            "Close or roll if the underlying trades through the short strike before expiration.",
        )
    if family == "long_call":
        return (
            "A long call is the right to buy the underlying at the strike. "
            "It is used when the outlook is bullish. Maximum loss is the premium times the contract multiplier. "
            "Maximum profit is unlimited above the breakeven. The breakeven is the strike plus the premium.",
            f"{factual} Exit if the directional thesis fails, or before expiration once the premium no longer matches the thesis.",
        )
    if family == "long_put":
        return (
            "A long put is the right to sell the underlying at the strike. "
            "It is used when the outlook is bearish. Maximum loss is the premium times the contract multiplier. "
            "Maximum profit is the strike minus the premium, times the multiplier, because the underlying cannot trade below zero. "
            "The breakeven is the strike minus the premium.",
            f"{factual} Exit if the directional thesis fails, or before expiration once the premium no longer matches the thesis.",
        )
    if family == "short_call":
        return (
            "A naked short call sells a call with no hedge. Profit is limited to the premium received. "
            "Loss is unlimited if the underlying rises. The card shows Unlimited for max loss.",
            f"{factual} This structure is undefined risk and is not an auto-execution candidate.",
        )
    if family == "short_put":
        return (
            "A naked short put sells a put with no hedge. Profit is limited to the premium received. "
            "Loss is shown as Unlimited. The card does not substitute a finite stand-in for that loss.",
            f"{factual} This structure is undefined risk and is not an auto-execution candidate.",
        )
    if family == "short_iron_condor":
        return (
            "A short iron condor sells an out-of-the-money put spread and an out-of-the-money call spread for a net credit. "
            "It is used when the outlook is range-bound. Maximum profit is the credit times the contract multiplier. "
            "Maximum loss is the wider wing minus the credit, times the multiplier.",
            f"{factual} Close or roll if the underlying trades through either short strike before expiration.",
        )
    if family == "long_iron_condor":
        return (
            "A long iron condor buys the inner strikes and sells the outer strikes for a net debit. "
            "It is used when a move outside the body is expected. Maximum loss is the debit times the contract multiplier. "
            "Maximum profit is the wider wing minus the debit, times the multiplier.",
            f"{factual} Close the structure if the expected move does not develop before expiration.",
        )
    if family == "long_straddle":
        return (
            "A long straddle buys a call and a put at the same strike and expiration. "
            "It is used when a large move is expected and direction is not chosen. "
            "Maximum loss is the combined premium times the contract multiplier. Maximum profit is unlimited.",
            f"{factual} Exit on a large move or before expiration if the premium has been spent.",
        )
    if family in {"calendar", "diagonal"}:
        lead = {
            "calendar": "A calendar sells the nearer expiration and buys the later expiration at the same strike. It is used when the outlook is roughly neutral and the near-dated option decays first.",
            "diagonal": "A diagonal buys a longer-dated option and sells a nearer-dated option at a different strike. It is used for a directional bias with the short option expiring first.",
        }[family]
        return (
            f"{lead} At front expiry the short leg is intrinsic and the long leg is repriced with Black-Scholes. "
            "Maximum profit and the breakevens come from that grid and depend on the back-leg IV assumption.",
            f"{factual} Manage the short option before it expires.",
        )
    if family in {"butterfly", "ratio", "multi_expiry", "four_leg"}:
        lead = {
            "butterfly": "A butterfly combines a short body with long wings, or the reverse, at three strikes. It is used for a view that price finishes near the body.",
            "ratio": "A ratio uses unequal quantities of long and short options. One side of the payoff is not a simple vertical.",
            "multi_expiry": "This structure uses options in more than one expiration.",
            "four_leg": "This structure uses four option legs in one expiration.",
        }[family]
        return (
            f"{lead} {_REMAINING_LONG_LEG}",
            f"{factual} Manage the short option before it expires. The remaining long leg is a separate position after that.",
        )
    if family == "equity_overlay":
        return (
            "This structure pairs stock with one or more options. The option payoff is only part of the position.",
            factual,
        )
    return None


def _apex_leg_sentence(legs: list[dict[str, Any]]) -> str:
    bits: list[str] = []
    for leg in legs:
        action = str(leg.get("action") or "trade").capitalize()
        side = leg.get("side")
        strike = _strike(leg)
        expiry = leg.get("expiry") or "—"
        mid = leg.get("mid")
        price = f" at ${float(mid):.2f}" if isinstance(mid, (int, float)) else ""
        symbol = leg.get("symbol") or ""
        qty = leg.get("quantity") or 1
        strike_txt = f"{float(strike):g}" if strike is not None else "—"
        bits.append(
            f"{action} {qty:g} {side} strike {strike_txt} expiring {expiry}{price} ({symbol})"
        )
    return "; ".join(bits) + "."


def _named_geometry_copy(strategy_name: str, legs: list[dict[str, Any]] | None) -> tuple[str, str] | None:
    """Name-specific copy once the legs actually match that structure."""
    factual = factual_structure_copy(legs)
    if strategy_name in {"APEX Strategy", "Gamma Trampoline™"}:
        from app.strategies.knowledge_base import GAMMA_CLASSIFIER, GAMMA_HOW, GAMMA_SCENARIOS, GAMMA_SUMMARY
        from app.strategies.validator import apex_structure_reason

        rows = [leg for leg in (legs or []) if isinstance(leg, dict)]
        if apex_structure_reason(rows) is None and len(rows) == 4:
            detail = _apex_leg_sentence(rows)
            if strategy_name == "Gamma Trampoline™":
                return (
                    f"{GAMMA_SUMMARY} {GAMMA_SCENARIOS} {detail}",
                    f"{GAMMA_HOW} {detail}",
                )
            return (
                "A double calendar sells the nearer expiration and buys the later expiration at the same strikes "
                "on each side. " + GAMMA_CLASSIFIER + " " + detail,
                detail,
            )
    if strategy_name == "APEX Benchmark Greeks Strategy":
        from app.strategies.knowledge_base import BENCHMARK_SUMMARY, RULE1_HOW

        rows = [leg for leg in (legs or []) if isinstance(leg, dict) and leg.get("side") in {"call", "put"}]
        if len(rows) == 1 and rows[0].get("action") == "buy":
            return (BENCHMARK_SUMMARY, RULE1_HOW)
    rows = [leg for leg in (legs or []) if isinstance(leg, dict)]
    stock = [leg for leg in rows if leg.get("side") == "stock"]
    opts = [leg for leg in rows if leg.get("side") in {"call", "put"}]
    if strategy_name == "Wheel Strategy":
        if len(stock) == 0 and len(opts) == 1 and opts[0].get("action") == "sell" and opts[0].get("side") == "put":
            return (
                "The wheel opens as a cash-secured short put. Cash is set aside to buy the shares if assigned. "
                "Profit is the premium times the contract multiplier. Loss, if the shares are put to the account and go to zero, "
                "is the strike minus the premium, times the multiplier. "
                "The covered-call stage is not included because shares are not already held.",
                f"{factual} This is not a naked put and it is not a vertical spread.",
            )
        if (
            len(stock) == 1
            and stock[0].get("already_held")
            and len(opts) == 1
            and opts[0].get("action") == "sell"
            and opts[0].get("side") == "call"
        ):
            return (
                "This is the covered-call stage of the wheel. The short call is sold against shares already held. "
                "The cash-secured put is the opening stage and is not added while those shares are held.",
                factual,
            )
    if strategy_name == "Synthetic Call" and len(stock) == 1 and stock[0].get("action") == "buy" and len(opts) == 1 and opts[0].get("side") == "put" and opts[0].get("action") == "buy":
        return (
            "A synthetic call is long stock plus a long put. Profit is unlimited above the breakeven. "
            "Loss is limited to the stock price minus the put strike, plus the put premium, times the contract multiplier.",
            f"{factual} The structure is not a long call paired with a short put.",
        )
    if strategy_name == "Synthetic Put" and len(stock) == 1 and stock[0].get("action") == "sell" and len(opts) == 1 and opts[0].get("side") == "call" and opts[0].get("action") == "buy":
        return (
            "A synthetic put is short stock plus a long call. Profit is capped because the stock cannot trade below zero. "
            "The long call caps the loss if the stock rises.",
            f"{factual} The structure is not a long put paired with a short call.",
        )
    if strategy_name == "Synthetic Straddle" and len(stock) == 1 and stock[0].get("action") == "buy" and len(opts) == 1 and opts[0].get("side") == "put" and opts[0].get("action") == "buy" and (opts[0].get("quantity") or 1) >= 2:
        return (
            "A synthetic straddle is long stock plus two long puts at the same strike. "
            "Profit is unlimited if the stock rises. Loss at the strike is finite.",
            f"{factual} The structure is not a long call and a long put without stock.",
        )
    if strategy_name == "Vega Neutral Spread" and len(opts) == 2 and len({str(leg.get("expiry")) for leg in opts}) > 1 and len({_strike(leg) for leg in opts}) == 1:
        return (
            "A vega-neutral spread buys and sells the same strike in two expirations, with quantities set so the vegas offset. "
            "It is not a same-expiry vertical. No closed-form max profit is shown.",
            factual,
        )
    if strategy_name == "Poor Man's Covered Call" and len(opts) == 2 and len({str(leg.get("expiry")) for leg in opts}) > 1:
        long_call = next((leg for leg in opts if leg.get("action") == "buy" and leg.get("side") == "call"), None)
        short_call = next((leg for leg in opts if leg.get("action") == "sell" and leg.get("side") == "call"), None)
        if long_call and short_call and str(long_call.get("expiry")) != str(short_call.get("expiry")):
            return (
                "A poor man's covered call is a diagonal: long a far-dated in-the-money call and short a nearer out-of-the-money call. "
                "Payoff depends on the remaining long leg. No closed-form max profit is shown.",
                factual,
            )
    if strategy_name == "Dispersion Trade" and len(opts) == 2 and {leg.get("underlying") for leg in opts} - {None} and len({leg.get("underlying") for leg in opts}) >= 2:
        return (
            "A dispersion trade sells an at-the-money call on one underlying and buys an at-the-money call on a second underlying. "
            "It is not a one-name vertical. No closed-form max profit is shown.",
            factual,
        )
    return None


def _structure_copy(
    strategy_name: str,
    legs: list[dict[str, Any]] | None,
    *,
    benchmark_rule: str | None = None,
) -> tuple[str, str]:
    """Describe the legs. A playbook line is kept only when it matches that geometry."""
    if benchmark_rule == "rule2" and strategy_name in {
        "Short Iron Condor",
        "Bull Put Spread (credit)",
        "Bear Call Spread (credit)",
    }:
        from app.strategies.knowledge_base import BENCHMARK_SUMMARY, RULE2_HOW

        detail = factual_structure_copy(legs)
        return (f"{BENCHMARK_SUMMARY} {RULE2_HOW}", detail)
    named = _named_geometry_copy(strategy_name, legs)
    if named:
        return named
    family = classify_legs(legs)
    grounded = _grounded_copy(family, legs)
    playbook = PLAYBOOK.get(strategy_name) or {}
    pb_summary = str(playbook.get("summary") or "").strip()
    pb_exec = str(playbook.get("execution") or "").strip()
    if _copy_conflicts(f"{pb_summary} {pb_exec}", family):
        pb_summary, pb_exec = "", ""
    factual = factual_structure_copy(legs)
    if grounded:
        summary, execution = grounded
        if "LEAPS" in strategy_name:
            summary = f"{summary} The expiration is more than a year out."
        if strategy_name in {"Deep ITM Call", "Deep ITM Put"}:
            summary = f"{summary} The strike is deep in the money, not at the money."
        if pb_exec and pb_exec not in execution:
            execution = f"{execution} {pb_exec}"
        return summary, execution
    summary = pb_summary or factual
    execution = pb_exec or factual
    return summary, execution


def _executable_name(strategy_name: str, *, direction: str, leg_structure: str | None) -> str:
    spec = get_strategy_spec(strategy_name)
    if spec is None or (spec.risk_type != "advisory" and spec.leg_count > 0):
        if spec is not None or strategy_name:
            if spec is None and strategy_name:
                return strategy_name
            if spec is not None and spec.leg_count > 0 and spec.risk_type != "advisory":
                return strategy_name
    if leg_structure:
        held = get_strategy_spec(leg_structure)
        if held is not None and held.leg_count > 0 and held.risk_type != "advisory":
            return leg_structure
    if direction == "bearish":
        return "Bear Put Spread"
    if direction == "neutral":
        return "Long Straddle"
    return "Bull Call Spread"


def _vol_citation(vol_layer: dict[str, Any]) -> str | None:
    """Cite IV and HV as percentages when the scan already supplied them."""
    iv = format_vol_percent(vol_layer.get("iv"))
    hv = format_vol_percent(vol_layer.get("hv"))
    if iv and hv:
        return f"IV {iv} versus HV {hv}."
    if iv:
        return f"IV {iv}."
    if hv:
        return f"HV {hv}."
    return None


def _outlook_for(strategy_name: str, direction: str) -> str:
    bias = DEFINED_RISK_PLAYBOOK.get(strategy_name, {}).get("bias")
    if bias in {"bullish", "bearish", "neutral"}:
        return str(bias)
    return direction


def _threshold_token(value: float) -> str:
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:g}"


def align_exit_copy(execution: str, threshold: float) -> str:
    """Printed exit is the hysteresis exit line, which sits below the entry line."""
    _ = threshold
    token = _threshold_token(exit_composite_min())
    return execution.replace("composite drop below 72", f"composite drop below {token}")


def printed_exit_level(execution: str) -> float | None:
    match = re.search(r"composite drop below (\d+(?:\.\d+)?)", execution)
    if not match:
        return None
    return float(match.group(1))


def _cites_rule1(text: str) -> bool:
    theta = "0.05" in text and ("Θ" in text or "theta" in text.lower())
    ratio = "Δ/Θ" in text or "delta/theta" in text.lower()
    return theta and ratio


def _cites_spread_rule(text: str) -> bool:
    lowered = text.lower()
    return "8%" in text and "mid" in lowered and "spread" in lowered


def _row_mid(row: dict[str, Any]) -> float | None:
    bid, ask = row.get("bid"), row.get("ask")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    mid = row.get("mid")
    if isinstance(mid, (int, float)) and mid > 0:
        return float(mid)
    return None


def _contract_for_leg(leg: dict[str, Any], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    symbol = leg.get("symbol")
    for row in contracts:
        if symbol and row.get("symbol") == symbol:
            return row
    strike = leg.get("strike")
    side = leg.get("side")
    for row in contracts:
        if side and row.get("side") == side and strike is not None and row.get("strike") is not None:
            if abs(float(row["strike"]) - float(strike)) < 0.01:
                return row
    return leg


def rule1_buy_failures(
    legs: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    *,
    hv: Any = None,
    mode: str | None = None,
    check_iv_below_hv: bool = False,
) -> list[str]:
    """Rule 1 misses for buy legs. Theta mode comes from settings unless a test passes one.

    IV below HV is a Rule 1 gate. Callers turn it on only for Rule 1 strategy names.
    """
    failures: list[str] = []
    checked = False
    for leg in legs:
        if str(leg.get("action") or "") != "buy" or leg.get("side") not in {"call", "put"}:
            continue
        checked = True
        source = _contract_for_leg(leg, contracts)
        mid = _row_mid(source) or _row_mid(leg)
        delta = source.get("delta")
        if delta is None:
            delta = leg.get("delta")
        theta = daily_theta_per_share(
            source.get("theta") if source.get("theta") is not None else leg.get("theta"),
            mid=mid,
            multiplier=source.get("multiplier") or leg.get("multiplier") or 100,
        )
        if not isinstance(delta, (int, float)) or isinstance(delta, bool) or theta is None:
            failures.append("buy delta or daily theta is missing, so Rule 1 cannot pass")
            continue
        theta_fail, _notes = rule1_theta_failures(
            delta=float(delta),
            theta_per_share=float(theta),
            premium=mid,
            mode=mode,
        )
        failures.extend(theta_fail)
        bid, ask = source.get("bid"), source.get("ask")
        if (
            isinstance(bid, (int, float))
            and not isinstance(bid, bool)
            and isinstance(ask, (int, float))
            and not isinstance(ask, bool)
            and bid > 0
            and ask > 0
        ):
            mid_px = (float(bid) + float(ask)) / 2.0
            if mid_px > 0 and (float(ask) - float(bid)) / mid_px >= 0.08:
                pct = (float(ask) - float(bid)) / mid_px
                failures.append(f"bid/ask spread is {pct * 100:.1f}% of mid, not below 8%")
        if check_iv_below_hv:
            contract_iv = source.get("iv")
            if contract_iv is None:
                contract_iv = leg.get("iv")
            below = iv_below_hv(contract_iv, hv)
            if below is False:
                failures.append("contract IV is not below HV")
            elif below is None and hv is not None:
                failures.append("contract IV is missing, so IV below HV cannot pass")
    if not checked:
        failures.append("no buy leg was available to grade against Rule 1")
    return failures


def _leg_spread_pct(source: dict[str, Any]) -> float | None:
    bid, ask = source.get("bid"), source.get("ask")
    if not (
        isinstance(bid, (int, float))
        and not isinstance(bid, bool)
        and isinstance(ask, (int, float))
        and not isinstance(ask, bool)
        and float(bid) > 0
        and float(ask) > 0
    ):
        return None
    mid = (float(bid) + float(ask)) / 2.0
    if mid <= 0:
        return None
    return (float(ask) - float(bid)) / mid


def _quote_meta(source: dict[str, Any], leg: dict[str, Any]) -> dict[str, Any] | None:
    for row in (source, leg):
        if not isinstance(row, dict):
            continue
        raw = row.get("quote_meta") or row.get("quoteMeta")
        if isinstance(raw, dict):
            return raw
    return None


def _quote_is_stale_failure(
    source: dict[str, Any],
    leg: dict[str, Any],
    *,
    now: datetime | None = None,
) -> bool:
    """Stale during the session. A last close is not a failure. The 300s cap stays."""
    meta = _quote_meta(source, leg)
    if meta is not None and meta.get("staleReason") == "last_close":
        return False
    quoted = None
    if isinstance(source, dict):
        quoted = source.get("quote_as_of") or source.get("as_of")
    if not quoted and isinstance(leg, dict):
        quoted = leg.get("quote_as_of") or leg.get("as_of")
    clock = now or datetime.now(timezone.utc)
    is_stale, reason = classify_quote_freshness(quoted_at=quoted, now=clock)
    if reason == "last_close":
        return False
    if meta is not None and meta.get("isStale") is True:
        return True
    return bool(is_stale)


def suspect_quote_failures(
    legs: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    *,
    spot: float | None,
    now: datetime | None = None,
) -> list[str]:
    """Flag a mid whose implied vol is more than 5 points from the chain IV, a stale quote, or a 2:1 mid."""
    from app.analysis.black_scholes import implied_vol, year_fraction

    failures: list[str] = []
    mids: list[float] = []
    for leg in legs:
        if not isinstance(leg, dict) or leg.get("side") not in {"call", "put"}:
            continue
        source = _contract_for_leg(leg, contracts)
        mid = _row_mid(source) or _row_mid(leg)
        if mid is not None:
            mids.append(float(mid))
        if _quote_is_stale_failure(source, leg, now=now):
            failures.append("Stale or suspect quote")
            continue
        chain_iv = source.get("iv")
        if chain_iv is None:
            chain_iv = leg.get("iv")
        if mid is None or spot is None or spot <= 0 or chain_iv is None:
            continue
        strike = source.get("strike") if source.get("strike") is not None else leg.get("strike")
        side = source.get("side") or leg.get("side")
        expiry = source.get("expiry") or leg.get("expiry")
        if strike is None or side not in {"call", "put"}:
            continue
        dte = 30
        if expiry:
            try:
                exp = datetime.fromisoformat(str(expiry)[:10]).date()
                dte = max((exp - datetime.now(timezone.utc).date()).days, 1)
            except ValueError:
                dte = 30
        solved = implied_vol(
            price=float(mid),
            spot=float(spot),
            strike=float(strike),
            years=year_fraction(dte),
            side=side,
        )
        if solved is None:
            continue
        chain = float(chain_iv)
        if chain > 3.0:
            chain = chain / 100.0
        if abs(solved - chain) * 100.0 > 5.0:
            failures.append("Stale or suspect quote")
    if len(mids) == 2 and mids_are_exact_double(mids):
        failures.append("Stale or suspect quote")
    deduped: list[str] = []
    for item in failures:
        if item not in deduped:
            deduped.append(item)
    return deduped


def spread_rule_failures(legs: list[dict[str, Any]], contracts: list[dict[str, Any]]) -> list[str]:
    """Fail when a cited spread-versus-mid rule is wider than 8%."""
    failures: list[str] = []
    for leg in legs:
        if not isinstance(leg, dict) or leg.get("side") not in {"call", "put"}:
            continue
        source = _contract_for_leg(leg, contracts)
        bid, ask = source.get("bid"), source.get("ask")
        if not (
            isinstance(bid, (int, float))
            and not isinstance(bid, bool)
            and isinstance(ask, (int, float))
            and not isinstance(ask, bool)
            and bid > 0
            and ask > 0
        ):
            failures.append(f"{leg.get('symbol') or leg.get('side')} has no live bid/ask, so spread versus mid cannot pass")
            continue
        mid = (float(bid) + float(ask)) / 2.0
        if mid <= 0:
            continue
        pct = (float(ask) - float(bid)) / mid
        if pct >= 0.08:
            failures.append(f"bid/ask spread is {pct * 100:.1f}% of mid, not below 8%")
    return failures


def _apply_mid_limits(metrics: dict[str, Any], contracts: list[dict[str, Any]]) -> list[str]:
    """Marketable limit from the live ask (buy) or bid (sell). Never a market order."""
    from app.services.executability import marketable_limit

    missing: list[str] = []
    for leg in metrics.get("legs") or []:
        if not isinstance(leg, dict) or leg.get("side") not in {"call", "put"}:
            continue
        source = _contract_for_leg(leg, contracts)
        bid, ask = source.get("bid"), source.get("ask")
        action = str(leg.get("action") or "").lower()
        priced = marketable_limit(action, {"bid": bid, "ask": ask})
        limit, basis = priced if priced is not None else (None, None)
        quoted = source.get("quote_as_of") or source.get("as_of") or leg.get("quote_as_of")
        if limit is None or basis is None:
            if leg.get("order_type") != "limit":
                mid = leg.get("mid")
                if isinstance(mid, (int, float)) and not isinstance(mid, bool) and mid > 0:
                    leg["order_type"] = "limit"
                    leg["limit_price"] = round(float(mid), 2)
                    leg["limit_basis"] = "mid"
                    leg["order_note"] = "limit at mid"
                else:
                    missing.append(str(leg.get("symbol") or leg.get("side") or "option"))
            if quoted:
                leg["quote_as_of"] = quoted
            continue
        leg["order_type"] = "limit"
        leg["limit_price"] = limit
        leg["limit_basis"] = basis
        leg["order_note"] = "limit at the ask" if basis == "ask" else "limit at the bid"
        if quoted:
            leg["quote_as_of"] = quoted
    return missing


def _apply_marketable_limits(metrics: dict[str, Any], contracts: list[dict[str, Any]]) -> None:
    """Option legs are limits at the live ask (buy) or bid (sell). Never a market order."""
    for leg in metrics.get("legs") or []:
        if not isinstance(leg, dict) or leg.get("side") not in {"call", "put"}:
            continue
        source = _contract_for_leg(leg, contracts)
        action = str(leg.get("action") or "").lower()
        quoted = source.get("quote_as_of") or leg.get("quote_as_of")
        if quoted:
            leg["quote_as_of"] = quoted
        bid, ask = source.get("bid"), source.get("ask")
        if (
            isinstance(bid, (int, float))
            and not isinstance(bid, bool)
            and isinstance(ask, (int, float))
            and not isinstance(ask, bool)
            and float(bid) > 0
            and float(ask) > 0
            and float(ask) >= float(bid)
            and action in {"buy", "sell"}
        ):
            if action == "buy":
                leg["limit_price"] = round(float(ask), 2)
                leg["limit_basis"] = "ask"
                leg["order_note"] = "limit at the ask"
                leg["quoted_side"] = "ask"
            else:
                leg["limit_price"] = round(float(bid), 2)
                leg["limit_basis"] = "bid"
                leg["order_note"] = "limit at the bid"
                leg["quoted_side"] = "bid"
            leg["order_type"] = "limit"
            continue
        mid = leg.get("mid")
        if isinstance(mid, (int, float)) and not isinstance(mid, bool) and float(mid) > 0:
            leg["order_type"] = "limit"
            leg["limit_price"] = round(float(mid), 2)
            leg["limit_basis"] = leg.get("limit_basis") or "mid"
            leg["order_note"] = leg.get("order_note") or "limit from the scan mid; live bid/ask was not on the quote"


def _stale_quote_phrase(legs: list[dict[str, Any]], contracts: list[dict[str, Any]]) -> str | None:
    oldest: tuple[float, str] | None = None
    clock = datetime.now(timezone.utc)
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        source = _contract_for_leg(leg, contracts)
        raw = source.get("quote_as_of") or leg.get("quote_as_of")
        if not _quote_is_stale_failure(source, leg, now=clock):
            continue
        phrase = quote_age_phrase(raw, now=clock)
        if not phrase:
            continue
        parsed = str(raw)
        age = 0.0
        try:
            stamp = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (clock - stamp).total_seconds()
        except ValueError:
            age = 0.0
        if oldest is None or age > oldest[0]:
            oldest = (age, f"Quote not current. {phrase}. Quoted {parsed}.")
    return oldest[1] if oldest else None


def _protective_put_label(legs: list[dict[str, Any]], *, covered: bool) -> str | None:
    """Shares already held plus one long put. The label comes from the legs."""
    if not covered:
        return None
    rows = [leg for leg in legs if isinstance(leg, dict)]
    stock = [leg for leg in rows if leg.get("side") == "stock"]
    puts = [
        leg
        for leg in rows
        if leg.get("side") == "put" and str(leg.get("action") or "").lower() == "buy"
    ]
    calls = [leg for leg in rows if leg.get("side") == "call"]
    if len(stock) == 1 and len(puts) == 1 and not calls:
        return "Protective Put"
    return None


def _earnings_inputs(
    fundamentals_layer: dict[str, Any] | None,
    sentiment_layer: dict[str, Any] | None,
) -> tuple[int | None, bool, bool]:
    """Days, confirmed, and whether a calendar was supplied."""
    fundamentals = fundamentals_layer or {}
    sentiment = sentiment_layer or {}
    calendar = fundamentals.get("earnings_calendar") if isinstance(fundamentals.get("earnings_calendar"), dict) else None
    alert = sentiment.get("earnings_alert") if isinstance(sentiment.get("earnings_alert"), dict) else None
    if calendar is not None and calendar.get("earnings_applicable") is False:
        return None, False, False
    if calendar is None and alert is None:
        return None, False, False
    status = calendar.get("date_status") if calendar is not None else None
    if status == "estimated":
        next_date = calendar.get("next_date") if calendar is not None else None
        if not next_date and alert is not None:
            next_date = alert.get("next_date")
        raw_days = None
        if calendar is not None:
            raw_days = calendar.get("dte")
            if raw_days is None:
                raw_days = calendar.get("days_until")
        if raw_days is None and alert is not None:
            raw_days = alert.get("dte")
            if raw_days is None:
                raw_days = alert.get("days_until")
        try:
            days = int(raw_days) if raw_days is not None else None
        except (TypeError, ValueError):
            days = None
        return days, True, True
    next_date = None
    if calendar is not None:
        next_date = calendar.get("next_date")
    if not next_date and alert is not None:
        next_date = alert.get("next_date")
    if not next_date:
        return None, False, True
    raw_days = None
    if calendar is not None:
        raw_days = calendar.get("dte")
        if raw_days is None:
            raw_days = calendar.get("days_until")
    if raw_days is None and alert is not None:
        raw_days = alert.get("dte")
        if raw_days is None:
            raw_days = alert.get("days_until")
    try:
        days = int(raw_days) if raw_days is not None else None
    except (TypeError, ValueError):
        days = None
    return days, True, True


_DTE_RANGE = re.compile(r"(\d+)\s*(?:–|—|-|to)\s*(\d+)\s*DTE", re.IGNORECASE)
_DTE_IS = re.compile(r"DTE\s+is\s+(\d+)\s+to\s+(\d+)", re.IGNORECASE)


def _window_from_text(text: str) -> tuple[int, int] | None:
    match = _DTE_RANGE.search(text) or _DTE_IS.search(text)
    if match is None:
        return None
    low, high = int(match.group(1)), int(match.group(2))
    if low > high:
        low, high = high, low
    return low, high


def _dte_inside(dte: int, low: int, high: int | None) -> bool:
    if dte < low:
        return False
    return True if high is None else dte <= high


def _window_phrase(low: int, high: int | None) -> str:
    if high is None:
        return f"more than {low - 1} calendar days"
    return f"{low} to {high} DTE"


def dte_window_for(strategy_name: str) -> tuple[int, int | None] | None:
    """Option DTE bounds from the catalog. A missing max is an open upper end.

    The Gamma Trampoline 5–10 day band is an earnings window, not option DTE.
    A catalog row with both bounds empty does not borrow a window from how-to text.
    """
    names = [strategy_name]
    if strategy_name in {"Protective Put", "Stock + Long Put"}:
        names.append("Married Put")
    from app.strategies.knowledge_base import entry_for

    saw_entry = False
    for name in names:
        entry = entry_for(name)
        if entry is None:
            continue
        saw_entry = True
        source = str(getattr(entry, "dte_source", "") or "").lower()
        label = str(getattr(entry, "dte_window", "") or "").lower()
        if "earnings window" in source or "before earnings" in label:
            return None
        explicit = getattr(entry, "dte_window", None)
        if isinstance(explicit, (tuple, list)) and len(explicit) == 2:
            return int(explicit[0]), int(explicit[1])
        low = getattr(entry, "dte_min", None)
        high = getattr(entry, "dte_max", None)
        if isinstance(low, int) and not isinstance(low, bool):
            if isinstance(high, int) and not isinstance(high, bool):
                return low, high
            if high is None:
                return low, None
        if low is None and high is None:
            return None
    if saw_entry:
        return None
    for name in names:
        play = PLAYBOOK.get(name) or {}
        found = _window_from_text(f"{play.get('execution', '')} {play.get('summary', '')}")
        if found is not None:
            return found
    return None


def _listed_expiries(chain_analysis: dict[str, Any], vol_layer: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key in ("expiration_dates", "expiries"):
        raw = chain_analysis.get(key)
        if isinstance(raw, list):
            found.extend(str(item)[:10] for item in raw if item)
    for row in chain_analysis.get("contracts") or []:
        if isinstance(row, dict) and row.get("expiry"):
            found.append(str(row["expiry"])[:10])
    term = vol_layer.get("term_structure")
    legs = term.get("legs") if isinstance(term, dict) else None
    if isinstance(legs, list):
        found.extend(str(leg.get("expiry"))[:10] for leg in legs if isinstance(leg, dict) and leg.get("expiry"))
    return found


def _option_iv(leg: dict[str, Any], pools: list[list[dict[str, Any]]]) -> float | None:
    if isinstance(leg.get("iv"), (int, float)) and not isinstance(leg.get("iv"), bool):
        return float(leg["iv"])
    for pool in pools:
        row = _contract_for_leg(leg, pool)
        iv = row.get("iv")
        if isinstance(iv, (int, float)) and not isinstance(iv, bool):
            return float(iv)
    return None


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _event_vega_note(
    legs: list[dict[str, Any]],
    *,
    earnings_on: date | None,
    earnings_label: str,
    hv: Any,
    pools: list[list[dict[str, Any]]],
) -> tuple[str | None, float | None]:
    """Penalty sentence and the measured vol points. Missing IV returns no points."""
    if earnings_on is None:
        return None, None
    shorts = [
        leg
        for leg in legs
        if str(leg.get("action") or "").lower() == "sell" and leg.get("side") in {"call", "put"} and leg.get("expiry")
    ]
    longs = [
        leg
        for leg in legs
        if str(leg.get("action") or "").lower() == "buy" and leg.get("side") in {"call", "put"} and leg.get("expiry")
    ]
    if not shorts or not longs:
        return None, None
    short_dates = [_parse_iso_date(leg.get("expiry")) for leg in shorts]
    if any(parsed is not None and parsed >= earnings_on for parsed in short_dates):
        return None, None
    spanning = []
    for leg in longs:
        parsed = _parse_iso_date(leg.get("expiry"))
        if parsed is not None and parsed > earnings_on:
            spanning.append(leg)
    if not spanning:
        return None, None
    long_leg = spanning[0]
    short_leg = shorts[0]
    long_iv = _option_iv(long_leg, pools)
    from app.analysis.gate_config import _as_fraction

    normal = _as_fraction(hv)
    long_fraction = _as_fraction(long_iv)
    premium = None
    if long_fraction is not None and normal is not None:
        premium = (long_fraction - normal) * 100.0
    side = str(long_leg.get("side") or "option")
    short_side = str(short_leg.get("side") or "option")
    base = (
        f"Event-vega penalty: the long {side} expiring {long_leg.get('expiry')} spans earnings on {earnings_label}. "
        f"The short {short_side} expiring {short_leg.get('expiry')} is before the event."
    )
    if premium is None or premium <= 0 or normal is None or long_fraction is None:
        return base + " Long-leg IV premium over normal IV could not be measured.", None
    shown = round(premium, 2)
    return (
        base
        + f" Long-leg IV {long_fraction * 100:.2f}% is {shown:.2f} vol points over normal IV {normal * 100:.2f}%."
        + f" Penalty {shown:.2f} points."
    ), shown


def _sentiment_direction(score: Any, bias: Any) -> str | None:
    text = str(bias or "").lower()
    if "bull" in text and "bear" not in text:
        return "bullish"
    if "bear" in text:
        return "bearish"
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if float(score) > 50:
        return "bullish"
    if float(score) < 50:
        return "bearish"
    return "neutral"


def _structure_direction(strategy_name: str, direction: str) -> str | None:
    bias = DEFINED_RISK_PLAYBOOK.get(strategy_name, {}).get("bias")
    if bias in {"bullish", "bearish"}:
        return str(bias)
    if direction in {"bullish", "bearish"}:
        return direction
    return None


def _front_back_iv(
    legs: list[dict[str, Any]],
    pools: list[list[dict[str, Any]]],
    vol_layer: dict[str, Any],
) -> tuple[Any, Any]:
    dated: list[tuple[date, float]] = []
    for leg in legs:
        exp = _parse_iso_date(leg.get("expiry"))
        if exp is None or leg.get("side") not in {"call", "put"}:
            continue
        iv = _option_iv(leg, pools)
        if iv is not None:
            dated.append((exp, iv))
    expiries = {row[0] for row in dated}
    if len(expiries) >= 2:
        dated.sort(key=lambda row: row[0])
        return dated[0][1], dated[-1][1]
    term = vol_layer.get("term_structure")
    term_legs = term.get("legs") if isinstance(term, dict) else None
    points: list[tuple[int, float]] = []
    if isinstance(term_legs, list):
        for leg in term_legs:
            if not isinstance(leg, dict):
                continue
            dte = leg.get("dte")
            iv = leg.get("atm_iv")
            if isinstance(dte, int) and isinstance(iv, (int, float)) and not isinstance(iv, bool):
                points.append((dte, float(iv)))
    if len(points) >= 2:
        points.sort(key=lambda row: row[0])
        return points[0][1], points[-1][1]
    return vol_layer.get("front_iv"), vol_layer.get("back_iv")


def _selected_vega_note(strategy_name: str, regime_view: Any) -> str | None:
    if regime_view.short != "sell premium" or strategy_vega_sign(strategy_name) != "long":
        return None
    time_spread = "Diagonal" in strategy_name or "Calendar" in strategy_name or strategy_name in {
        APEX_STRATEGY_NAME,
        "Gamma Trampoline™",
    }
    if regime_view.inverted and time_spread:
        return (
            "Term-structure inversion justifies the long vega: front IV is at least 1.25 times back IV."
        )
    return (
        f"Long-vega penalty: {strategy_name} is long vega in a rich IV regime "
        f"({LONG_VEGA_RICH_PENALTY:g} points versus the {IV_MISMATCH_VOL_POINTS:.0f} vol point threshold). "
        "A long-vega structure in a sell-premium regime "
        "is penalized unless term-structure inversion justifies a diagonal or calendar."
    )


def _earnings_span_note(
    legs: list[dict[str, Any]],
    *,
    fundamentals_layer: dict[str, Any],
    sentiment_layer: dict[str, Any],
    hv: Any,
    pools: list[list[dict[str, Any]]],
) -> tuple[str | None, float | None]:
    calendar = fundamentals_layer.get("earnings_calendar") if isinstance(fundamentals_layer, dict) else None
    alert = sentiment_layer.get("earnings_alert") if isinstance(sentiment_layer, dict) else None
    if isinstance(calendar, dict) and calendar.get("earnings_applicable") is False:
        return None, None
    raw = None
    label = None
    if isinstance(calendar, dict):
        raw = calendar.get("next_date")
        label = calendar.get("display") or raw
    if not raw and isinstance(alert, dict):
        raw = alert.get("next_date")
        label = label or raw
    return _event_vega_note(
        legs,
        earnings_on=_parse_iso_date(raw),
        earnings_label=str(label or raw or ""),
        hv=hv,
        pools=pools,
    )


def _retarget_dte_window(
    strategy_name: str,
    *,
    contracts: list[dict[str, Any]],
    front_expiry: str | None,
    back_month_contracts: list[dict[str, Any]] | None,
    back_expiry: str | None,
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]] | None, str | None, str] | None:
    """Move the candidate onto the nearest listed expiry inside the how-to window."""
    window = dte_window_for(strategy_name)
    if window is None or not front_expiry:
        return None
    low, high = window
    today = datetime.now(timezone.utc).date()
    user_dte = _dte_from_expiry(str(front_expiry), today=today)
    if user_dte is None or _dte_inside(user_dte, low, high):
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in contracts:
        if not isinstance(row, dict):
            continue
        exp = str(row.get("expiry") or front_expiry)[:10]
        groups.setdefault(exp, []).append(row)
    compliant: list[tuple[float, str, list[dict[str, Any]], int]] = []
    midpoint = float(low) if high is None else (low + high) / 2.0
    for exp, rows in groups.items():
        dte = _dte_from_expiry(exp, today=today)
        if dte is None or not _dte_inside(dte, low, high):
            continue
        compliant.append((abs(dte - midpoint), exp, rows, dte))
    if not compliant:
        return None
    compliant.sort()
    _, exp, rows, dte = compliant[0]
    if exp == str(front_expiry)[:10]:
        return None
    note = (
        f"User expiry {front_expiry} is {user_dte} DTE, outside the {_window_phrase(low, high)}. "
        f"The candidate uses {exp} ({dte} DTE)."
    )
    return rows, exp, back_month_contracts, back_expiry, note


def _dte_window_note(
    strategy_name: str,
    *,
    chain_analysis: dict[str, Any],
    vol_layer: dict[str, Any],
    option_legs: list[dict[str, Any]],
) -> str | None:
    window = dte_window_for(strategy_name)
    if window is None:
        return None
    low, high = window
    user_expiry = chain_analysis.get("expiry")
    if not user_expiry and option_legs:
        user_expiry = option_legs[0].get("expiry")
    dte = _dte_from_expiry(str(user_expiry) if user_expiry else None)
    if dte is None or _dte_inside(dte, low, high):
        return None
    from app.strategies.expiry_utils import nearest_expiry_in_window

    today = datetime.now(timezone.utc).date()
    nearest = nearest_expiry_in_window(
        _listed_expiries(chain_analysis, vol_layer),
        low=low,
        high=high,
        today=today,
    )
    base = (
        f"DTE penalty: selected expiry {user_expiry} is {dte} DTE, outside the how-to window of {_window_phrase(low, high)}."
    )
    if nearest is None:
        return base + " No listed expiry falls in that window."
    nearest_dte = _dte_from_expiry(nearest, today=today)
    return base + f" Nearest compliant expiry is {nearest} ({nearest_dte} DTE)."


def _sentiment_fit_note(
    *,
    strategy_name: str,
    direction: str,
    tech_score: float,
    sentiment_layer: dict[str, Any],
) -> tuple[str | None, bool]:
    score = sentiment_layer.get("score_0_100")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None, False
    struct_dir = _structure_direction(strategy_name, direction)
    sent_dir = _sentiment_direction(score, sentiment_layer.get("bias"))
    tech_dir = direction if direction in {"bullish", "bearish"} else None
    margin = direction_margin(tech_score=float(tech_score), sentiment_score=float(score)) if tech_dir else None
    low = margin is not None and margin < direction_margin_min()
    if struct_dir not in {"bullish", "bearish"} or sent_dir not in {"bullish", "bearish"} or struct_dir == sent_dir:
        return None, low
    tech_w = float(APEX_COMPOSITE_WEIGHTS["technicals"])
    sent_w = float(APEX_COMPOSITE_WEIGHTS["sentiment"])
    tech_mag = abs(float(tech_score)) * tech_w
    sent_mag = abs((float(score) - 50.0) * 2.0) * sent_w
    threshold = direction_margin_min()
    if tech_mag >= sent_mag:
        lead = (
            f"The technical weighted vote {tech_mag:.1f} leads the sentiment weighted vote {sent_mag:.1f}, "
            f"so the {struct_dir} direction prevailed."
        )
    else:
        lead = (
            f"The sentiment weighted vote {sent_mag:.1f} leads the technical weighted vote {tech_mag:.1f}. "
            f"The structure follows the technical direction {direction}."
        )
    margin_text = "unavailable" if margin is None else f"{margin:.1f}"
    conviction = (
        f"Direction margin {margin_text} is below {threshold:g}, so the outlook is low conviction."
        if low
        else f"Direction margin {margin_text} is at or above {threshold:g}."
    )
    note = (
        f"Sentiment conflict: score {float(score):g} ({sent_dir}) weight {sent_w * 100:.0f}% "
        f"opposes the {struct_dir} structure. Technical bias {direction} score {float(tech_score):g} "
        f"weight {tech_w * 100:.0f}%. {lead} {conviction}"
    )
    return note, low


def _card_stamp(quote_as_of: Any) -> str:
    if isinstance(quote_as_of, str) and quote_as_of.strip():
        return quote_as_of.strip()
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _record_card_figures(
    scan_id: str,
    strategy_name: str,
    figures: dict[str, Any],
    *,
    feed: Any,
    timestamp: str,
) -> None:
    """Persist the numbers the card is allowed to print. Does not read the prose."""
    from app.services.evidence_ledger import record_card_value

    feed_text = feed if isinstance(feed, str) and feed.strip() else None
    for key, value in figures.items():
        if value is None or value == "":
            continue
        inputs: dict[str, Any] = {"strategy": strategy_name}
        if str(key).startswith("threshold_"):
            inputs["threshold"] = value
        else:
            inputs["measured"] = value
        record_card_value(
            scan_id,
            str(key),
            value,
            inputs=inputs,
            source="strategy_layer",
            feed=feed_text,
            timestamp=timestamp,
            fn="build_strategy_layer",
            strategy_id=strategy_name,
        )


def _without_catalog_sentences(text: str, strategy_name: str) -> str:
    """Drop verbatim knowledge-base sentences so the check can judge the generated remainder."""
    try:
        from app.strategies.knowledge_base import entry_for
    except Exception:
        return text
    entry = entry_for(strategy_name)
    if entry is None:
        return text
    catalog = "\n".join(
        str(getattr(entry, name, "") or "")
        for name in ("title", "summary", "why_it_fits", "how_to_use", "key_risks", "greeks_profile")
    )
    pieces = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        cleaned = sentence.strip()
        if cleaned and cleaned not in catalog and catalog.find(cleaned.rstrip(".")) < 0:
            pieces.append(cleaned)
    return " ".join(pieces)


def _guard_card_text(text: str, *, scan_id: str, strategy_name: str) -> str:
    from app.services.narrative_guard import check_narrative

    result = check_narrative(text or "", scan_id=scan_id, strategy_id=strategy_name)
    if result.accepted:
        return result.text
    remainder = _without_catalog_sentences(text or "", strategy_name)
    if remainder != (text or ""):
        again = check_narrative(remainder, scan_id=scan_id, strategy_id=strategy_name)
        if again.accepted:
            return text
    return result.text


def _guard_strategy_card(
    *,
    scan_id: str,
    strategy_name: str,
    fit: str,
    execution: str,
    notes: list[str],
    summary: str,
    status_line: str,
    narrative: str,
    figures: dict[str, Any],
    feed: Any,
    quote_as_of: Any,
) -> tuple[str, str, list[str], str, str, str]:
    _record_card_figures(
        scan_id,
        strategy_name,
        figures,
        feed=feed,
        timestamp=_card_stamp(quote_as_of),
    )
    guarded_notes = [
        _guard_card_text(note, scan_id=scan_id, strategy_name=strategy_name) for note in notes if note
    ]
    return (
        _guard_card_text(fit, scan_id=scan_id, strategy_name=strategy_name),
        _guard_card_text(execution, scan_id=scan_id, strategy_name=strategy_name),
        guarded_notes,
        _guard_card_text(summary, scan_id=scan_id, strategy_name=strategy_name),
        _guard_card_text(status_line, scan_id=scan_id, strategy_name=strategy_name),
        _guard_card_text(narrative, scan_id=scan_id, strategy_name=strategy_name),
    )


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
    auto_exec_threshold: float = DEFAULT_AUTO_EXEC_THRESHOLD,
    back_month_contracts: list[dict[str, Any]] | None = None,
    back_expiry: str | None = None,
    earnings_risk_opt_in: bool = False,
    in_position: bool = False,
    ticker: str = "",
    gate_reason: str | None = None,
    leg_structure: str | None = None,
    strategies_evaluated: int | None = None,
    risk_notes: list[str] | None = None,
    benchmark_rule: str | None = None,
) -> dict[str, Any]:
    from app.analysis.score_bounds import validate_scan_scores

    requested_name = strategy_name
    sid = resolve_strategy_id(strategy_name)
    if sid and sid in STRATEGY_REGISTRY:
        strategy_name = STRATEGY_REGISTRY[sid].display_name  # type: ignore[assignment]
    from app.services.apex_strategy import GAMMA_TRAMPOLINE_NAME

    if requested_name == GAMMA_TRAMPOLINE_NAME:
        strategy_name = GAMMA_TRAMPOLINE_NAME  # type: ignore[assignment]

    tier = _execution_tier(composite, auto_exec_threshold=auto_exec_threshold)
    strategy_name = _executable_name(strategy_name, direction=direction, leg_structure=leg_structure)
    earnings_calendar = (fundamentals_layer or {}).get("earnings_calendar")
    drop_unconfirmed = (
        isinstance(earnings_calendar, dict) and earnings_calendar.get("earnings_applicable") is False
    )
    notes = [
        note
        for note in (risk_notes or [])
        if isinstance(note, str)
        and note.strip()
        and "1.35" not in note
        and not (drop_unconfirmed and note.strip() == "Earnings date is unconfirmed.")
    ]
    _ = gate_reason

    recommended = chain_analysis.get("recommendedContract")
    if strategy_name == "APEX Benchmark Greeks Strategy":
        side = "put" if direction == "bearish" else "call"
        recommended = {**(recommended or {}), "side": side, "benchmark_side": side}
    contracts = list(chain_analysis.get("contracts") or [])
    sym = ticker or chain_analysis.get("symbol") or ""
    front_expiry = chain_analysis.get("expiry")
    dte_switch_note: str | None = None
    retargeted = _retarget_dte_window(
        strategy_name,
        contracts=contracts,
        front_expiry=str(front_expiry) if front_expiry else None,
        back_month_contracts=back_month_contracts,
        back_expiry=back_expiry,
    )
    if retargeted is not None:
        contracts, front_expiry, back_month_contracts, back_expiry, dte_switch_note = retargeted
        if isinstance(recommended, dict):
            recommended = {**recommended, "expiry": front_expiry}
    metrics = compute_strategy_metrics(
        strategy_name,
        spot=chain_analysis.get("spot"),
        contracts=contracts,
        recommended=recommended,
        back_month_contracts=back_month_contracts,
        front_expiry=front_expiry,
        back_expiry=back_expiry,
        iv=vol_layer.get("iv") if isinstance(vol_layer.get("iv"), (int, float)) else None,
        ticker=sym,
        shares_held=int(chain_analysis.get("shares_held") or chain_analysis.get("sharesHeld") or 0),
        shares_encumbered=int(chain_analysis.get("shares_encumbered") or 0),
        shares_short=int(chain_analysis.get("shares_short") or 0),
        share_avg_cost=chain_analysis.get("share_avg_cost"),
        stock_ask=chain_analysis.get("stock_ask"),
        component_contracts=chain_analysis.get("component_contracts"),
        component_ticker=chain_analysis.get("component_symbol") or chain_analysis.get("component_ticker"),
        hv=vol_layer.get("hv") if isinstance(vol_layer.get("hv"), (int, float)) else None,
    )
    inferred = structure_name_from_legs(metrics.get("legs") or [])
    if inferred and inferred != strategy_name:
        built = get_strategy_spec(strategy_name)
        # A single long put is both Married Put and Long Put. A single long call is
        # both APEX Benchmark Greeks Strategy and Long Call. The matrix name stays.
        # Leg shape fills in a label only when the selector did not already name a structure.
        if built is None or built.risk_type == "advisory" or built.leg_count == 0:
            strategy_name = inferred
    recommended = _anchor_from_metrics_legs(metrics, recommended, sym)
    scan_scores = {
        "iv_rank": vol_layer.get("iv_rank"),
        "iv_percentile": vol_layer.get("iv_percentile"),
        "composite": composite,
        "technical": tech_score,
        "sentiment": sentiment_layer.get("score_0_100"),
        "fundamentals": fundamentals_layer.get("score"),
        "hv_rank": vol_layer.get("hv_rank"),
    }
    try:
        validate_scan_scores(**scan_scores)
    except ValueError as exc:
        metrics = {**metrics, "validation_blocked": True, "validation_error": str(exc)}
    spec = get_strategy_spec(strategy_name)
    validation = validate_strategy_output(
        strategy_name,
        metrics,
        sym,
        recommended_contract=recommended,
        scan_scores=scan_scores,
        spot=chain_analysis.get("spot") if isinstance(chain_analysis.get("spot"), (int, float)) else None,
    )
    validation_blocked = bool(metrics.get("validation_blocked")) or not validation.valid
    validation_errors = [e.to_log_dict() for e in validation.errors]
    if metrics.get("validation_error"):
        validation_errors.append(
            {
                "strategy_id": validation.strategy_id or strategy_name,
                "ticker": sym,
                "check": "handler",
                "expected": "complete leg structure",
                "actual": str(metrics.get("validation_error")),
            }
        )
    if validation_errors:
        validation_blocked = True
    max_profit_unlimited_allowed = bool(spec and spec.max_profit_type == "unlimited")
    if metrics.get("max_profit_unlimited_allowed") is not None:
        max_profit_unlimited_allowed = bool(metrics.get("max_profit_unlimited_allowed"))
    metrics = {**metrics, "max_profit_unlimited_allowed": max_profit_unlimited_allowed}
    if validation_errors:
        first = validation_errors[0]
        notes.append(
            f"Pre-trade check {first.get('check')}: expected {first.get('expected')}; actual {first.get('actual')}."
        )
    summary, execution = _structure_copy(
        strategy_name,
        metrics.get("legs") or [],
        benchmark_rule=benchmark_rule,
    )
    if strategy_name == "Gamma Trampoline™" and isinstance(metrics, dict) and metrics.get("scenario_conflict"):
        from app.strategies.knowledge_base import GAMMA_SCENARIOS

        summary = summary.replace(GAMMA_SCENARIOS, "").strip()
    reason = metrics.get("validation_error")
    if metrics.get("validation_blocked") and reason:
        summary = str(reason)
        execution = str(reason)
    else:
        execution = align_exit_copy(execution, auto_exec_threshold)
    card_text = f"{summary} {execution}"
    block_notes: list[str] = []
    chain_rows = contracts if isinstance(contracts, list) else []
    option_legs = [leg for leg in (metrics.get("legs") or []) if isinstance(leg, dict) and leg.get("side") in {"call", "put"}]
    if not validation_blocked and (_cites_spread_rule(card_text) or "mid-price" in card_text.lower() or "mid of the net" in card_text.lower()):
        missing_mids = _apply_mid_limits(metrics, chain_rows)
        block_notes.extend(spread_rule_failures(metrics.get("legs") or [], chain_rows))
        if missing_mids:
            block_notes.append(
                "Live bid/ask mid is unavailable, so a limit at mid cannot be priced for "
                + ", ".join(missing_mids)
                + "."
            )
        elif "limit at the live bid or ask" not in execution:
            execution = (
                f"{execution} Option orders are a limit at the live bid or ask."
            ).strip()
    spread_cap = None
    if strategy_name in CREDIT_STRUCTURES:
        spread_cap = 0.10
    elif strategy_name in {APEX_STRATEGY_NAME, "Gamma Trampoline™"}:
        spread_cap = 0.08
    if spread_cap is not None:
        for leg in option_legs:
            source = _contract_for_leg(leg, chain_rows)
            spread_pct = _leg_spread_pct(source)
            if spread_pct is not None and spread_pct >= spread_cap:
                bid, ask = source.get("bid"), source.get("ask")
                slip = ""
                if (
                    isinstance(bid, (int, float))
                    and not isinstance(bid, bool)
                    and isinstance(ask, (int, float))
                    and not isinstance(ask, bool)
                    and float(ask) >= float(bid)
                ):
                    dollars = round((float(ask) - float(bid)) / 2.0 * 100.0, 2)
                    slip = f" Estimated slippage is ${dollars:.2f}."
                block_notes.append(
                    f"bid/ask spread is {spread_pct * 100:.1f}% of mid, not below {spread_cap * 100:.0f}%.{slip}"
                )
    # IV < HV belongs to Rule 1 names only. Copy that mentions the old theta line does not apply it.
    if not validation_blocked and strategy_name in PLAIN_LONG_PREMIUM:
        block_notes.extend(
            rule1_buy_failures(
                metrics.get("legs") or [],
                chain_rows,
                hv=vol_layer.get("hv"),
                check_iv_below_hv=True,
            )
        )
    iv_rank_value = vol_layer.get("iv_rank")
    if (
        strategy_name in PLAIN_LONG_PREMIUM
        and isinstance(iv_rank_value, (int, float))
        and not isinstance(iv_rank_value, bool)
        and float(iv_rank_value) > 70
    ):
        block_notes.append("IV rank is above 70, so a plain long call or long put is not selected")
    spot_px = chain_analysis.get("spot") if isinstance(chain_analysis.get("spot"), (int, float)) else None
    if option_legs:
        block_notes.extend(suspect_quote_failures(option_legs, chain_rows, spot=spot_px))
    stale_phrase = _stale_quote_phrase(option_legs, chain_rows)
    if stale_phrase:
        block_notes = [
            stale_phrase if ("stale" in note.lower() or "suspect" in note.lower()) else note
            for note in block_notes
        ]
    _apply_marketable_limits(metrics, chain_rows)
    exit_level = printed_exit_level(execution)
    if exit_level is not None and composite < exit_level:
        block_notes.append(
            f"Composite {float(composite):.1f} is already below the exit level { _threshold_token(exit_level) } printed on the card."
        )
    earn_days, earn_confirmed, earn_discussed = _earnings_inputs(fundamentals_layer, sentiment_layer)
    earnings_sentence: str | None = None
    if earn_discussed:
        earn_block, earn_note = earnings_position_note(strategy_name, days=earn_days, confirmed=earn_confirmed)
        if earn_note and earn_note not in notes and earn_note not in block_notes:
            notes.append(earn_note)
        if earn_block:
            block_notes.append(earn_note or "Earnings are within 1 day.")
        next_raw = None
        calendar = (fundamentals_layer or {}).get("earnings_calendar")
        alert = (sentiment_layer or {}).get("earnings_alert")
        if isinstance(calendar, dict):
            next_raw = calendar.get("next_date")
        if not next_raw and isinstance(alert, dict):
            next_raw = alert.get("next_date")
        expiries = [str(leg.get("expiry")) for leg in option_legs if leg.get("expiry")]
        latest_expiry = max(expiries) if expiries else chain_analysis.get("expiry")
        earn_source = None
        if isinstance(calendar, dict):
            earn_source = calendar.get("source")
        if not earn_source and isinstance(alert, dict):
            earn_source = alert.get("source")
        inside, crush_note = earnings_before_expiry(
            next_raw,
            latest_expiry,
            confirmed=earn_confirmed and bool(next_raw),
        )
        if (
            isinstance(calendar, dict)
            and calendar.get("date_status") == "estimated"
            and isinstance(crush_note, str)
            and crush_note.startswith("Earnings on ")
        ):
            shown = calendar.get("display") or next_raw
            if isinstance(shown, str) and shown.strip():
                label = shown if shown.endswith("est.") else f"{shown} est."
                tail = crush_note.split(" before expiry", 1)
                if len(tail) == 2:
                    crush_note = f"Earnings on {label} before expiry{tail[1]}"
        if (
            isinstance(calendar, dict)
            and calendar.get("earnings_applicable") is False
        ):
            crush_note = None
            earn_note = None
        if crush_note == "Earnings date is unconfirmed." and isinstance(calendar, dict):
            if calendar.get("earnings_applicable") is False:
                crush_note = None
            elif calendar.get("date_status") == "estimated":
                shown = calendar.get("display")
                crush_note = f"Earnings date {shown}." if isinstance(shown, str) and shown else None
        if crush_note and crush_note not in notes:
            notes.append(crush_note)
            earnings_sentence = crush_note
        if inside and strategy_name in PLAIN_LONG_PREMIUM and not earnings_risk_opt_in:
            block_notes.append(crush_note or "Earnings before expiry blocks auto-execute on a single-leg long option.")
    elif strategy_name != APEX_STRATEGY_NAME and any("Earnings are within 1 day." in note for note in notes):
        block_notes.append("Earnings are within 1 day.")
    deduped_blocks: list[str] = []
    for block_note in block_notes:
        if block_note and block_note not in deduped_blocks:
            deduped_blocks.append(block_note)
    block_notes = deduped_blocks
    for block_note in block_notes:
        if block_note not in notes:
            notes.append(block_note)
    deduped_notes: list[str] = []
    for note in notes:
        if note not in deduped_notes:
            deduped_notes.append(note)
    notes = deduped_notes
    from app.services.stock_leg import leg_completeness_error

    completeness = leg_completeness_error(strategy_name, metrics.get("legs") or [])
    if completeness:
        block_notes.append(completeness)
        validation_blocked = True
        if completeness not in notes:
            notes.append(completeness)
    _apply_mid_limits(metrics, chain_rows)
    auto_exec_blocked = bool(block_notes) or validation_blocked
    checks_passed = not auto_exec_blocked
    position_action = hysteresis_action(composite, in_position=in_position)
    regime_iv = vol_layer.get("atm_iv")
    if regime_iv is None:
        regime_iv = vol_layer.get("iv")
    back_pool = back_month_contracts if isinstance(back_month_contracts, list) else []
    iv_pools = [chain_rows, back_pool]
    front_iv, back_iv = _front_back_iv(option_legs, iv_pools, vol_layer)
    regime_view = assess_vol_regime(
        iv=regime_iv,
        hv=vol_layer.get("hv"),
        iv_rank=vol_layer.get("iv_rank"),
        vol_signal=vol_signal,
        front_iv=front_iv,
        back_iv=back_iv,
        inversion_flagged=bool(vol_layer.get("term_structure_inverted")),
    )
    regime = regime_view.display
    if auto_exec_blocked:
        failed = "; ".join(block_notes) if block_notes else "a pre-trade check failed"
        lead = f"NOT EXECUTABLE. Failed checks: {failed}."
    elif position_action == "no_entry":
        lead = (
            f"Composite {float(composite):.1f}/100 is below the entry line ({entry_composite_min():.0f}), "
            "so this is not a new entry."
        )
    elif position_action == "hold":
        lead = (
            f"Composite {float(composite):.1f}/100 is at or above the exit line ({exit_composite_min():.0f}), "
            "so an open position is held."
        )
    elif position_action == "exit":
        lead = (
            f"Composite {float(composite):.1f}/100 is below the exit line ({exit_composite_min():.0f})."
        )
    elif tier == "caution":
        lead = (
            f"Composite {float(composite):.1f}/100 — manual review required below your auto-execution threshold "
            f"({auto_exec_threshold:.0f})."
        )
    else:
        lead = f"Composite {float(composite):.1f}/100 meets your auto-execution threshold ({auto_exec_threshold:.0f})."
    why_parts_direction = f"Technical bias {direction} (score {tech_score})."
    rank_reason = vol_layer.get("iv_rank_gap") if isinstance(vol_layer.get("iv_rank_gap"), str) else None
    if rank_reason is None and isinstance(vol_layer.get("iv_rank_invalid"), str):
        rank_reason = vol_layer.get("iv_rank_invalid")
    iv_rank_text = format_iv_rank_with_reason(vol_layer.get("iv_rank"), rank_reason)
    why_parts = [
        lead,
        why_parts_direction,
        f"Volatility regime: {regime} (IV rank {iv_rank_text}).",
        regime_view.verdict,
        regime_view.rule,
    ]
    if earnings_sentence:
        why_parts.append(earnings_sentence)
    atm_for_label = vol_layer.get("atm_iv") if vol_layer.get("atm_iv") is not None else vol_layer.get("iv")
    contract_iv = None
    if isinstance(recommended, dict):
        contract_iv = recommended.get("iv")
    if contract_iv is None and option_legs:
        contract_iv = _contract_for_leg(option_legs[0], chain_rows).get("iv")
    if "30-day ATM IV" not in regime_view.verdict and atm_for_label is not None and vol_layer.get("hv") is not None:
        why_parts.append(
            f"30-day ATM IV {format_vol_percent(atm_for_label)} versus HV {format_vol_percent(vol_layer.get('hv'))}."
        )
    if contract_iv is not None and format_vol_percent(contract_iv) != format_vol_percent(atm_for_label):
        why_parts.append(f"Selected contract IV {format_vol_percent(contract_iv)}.")
    if sentiment_layer.get("bias"):
        shown_score = sentiment_layer.get("score_0_100")
        score_text = "unavailable: sentiment score was not supplied" if shown_score is None else shown_score
        why_parts.append(f"Sentiment {sentiment_layer.get('bias')} on 0–100 scale {score_text}.")
    conflict_note, low_conviction = _sentiment_fit_note(
        strategy_name=strategy_name,
        direction=direction,
        tech_score=tech_score,
        sentiment_layer=sentiment_layer,
    )
    if conflict_note:
        why_parts.append(conflict_note)
    vega_note = _selected_vega_note(strategy_name, regime_view)
    if vega_note:
        notes.append(vega_note)
        why_parts.append(vega_note)
    event_note, event_points = _earnings_span_note(
        option_legs,
        fundamentals_layer=fundamentals_layer,
        sentiment_layer=sentiment_layer,
        hv=vol_layer.get("hv"),
        pools=iv_pools,
    )
    if event_note:
        notes.append(event_note)
        why_parts.append(event_note)
    dte_note = dte_switch_note or _dte_window_note(
        strategy_name,
        chain_analysis=chain_analysis,
        vol_layer=vol_layer,
        option_legs=option_legs,
    )
    if dte_note:
        why_parts.append(dte_note)
        execution = f"{execution} {dte_note}".strip()
    for note in notes:
        if "ranked first" in note and note not in why_parts:
            why_parts.append(note)
    if fundamentals_layer.get("score") is not None:
        why_parts.append(f"Fundamentals score {fundamentals_layer.get('score')}.")

    selection_rationale = selection_rationale_for(
        strategy_name,
        direction=direction,
        tech_score=tech_score,
        vol_signal=vol_signal,
    )
    if selection_rationale:
        why_parts.append(selection_rationale)
    if strategy_name == "APEX Benchmark Greeks Strategy":
        from app.strategies.knowledge_base import RULE1_RATIO, RULE1_RISKS, RULE1_WHY

        option_rows = [leg for leg in option_legs if leg.get("action") == "buy"]
        if len(option_legs) == 1 and option_rows:
            why_parts.append(RULE1_WHY)
            why_parts.append(RULE1_RATIO)
            if RULE1_RISKS not in notes:
                notes.append(RULE1_RISKS)
    if benchmark_rule == "rule2":
        from app.strategies.knowledge_base import RULE2_PROBABILITY, RULE2_RISKS, RULE2_WHY

        why_parts.append(RULE2_WHY)
        why_parts.append(RULE2_PROBABILITY)
        if RULE2_RISKS not in notes:
            notes.append(RULE2_RISKS)
    if strategy_name == "Gamma Trampoline™":
        from app.strategies.knowledge_base import GAMMA_GREEKS, GAMMA_PROBLEM

        why_parts.append(GAMMA_PROBLEM)
        why_parts.append(GAMMA_GREEKS)

    defined = is_defined_risk_strategy(strategy_name)
    score_clears = (
        position_action == "enter"
        and composite >= auto_exec_threshold
        and defined
        and not validation_blocked
        and not auto_exec_blocked
    )
    hard_blocks, spread_blocks = split_block_notes(block_notes)
    if validation_blocked and not hard_blocks:
        hard_blocks = ["Pre-trade validation did not pass."]
    placeable = not validation_blocked and not hard_blocks
    executable_flag = bool(placeable and not spread_blocks and defined and not auto_exec_blocked)
    validation_flag = not validation_blocked and not hard_blocks
    exec_reason = None
    if not executable_flag:
        if hard_blocks:
            exec_reason = hard_blocks[0]
        elif spread_blocks:
            exec_reason = spread_blocks[0]
        elif not defined:
            exec_reason = "The structure is not defined risk."
        elif block_notes:
            exec_reason = block_notes[0]
        else:
            exec_reason = "Not executable."
    decision = can_auto_execute(
        {
            "composite_score": composite,
            "executable": executable_flag,
            "validation_passed": validation_flag,
            "executability_reason": exec_reason,
            "validation_reason": hard_blocks[0] if not validation_flag else None,
        },
        {"auto_execution_threshold": auto_exec_threshold},
    )
    status_line = eligibility_sentence(composite, auto_exec_threshold, decision)
    structure_label = _protective_put_label(
        metrics.get("legs") or [],
        covered=bool(metrics.get("equity_covered_by_holdings")),
    )
    quote_not_current = any("quote not current" in note.lower() for note in hard_blocks)
    quote_as_of = None
    for leg in option_legs:
        source = _contract_for_leg(leg, chain_rows)
        quote_as_of = source.get("quote_as_of") or leg.get("quote_as_of") or quote_as_of
    from app.contracts import VolRegime

    scan_key = str(ticker or chain_analysis.get("symbol") or "scan")
    record_ledger(
        scan_id=scan_key,
        kind="value",
        key="vol_regime",
        value=VolRegime(
            ivMinusHvPts=regime_view.iv_minus_hv_pts,
            ivToHv=regime_view.iv_to_hv,
            ivRank=regime_view.iv_rank,
            verdict=regime_view.verdict,
            rule=regime_view.rule,
        ),
        inputs={
            "iv": regime_iv,
            "hv": vol_layer.get("hv"),
            "iv_rank": vol_layer.get("iv_rank"),
            "display": regime,
        },
        fn="build_strategy_layer",
    )
    if vega_note:
        record_ledger(
            scan_id=scan_key,
            kind="score",
            key="vega_regime",
            value=vega_note,
            inputs={"strategy": strategy_name, "regime": regime_view.short},
            fn="build_strategy_layer",
        )
    if event_note:
        record_ledger(
            scan_id=scan_key,
            kind="score",
            key="event_vega",
            value=event_note,
            inputs={"strategy": strategy_name},
            fn="build_strategy_layer",
        )
    if dte_note:
        record_ledger(
            scan_id=scan_key,
            kind="gate",
            key="dte_window",
            value=dte_note,
            inputs={"strategy": strategy_name},
            fn="build_strategy_layer",
        )
    if conflict_note:
        record_ledger(
            scan_id=scan_key,
            kind="score",
            key="sentiment_conflict",
            value=conflict_note,
            inputs={"direction": direction, "low_conviction": low_conviction},
            fn="build_strategy_layer",
        )
    fit = " ".join(why_parts)
    from app.analysis.gate_config import IV_RANK_CHEAP_BELOW, IV_RANK_RICH_ABOVE, gamma_front_back_iv_ratio_min

    sent_score = sentiment_layer.get("score_0_100") if isinstance(sentiment_layer, dict) else None
    margin = None
    if isinstance(sent_score, (int, float)) and not isinstance(sent_score, bool):
        margin = direction_margin(tech_score=float(tech_score), sentiment_score=float(sent_score))
    fund_score = fundamentals_layer.get("score") if isinstance(fundamentals_layer, dict) else None
    figures: dict[str, Any] = {
        "composite": float(composite),
        "technical": float(tech_score),
        "sentiment": float(sent_score) if isinstance(sent_score, (int, float)) and not isinstance(sent_score, bool) else None,
        "fundamentals": float(fund_score) if isinstance(fund_score, (int, float)) and not isinstance(fund_score, bool) else None,
        "iv": regime_iv if isinstance(regime_iv, (int, float)) and not isinstance(regime_iv, bool) else None,
        "hv": vol_layer.get("hv") if isinstance(vol_layer.get("hv"), (int, float)) else None,
        "iv_rank": regime_view.iv_rank,
        "iv_minus_hv_pts": regime_view.iv_minus_hv_pts,
        "iv_to_hv": regime_view.iv_to_hv,
        "threshold_auto_exec": float(auto_exec_threshold),
        "threshold_entry": float(entry_composite_min()),
        "threshold_exit": float(exit_composite_min()),
        "threshold_vol_band": float(IV_MISMATCH_VOL_POINTS),
        "threshold_iv_rank_cheap": float(IV_RANK_CHEAP_BELOW),
        "threshold_iv_rank_rich": float(IV_RANK_RICH_ABOVE),
        "threshold_inversion": float(gamma_front_back_iv_ratio_min()),
        "threshold_direction_margin": float(direction_margin_min()),
        "vega_penalty": float(LONG_VEGA_RICH_PENALTY),
        "direction_margin": margin,
        "technical_weighted_vote": (
            abs(float(tech_score)) * float(APEX_COMPOSITE_WEIGHTS["technicals"])
            if isinstance(sent_score, (int, float)) and not isinstance(sent_score, bool)
            else None
        ),
        "sentiment_weighted_vote": (
            abs((float(sent_score) - 50.0) * 2.0) * float(APEX_COMPOSITE_WEIGHTS["sentiment"])
            if isinstance(sent_score, (int, float)) and not isinstance(sent_score, bool)
            else None
        ),
        "event_vega_points": event_points,
        "weight_technical": float(APEX_COMPOSITE_WEIGHTS["technicals"]),
        "weight_sentiment": float(APEX_COMPOSITE_WEIGHTS["sentiment"]),
        "scale_low": 0,
        "scale_high": 100,
        "leg_count": len(option_legs),
        "threshold_theta_cap_pct": round(float(theta_max_pct_per_day()) * 100.0, 2),
        "threshold_rule1_theta": 0.05,
        "threshold_rule1_delta": 0.55,
        "threshold_delta_theta": 10,
        "symbol": str(ticker or chain_analysis.get("symbol") or ""),
    }
    calendar = fundamentals_layer.get("earnings_calendar") if isinstance(fundamentals_layer, dict) else None
    if isinstance(calendar, dict) and calendar.get("next_date"):
        figures["earnings_date"] = str(calendar.get("next_date"))[:10]
    window = dte_window_for(strategy_name)
    if window is not None:
        figures["threshold_dte_min"] = int(window[0])
        if window[1] is not None:
            figures["threshold_dte_max"] = int(window[1])
    selected_expiry = chain_analysis.get("expiry") or (option_legs[0].get("expiry") if option_legs else None)
    selected_dte = _dte_from_expiry(str(selected_expiry) if selected_expiry else None)
    if selected_dte is not None:
        figures["selected_dte"] = int(selected_dte)
    for index, leg in enumerate(option_legs):
        source = _contract_for_leg(leg, chain_rows)
        for field in ("strike", "bid", "ask", "delta", "iv", "theta", "mid", "quantity"):
            raw = source.get(field) if isinstance(source, dict) else None
            if raw is None:
                raw = leg.get(field)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                figures[f"leg{index}_{field}"] = float(raw)
        mid = leg.get("mid")
        theta = leg.get("theta")
        if (
            isinstance(mid, (int, float))
            and isinstance(theta, (int, float))
            and not isinstance(mid, bool)
            and not isinstance(theta, bool)
            and float(mid) > 0
        ):
            figures[f"leg{index}_theta_pct"] = round(abs(float(theta)) / float(mid) * 100.0, 2)
        theta_raw = figures.get(f"leg{index}_theta")
        delta_raw = figures.get(f"leg{index}_delta")
        if isinstance(theta_raw, float):
            figures[f"leg{index}_theta_abs"] = abs(theta_raw)
        if isinstance(theta_raw, float) and isinstance(delta_raw, float) and theta_raw != 0:
            figures[f"leg{index}_delta_over_theta"] = abs(delta_raw) / abs(theta_raw)
        expiry = leg.get("expiry") or (source.get("expiry") if isinstance(source, dict) else None)
        if expiry:
            figures[f"leg{index}_expiry"] = str(expiry)[:10]
        occ = leg.get("symbol") or (source.get("symbol") if isinstance(source, dict) else None)
        if isinstance(occ, str) and occ.strip():
            figures[f"leg{index}_symbol"] = occ.strip()
        spread = _leg_spread_pct(source) if isinstance(source, dict) else None
        if spread is not None:
            figures[f"leg{index}_spread"] = float(spread)
            bid, ask = source.get("bid"), source.get("ask")
            if (
                isinstance(bid, (int, float))
                and isinstance(ask, (int, float))
                and not isinstance(bid, bool)
                and not isinstance(ask, bool)
                and float(ask) >= float(bid)
            ):
                figures[f"leg{index}_slippage"] = round((float(ask) - float(bid)) / 2.0 * 100.0, 2)
    metric_queue: list[tuple[str, Any]] = [("metric", metrics)]
    while metric_queue and len(figures) < 400:
        prefix, node = metric_queue.pop()
        if isinstance(node, dict):
            for key, val in node.items():
                if key in {"legs", "validation_error"}:
                    continue
                metric_queue.append((f"{prefix}_{key}", val))
        elif isinstance(node, (list, tuple)):
            for offset, val in enumerate(node[:12]):
                metric_queue.append((f"{prefix}_{offset}", val))
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            figures[prefix] = float(node)
        elif isinstance(node, str) and re.fullmatch(r"[A-Z]{1,5}", node.strip()):
            figures[prefix] = node.strip()
    if strategy_name == "APEX Benchmark Greeks Strategy" or benchmark_rule:
        figures.update({"rule_ratio": 10, "rule_move_pct": 0.01, "rule_final_dte": 21})
    if benchmark_rule == "rule2":
        figures.update({"short_delta_cap": 0.20, "model_probability": 0.80, "profit_take": 0.50, "loss_multiple": 2})
    if strategy_name == "Gamma Trampoline™":
        figures.update({"gamma_days_min": 5, "gamma_days_max": 10})
    outlook = _outlook_for(strategy_name, direction)
    if low_conviction and margin is not None:
        outlook = (
            f"{outlook}, low conviction, direction margin {margin:.1f} "
            f"versus threshold {direction_margin_min():g}."
        )
    narrative = f"Recommended: {strategy_name}. {summary} {execution}"
    fit, execution, notes, summary, status_line, narrative = _guard_strategy_card(
        scan_id=scan_key,
        strategy_name=strategy_name,
        fit=fit,
        execution=execution,
        notes=notes,
        summary=summary,
        status_line=status_line,
        narrative=narrative,
        figures=figures,
        feed=vol_layer.get("feed") if isinstance(vol_layer, dict) else None,
        quote_as_of=quote_as_of,
    )
    outlook = _guard_card_text(outlook, scan_id=scan_key, strategy_name=strategy_name)
    return {
        "title": "Strategy playbook",
        "tradeable": checks_passed,
        "checks_passed": checks_passed,
        "execution_banner": None if checks_passed else NOT_EXECUTABLE,
        "execution_tier": tier,
        "selected_strategy": strategy_name,
        "structure_label": structure_label,
        "composite_score": composite,
        "clears_threshold": score_clears,
        "position_action": position_action,
        "auto_exec_blocked": auto_exec_blocked,
        "direction": direction,
        "vol_signal": vol_signal,
        "vol_regime": regime,
        "recommended_contract": recommended,
        "equity_required": bool(spec and spec.equity_required),
        "equity_overlay_only": False,
        "equity_note": metrics.get("equity_note"),
        "what_is_this": summary,
        "why_recommended": fit,
        "why_it_fits": fit,
        "outlook": outlook,
        "strategies_evaluated": strategies_evaluated,
        "selection_rationale": selection_rationale,
        "how_to_execute": execution,
        "risk_notes": notes,
        "auto_exec_line": status_line,
        "auto_execute_eligible": decision.eligible,
        "auto_exec_reasons": decision.reasons,
        "placeable": placeable,
        "hard_block_reasons": hard_blocks,
        "spread_block_reasons": spread_blocks,
        "block_reason": (hard_blocks or spread_blocks or [None])[0],
        "quote_not_current": quote_not_current,
        "quote_as_of": quote_as_of,
        "metrics": metrics,
        "validation_errors": validation_errors,
        "narrative": narrative,
    }
