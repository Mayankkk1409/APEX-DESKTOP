"""Universal strategy output validator — blocks trade card and execution on mismatch."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.analysis.score_bounds import assert_score_bounded
from app.strategies.chain_utils import net_debit_credit, normalize_leg_mids
from app.strategies.exceptions import StrategyValidationError
from app.strategies.payoffs import PAYOFF_FUNCTIONS
from app.strategies.registry import LEG_QUANTITY_BY_INDEX, StrategySpec, get_strategy_spec, resolve_strategy_id

logger = logging.getLogger(__name__)

_OCC_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")

_CREDIT_TOLERANCE_PER_SHARE = 0.01
_CONTRACT_MULTIPLIER_DEFAULT = 100

# Strategy families where same-side same-expiry premium must decrease away from spot.
_MONOTONIC_PAYOFF_REFS = frozenset(
    {
        "payoff_vertical_debit",
        "payoff_vertical_credit",
        "payoff_iron_condor",
        "payoff_long_iron_condor",
        "payoff_butterfly",
        "payoff_short_butterfly",
        "payoff_iron_butterfly",
        "payoff_long_iron_butterfly",
        "payoff_condor_spread",
        "payoff_broken_wing_butterfly",
    }
)


@dataclass
class ValidationResult:
    valid: bool
    strategy_id: str | None = None
    ticker: str = ""
    errors: list[StrategyValidationError] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if not self.valid and self.errors:
            raise self.errors[0]


def _err(
    *,
    strategy_id: str,
    ticker: str,
    check: str,
    expected: str,
    actual: str,
) -> StrategyValidationError:
    exc = StrategyValidationError(strategy_id=strategy_id, ticker=ticker, check=check, expected=expected, actual=actual)
    logger.error("strategy_validation_failed", extra=exc.to_log_dict())
    return exc


def _parse_occ_symbol(symbol: str) -> dict[str, Any] | None:
    sym = symbol.upper().strip()
    m = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", sym)
    if not m:
        return None
    root, yymmdd, cp, strike_raw = m.groups()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy
    expiry = f"{year:04d}-{mm:02d}-{dd:02d}"
    strike = int(strike_raw) / 1000.0
    return {"root": root, "expiry": expiry, "side": "call" if cp == "C" else "put", "strike": strike}


def _check_expiration_relationships(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    expiries = [leg.get("expiry") for leg in legs if leg.get("expiry")]
    if not expiries:
        return
    needs_two = any(ls.expiration_relationship == "two_distinct" for ls in spec.leg_specs)
    if needs_two and len(set(expiries)) < 2:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="expiration_relationship",
                expected="two distinct expirations",
                actual=str(expiries),
            )
        )
    same_exp = any(ls.expiration_relationship == "same" for ls in spec.leg_specs)
    if same_exp and len(set(expiries)) > 1 and not needs_two:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="expiration_relationship",
                expected="same expiration on all legs",
                actual=str(sorted(set(expiries))),
            )
        )


def _check_strike_relationships(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    if spec.leg_specs and all(ls.strike_relationship == "same" for ls in spec.leg_specs if ls.option_type != "stock"):
        strikes = [leg.get("strike") for leg in legs if leg.get("strike") is not None]
        if strikes and len({round(float(s), 4) for s in strikes}) > 1:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="strike_relationship",
                    expected="same strike across calendar legs",
                    actual=str(strikes),
                )
            )


def _check_occ_consistency(
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    for leg in legs:
        if leg.get("side") == "stock":
            if not leg.get("symbol"):
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check="stock_symbol",
                        expected="ticker symbol on stock leg",
                        actual="missing symbol",
                    )
                )
            continue
        occ = leg.get("symbol")
        if not occ:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="occ_symbol",
                    expected="OCC symbol on every leg",
                    actual="missing symbol",
                )
            )
            continue
        if not _OCC_RE.match(str(occ).upper()):
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="occ_symbol",
                    expected="valid OCC format",
                    actual=str(occ),
                )
            )
            continue
        parsed = _parse_occ_symbol(str(occ))
        if not parsed:
            continue
        leg_strike = leg.get("strike")
        leg_side = leg.get("side")
        leg_expiry = leg.get("expiry")
        if leg_strike is not None and abs(float(leg_strike) - parsed["strike"]) > 0.02:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="occ_strike_match",
                    expected=str(parsed["strike"]),
                    actual=str(leg_strike),
                )
            )
        if leg_side and leg_side != parsed["side"]:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="occ_side_match",
                    expected=parsed["side"],
                    actual=str(leg_side),
                )
            )
        if leg_expiry and leg_expiry != parsed["expiry"]:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="occ_expiry_match",
                    expected=parsed["expiry"],
                    actual=str(leg_expiry),
                )
            )


def _check_equity_policy(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    stock_legs = [leg for leg in legs if leg.get("side") == "stock"]
    option_legs = [leg for leg in legs if leg.get("side") in {"call", "put"}]

    if spec.equity_required:
        overlay_only = spec.equity_leg_spec is not None and spec.equity_leg_spec.entry_mode == "pre_existing"
        expected_options = spec.leg_count if overlay_only else max(spec.leg_count - len(stock_legs), 0)
        if overlay_only:
            if not option_legs:
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check="equity_overlay_options",
                        expected="at least one options leg for overlay strategy",
                        actual=str(len(option_legs)),
                    )
                )
        elif not stock_legs:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="equity_leg_required",
                    expected="stock leg in payload for equity-required strategy",
                    actual="missing stock leg",
                )
            )
        elif len(stock_legs) != 1:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="equity_leg_count",
                    expected="exactly one stock leg",
                    actual=str(len(stock_legs)),
                )
            )
        if not overlay_only and stock_legs and len(option_legs) < expected_options:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="equity_options_pair",
                    expected=f"{expected_options} option leg(s) paired with stock",
                    actual=str(len(option_legs)),
                )
            )
    elif stock_legs:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="equity_forbidden",
                expected="options-only payload (no stock legs)",
                actual=f"{len(stock_legs)} stock leg(s) present",
            )
        )


def _check_anchor_leg_consistency(
    recommended: dict[str, Any] | None,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    """Anchor leg (recommended contract) must match the primary order leg on strike/exp/side."""
    if not recommended:
        return
    option_legs = [leg for leg in legs if leg.get("side") in {"call", "put"}]
    if not option_legs:
        return
    rec_side = recommended.get("side")
    primary = next((leg for leg in option_legs if leg.get("side") == rec_side), option_legs[0])
    rec_strike = recommended.get("strike")
    if rec_strike is not None and primary.get("strike") is not None:
        if abs(float(rec_strike) - float(primary["strike"])) > 0.02:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="anchor_strike_match",
                    expected=str(rec_strike),
                    actual=str(primary.get("strike")),
                )
            )
    rec_exp = recommended.get("expiry")
    leg_exp = primary.get("expiry")
    if rec_exp and leg_exp and rec_exp != leg_exp:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="anchor_expiry_match",
                expected=str(rec_exp),
                actual=str(leg_exp),
            )
        )
    if rec_side and primary.get("side") and rec_side != primary.get("side"):
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="anchor_side_match",
                expected=str(rec_side),
                actual=str(primary.get("side")),
            )
        )


def _check_order_ticket_consistency(
    legs: list[dict[str, Any]],
    order_legs: list[dict[str, Any]] | None,
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    """Every metrics leg must match the order ticket when order legs are supplied."""
    if not order_legs:
        return
    metrics_opts = [leg for leg in legs if leg.get("side") in {"call", "put"}]
    for idx, metric_leg in enumerate(metrics_opts):
        if idx >= len(order_legs):
            break
        ticket = order_legs[idx]
        for field, m_key, t_key in (
            ("strike", "strike", "strike"),
            ("expiry", "expiry", "expiry"),
            ("side", "side", "option_side"),
        ):
            mv = metric_leg.get(m_key)
            tv = ticket.get(t_key) or ticket.get(m_key)
            if mv is None or tv is None:
                continue
            if field == "strike" and abs(float(mv) - float(tv)) > 0.02:
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check="order_strike_match",
                        expected=str(mv),
                        actual=str(tv),
                    )
                )
            elif field != "strike" and str(mv) != str(tv):
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check=f"order_{field}_match",
                        expected=str(mv),
                        actual=str(tv),
                    )
                )
        occ = str(metric_leg.get("symbol") or "").upper()
        ticket_occ = str(ticket.get("symbol") or "").upper()
        if occ and ticket_occ and occ != ticket_occ:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="order_occ_match",
                    expected=occ,
                    actual=ticket_occ,
                )
            )


def _check_score_bounds(
    scores: dict[str, float | int | None] | None,
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    if not scores:
        return
    for name, value in scores.items():
        if value is None:
            continue
        try:
            assert_score_bounded(name, value)
        except ValueError as exc:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="score_bounds",
                    expected="0–100",
                    actual=str(exc),
                )
            )


def _check_payoff_shape(
    spec: StrategySpec,
    metrics: dict[str, Any],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    max_profit = metrics.get("max_profit")
    max_loss = metrics.get("max_loss")
    breakevens = metrics.get("breakevens") or []

    if spec.max_profit_type == "finite" and max_profit is None and not metrics.get("payoff_depends_on_remaining_leg"):
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="max_profit_finite",
                expected="finite max_profit",
                actual="null",
            )
        )
    if spec.max_profit_type in {"finite", "variable_iv"} and max_profit == "Unlimited":
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="max_profit_not_unlimited",
                expected="bounded numeric max_profit",
                actual=str(max_profit),
            )
        )

    if spec.risk_type == "defined" and spec.max_loss_type == "finite" and max_loss is None:
        if not metrics.get("max_loss_unlimited_allowed"):
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="max_loss_finite",
                    expected="finite max_loss for defined-risk",
                    actual="null",
                )
            )

    if spec.max_loss_type == "unlimited" and max_loss is not None and not metrics.get("max_loss_unlimited_allowed"):
        pass  # numeric bound from scan is acceptable advisory

    if spec.max_profit_type == "unlimited" and max_profit is not None and not metrics.get("max_profit_unlimited_allowed"):
        pass  # numeric bound acceptable

    # Calendars and diagonals publish no closed-form breakeven. An empty scan is not a missing contract.
    if metrics.get("payoff_depends_on_remaining_leg"):
        return

    be_clean = [b for b in breakevens if b is not None and isinstance(b, (int, float))]
    if spec.breakeven_type == "none" and be_clean:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="breakeven_shape",
                expected="no breakevens",
                actual=str(be_clean),
            )
        )
    elif spec.breakeven_type == "single" and len(be_clean) != 1:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="breakeven_shape",
                expected="exactly one breakeven",
                actual=str(be_clean),
            )
        )
    elif spec.breakeven_type == "dual" and len(be_clean) != 2:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="breakeven_shape",
                expected="two breakevens",
                actual=str(be_clean),
            )
        )
    elif spec.breakeven_type == "range" and len(be_clean) < 2:
        # Front-expiry calendars publish the scan's zero crossings. Fewer than two means the
        # grid does not cross zero inside ±40% of spot. That is a model result, not a missing leg.
        if not metrics.get("max_profit_iv_assumption_dependent"):
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="breakeven_shape",
                    expected="breakeven range (lower and upper)",
                    actual=str(be_clean),
                )
            )


def _check_credit_consistency(
    spec: StrategySpec,
    metrics: dict[str, Any],
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
) -> None:
    """Recompute net credit/debit from leg mids; summary must match within $0.01/share."""
    if not legs or spec.payoff_function_ref is None:
        return
    if any(leg.get("side") == "stock" for leg in legs):
        return
    if spec.payoff_function_ref not in {
        "payoff_vertical_credit",
        "payoff_iron_condor",
        "payoff_short_butterfly",
        "payoff_iron_butterfly",
        "payoff_jade_lizard",
        "payoff_vertical_debit",
        "payoff_butterfly",
        "payoff_condor_spread",
        "payoff_long_iron_condor",
        "payoff_long_iron_butterfly",
    }:
        return
    option_legs = [leg for leg in normalize_leg_mids(list(legs)) if leg.get("side") in {"call", "put"}]
    if not option_legs:
        return

    net, net_type = net_debit_credit(option_legs)
    per_share = abs(net)
    displayed = metrics.get("net_debit_credit")
    mult = int(metrics.get("per_contract_multiplier") or _CONTRACT_MULTIPLIER_DEFAULT)
    max_profit = metrics.get("max_profit")
    max_loss = metrics.get("max_loss")
    breakevens = metrics.get("breakevens") or []

    if displayed is not None and abs(float(displayed) - per_share) > _CREDIT_TOLERANCE_PER_SHARE:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="credit_recomputation",
                expected=f"net {per_share:.4f}/share from leg mids",
                actual=f"summary net_debit_credit={displayed}",
            )
        )

    if net_type == "credit" and spec.payoff_function_ref in {
        "payoff_vertical_credit",
        "payoff_iron_condor",
        "payoff_short_butterfly",
        "payoff_iron_butterfly",
        "payoff_jade_lizard",
    }:
        expected_profit = round(per_share * mult, 2)
        if isinstance(max_profit, (int, float)) and abs(float(max_profit) - expected_profit) > mult * _CREDIT_TOLERANCE_PER_SHARE:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="max_profit_credit_match",
                    expected=str(expected_profit),
                    actual=str(max_profit),
                )
            )

    if spec.payoff_function_ref == "payoff_iron_condor" and len(option_legs) >= 4:
        puts = sorted(
            [leg for leg in option_legs if leg.get("side") == "put" and leg.get("strike") is not None],
            key=lambda leg: float(leg["strike"]),
        )
        calls = sorted(
            [leg for leg in option_legs if leg.get("side") == "call" and leg.get("strike") is not None],
            key=lambda leg: float(leg["strike"]),
        )
        if len(puts) >= 2 and len(calls) >= 2:
            put_width = float(puts[-1]["strike"]) - float(puts[0]["strike"])
            call_width = float(calls[-1]["strike"]) - float(calls[0]["strike"])
            wing = max(put_width, call_width)
            credit = per_share if net_type == "credit" else 0.0
            if net_type == "credit" and isinstance(max_loss, (int, float)):
                expected_loss = round((wing - credit) * mult, 2)
                if abs(float(max_loss) - expected_loss) > mult * _CREDIT_TOLERANCE_PER_SHARE:
                    errors.append(
                        _err(
                            strategy_id=strategy_id,
                            ticker=ticker,
                            check="max_loss_credit_match",
                            expected=str(expected_loss),
                            actual=str(max_loss),
                        )
                    )
            if net_type == "credit" and len(breakevens) >= 2:
                short_put = float(puts[-1]["strike"])
                short_call = float(calls[0]["strike"])
                expected_be = [round(short_put - credit, 2), round(short_call + credit, 2)]
                be_clean = [round(float(b), 2) for b in breakevens if isinstance(b, (int, float))]
                if be_clean and (
                    abs(be_clean[0] - expected_be[0]) > _CREDIT_TOLERANCE_PER_SHARE
                    or abs(be_clean[-1] - expected_be[-1]) > _CREDIT_TOLERANCE_PER_SHARE
                ):
                    errors.append(
                        _err(
                            strategy_id=strategy_id,
                            ticker=ticker,
                            check="breakeven_credit_match",
                            expected=str(expected_be),
                            actual=str(be_clean),
                        )
                    )


def _estimate_spot_from_legs(legs: list[dict[str, Any]]) -> float | None:
    strikes = sorted(float(leg["strike"]) for leg in legs if leg.get("strike") is not None)
    if not strikes:
        return None
    return (strikes[0] + strikes[-1]) / 2.0


def _check_moneyness_monotonicity(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
    spot: float | None = None,
) -> None:
    """Same side + same expiry: premium must decrease as strike moves away from spot."""
    if spec.payoff_function_ref not in _MONOTONIC_PAYOFF_REFS:
        return

    spot_ref = spot if spot is not None else _estimate_spot_from_legs(legs)

    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for leg in legs:
        if leg.get("side") not in {"call", "put"} or leg.get("mid") is None:
            continue
        expiry = str(leg.get("expiry") or "")
        by_group.setdefault((str(leg["side"]), expiry), []).append(leg)

    for (side, expiry), group in by_group.items():
        if len(group) < 2 or spot_ref is None:
            continue
        ordered = sorted(group, key=lambda leg: abs(float(leg["strike"]) - spot_ref))
        for idx in range(len(ordered) - 1):
            closer = ordered[idx]
            further = ordered[idx + 1]
            closer_mid = float(closer["mid"])
            further_mid = float(further["mid"])
            if closer_mid + 0.001 < further_mid:
                raw = [
                    {
                        "action": leg.get("action"),
                        "side": leg.get("side"),
                        "strike": leg.get("strike"),
                        "mid": leg.get("mid"),
                        "bid": leg.get("bid"),
                        "ask": leg.get("ask"),
                        "symbol": leg.get("symbol"),
                        "expiry": leg.get("expiry"),
                    }
                    for leg in group
                ]
                logger.error(
                    "strategy_validation_moneyness_inverted",
                    extra={
                        "strategy_id": strategy_id,
                        "ticker": ticker,
                        "side": side,
                        "expiry": expiry,
                        "closer_strike": closer.get("strike"),
                        "closer_mid": closer_mid,
                        "further_strike": further.get("strike"),
                        "further_mid": further_mid,
                        "raw_quotes": raw,
                    },
                )
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check="moneyness_monotonicity",
                        expected=f"{side} {closer.get('strike')} premium >= {further.get('strike')}",
                        actual=f"{closer_mid:.4f} < {further_mid:.4f} (exp {expiry})",
                    )
                )
                break


def _leg_number(leg: dict[str, Any], key: str) -> float | None:
    raw = leg.get(key)
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return round(float(raw), 4)
    except (TypeError, ValueError):
        return None


def apex_structure_reason(
    legs: list[dict[str, Any]],
    *,
    spot: float | None = None,
    missing: list[str] | None = None,
) -> str | None:
    """Full Document §10 four-leg template. A partial list is not an APEX Strategy."""
    if missing:
        return "APEX Strategy requires all four legs. Missing: " + ", ".join(missing) + "."
    opts = [leg for leg in legs if leg.get("side") in {"call", "put"}]
    if len(opts) != 4:
        return (
            "APEX Strategy requires all four legs: buy the back-week call, buy the back-week put, "
            "sell the front-week call, and sell the front-week put."
        )
    wanted = {("buy", "call"), ("buy", "put"), ("sell", "call"), ("sell", "put")}
    found = {(str(leg.get("action") or "").lower(), str(leg.get("side") or "")) for leg in opts}
    if found != wanted:
        return (
            "APEX Strategy requires buy call, buy put, sell call, and sell put. "
            f"Built actions were {sorted(found)}."
        )
    if any(int(leg.get("quantity") or 1) != 1 for leg in opts):
        return "APEX Strategy quantity is 1 on each of the four legs."

    def _one(action: str, side: str) -> dict[str, Any]:
        return next(leg for leg in opts if leg.get("action") == action and leg.get("side") == side)

    buy_call, buy_put = _one("buy", "call"), _one("buy", "put")
    sell_call, sell_put = _one("sell", "call"), _one("sell", "put")
    call_strike = _leg_number(buy_call, "strike")
    put_strike = _leg_number(buy_put, "strike")
    if call_strike is None or put_strike is None:
        return "APEX Strategy requires a call strike and a put strike."
    if _leg_number(sell_call, "strike") != call_strike or _leg_number(sell_put, "strike") != put_strike:
        return "APEX Strategy uses the same call strike and the same put strike on both expirations."
    if call_strike <= put_strike:
        return "APEX Strategy uses Strike A above Strike B."
    buy_expiry = str(buy_call.get("expiry") or "")
    sell_expiry = str(sell_call.get("expiry") or "")
    if not buy_expiry or not sell_expiry or buy_expiry == sell_expiry:
        return "APEX Strategy requires a front-week expiration and a later back-week expiration."
    if str(buy_put.get("expiry") or "") != buy_expiry or str(sell_put.get("expiry") or "") != sell_expiry:
        return "APEX Strategy keeps the call and the put on the same expiration within each week."
    if sell_expiry > buy_expiry:
        return "APEX Strategy sells the front week and buys the back week."
    if spot is not None and not (call_strike > float(spot) > put_strike):
        return "APEX Strategy uses a call strike above the spot and a put strike below the spot."
    return None


def _check_leg_template(
    spec: StrategySpec,
    legs: list[dict[str, Any]],
    errors: list[StrategyValidationError],
    *,
    strategy_id: str,
    ticker: str,
    spot: float | None = None,
) -> None:
    """Block a recommendation whose legs do not match the registry template."""
    if strategy_id == "vega_neutral_spread":
        expected_pairs = [(ls.side, ls.option_type) for ls in spec.leg_specs]
        actual_pairs = [
            (
                str(leg.get("action") or "").lower(),
                "stock" if leg.get("side") == "stock" else str(leg.get("side") or ""),
            )
            for leg in legs
        ]
        if sorted(expected_pairs) != sorted(actual_pairs):
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="leg_template",
                    expected=str(expected_pairs),
                    actual=str(actual_pairs),
                )
            )
        return

    qty_overrides = LEG_QUANTITY_BY_INDEX.get(strategy_id, {})
    expected_options: list[tuple[str, str, int]] = []
    expected_stock: list[str] = []
    for index, leg_spec in enumerate(spec.leg_specs):
        if leg_spec.option_type == "stock":
            expected_stock.append(leg_spec.side)
            continue
        expected_options.append((leg_spec.side, leg_spec.option_type, qty_overrides.get(index, 1)))
    actual_options: list[tuple[str, str, int]] = []
    actual_stock: list[str] = []
    for leg in legs:
        action = str(leg.get("action") or "").lower()
        if leg.get("side") == "stock":
            actual_stock.append(action)
            try:
                shares = int(leg.get("quantity") or 0)
            except (TypeError, ValueError):
                shares = 0
            if shares <= 0:
                errors.append(
                    _err(
                        strategy_id=strategy_id,
                        ticker=ticker,
                        check="leg_ratio",
                        expected="positive share quantity",
                        actual=str(leg.get("quantity")),
                    )
                )
            continue
        try:
            qty = int(leg.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 0
        actual_options.append((action, str(leg.get("side") or ""), qty))
    if sorted(expected_stock) != sorted(actual_stock) or sorted(
        (action, side) for action, side, _qty in expected_options
    ) != sorted((action, side) for action, side, _qty in actual_options):
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="leg_template",
                expected=str(expected_stock + [(a, s) for a, s, _q in expected_options]),
                actual=str(actual_stock + [(a, s) for a, s, _q in actual_options]),
            )
        )
    elif sorted(expected_options) != sorted(actual_options):
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="leg_ratio",
                expected=str(expected_options),
                actual=str(actual_options),
            )
        )
    if strategy_id == "apex_strategy":
        reason = apex_structure_reason(legs, spot=spot)
        if reason:
            errors.append(
                _err(
                    strategy_id=strategy_id,
                    ticker=ticker,
                    check="apex_structure",
                    expected="four-leg APEX Strategy template",
                    actual=reason,
                )
            )


def _wheel_stage(legs: list[dict[str, Any]]) -> str | None:
    """Opening stage is a cash-secured short put. Covered call only when stock is already in the legs."""
    stock = [leg for leg in legs if leg.get("side") == "stock"]
    opts = [leg for leg in legs if leg.get("side") in {"call", "put"}]
    if not stock and len(opts) == 1 and opts[0].get("action") == "sell" and opts[0].get("side") == "put":
        return "cash_secured_put"
    if (
        len(stock) == 1
        and stock[0].get("action") == "buy"
        and len(opts) == 1
        and opts[0].get("action") == "sell"
        and opts[0].get("side") == "call"
    ):
        return "covered_call"
    return None


def validate_strategy_output(
    strategy_name: str,
    metrics: dict[str, Any],
    ticker: str,
    *,
    strict_payoff: bool = True,
    recommended_contract: dict[str, Any] | None = None,
    order_legs: list[dict[str, Any]] | None = None,
    scan_scores: dict[str, float | int | None] | None = None,
    spot: float | None = None,
) -> ValidationResult:
    """Validate leg structure and payoff metrics against the strategy registry."""
    errors: list[StrategyValidationError] = []
    strategy_id = resolve_strategy_id(strategy_name)
    if not strategy_id:
        errors.append(
            _err(
                strategy_id=strategy_name,
                ticker=ticker,
                check="strategy_registry",
                expected="known strategy_id",
                actual=strategy_name,
            )
        )
        return ValidationResult(valid=False, strategy_id=strategy_id, ticker=ticker, errors=errors)

    spec = get_strategy_spec(strategy_id)
    if spec is None:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="strategy_registry",
                expected="registry entry",
                actual="missing",
            )
        )
        return ValidationResult(valid=False, strategy_id=strategy_id, ticker=ticker, errors=errors)

    if not spec.tradeable or spec.leg_count == 0:
        return ValidationResult(valid=True, strategy_id=strategy_id, ticker=ticker, errors=[])

    if strict_payoff and spec.payoff_function_ref is None:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="payoff_function_ref",
                expected="implemented payoff handler",
                actual="None",
            )
        )

    if strict_payoff and spec.payoff_function_ref and spec.payoff_function_ref not in PAYOFF_FUNCTIONS:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="payoff_function_ref",
                expected=f"registered handler {spec.payoff_function_ref}",
                actual="missing from PAYOFF_FUNCTIONS",
            )
        )

    legs = metrics.get("legs") or []
    wheel_stage = _wheel_stage(legs) if strategy_id == "wheel_strategy" else None
    if wheel_stage == "covered_call":
        # Shares are already held, so this stage is stock plus a short call.
        pass
    elif len(legs) != spec.leg_count:
        errors.append(
            _err(
                strategy_id=strategy_id,
                ticker=ticker,
                check="leg_count",
                expected=str(spec.leg_count),
                actual=str(len(legs)),
            )
        )

    if wheel_stage != "covered_call":
        _check_equity_policy(spec, legs, errors, strategy_id=strategy_id, ticker=ticker)
        _check_leg_template(spec, legs, errors, strategy_id=strategy_id, ticker=ticker, spot=spot)
    _check_expiration_relationships(spec, legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_strike_relationships(spec, legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_occ_consistency(legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_anchor_leg_consistency(recommended_contract, legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_order_ticket_consistency(legs, order_legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_score_bounds(scan_scores, errors, strategy_id=strategy_id, ticker=ticker)
    _check_moneyness_monotonicity(spec, legs, errors, strategy_id=strategy_id, ticker=ticker, spot=spot)
    _check_credit_consistency(spec, metrics, legs, errors, strategy_id=strategy_id, ticker=ticker)
    _check_payoff_shape(spec, metrics, errors, strategy_id=strategy_id, ticker=ticker)

    return ValidationResult(valid=len(errors) == 0, strategy_id=strategy_id, ticker=ticker, errors=errors)


def assert_strategy_handler(strategy_name: str, handler_strategy_id: str) -> None:
    """Entry assertion: handler strategy_id must match requested strategy."""
    expected = resolve_strategy_id(strategy_name)
    if expected != handler_strategy_id:
        raise StrategyValidationError(
            strategy_id=handler_strategy_id,
            ticker="—",
            check="handler_strategy_id",
            expected=str(expected),
            actual=handler_strategy_id,
        )


def validate_or_raise(
    strategy_name: str,
    metrics: dict[str, Any],
    ticker: str,
    **kwargs: Any,
) -> ValidationResult:
    result = validate_strategy_output(strategy_name, metrics, ticker, **kwargs)
    result.raise_if_invalid()
    return result
