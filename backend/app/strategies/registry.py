"""Canonical registry of all 100 APEX encyclopedia strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

RiskType = Literal["defined", "undefined", "advisory"]
MaxProfitType = Literal["finite", "unlimited", "variable_iv"]
MaxLossType = Literal["finite", "unlimited", "variable"]
BreakevenType = Literal["none", "single", "range", "dual"]
ExpirationRel = Literal[
    "single",
    "same",
    "two_distinct",
    "multi",
    "stock_plus_option",
    "n_a",
]
StrikeRel = Literal[
    "same",
    "different",
    "otm_pair",
    "atm",
    "wide_otm",
    "mixed",
    "n_a",
]
EquityEntryMode = Literal["simultaneous", "pre_existing"]


@dataclass(frozen=True)
class EquityLegSpec:
    side: Literal["buy", "sell"]
    shares_per_contract: int = 100
    entry_mode: EquityEntryMode = "simultaneous"


@dataclass(frozen=True)
class LegSpec:
    side: Literal["buy", "sell"]
    option_type: Literal["call", "put", "stock"]
    strike_relationship: StrikeRel
    expiration_relationship: ExpirationRel


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    display_name: str
    family: int
    leg_count: int
    leg_specs: tuple[LegSpec, ...]
    risk_type: RiskType
    max_profit_type: MaxProfitType
    max_loss_type: MaxLossType
    breakeven_type: BreakevenType
    payoff_function_ref: str | None
    tradeable: bool = True
    equity_required: bool = False
    equity_leg_spec: EquityLegSpec | None = None


def _equity(
    side: Literal["buy", "sell"],
    *,
    entry_mode: EquityEntryMode = "simultaneous",
    shares: int = 100,
) -> EquityLegSpec:
    return EquityLegSpec(side=side, shares_per_contract=shares, entry_mode=entry_mode)


def _leg(
    side: Literal["buy", "sell"],
    option_type: Literal["call", "put", "stock"],
    strike_rel: StrikeRel,
    exp_rel: ExpirationRel,
) -> LegSpec:
    return LegSpec(side, option_type, strike_rel, exp_rel)


def _spec(
    strategy_id: str,
    display_name: str,
    family: int,
    legs: tuple[LegSpec, ...],
    *,
    risk_type: RiskType = "defined",
    max_profit_type: MaxProfitType = "finite",
    max_loss_type: MaxLossType = "finite",
    breakeven_type: BreakevenType = "single",
    payoff_function_ref: str | None = None,
    tradeable: bool = True,
    equity_required: bool = False,
    equity_leg_spec: EquityLegSpec | None = None,
) -> StrategySpec:
    return StrategySpec(
        strategy_id=strategy_id,
        display_name=display_name,
        family=family,
        leg_count=len(legs),
        leg_specs=legs,
        risk_type=risk_type,
        max_profit_type=max_profit_type,
        max_loss_type=max_loss_type,
        breakeven_type=breakeven_type,
        payoff_function_ref=payoff_function_ref,
        tradeable=tradeable,
        equity_required=equity_required,
        equity_leg_spec=equity_leg_spec,
    )


# --- Family 1: Directional single-leg (10) ---
_F1: list[StrategySpec] = [
    _spec("long_call", "Long Call", 1, (_leg("buy", "call", "atm", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
    _spec("long_put", "Long Put", 1, (_leg("buy", "put", "atm", "single"),), max_profit_type="finite", payoff_function_ref="payoff_long_option"),
    _spec("naked_call", "Naked Call", 1, (_leg("sell", "call", "otm_pair", "single"),), risk_type="undefined", max_loss_type="unlimited", max_profit_type="finite", tradeable=False, payoff_function_ref="payoff_short_option"),
    _spec("naked_put", "Naked Put", 1, (_leg("sell", "put", "otm_pair", "single"),), risk_type="undefined", max_loss_type="unlimited", max_profit_type="finite", tradeable=False, payoff_function_ref="payoff_short_option"),
    _spec("apex_benchmark_greeks_strategy", "APEX Benchmark Greeks Strategy", 1, (_leg("buy", "call", "atm", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
    _spec("long_call_leaps", "Long Call LEAPS", 1, (_leg("buy", "call", "atm", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
    _spec("long_put_leaps", "Long Put LEAPS", 1, (_leg("buy", "put", "atm", "single"),), max_profit_type="finite", payoff_function_ref="payoff_long_option"),
    _spec("deep_itm_call", "Deep ITM Call", 1, (_leg("buy", "call", "atm", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
    _spec("deep_itm_put", "Deep ITM Put", 1, (_leg("buy", "put", "atm", "single"),), max_profit_type="finite", payoff_function_ref="payoff_long_option"),
    _spec("atm_call", "At-The-Money Call", 1, (_leg("buy", "call", "same", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
]

# --- Family 2: Vertical spreads (10) ---
_F2: list[StrategySpec] = [
    _spec("bull_call_spread", "Bull Call Spread", 2, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("bear_put_spread", "Bear Put Spread", 2, (_leg("buy", "put", "atm", "same"), _leg("sell", "put", "different", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("bull_put_spread_credit", "Bull Put Spread (credit)", 2, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same")), payoff_function_ref="payoff_vertical_credit"),
    _spec("bear_call_spread_credit", "Bear Call Spread (credit)", 2, (_leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), payoff_function_ref="payoff_vertical_credit"),
    _spec("call_debit_spread", "Call Debit Spread", 2, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("put_debit_spread", "Put Debit Spread", 2, (_leg("buy", "put", "atm", "same"), _leg("sell", "put", "different", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("call_credit_spread", "Call Credit Spread", 2, (_leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), payoff_function_ref="payoff_vertical_credit"),
    _spec("put_credit_spread", "Put Credit Spread", 2, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same")), payoff_function_ref="payoff_vertical_credit"),
    _spec("wide_bull_call_spread", "Wide Bull Call Spread", 2, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "wide_otm", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("wide_bear_put_spread", "Wide Bear Put Spread", 2, (_leg("buy", "put", "atm", "same"), _leg("sell", "put", "wide_otm", "same")), payoff_function_ref="payoff_vertical_debit"),
]

# --- Family 3: Straddles & strangles (10) ---
_F3: list[StrategySpec] = [
    _spec("long_straddle", "Long Straddle", 3, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
    _spec("long_strangle", "Long Strangle", 3, (_leg("buy", "call", "different", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_strangle"),
    _spec("short_straddle", "Short Straddle", 3, (_leg("sell", "call", "same", "same"), _leg("sell", "put", "same", "same")), risk_type="undefined", max_loss_type="unlimited", breakeven_type="dual", tradeable=False, payoff_function_ref="payoff_short_straddle"),
    _spec("short_strangle", "Short Strangle", 3, (_leg("sell", "call", "different", "same"), _leg("sell", "put", "different", "same")), risk_type="undefined", max_loss_type="unlimited", breakeven_type="dual", tradeable=False, payoff_function_ref="payoff_short_strangle"),
    _spec("long_guts", "Long Guts", 3, (_leg("buy", "call", "different", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_guts"),
    _spec("short_guts", "Short Guts", 3, (_leg("sell", "call", "different", "same"), _leg("sell", "put", "different", "same")), risk_type="undefined", max_loss_type="unlimited", breakeven_type="dual", payoff_function_ref="payoff_short_straddle"),
    _spec("strip", "Strip", 3, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_strip"),
    _spec("strap", "Strap", 3, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_strap"),
    _spec("long_straddle_leaps", "Long Straddle LEAPS", 3, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
    _spec("short_iron_butterfly_variant", "Short Iron Butterfly (variant)", 3, (_leg("sell", "call", "same", "same"), _leg("sell", "put", "same", "same"), _leg("buy", "call", "different", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_butterfly"),
]

# --- Family 4: Calendars & diagonals (10) — priority ---
_F4: list[StrategySpec] = [
    _spec(
        "calendar_spread",
        "Calendar Spread",
        4,
        (_leg("sell", "call", "same", "two_distinct"), _leg("buy", "call", "same", "two_distinct")),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_calendar_spread",
    ),
    _spec(
        "calendar_put_spread",
        "Calendar Put Spread",
        4,
        (_leg("sell", "put", "same", "two_distinct"), _leg("buy", "put", "same", "two_distinct")),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_calendar_spread",
    ),
    _spec(
        "calendar_call_spread",
        "Calendar Call Spread",
        4,
        (_leg("sell", "call", "same", "two_distinct"), _leg("buy", "call", "same", "two_distinct")),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_calendar_spread",
    ),
    _spec(
        "double_calendar",
        "Double Calendar",
        4,
        (
            _leg("sell", "call", "same", "two_distinct"),
            _leg("buy", "call", "same", "two_distinct"),
            _leg("sell", "put", "same", "two_distinct"),
            _leg("buy", "put", "same", "two_distinct"),
        ),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_double_calendar",
    ),
    _spec(
        "diagonal_spread_bullish",
        "Diagonal Spread (bullish)",
        4,
        (_leg("buy", "call", "atm", "two_distinct"), _leg("sell", "call", "different", "two_distinct")),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_calendar_spread",
    ),
    _spec(
        "diagonal_spread_bearish",
        "Diagonal Spread (bearish)",
        4,
        (_leg("buy", "put", "atm", "two_distinct"), _leg("sell", "put", "different", "two_distinct")),
        max_profit_type="variable_iv",
        breakeven_type="range",
        payoff_function_ref="payoff_calendar_spread",
    ),
    _spec("double_diagonal", "Double Diagonal", 4, (_leg("buy", "call", "atm", "two_distinct"), _leg("sell", "call", "different", "two_distinct"), _leg("buy", "put", "atm", "two_distinct"), _leg("sell", "put", "different", "two_distinct")), max_profit_type="variable_iv", breakeven_type="range", payoff_function_ref="payoff_double_calendar"),
    _spec("reverse_calendar", "Reverse Calendar", 4, (_leg("buy", "call", "same", "two_distinct"), _leg("sell", "call", "same", "two_distinct")), max_profit_type="variable_iv", breakeven_type="range", payoff_function_ref="payoff_calendar_spread"),
    _spec("calendar_straddle", "Calendar Straddle", 4, (_leg("sell", "call", "same", "two_distinct"), _leg("buy", "call", "same", "two_distinct"), _leg("sell", "put", "same", "two_distinct"), _leg("buy", "put", "same", "two_distinct")), max_profit_type="variable_iv", breakeven_type="range", payoff_function_ref="payoff_double_calendar"),
    _spec("diagonal_call_spread", "Diagonal Call Spread", 4, (_leg("buy", "call", "atm", "two_distinct"), _leg("sell", "call", "different", "two_distinct")), max_profit_type="variable_iv", breakeven_type="range", payoff_function_ref="payoff_calendar_spread"),
]

# --- Family 5: Butterflies & condors (15) ---
_F5: list[StrategySpec] = [
    _spec("long_call_butterfly", "Long Call Butterfly", 5, (_leg("buy", "call", "different", "same"), _leg("sell", "call", "same", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_butterfly"),
    _spec("long_put_butterfly", "Long Put Butterfly", 5, (_leg("buy", "put", "different", "same"), _leg("sell", "put", "same", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_butterfly"),
    _spec("iron_butterfly", "Iron Butterfly", 5, (_leg("sell", "put", "same", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "same", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_butterfly"),
    _spec("short_iron_condor", "Short Iron Condor", 5, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_condor"),
    _spec("long_iron_condor", "Long Iron Condor", 5, (_leg("buy", "put", "otm_pair", "same"), _leg("sell", "put", "different", "same"), _leg("buy", "call", "otm_pair", "same"), _leg("sell", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_long_iron_condor"),
    _spec("broken_wing_butterfly", "Broken Wing Butterfly", 5, (_leg("buy", "call", "different", "same"), _leg("sell", "call", "same", "same"), _leg("buy", "call", "wide_otm", "same")), breakeven_type="dual", payoff_function_ref="payoff_broken_wing_butterfly"),
    _spec("skip_strike_butterfly", "Skip Strike Butterfly", 5, (_leg("buy", "call", "different", "same"), _leg("sell", "call", "same", "same"), _leg("buy", "call", "wide_otm", "same")), breakeven_type="dual", payoff_function_ref="payoff_broken_wing_butterfly"),
    _spec("iron_condor_wide", "Iron Condor (wide)", 5, (_leg("sell", "put", "wide_otm", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "wide_otm", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_condor"),
    _spec("condor_spread_call", "Condor Spread (call)", 5, (_leg("buy", "call", "different", "same"), _leg("sell", "call", "different", "same"), _leg("sell", "call", "different", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_condor_spread"),
    _spec("condor_spread_put", "Condor Spread (put)", 5, (_leg("buy", "put", "different", "same"), _leg("sell", "put", "different", "same"), _leg("sell", "put", "different", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_condor_spread"),
    _spec("reverse_iron_condor", "Reverse Iron Condor", 5, (_leg("buy", "put", "otm_pair", "same"), _leg("sell", "put", "different", "same"), _leg("buy", "call", "otm_pair", "same"), _leg("sell", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_long_iron_condor"),
    _spec("long_iron_butterfly", "Long Iron Butterfly", 5, (_leg("buy", "put", "same", "same"), _leg("sell", "put", "different", "same"), _leg("buy", "call", "same", "same"), _leg("sell", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_long_iron_butterfly"),
    _spec("short_call_butterfly", "Short Call Butterfly", 5, (_leg("sell", "call", "different", "same"), _leg("buy", "call", "same", "same"), _leg("sell", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_short_butterfly"),
    _spec("short_put_butterfly", "Short Put Butterfly", 5, (_leg("sell", "put", "different", "same"), _leg("buy", "put", "same", "same"), _leg("sell", "put", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_short_butterfly"),
    _spec("christmas_tree_spread", "Christmas Tree Spread", 5, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same"), _leg("sell", "call", "different", "same")), payoff_function_ref="payoff_christmas_tree"),
]

# --- Family 6: Ratio & back spreads (10) ---
_F6: list[StrategySpec] = [
    _spec("ratio_spread", "Ratio Spread", 6, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), risk_type="undefined", max_loss_type="unlimited", breakeven_type="dual", tradeable=False, payoff_function_ref="payoff_multi_leg_scan"),
    _spec("call_ratio_spread", "Call Ratio Spread", 6, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), risk_type="undefined", max_loss_type="unlimited", tradeable=False, payoff_function_ref="payoff_multi_leg_scan"),
    _spec("put_ratio_spread", "Put Ratio Spread", 6, (_leg("buy", "put", "atm", "same"), _leg("sell", "put", "different", "same")), risk_type="undefined", max_loss_type="unlimited", tradeable=False, payoff_function_ref="payoff_multi_leg_scan"),
    _spec("back_ratio_spread", "Back Ratio Spread", 6, (_leg("sell", "call", "atm", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_backspread"),
    _spec("call_backspread", "Call Backspread", 6, (_leg("sell", "call", "atm", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_backspread"),
    _spec("put_backspread", "Put Backspread", 6, (_leg("sell", "put", "atm", "same"), _leg("buy", "put", "different", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_backspread"),
    _spec("one_by_two_ratio_spread", "1x2 Ratio Spread", 6, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), risk_type="undefined", tradeable=False, payoff_function_ref="payoff_multi_leg_scan"),
    _spec("two_by_one_ratio_spread", "2x1 Ratio Spread", 6, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), risk_type="undefined", tradeable=False, payoff_function_ref="payoff_multi_leg_scan"),
    _spec("jade_lizard", "Jade Lizard", 6, (_leg("sell", "put", "otm_pair", "same"), _leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), risk_type="undefined", max_loss_type="unlimited", tradeable=False, payoff_function_ref="payoff_jade_lizard"),
    _spec("reverse_jade_lizard", "Reverse Jade Lizard", 6, (_leg("sell", "call", "otm_pair", "same"), _leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same")), risk_type="undefined", tradeable=False, payoff_function_ref="payoff_jade_lizard"),
]

# --- Family 7: Stock-option combos (10) ---
_F7: list[StrategySpec] = [
    _spec(
        "covered_call",
        "Covered Call",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("sell", "call", "otm_pair", "single")),
        max_profit_type="finite",
        payoff_function_ref="payoff_covered_call",
        equity_required=True,
        equity_leg_spec=_equity("buy"),
    ),
    _spec(
        "covered_put",
        "Covered Put",
        7,
        (_leg("sell", "stock", "n_a", "n_a"), _leg("sell", "put", "otm_pair", "single")),
        risk_type="undefined",
        payoff_function_ref="payoff_covered_put",
        equity_required=True,
        equity_leg_spec=_equity("sell"),
    ),
    _spec(
        "married_put",
        "Married Put",
        7,
        (_leg("buy", "put", "otm_pair", "single"),),
        max_profit_type="unlimited",
        payoff_function_ref="payoff_long_option",
        equity_required=True,
        equity_leg_spec=_equity("buy", entry_mode="pre_existing"),
    ),
    _spec(
        "leveraged_covered_call",
        "Leveraged Covered Call",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("buy", "call", "atm", "single")),
        max_profit_type="unlimited",
        payoff_function_ref="payoff_leveraged_covered_call",
        equity_required=True,
        equity_leg_spec=_equity("buy"),
    ),
    _spec(
        "protective_collar",
        "Protective Collar",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("buy", "put", "otm_pair", "single"), _leg("sell", "call", "otm_pair", "single")),
        payoff_function_ref="payoff_collar",
        equity_required=True,
        equity_leg_spec=_equity("buy"),
    ),
    _spec(
        "stock_short_call",
        "Stock + Short Call",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("sell", "call", "otm_pair", "single")),
        payoff_function_ref="payoff_covered_call",
        equity_required=True,
        equity_leg_spec=_equity("buy", entry_mode="pre_existing"),
    ),
    _spec(
        "stock_long_put",
        "Stock + Long Put",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("buy", "put", "otm_pair", "single")),
        max_profit_type="unlimited",
        payoff_function_ref="payoff_protective_put",
        equity_required=True,
        equity_leg_spec=_equity("buy", entry_mode="pre_existing"),
    ),
    _spec(
        "collar",
        "Collar",
        7,
        (_leg("buy", "stock", "n_a", "n_a"), _leg("buy", "put", "otm_pair", "single"), _leg("sell", "call", "otm_pair", "single")),
        payoff_function_ref="payoff_collar",
        equity_required=True,
        equity_leg_spec=_equity("buy"),
    ),
    _spec("synthetic_long_stock", "Synthetic Long Stock", 7, (_leg("buy", "call", "atm", "same"), _leg("sell", "put", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_long"),
    _spec("synthetic_short_stock", "Synthetic Short Stock", 7, (_leg("sell", "call", "atm", "same"), _leg("buy", "put", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_short"),
]

# --- Family 8: Synthetic & conversion (10) ---
_F8: list[StrategySpec] = [
    _spec("synthetic_call", "Synthetic Call", 8, (_leg("buy", "call", "atm", "same"), _leg("sell", "put", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_long"),
    _spec("synthetic_put", "Synthetic Put", 8, (_leg("buy", "put", "atm", "same"), _leg("sell", "call", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_short"),
    _spec("conversion", "Conversion", 8, (_leg("buy", "stock", "n_a", "n_a"), _leg("sell", "call", "same", "same"), _leg("buy", "put", "same", "same")), payoff_function_ref="payoff_conversion", equity_required=True, equity_leg_spec=_equity("buy")),
    _spec("reversal", "Reversal", 8, (_leg("sell", "stock", "n_a", "n_a"), _leg("buy", "call", "same", "same"), _leg("sell", "put", "same", "same")), payoff_function_ref="payoff_conversion", equity_required=True, equity_leg_spec=_equity("sell")),
    _spec("box_spread", "Box Spread", 8, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "put", "atm", "same")), payoff_function_ref="payoff_box_spread"),
    _spec("jelly_roll", "Jelly Roll", 8, (_leg("buy", "call", "same", "two_distinct"), _leg("sell", "call", "same", "two_distinct"), _leg("sell", "put", "same", "two_distinct"), _leg("buy", "put", "same", "two_distinct")), max_profit_type="variable_iv", breakeven_type="range", payoff_function_ref="payoff_jelly_roll"),
    _spec("long_combo", "Long Combo", 8, (_leg("buy", "call", "atm", "same"), _leg("sell", "put", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_long"),
    _spec("short_combo", "Short Combo", 8, (_leg("sell", "call", "atm", "same"), _leg("buy", "put", "same", "same")), max_profit_type="unlimited", max_loss_type="unlimited", payoff_function_ref="payoff_synthetic_short"),
    _spec("risk_reversal", "Risk Reversal", 8, (_leg("buy", "call", "otm_pair", "same"), _leg("sell", "put", "otm_pair", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_risk_reversal"),
    _spec("synthetic_straddle", "Synthetic Straddle", 8, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
]

# --- Family 9: Volatility & advanced (10) ---
_F9: list[StrategySpec] = [
    _spec("long_straddle_pre_earnings", "Long Straddle (pre-earnings)", 9, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
    _spec("iv_crush_short_iron_condor", "IV Crush Short Iron Condor", 9, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_condor"),
    _spec("volatility_skew_trade", "Volatility Skew Trade", 9, (_leg("buy", "put", "otm_pair", "same"), _leg("sell", "call", "otm_pair", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_risk_reversal"),
    _spec("vix_call_hedge", "VIX Call Hedge", 9, (_leg("buy", "call", "otm_pair", "single"),), max_profit_type="unlimited", payoff_function_ref="payoff_long_option"),
    _spec("dispersion_trade", "Dispersion Trade", 9, (_leg("sell", "call", "atm", "same"), _leg("buy", "call", "atm", "same")), max_profit_type="variable_iv", breakeven_type="none", payoff_function_ref="payoff_dispersion"),
    _spec("apex_strategy", "APEX Strategy", 9, (_leg("buy", "call", "wide_otm", "two_distinct"), _leg("buy", "put", "wide_otm", "two_distinct"), _leg("sell", "call", "wide_otm", "two_distinct"), _leg("sell", "put", "wide_otm", "two_distinct")), max_profit_type="unlimited", breakeven_type="range", payoff_function_ref="payoff_apex_strategy"),
    _spec("gamma_scalping", "Gamma Scalping", 9, (_leg("buy", "call", "atm", "single"), _leg("buy", "put", "atm", "single")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
    _spec("vega_neutral_spread", "Vega Neutral Spread", 9, (_leg("buy", "call", "atm", "same"), _leg("sell", "call", "different", "same")), payoff_function_ref="payoff_vertical_debit"),
    _spec("theta_harvest_iron_condor", "Theta Harvest Iron Condor", 9, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_condor"),
    _spec("earnings_straddle", "Earnings Straddle", 9, (_leg("buy", "call", "same", "same"), _leg("buy", "put", "same", "same")), breakeven_type="dual", max_profit_type="unlimited", payoff_function_ref="payoff_long_straddle"),
]

# --- Family 10: Neutral, income & no-trade (5) ---
_F10: list[StrategySpec] = [
    _spec("iron_condor_monthly", "Iron Condor (monthly)", 10, (_leg("sell", "put", "otm_pair", "same"), _leg("buy", "put", "different", "same"), _leg("sell", "call", "otm_pair", "same"), _leg("buy", "call", "different", "same")), breakeven_type="dual", payoff_function_ref="payoff_iron_condor"),
    _spec("wheel_strategy", "Wheel Strategy", 10, (_leg("sell", "put", "otm_pair", "single"),), max_profit_type="finite", payoff_function_ref="payoff_short_option"),
    _spec("poor_mans_covered_call", "Poor Man's Covered Call", 10, (_leg("buy", "call", "atm", "single"), _leg("sell", "call", "different", "single")), payoff_function_ref="payoff_pmcc"),
    _spec("no_trade_insufficient_conviction", "NO TRADE — Insufficient Conviction", 10, (), risk_type="advisory", max_profit_type="finite", max_loss_type="finite", breakeven_type="none", tradeable=False),
    _spec("no_trade_wait_iv_crush", "NO TRADE — Wait for IV Crush", 10, (), risk_type="advisory", max_profit_type="finite", max_loss_type="finite", breakeven_type="none", tradeable=False),
]

_ALL_FAMILIES = _F1 + _F2 + _F3 + _F4 + _F5 + _F6 + _F7 + _F8 + _F9 + _F10

assert len(_ALL_FAMILIES) == 100, f"Expected 100 strategies, got {len(_ALL_FAMILIES)}"

STRATEGY_REGISTRY: dict[str, StrategySpec] = {s.strategy_id: s for s in _ALL_FAMILIES}

DISPLAY_NAME_TO_ID: dict[str, str] = {s.display_name: s.strategy_id for s in _ALL_FAMILIES}

# Aliases for playbook labels that differ slightly from registry display names
DISPLAY_NAME_TO_ID.update(
    {
        "APEX Strategy": "apex_strategy",
        "Gamma Trampoline™": "apex_strategy",
        # Legacy misname: "Married Call" was a standalone long call (no stock leg).
        "Married Call": "apex_benchmark_greeks_strategy",
    }
)


def resolve_strategy_id(strategy_name: str) -> str | None:
    if strategy_name in DISPLAY_NAME_TO_ID:
        return DISPLAY_NAME_TO_ID[strategy_name]
    normalized = strategy_name.strip().lower().replace(" ", "_").replace("—", "").replace("'", "")
    normalized = normalized.replace("__", "_").strip("_")
    for spec in _ALL_FAMILIES:
        if spec.strategy_id == normalized:
            return spec.strategy_id
    return None


def get_strategy_spec(strategy_name_or_id: str) -> StrategySpec | None:
    if strategy_name_or_id in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[strategy_name_or_id]
    sid = resolve_strategy_id(strategy_name_or_id)
    if sid:
        return STRATEGY_REGISTRY.get(sid)
    return None


def implemented_strategy_names() -> list[str]:
    return [s.display_name for s in _ALL_FAMILIES if s.payoff_function_ref is not None and s.tradeable]
