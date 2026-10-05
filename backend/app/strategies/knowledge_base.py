"""Versioned strategy knowledge base. User-facing card text is read from here.

Change 11 v2 replaces conflicting APEX Strategy prose. The trademark name
Gamma Trampoline™ is the earnings label only. The same four legs without the
earnings gates are a standard double calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.strategies.registry import STRATEGY_REGISTRY, format_legs_template

KB_VERSION = "12.0"
CHANGELOG: tuple[dict[str, str], ...] = (
    {
        "version": "11.0",
        "note": "Unversioned encyclopedia playbook used before Change 11.",
    },
    {
        "version": "11.2",
        "note": (
            "Change 11 v2. Adds apex_benchmark_greeks_buy and apex_benchmark_greeks_sell. "
            "Labels the earnings double calendar Gamma Trampoline™ only when its gates pass. "
            "Replaces the 1.5% Rule 1 theta cap with 1.0% of premium and the spot-scaled delta/theta ratio. "
            "Removes the premium-offset gate and the 0.15–0.25 delta band from the earnings structure. "
            "Drops conflicting APEX Strategy scenario prose. "
            "Corrects the reverse calendar so the near leg is long and the later leg is short on the grid."
        ),
    },
    {
        "version": "12.0",
        "note": (
            "Change 12. Each catalog row stores a legs template, outlook, vega/theta/gamma sign, "
            "ideal IV regime, DTE window, payoff formulas, assignment note, entry and exit rules, "
            "brokerage approval class, a named reference, and this version. "
            "Windows that the product does not state stay unstated. "
            "Gamma Trampoline™ wording from Change 11 v2 is unchanged."
        ),
    },
)

BENCHMARK_SUMMARY = (
    "The APEX Benchmark Greeks Strategy is a rules-based framework that uses an option's Greeks to decide "
    "when to buy options for directional exposure and when to sell options for premium income. Rule 1 buys "
    "options only when they offer strong directional exposure for little time decay. Rule 2 sells options "
    "only when implied volatility is elevated, momentum is neutral, and the short strike is far from the "
    "current price, always with a protective wing so risk is defined."
)
RULE1_WHY = (
    "High delta gives the option meaningful participation in the stock's move, while its daily time decay "
    "is small relative to its price. Implied volatility is below the stock's recent realized volatility, "
    "so you are not overpaying for the option."
)
RULE1_RATIO = (
    "The ratio compares what a 1% move in your favor earns against what one day of time decay costs. "
    "A ratio above 10 means a 1% favorable move earns more than ten days of decay."
)
RULE1_HOW = (
    "Buy the option with a limit order near the mid-price. Size the position so that the full premium is "
    "an amount you can afford to lose. Consider taking profits at a predefined target, and exit or "
    "re-evaluate if the trend or sentiment alignment breaks. Close or roll before the final 21 days, "
    "when time decay accelerates."
)
RULE1_RISKS = (
    "The full premium can be lost if the stock does not move in the expected direction before expiration. "
    "A drop in implied volatility reduces the option's value even when the stock price is unchanged."
)
RULE2_WHY = (
    "Implied volatility is high relative to its past year, so option premiums are rich. Momentum is neutral, "
    "which suggests the stock is less likely to make a strong directional move. The short strike sits well "
    "outside the current price, and the long wing caps the maximum loss."
)
RULE2_PROBABILITY = (
    "A short-strike delta of 0.20 or less roughly corresponds to an 80% or greater chance that strike expires "
    "out of the money, under standard pricing assumptions. The app shows the model-calculated probability of "
    "profit for the entire position, which is the figure to rely on."
)
RULE2_HOW = (
    "Enter with a limit order near the mid-price for the net credit. A common management approach is to close "
    "the position once about 50% of the maximum profit has been captured, and to close it if the loss reaches "
    "about 2 times the credit received or the position reaches 21 days to expiration, whichever comes first. "
    "Watch for early-assignment risk on short calls ahead of ex-dividend dates."
)
RULE2_RISKS = (
    "A sharp move through the short strike can produce a loss up to the stated maximum. High implied volatility "
    "can rise further before it falls. Early assignment of a short option is possible, especially before "
    "ex-dividend dates."
)
GAMMA_SUMMARY = (
    "The Gamma Trampoline is APEX's earnings volatility strategy, built on a double calendar structure. "
    "It sells front-week options while their implied volatility is inflated ahead of earnings, and buys the "
    "same strikes in a later expiration that keep more of their value once the announcement passes. It profits "
    "when the post-earnings move stays within or near the expected range and front-week volatility collapses. "
    "The maximum loss is limited to the net debit paid when all legs are closed together by the front-week expiration."
)
GAMMA_PROBLEM = (
    "Before earnings, front-week options price in a large expected move, and their implied volatility typically "
    "collapses after the announcement. Buying a straddle means paying for that inflated volatility, which often "
    "loses value even when the stock moves. The Gamma Trampoline takes the other side of that front-week "
    "volatility while owning later-dated options with the same strikes, so the risk is defined. "
    "The structure is a double calendar spread. APEX's contribution is the entry model: event timing, "
    "term-structure inversion, liquidity screens and strike placement at the expected move."
)
GAMMA_GREEKS = (
    "Before earnings: the position collects time decay (positive theta), is hurt by large fast moves "
    "(net short gamma), and is net long vega overall. Its edge comes from front-week volatility falling much "
    "more than back-week volatility after the announcement. A broad drop in volatility across all expirations "
    "works against it. After the front-week options expire: if you choose to keep the back-week options, you "
    "hold a long strangle. That position is long gamma, with unlimited upside on the call side, and it can "
    "still lose the remaining premium."
)
GAMMA_SCENARIOS = (
    "Scenario A — the stock lands near Strike A or Strike B (best case). The short option at that strike "
    "expires at or near zero while the same-strike back-week option keeps most of its time value. This is "
    "where the maximum profit occurs. "
    "Scenario B — the stock barely moves. Both front-week options expire worthless and the full front-week "
    "premium is kept. The back-week options lose some value to the volatility drop. The result is typically "
    "a moderate profit, depending on how far the strikes are from the current price. "
    "Scenario C — a large move well beyond Strike A or Strike B. The short and long options at the breached "
    "strike both move toward their intrinsic value, so their gains and losses largely offset. The position "
    "loses value, with the maximum loss limited to the net debit paid. This defined risk is what separates "
    "the strategy from selling a strangle outright."
)
GAMMA_HOW = (
    "Enter all four legs together as one order, about 5 to 10 days before earnings, with a limit price near "
    "the mid of the net debit. Close all four legs together after the announcement, ideally on the first "
    "trading session after earnings, and no later than the front-week expiration. Do not hold the short legs "
    "into their expiration close, where assignment and pin risk rise. If you want to keep exposure to a "
    "continued move, you may close the front-week shorts and keep the back-week options. Your risk is then "
    "the remaining value of those options."
)
GAMMA_CLASSIFIER = (
    "Gamma Trampoline™ is labeled only when the earnings gates pass. The same four legs without those gates "
    "are a standard double calendar."
)

_OIC = "Options Industry Council strategy education (optionseducation.org); formulas are the standard expiry identities, not a pasted page."
_OCC = "OCC, Characteristics and Risks of Standardized Options, general long and short option payoff identities."
_CBOE = "Cboe options strategy education; credit-spread and condor identities use width and net credit."

_BANNED = ("guaranteed", "risk-free", "consistent edge through volume")


@dataclass(frozen=True)
class KnowledgeEntry:
    entry_id: str
    title: str
    registry_ids: tuple[str, ...]
    summary: str
    why_it_fits: str
    how_to_use: str
    key_risks: str
    outlook: str
    vol_view: str
    greeks_profile: str
    ideal_conditions: str
    when_not_to_use: str
    assignment_dividend_pin: str
    entry_management_exit: str
    max_profit: str
    max_loss: str
    breakevens: str
    capital_or_margin: str
    reference: str
    legs_template: str
    vega_sign: str
    theta_sign: str
    gamma_sign: str
    ideal_iv_regime: str
    dte_window: str
    dte_min: int | None
    dte_max: int | None
    dte_source: str
    approval_level: str
    approval_note: str
    version: str
    entry_rules: str
    management_rules: str
    exit_rules: str
    verbatim: bool = False


def _entry(**kwargs: object) -> KnowledgeEntry:
    entry_id = str(kwargs.get("entry_id") or "")
    for key, value in _structured_fields(entry_id).items():
        kwargs.setdefault(key, value)
    return KnowledgeEntry(**kwargs)  # type: ignore[arg-type]


def _template(spec_id: str) -> KnowledgeEntry:
    spec = STRATEGY_REGISTRY[spec_id]
    ref = spec.payoff_function_ref or ""
    name = spec.display_name
    if spec.risk_type == "advisory" or spec.leg_count == 0:
        return _entry(
            entry_id=spec_id,
            title=name,
            registry_ids=(spec_id,),
            summary=f"{name} is an advisory label. It is not an order.",
            why_it_fits="The scan did not find a structure that passed its own gates.",
            how_to_use="Re-scan when the inputs change. No order is sent for this label.",
            key_risks="There is no position, so there is no option payoff.",
            outlook="none",
            vol_view="Not a volatility trade.",
            greeks_profile="No Greeks. There are no legs.",
            ideal_conditions="Shown when a named structure is not the selection.",
            when_not_to_use="Do not send an order under this label.",
            assignment_dividend_pin="No short option, so no assignment.",
            entry_management_exit="No entry.",
            max_profit="Not applicable.",
            max_loss="Not applicable.",
            breakevens="Not applicable.",
            capital_or_margin="None.",
            reference=_OIC,
        )
    formulas = _FORMULAS.get(ref, _DEFAULT_FORMULA)
    greeks = _GREEKS.get(ref, "Greeks follow the signed legs. Short options flip the sign of each Greek.")
    outlook = _OUTLOOK.get(spec_id, _OUTLOOK_BY_REF.get(ref, "depends on the legs"))
    return _entry(
        entry_id=spec_id,
        title=name,
        registry_ids=(spec_id,),
        summary=f"{name}. {formulas['summary']}",
        why_it_fits=formulas["why"],
        how_to_use=formulas["how"],
        key_risks=formulas["risks"],
        outlook=outlook,
        vol_view=formulas["vol"],
        greeks_profile=greeks,
        ideal_conditions=formulas["ideal"],
        when_not_to_use=formulas["avoid"],
        assignment_dividend_pin=formulas["assignment"],
        entry_management_exit=formulas["manage"],
        max_profit=formulas["max_profit"],
        max_loss=formulas["max_loss"],
        breakevens=formulas["breakevens"],
        capital_or_margin=formulas["capital"],
        reference=formulas["reference"],
    )


_DEFAULT_FORMULA = {
    "summary": "Payoff is the model grid at the relevant expiration. No single-expiry closed form is shown when a later leg remains.",
    "why": "The legs match the named structure on the chain that was scanned.",
    "how": "Enter the legs as one limit near the net mid. Close or roll short options before expiration.",
    "risks": "Loss can reach the stated maximum. Short options can be assigned.",
    "vol": "Follows the volatility view named with the structure.",
    "ideal": "Use when the chain can fill every leg inside the spread cap.",
    "avoid": "Skip it when a leg quote is missing or the thesis no longer matches the legs.",
    "assignment": "Short options can be assigned, including before an ex-dividend date on a short call. Pin risk rises into expiration.",
    "manage": "Manage short legs before expiration. A remaining long leg is a separate position after that.",
    "max_profit": "No single closed form when a later expiration remains. The card shows the model grid.",
    "max_loss": "Defined by the debit paid, or by the wing width minus credit, when the structure has a cap. Otherwise the card states the unbounded side.",
    "breakevens": "Solved from the same model as the grid when there is no closed form.",
    "capital": "Capital at risk is the maximum loss when that loss is finite.",
    "reference": _OIC,
}

_FORMULAS: dict[str, dict[str, str]] = {
    "payoff_long_option": {
        "summary": "One long option. A call profits if the stock rises above the breakeven. A put profits if it falls below the breakeven.",
        "why": "The long option supplies directional exposure for a debit equal to the premium.",
        "how": "Buy with a limit near the mid. The full premium is the amount that can be lost.",
        "risks": "The full premium can be lost. A drop in implied volatility reduces the value even if the stock is unchanged.",
        "vol": "Long volatility. Cheaper when implied volatility is below recent realized volatility.",
        "ideal": "A directional view and a premium the account can lose.",
        "avoid": "Skip a long option when implied volatility is far above realized volatility and the thesis is only a small move.",
        "assignment": "A long option is not short, so the holder is not assigned. Early exercise is the holder's choice.",
        "manage": "Exit or roll before the final weeks if time decay is the concern.",
        "max_profit": "Long call: unlimited. Long put: (strike − premium) × multiplier × contracts.",
        "max_loss": "Premium × multiplier × contracts.",
        "breakevens": "Long call: strike + premium. Long put: strike − premium.",
        "capital": "The debit paid.",
        "reference": _OCC,
    },
    "payoff_short_option": {
        "summary": "One short option. Profit is limited to the premium. Loss is not capped on a naked call, and a naked put can lose down to a zero stock.",
        "why": "The short option collects premium.",
        "how": "This structure is not auto-executed. A covered or cash-secured version is a different strategy.",
        "risks": "Loss is not capped on a naked short call.",
        "vol": "Short volatility.",
        "ideal": "Not used for auto-execution.",
        "avoid": "Do not send a naked short from this label.",
        "assignment": "Short options can be assigned at any time, including before an ex-dividend date on a short call.",
        "manage": "Close before expiration if the short strike is approached.",
        "max_profit": "Premium × multiplier × contracts.",
        "max_loss": "Unbounded on a naked call. A naked put loses down to a stock price of zero: (strike − premium) × multiplier × contracts.",
        "breakevens": "Short call: strike + premium. Short put: strike − premium.",
        "capital": "Margin is broker-defined and is not the premium alone.",
        "reference": _OCC,
    },
    "payoff_vertical_debit": {
        "summary": "A debit vertical buys one option and sells a further option in the same expiration.",
        "why": "The short option reduces the debit and caps the gain.",
        "how": "Buy the nearer strike and sell the further strike as one limit debit.",
        "risks": "The maximum loss is the debit. The maximum gain is the width minus that debit.",
        "vol": "Long the spread. Less sensitive to volatility than a naked long option.",
        "ideal": "A moderate move in the spread's direction.",
        "avoid": "Skip it when the debit is almost the width, because the remaining gain is small.",
        "assignment": "The short leg can be assigned. A short call is more exposed before an ex-dividend date.",
        "manage": "Close as a spread. Do not leave the short leg on alone.",
        "max_profit": "(width − net debit) × multiplier × contracts.",
        "max_loss": "Net debit × multiplier × contracts.",
        "breakevens": "Call debit: long strike + net debit. Put debit: long strike − net debit.",
        "capital": "The debit paid.",
        "reference": _OIC,
    },
    "payoff_vertical_credit": {
        "summary": "A credit vertical sells one option and buys a further option in the same expiration so the loss is capped.",
        "why": "Premium is collected and the long wing caps the loss.",
        "how": "Sell the nearer strike and buy the further strike as one limit credit.",
        "risks": "A move through the short strike can lose up to the width minus the credit.",
        "vol": "Short volatility relative to a long option.",
        "ideal": "Elevated implied volatility and a strike the thesis expects to hold.",
        "avoid": "Skip it when the credit is thin relative to the width.",
        "assignment": "The short leg can be assigned, especially a short call before an ex-dividend date.",
        "manage": "Close the spread together. A common approach is to take the credit off before expiration.",
        "max_profit": "Net credit × multiplier × contracts.",
        "max_loss": "(width − net credit) × multiplier × contracts.",
        "breakevens": "Short put: short strike − credit. Short call: short strike + credit.",
        "capital": "The maximum loss, which is the width minus the credit.",
        "reference": _CBOE,
    },
    "payoff_iron_condor": {
        "summary": "A short iron condor sells an out-of-the-money put spread and an out-of-the-money call spread.",
        "why": "The position collects a net credit and both wings are long, so the loss is capped.",
        "how": "Enter all four legs as one limit credit.",
        "risks": "A move through either short strike can lose up to the wider wing minus the credit.",
        "vol": "Short volatility, used when a range is the view.",
        "ideal": "Elevated implied volatility and no strong directional view.",
        "avoid": "Skip it into a known event if the expected move is wider than the short strikes.",
        "assignment": "Either short leg can be assigned. Short calls are exposed before an ex-dividend date. Pin risk rises at expiration.",
        "manage": "Close the condor as one order. Do not leave a naked short.",
        "max_profit": "Net credit × multiplier × contracts.",
        "max_loss": "(wider wing width − net credit) × multiplier × contracts.",
        "breakevens": "Short put strike − net credit, and short call strike + net credit.",
        "capital": "The maximum loss.",
        "reference": _CBOE,
    },
    "payoff_long_iron_condor": {
        "summary": "A long iron condor buys the body and sells the wings, the reverse of a short condor.",
        "why": "The debit buys a position that gains if price moves beyond a wing.",
        "how": "Enter the four legs as one limit debit.",
        "risks": "The debit can be lost if price finishes between the long strikes.",
        "vol": "Long volatility relative to the short condor.",
        "ideal": "A view that price leaves the body.",
        "avoid": "Skip it when the debit is close to the width.",
        "assignment": "The short wings can be assigned.",
        "manage": "Close the four legs together.",
        "max_profit": "(wider wing − net debit) × multiplier × contracts.",
        "max_loss": "Net debit × multiplier × contracts.",
        "breakevens": "Solved from the debit and the wing strikes.",
        "capital": "The debit paid.",
        "reference": _OIC,
    },
    "payoff_long_straddle": {
        "summary": "A long straddle buys a call and a put at the same strike and expiration.",
        "why": "The position gains from a large move in either direction.",
        "how": "Buy both options as one debit.",
        "risks": "The combined premium can be lost if the stock does not move enough.",
        "vol": "Long volatility.",
        "ideal": "A large move is expected and direction is not chosen.",
        "avoid": "Skip it when implied volatility already prices a move larger than the thesis.",
        "assignment": "Both legs are long, so the holder is not assigned.",
        "manage": "Exit on a large move or before the premium is spent.",
        "max_profit": "Unlimited on the upside. On the downside, limited by a stock price of zero.",
        "max_loss": "Combined premium × multiplier × contracts.",
        "breakevens": "Strike + total premium, and strike − total premium.",
        "capital": "The debit paid.",
        "reference": _OIC,
    },
    "payoff_long_strangle": {
        "summary": "A long strangle buys an out-of-the-money call and an out-of-the-money put.",
        "why": "The debit is lower than a straddle because both strikes are away from the spot.",
        "how": "Buy both options in the same expiration.",
        "risks": "The premium can be lost if price stays between the strikes.",
        "vol": "Long volatility.",
        "ideal": "A large move with a lower debit than a straddle.",
        "avoid": "Skip it when the required move is larger than the thesis.",
        "assignment": "Both legs are long.",
        "manage": "Exit on a large move or before expiration.",
        "max_profit": "Unlimited on the upside.",
        "max_loss": "Combined premium × multiplier × contracts.",
        "breakevens": "Call strike + total premium, and put strike − total premium.",
        "capital": "The debit paid.",
        "reference": _OIC,
    },
    "payoff_short_straddle": {
        "summary": "A short straddle sells a call and a put at the same strike. Loss is not capped.",
        "why": "Premium is collected if price stays near the strike.",
        "how": "Not auto-executed. The loss is unbounded.",
        "risks": "A large move can lose more than the premium.",
        "vol": "Short volatility.",
        "ideal": "Not used for auto-execution.",
        "avoid": "Do not treat this as a defined-risk condor.",
        "assignment": "Either short can be assigned. The short call is exposed before an ex-dividend date.",
        "manage": "Close before expiration if price leaves the strike.",
        "max_profit": "Combined premium × multiplier × contracts.",
        "max_loss": "Unbounded.",
        "breakevens": "Strike ± the combined premium.",
        "capital": "Margin is broker-defined.",
        "reference": _OCC,
    },
    "payoff_short_strangle": {
        "summary": "A short strangle sells an out-of-the-money call and put. Loss is not capped.",
        "why": "Premium is collected if price stays between the strikes.",
        "how": "Not auto-executed.",
        "risks": "A large move can lose more than the premium.",
        "vol": "Short volatility.",
        "ideal": "Not used for auto-execution.",
        "avoid": "Do not treat this as an iron condor. There is no long wing.",
        "assignment": "Either short can be assigned.",
        "manage": "Close before expiration.",
        "max_profit": "Combined premium × multiplier × contracts.",
        "max_loss": "Unbounded.",
        "breakevens": "Call strike + premium, and put strike − premium.",
        "capital": "Margin is broker-defined.",
        "reference": _OCC,
    },
}

_GREEKS = {
    "payoff_long_option": "Long gamma, short theta, long vega. A call is long delta. A put is short delta.",
    "payoff_short_option": "Short gamma, positive theta, short vega. A short call is short delta. A short put is long delta.",
    "payoff_vertical_debit": "Net long delta for a call debit and net short delta for a put debit. Gamma, theta, and vega are smaller than a single long option.",
    "payoff_vertical_credit": "A bull put is net long delta. A bear call is net short delta. Theta is positive if the short option decays faster. Vega is net short.",
    "payoff_iron_condor": "Near the spot the condor is short gamma, positive theta, and short vega. Delta is near flat when the wings are balanced.",
    "payoff_long_iron_condor": "The reverse condor is long gamma relative to the short condor and pays a debit.",
    "payoff_long_straddle": "Near the strike: small delta, long gamma, short theta, long vega.",
    "payoff_long_strangle": "Long gamma, short theta, long vega. Delta is small between the strikes.",
    "payoff_short_straddle": "Short gamma, positive theta, short vega, and unbounded loss.",
    "payoff_short_strangle": "Short gamma, positive theta, short vega, and unbounded loss.",
    "payoff_apex_strategy": (
        "Before the front expiration the earnings structure is positive theta, net short gamma, and net long vega. "
        "After the front options expire, the remaining long strangle is long gamma."
    ),
}

_OUTLOOK_BY_REF = {
    "payoff_long_option": "directional",
    "payoff_vertical_debit": "directional",
    "payoff_vertical_credit": "mild directional",
    "payoff_iron_condor": "neutral",
    "payoff_long_straddle": "neutral",
    "payoff_long_strangle": "neutral",
    "payoff_apex_strategy": "neutral",
}

_OUTLOOK = {
    "bull_call_spread": "bullish",
    "bear_put_spread": "bearish",
    "bull_put_spread_credit": "mild bullish",
    "bear_call_spread_credit": "mild bearish",
    "covered_call": "mild bullish",
    "married_put": "bullish",
}

# Signs and regimes below are taken from the greek and volatility sentences already
# stored on each payoff family. A sign the sentence does not name stays "not_stated".
# vega, theta, gamma, ideal IV regime.
_SIGNS_BY_REF: dict[str, tuple[str, str, str, str]] = {
    "payoff_long_option": ("long", "negative", "long", "cheap"),
    "payoff_short_option": ("short", "positive", "short", "not_stated"),
    "payoff_vertical_debit": ("long", "negative", "long", "not_stated"),
    "payoff_vertical_credit": ("short", "positive", "not_stated", "rich"),
    "payoff_iron_condor": ("short", "positive", "short", "rich"),
    "payoff_long_iron_condor": ("not_stated", "not_stated", "long", "not_stated"),
    "payoff_long_straddle": ("long", "negative", "long", "not_stated"),
    "payoff_long_strangle": ("long", "negative", "long", "not_stated"),
    "payoff_short_straddle": ("short", "positive", "short", "not_stated"),
    "payoff_short_strangle": ("short", "positive", "short", "not_stated"),
    "payoff_apex_strategy": ("long", "positive", "short", "not_stated"),
}

_NO_WINDOW = "No product DTE window is stated."
_NO_WINDOW_SOURCE = (
    "No DTE window is stated in the strategy playbook, the Change 11 settings, or LEAPS_MIN_DTE."
)
_APPROVAL_NOTE = (
    "Brokerages set the options approval class. OCC, Characteristics and Risks of Standardized Options, "
    "describes the payoff and the risks of long options, spreads, covered positions, and uncovered shorts. "
    "It does not assign a numeric approval level."
)

_VEGA_SIGNS = frozenset({"long", "short", "mixed", "flat", "none", "not_stated"})
_THETA_SIGNS = frozenset({"positive", "negative", "mixed", "flat", "none", "not_stated"})
_GAMMA_SIGNS = frozenset({"long", "short", "mixed", "flat", "none", "not_stated"})
_IV_REGIMES = frozenset({"cheap", "rich", "fair", "inversion", "neutral_range", "not_stated", "not_a_trade"})
_APPROVAL_LEVELS = frozenset(
    {"long_premium", "defined_risk_spread", "stock_combo", "uncovered", "cash_secured", "advisory"}
)
_REFERENCE_NAMES = ("OCC", "Options Industry Council", "Cboe")

REQUIRED_KB_FIELDS: tuple[str, ...] = (
    "legs_template",
    "outlook",
    "vega_sign",
    "theta_sign",
    "gamma_sign",
    "ideal_iv_regime",
    "dte_window",
    "dte_source",
    "max_profit",
    "max_loss",
    "breakevens",
    "assignment_dividend_pin",
    "entry_management_exit",
    "approval_level",
    "approval_note",
    "reference",
    "version",
    "summary",
    "why_it_fits",
    "how_to_use",
    "key_risks",
    "greeks_profile",
    "ideal_conditions",
    "when_not_to_use",
    "capital_or_margin",
    "entry_rules",
    "management_rules",
    "exit_rules",
)


def _approval_level(spec_id: str) -> str:
    spec = STRATEGY_REGISTRY[spec_id]
    if spec.risk_type == "advisory" or spec.leg_count == 0:
        return "advisory"
    if spec.strategy_id == "wheel_strategy":
        return "cash_secured"
    if spec.equity_required:
        return "stock_combo"
    if spec.risk_type == "undefined" or spec.max_loss_type == "unlimited":
        return "uncovered"
    if spec.leg_count == 1 and spec.leg_specs and spec.leg_specs[0].side == "sell":
        return "uncovered"
    if spec.leg_count == 1:
        return "long_premium"
    return "defined_risk_spread"


_CONDOR_30_45 = {
    "short_iron_condor",
    "iron_condor_wide",
    "iv_crush_short_iron_condor",
    "theta_harvest_iron_condor",
    "iron_condor_monthly",
}
_CREDIT_30_45 = {
    "bull_put_spread_credit",
    "bear_call_spread_credit",
    "put_credit_spread",
    "call_credit_spread",
}
_PROTECTIVE_30_45 = {"married_put", "stock_long_put", "synthetic_call"}
_MATRIX_REGIME = {
    "bull_call_spread": "cheap",
    "call_debit_spread": "cheap",
    "wide_bull_call_spread": "cheap",
    "bear_put_spread": "cheap",
    "put_debit_spread": "cheap",
    "wide_bear_put_spread": "cheap",
    "long_straddle": "cheap",
    "long_strangle": "cheap",
    "long_straddle_leaps": "cheap",
    "long_straddle_pre_earnings": "cheap",
    "earnings_straddle": "cheap",
    "gamma_scalping": "cheap",
    "calendar_spread": "fair",
    "calendar_call_spread": "fair",
    "calendar_put_spread": "fair",
    "diagonal_spread_bullish": "fair",
    "diagonal_spread_bearish": "fair",
    "diagonal_call_spread": "fair",
}


def _dte_fields(spec_id: str) -> dict[str, object]:
    if spec_id in {"long_call_leaps", "long_put_leaps", "long_straddle_leaps"}:
        return {
            "dte_window": "more than 365 calendar days",
            "dte_min": 366,
            "dte_max": None,
            "dte_source": (
                "metrics_builder.LEAPS_MIN_DTE is 365. The builder keeps an expiration only when "
                "days to expiration are greater than 365."
            ),
        }
    if spec_id in _PROTECTIVE_30_45:
        return {
            "dte_window": "30 to 45",
            "dte_min": 30,
            "dte_max": 45,
            "dte_source": (
                "Strategy playbook for Married Put: buy a put slightly OTM at 30–45 DTE. "
                "The same window is stored for long stock plus a long put."
            ),
        }
    if spec_id in _CONDOR_30_45:
        return {
            "dte_window": "30 to 45",
            "dte_min": 30,
            "dte_max": 45,
            "dte_source": "Strategy playbook for Short Iron Condor: Target 30–45 DTE. Same short-condor legs.",
        }
    if spec_id in _CREDIT_30_45:
        return {
            "dte_window": "30 to 45",
            "dte_min": 30,
            "dte_max": 45,
            "dte_source": "Change 11 v2 Rule 2 setting: DTE 30 to 45. Rule 2 uses this credit spread.",
        }
    return {
        "dte_window": _NO_WINDOW,
        "dte_min": None,
        "dte_max": None,
        "dte_source": _NO_WINDOW_SOURCE,
    }


def _activity_rules(entry_id: str) -> dict[str, str]:
    """Entry, management, and exit sentences already used by the playbook or the formula text."""
    if entry_id == "apex_benchmark_greeks_buy":
        return {
            "entry_rules": (
                "Buy the option with a limit order near the mid-price. "
                "Size the position so that the full premium is an amount you can afford to lose."
            ),
            "management_rules": (
                "Consider taking profits at a predefined target, and exit or re-evaluate if the trend "
                "or sentiment alignment breaks."
            ),
            "exit_rules": "Close or roll before the final 21 days, when time decay accelerates.",
        }
    if entry_id == "apex_benchmark_greeks_sell":
        return {
            "entry_rules": "Enter with a limit order near the mid-price for the net credit.",
            "management_rules": (
                "A common management approach is to close the position once about 50% of the maximum profit has been captured."
            ),
            "exit_rules": (
                "Close it if the loss reaches about 2 times the credit received or the position reaches 21 days "
                "to expiration, whichever comes first. Watch for early-assignment risk on short calls ahead of ex-dividend dates."
            ),
        }
    if entry_id == "gamma_trampoline":
        return {
            "entry_rules": (
                "Enter all four legs together as one order, about 5 to 10 days before earnings, "
                "with a limit price near the mid of the net debit."
            ),
            "management_rules": (
                "Do not hold the short legs into their expiration close, where assignment and pin risk rise. "
                "If you want to keep exposure to a continued move, you may close the front-week shorts and keep the back-week options."
            ),
            "exit_rules": (
                "Close all four legs together after the announcement, ideally on the first trading session after earnings, "
                "and no later than the front-week expiration."
            ),
        }
    if entry_id in _PROTECTIVE_30_45:
        return {
            "entry_rules": "Own or plan to own shares. Buy a put slightly OTM at 30–45 DTE.",
            "management_rules": "Strike near pivot support.",
            "exit_rules": "Roll before expiry if the thesis is intact.",
        }
    if entry_id in _CONDOR_30_45:
        return {
            "entry_rules": "Sell one OTM put spread and one OTM call spread.",
            "management_rules": "Target 30–45 DTE.",
            "exit_rules": "Manage at 50% of max profit or if price breaches a short strike.",
        }
    spec = STRATEGY_REGISTRY.get(entry_id)
    if spec is None or spec.risk_type == "advisory" or spec.leg_count == 0:
        return {
            "entry_rules": "No entry.",
            "management_rules": "No position to manage.",
            "exit_rules": "No exit. No order is sent for this label.",
        }
    formulas = _FORMULAS.get(spec.payoff_function_ref or "", _DEFAULT_FORMULA)
    manage = formulas["manage"]
    pieces = [part.strip().rstrip(".") for part in manage.split(". ") if part.strip()]
    if len(pieces) >= 2:
        management = pieces[0] + "."
        exit_rule = ". ".join(pieces[1:]) + "."
    else:
        management = manage
        exit_rule = "Close or roll before expiration."
    return {
        "entry_rules": formulas["how"],
        "management_rules": management,
        "exit_rules": exit_rule,
    }


def _catalog_fields(entry_id: str) -> dict[str, object]:
    """Machine-readable fields 2A can read. Missing product windows stay unstated."""
    if entry_id == "apex_benchmark_greeks_buy":
        return {
            "legs_template": "buy 1 call or buy 1 put",
            "vega_sign": "long",
            "theta_sign": "negative",
            "gamma_sign": "long",
            "ideal_iv_regime": "cheap",
            "dte_window": "30 to 90",
            "dte_min": 30,
            "dte_max": 90,
            "dte_source": "Change 11 v2 Rule 1 setting: DTE 30 to 90.",
            "approval_level": "long_premium",
            "approval_note": _APPROVAL_NOTE,
            "version": KB_VERSION,
        }
    if entry_id == "apex_benchmark_greeks_sell":
        return {
            "legs_template": (
                "neutral: short iron condor (sell put, buy lower put, sell call, buy higher call); "
                "mild bullish: sell put, buy lower put; mild bearish: sell call, buy higher call"
            ),
            "vega_sign": "short",
            "theta_sign": "positive",
            "gamma_sign": "short",
            "ideal_iv_regime": "rich",
            "dte_window": "30 to 45",
            "dte_min": 30,
            "dte_max": 45,
            "dte_source": "Change 11 v2 Rule 2 setting: DTE 30 to 45.",
            "approval_level": "defined_risk_spread",
            "approval_note": _APPROVAL_NOTE,
            "version": KB_VERSION,
        }
    if entry_id == "gamma_trampoline":
        return {
            "legs_template": (
                "sell 1 front-week call; buy 1 later call at the same strike; "
                "sell 1 front-week put; buy 1 later put at the same strike"
            ),
            "vega_sign": "long",
            "theta_sign": "positive",
            "gamma_sign": "short",
            "ideal_iv_regime": "inversion",
            "dte_window": "5 to 10 calendar days before earnings",
            "dte_min": 5,
            "dte_max": 10,
            "dte_source": (
                "Change 11 v2 earnings window: 5 to 10 calendar days. "
                "Gamma Trampoline™ uses this window only when its earnings gates pass. "
                "The same legs otherwise stay a double calendar, which has no separate product DTE window."
            ),
            "approval_level": "defined_risk_spread",
            "approval_note": _APPROVAL_NOTE,
            "version": KB_VERSION,
        }
    spec = STRATEGY_REGISTRY.get(entry_id)
    if spec is None:
        return {
            "legs_template": "no legs",
            "vega_sign": "none",
            "theta_sign": "none",
            "gamma_sign": "none",
            "ideal_iv_regime": "not_a_trade",
            "dte_window": "not applicable",
            "dte_min": None,
            "dte_max": None,
            "dte_source": "Advisory label. There is no expiration.",
            "approval_level": "advisory",
            "approval_note": _APPROVAL_NOTE,
            "version": KB_VERSION,
        }
    ref = spec.payoff_function_ref or ""
    vega, theta, gamma, regime = _SIGNS_BY_REF.get(ref, ("not_stated", "not_stated", "not_stated", "not_stated"))
    if spec.risk_type == "advisory" or spec.leg_count == 0:
        vega, theta, gamma, regime = "none", "none", "none", "not_a_trade"
    fields: dict[str, object] = {
        "legs_template": format_legs_template(spec),
        "vega_sign": vega,
        "theta_sign": theta,
        "gamma_sign": gamma,
        "ideal_iv_regime": regime,
        "approval_level": _approval_level(entry_id),
        "approval_note": _APPROVAL_NOTE,
        "version": KB_VERSION,
    }
    fields.update(_dte_fields(entry_id))
    return fields


def _structured_fields(entry_id: str) -> dict[str, object]:
    fields = _catalog_fields(entry_id)
    fields.update(_activity_rules(entry_id))
    if entry_id in _MATRIX_REGIME:
        fields["ideal_iv_regime"] = _MATRIX_REGIME[entry_id]
    return fields


def _specials() -> dict[str, KnowledgeEntry]:
    buy = _entry(
        entry_id="apex_benchmark_greeks_buy",
        title="APEX Benchmark Greeks Strategy",
        registry_ids=("apex_benchmark_greeks_strategy",),
        summary=BENCHMARK_SUMMARY,
        why_it_fits=f"{RULE1_WHY} {RULE1_RATIO}",
        how_to_use=RULE1_HOW,
        key_risks=RULE1_RISKS,
        outlook="directional",
        vol_view="Buy when option IV is below 20-day close-to-close historical volatility, annualized with sqrt(252).",
        greeks_profile="Long gamma and long vega. A call is long delta. A put is short delta. Daily theta is small relative to the premium.",
        ideal_conditions="Technical trend and sentiment are both clearly aligned, absolute delta is at least 0.55, and DTE is 30 to 90.",
        when_not_to_use="Do not buy under Rule 1 when any Rule 1 gate fails. Another structure can still be selected.",
        assignment_dividend_pin="The option is long, so the holder is not assigned.",
        entry_management_exit=RULE1_HOW,
        max_profit="Long call: unlimited. Long put: (strike − premium) × multiplier × contracts.",
        max_loss="Premium × multiplier × contracts.",
        breakevens="Long call: strike + premium. Long put: strike − premium.",
        capital_or_margin="The full premium.",
        reference=_OCC,
        verbatim=True,
    )
    sell = _entry(
        entry_id="apex_benchmark_greeks_sell",
        title="APEX Benchmark Greeks Strategy",
        registry_ids=("short_iron_condor", "bull_put_spread_credit", "bear_call_spread_credit"),
        summary=BENCHMARK_SUMMARY,
        why_it_fits=f"{RULE2_WHY} {RULE2_PROBABILITY}",
        how_to_use=RULE2_HOW,
        key_risks=RULE2_RISKS,
        outlook="neutral or mild",
        vol_view="Sell when IV Rank, 252-day lookback, is above 50 and RSI(14) is between 40 and 60.",
        greeks_profile="Defined-risk short premium: short gamma near the spot, positive theta, short vega. A long wing is required.",
        ideal_conditions="Neutral tape uses an iron condor. Mild bullish uses a bull put spread. Mild bearish uses a bear call spread.",
        when_not_to_use="Never a naked short. If a Rule 2 gate fails, that structure is ineligible and another strategy can still be selected.",
        assignment_dividend_pin=RULE2_RISKS,
        entry_management_exit=RULE2_HOW,
        max_profit="Credit spread and iron condor: net credit × multiplier × contracts.",
        max_loss="Credit spread: (width − net credit) × multiplier × contracts. Iron condor: (wider wing width − net credit) × multiplier × contracts.",
        breakevens="Credit spread: short put strike minus credit, or short call strike plus credit. Iron condor: short put strike minus net credit, and short call strike plus net credit.",
        capital_or_margin="The maximum loss. The long wing is part of the order.",
        reference=_CBOE,
        verbatim=True,
    )
    gamma = _entry(
        entry_id="gamma_trampoline",
        title="Gamma Trampoline™",
        registry_ids=("apex_strategy",),
        summary=f"{GAMMA_SUMMARY} {GAMMA_PROBLEM}",
        why_it_fits=GAMMA_SCENARIOS,
        how_to_use=GAMMA_HOW,
        key_risks=(
            "The maximum loss is the net debit when all four legs are closed together by the front-week expiration. "
            "Early assignment is possible, especially before an ex-dividend date. "
            + GAMMA_CLASSIFIER
        ),
        outlook="neutral",
        vol_view="Front-week implied volatility is elevated versus the later expiration and is expected to fall after the announcement.",
        greeks_profile=GAMMA_GREEKS,
        ideal_conditions="Confirmed earnings in 5 to 10 calendar days, front-week IV rank above 70, and front IV at least 1.25 times back IV.",
        when_not_to_use=GAMMA_CLASSIFIER,
        assignment_dividend_pin=(
            "Do not hold the short legs into their expiration close, where assignment and pin risk rise. "
            "Early assignment is possible, especially on a short call before an ex-dividend date."
        ),
        entry_management_exit=GAMMA_HOW,
        max_profit="No closed form. The maximum on the card is the front-expiry grid under the stated post-earnings IV assumption.",
        max_loss="The net debit when all four legs are closed together by front-week expiration.",
        breakevens="Two prices from the same European Black-Scholes grid, with the IV assumption shown.",
        capital_or_margin="The net debit.",
        reference=_OIC + " " + GAMMA_CLASSIFIER,
        verbatim=True,
    )
    return {
        "apex_benchmark_greeks_buy": buy,
        "apex_benchmark_greeks_sell": sell,
        "gamma_trampoline": gamma,
    }


def knowledge_entries() -> dict[str, KnowledgeEntry]:
    entries = {spec_id: _template(spec_id) for spec_id in STRATEGY_REGISTRY}
    entries.update(_specials())
    # The registry id stays APEX Strategy. Gamma Trampoline™ is a separate label.
    apex = entries["apex_strategy"]
    entries["apex_strategy"] = replace(
        apex,
        summary=(
            "APEX Strategy. The four legs are a double calendar: sell the front-week call and put "
            "and buy the same strikes in the later expiration. " + GAMMA_CLASSIFIER
        ),
        when_not_to_use=GAMMA_CLASSIFIER,
        key_risks=f"{apex.key_risks} {GAMMA_CLASSIFIER}",
    )
    entries["apex_benchmark_greeks_strategy"] = _specials()["apex_benchmark_greeks_buy"]
    entries["reverse_calendar"] = _entry(
        entry_id="reverse_calendar",
        title="Reverse Calendar",
        registry_ids=("reverse_calendar",),
        summary="Reverse Calendar. Buy the nearer call and sell the same strike in a later expiration.",
        why_it_fits="The near call is the long leg. The later call is the short leg.",
        how_to_use="Enter the two legs together. The later short is still open after the near call expires.",
        key_risks="After the near call expires, the short later call is uncovered. Loss on that remaining short call is not capped by the near leg.",
        outlook="directional",
        vol_view="The later option is short, so a rise in its implied volatility hurts.",
        greeks_profile="Short the later call's vega and gamma once the near call has expired.",
        ideal_conditions="A view that the later option is rich relative to the near option.",
        when_not_to_use="Do not treat this as a standard calendar. The short leg is the later expiration.",
        assignment_dividend_pin="The short later call can be assigned, including before an ex-dividend date.",
        entry_management_exit="Close the short later call before or when the near call expires. Do not leave it uncovered.",
        max_profit="No closed form. The card grid is the value at the near expiration under European Black-Scholes.",
        max_loss="Not capped by the near-term debit. After the near call expires the remaining short call is uncovered.",
        breakevens="Solved on the near-expiration grid, not by the standard long-calendar debit formula.",
        capital_or_margin="Margin on the uncovered later short call. It is not the net debit alone.",
        reference=_OCC,
    )
    return entries


def entry_for(strategy_name_or_id: str) -> KnowledgeEntry | None:
    entries = knowledge_entries()
    if strategy_name_or_id in entries:
        return entries[strategy_name_or_id]
    from app.strategies.registry import resolve_strategy_id

    sid = resolve_strategy_id(strategy_name_or_id)
    if sid and sid in entries:
        return entries[sid]
    if strategy_name_or_id in {"Gamma Trampoline™", "Gamma Trampoline"}:
        return entries["gamma_trampoline"]
    return None


def validate_entries(entries: dict[str, KnowledgeEntry]) -> list[str]:
    """Return errors for a catalog snapshot. Startup and CI call this with the live catalog."""
    errors: list[str] = []
    if KB_VERSION != "12.0":
        errors.append(f"knowledge base version {KB_VERSION} is not 12.0")
    if not any(row["version"] == "11.2" for row in CHANGELOG):
        errors.append("changelog is missing version 11.2")
    if not any(row["version"] == "12.0" for row in CHANGELOG):
        errors.append("changelog is missing version 12.0")
    covered: set[str] = set()
    for entry in entries.values():
        covered.update(entry.registry_ids)
        for field in REQUIRED_KB_FIELDS:
            if not str(getattr(entry, field) or "").strip():
                errors.append(f"{entry.entry_id} missing {field}")
        if entry.vega_sign not in _VEGA_SIGNS:
            errors.append(f"{entry.entry_id} vega_sign {entry.vega_sign} is not an allowed sign")
        if entry.theta_sign not in _THETA_SIGNS:
            errors.append(f"{entry.entry_id} theta_sign {entry.theta_sign} is not an allowed sign")
        if entry.gamma_sign not in _GAMMA_SIGNS:
            errors.append(f"{entry.entry_id} gamma_sign {entry.gamma_sign} is not an allowed sign")
        if entry.ideal_iv_regime not in _IV_REGIMES:
            errors.append(f"{entry.entry_id} ideal_iv_regime {entry.ideal_iv_regime} is not an allowed regime")
        if entry.approval_level not in _APPROVAL_LEVELS:
            errors.append(f"{entry.entry_id} approval_level {entry.approval_level} is not an allowed class")
        if entry.version != KB_VERSION:
            errors.append(f"{entry.entry_id} version {entry.version} is not {KB_VERSION}")
        if entry.dte_min is not None and entry.dte_max is not None and entry.dte_min > entry.dte_max:
            errors.append(f"{entry.entry_id} dte_min {entry.dte_min} is above dte_max {entry.dte_max}")
        if not any(name in entry.reference for name in _REFERENCE_NAMES):
            errors.append(f"{entry.entry_id} reference does not name OCC, Options Industry Council, or Cboe")
        if entry.verbatim:
            continue
        blob = " ".join(str(getattr(entry, field)) for field in REQUIRED_KB_FIELDS).lower()
        for phrase in _BANNED:
            if phrase in blob:
                errors.append(f"{entry.entry_id} contains unsupported phrase {phrase}")
        if " always " in f" {blob} ":
            errors.append(f"{entry.entry_id} contains unsupported word always")
    missing = [sid for sid in STRATEGY_REGISTRY if sid not in covered]
    if missing:
        errors.append("uncovered strategies: " + ", ".join(missing))
    gamma = entries.get("gamma_trampoline")
    if gamma is None:
        errors.append("gamma_trampoline entry is missing")
    else:
        if gamma.title != "Gamma Trampoline™":
            errors.append("gamma_trampoline title was renamed")
        for paragraph in (GAMMA_SUMMARY, GAMMA_PROBLEM, GAMMA_GREEKS, GAMMA_SCENARIOS, GAMMA_HOW, GAMMA_CLASSIFIER):
            blob = " ".join(
                (
                    gamma.summary,
                    gamma.why_it_fits,
                    gamma.how_to_use,
                    gamma.key_risks,
                    gamma.greeks_profile,
                    gamma.when_not_to_use,
                    gamma.entry_management_exit,
                    gamma.reference,
                )
            )
            if paragraph not in blob:
                errors.append("gamma_trampoline is missing a Change 11 v2 paragraph")
                break
    calendar = entries.get("double_calendar")
    if calendar is None or calendar.title != "Double Calendar":
        errors.append("double_calendar title must stay Double Calendar")
    elif "Gamma Trampoline" in calendar.title:
        errors.append("double_calendar title must not use the earnings label")
    apex = entries.get("apex_strategy")
    if apex is None or apex.title != "APEX Strategy":
        errors.append("apex_strategy title must stay APEX Strategy")
    elif GAMMA_CLASSIFIER not in f"{apex.summary} {apex.when_not_to_use}":
        errors.append("apex_strategy is missing the Change 11 classifier sentence")
    return errors


def validate_knowledge_base() -> list[str]:
    """Return errors. An empty list means the base is valid for startup and CI."""
    return validate_entries(knowledge_entries())
