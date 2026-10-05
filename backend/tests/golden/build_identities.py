"""One-shot writer for stated-premium expiry identities. Not part of the suite."""

from __future__ import annotations

import pprint
from pathlib import Path

MULTI = (
    "Two expirations. Value at the near expiration depends on the later option's implied volatility. "
    "The repository and docs/qa/APEX_QA_Test_Results.csv have no recorded bid/ask chain, "
    "so five chain fixtures were not built."
)
ADVISORY = "Advisory label. There are no legs and no payoff grid."
DISPERSION = (
    "Two underlyings. No recorded pair of chains is in the repository or the QA CSV."
)

INCOMPLETE = {
    "calendar_spread": MULTI,
    "calendar_put_spread": MULTI,
    "calendar_call_spread": MULTI,
    "diagonal_spread_bullish": MULTI,
    "diagonal_spread_bearish": MULTI,
    "diagonal_call_spread": MULTI,
    "reverse_calendar": MULTI,
    "double_calendar": MULTI,
    "double_diagonal": MULTI,
    "calendar_straddle": MULTI,
    "vega_neutral_spread": MULTI,
    "jelly_roll": MULTI,
    "apex_strategy": MULTI,
    "poor_mans_covered_call": MULTI,
    "dispersion_trade": DISPERSION,
    "no_trade_insufficient_conviction": ADVISORY,
    "no_trade_wait_iv_crush": ADVISORY,
}

SOURCE = (
    "Stated premium identity using the OCC expiry payoff "
    "(long value is intrinsic minus premium; short is the reverse). "
    "Not a recorded OPRA or Alpaca chain."
)


def opt(action: str, side: str, strike: float, mid: float, qty: int = 1) -> dict:
    return {
        "action": action,
        "side": side,
        "strike": float(strike),
        "mid": float(mid),
        "quantity": qty,
    }


def stock(action: str, price: float, shares: int = 100) -> dict:
    return {"action": action, "side": "stock", "strike": float(price), "mid": float(price), "quantity": shares}


def pnl(legs: list[dict], underlying: float) -> float:
    total = 0.0
    for leg in legs:
        qty = int(leg["quantity"])
        premium = float(leg["mid"])
        if leg["side"] == "stock":
            signed = (underlying - premium) if leg["action"] == "buy" else (premium - underlying)
            total += signed * qty
            continue
        strike = float(leg["strike"])
        if leg["side"] == "call":
            intrinsic = max(underlying - strike, 0.0)
        else:
            intrinsic = max(strike - underlying, 0.0)
        signed = (intrinsic - premium) if leg["action"] == "buy" else (premium - intrinsic)
        total += signed * qty * 100
    return round(total, 2)


def scenario(name: str, legs: list[dict], spots: list[float], breakevens: list[float]) -> dict:
    checks = [(round(spot, 2), pnl(legs, spot)) for spot in spots]
    clean_be = []
    for be in breakevens:
        if abs(pnl(legs, be)) <= 0.01:
            clean_be.append(round(be, 2))
    return {
        "name": name,
        "legs": legs,
        "checks": checks,
        "breakevens": clean_be,
        "source": SOURCE,
        "feed": "none",
        "function": "app.strategies.payoffs.helpers.multi_leg_payoff_at_expiry",
    }


def five(shape: str, rows: list[tuple[list[dict], list[float], list[float]]]) -> list[dict]:
    assert len(rows) == 5, shape
    return [scenario(f"{shape}-{index + 1}", legs, spots, bes) for index, (legs, spots, bes) in enumerate(rows)]


def call_debit(k: float, width: float, long_mid: float, short_mid: float) -> tuple[list[dict], list[float], list[float]]:
    debit = round(long_mid - short_mid, 2)
    be = round(k + debit, 2)
    legs = [opt("buy", "call", k, long_mid), opt("sell", "call", k + width, short_mid)]
    return legs, [k - width, k, be, k + width, k + width + 15], [be]


def put_debit(k: float, width: float, long_mid: float, short_mid: float) -> tuple[list[dict], list[float], list[float]]:
    debit = round(long_mid - short_mid, 2)
    be = round(k - debit, 2)
    legs = [opt("buy", "put", k, long_mid), opt("sell", "put", k - width, short_mid)]
    return legs, [k + width, k, be, k - width, max(k - width - 15, 0)], [be]


def put_credit(short_k: float, width: float, short_mid: float, long_mid: float) -> tuple[list[dict], list[float], list[float]]:
    credit = round(short_mid - long_mid, 2)
    be = round(short_k - credit, 2)
    legs = [opt("sell", "put", short_k, short_mid), opt("buy", "put", short_k - width, long_mid)]
    return legs, [short_k + 10, short_k, be, short_k - width, max(short_k - width - 10, 0)], [be]


def call_credit(short_k: float, width: float, short_mid: float, long_mid: float) -> tuple[list[dict], list[float], list[float]]:
    credit = round(short_mid - long_mid, 2)
    be = round(short_k + credit, 2)
    legs = [opt("sell", "call", short_k, short_mid), opt("buy", "call", short_k + width, long_mid)]
    return legs, [short_k - 10, short_k, be, short_k + width, short_k + width + 15], [be]


def condor(sp: float, lp: float, sc: float, lc: float, mids: tuple[float, float, float, float]) -> tuple[list[dict], list[float], list[float]]:
    credit = round(mids[0] + mids[2] - mids[1] - mids[3], 2)
    bes = [round(sp - credit, 2), round(sc + credit, 2)]
    legs = [
        opt("sell", "put", sp, mids[0]),
        opt("buy", "put", lp, mids[1]),
        opt("sell", "call", sc, mids[2]),
        opt("buy", "call", lc, mids[3]),
    ]
    return legs, [max(lp - 10, 0), bes[0], (sp + sc) / 2, bes[1], lc + 15], bes


def long_condor(lp: float, sp: float, lc: float, sc: float, mids: tuple[float, float, float, float]) -> tuple[list[dict], list[float], list[float]]:
    debit = round(mids[0] + mids[2] - mids[1] - mids[3], 2)
    bes = [round(lp + debit, 2), round(lc - debit, 2)]
    legs = [
        opt("buy", "put", lp, mids[0]),
        opt("sell", "put", sp, mids[1]),
        opt("buy", "call", lc, mids[2]),
        opt("sell", "call", sc, mids[3]),
    ]
    return legs, [max(sp - 10, 0), bes[0], (lp + lc) / 2, bes[1], sc + 15], bes


SCENARIOS: dict[str, list[dict]] = {
    "long_call": five(
        "long_call",
        [
            ([opt("buy", "call", k, p)], [k - 10, k, round(k + p, 2), k + 10, k + 20], [round(k + p, 2)])
            for k, p in ((100, 2.0), (50, 1.25), (80, 4.5), (120, 3.0), (95, 0.75))
        ],
    ),
    "long_put": five(
        "long_put",
        [
            ([opt("buy", "put", k, p)], [k + 10, k, round(k - p, 2), max(k - 10, 0), max(k - 25, 0)], [round(k - p, 2)])
            for k, p in ((100, 2.0), (50, 1.25), (80, 4.5), (40, 3.0), (95, 0.75))
        ],
    ),
    "short_call": five(
        "short_call",
        [
            ([opt("sell", "call", k, p)], [k - 10, k, round(k + p, 2), k + 10, k + 30], [round(k + p, 2)])
            for k, p in ((100, 1.5), (90, 2.25), (110, 0.8), (75, 3.4), (130, 1.1))
        ],
    ),
    "short_put": five(
        "short_put",
        [
            ([opt("sell", "put", k, p)], [k + 10, k, round(k - p, 2), max(k - 15, 0), 0], [round(k - p, 2)])
            for k, p in ((100, 1.5), (80, 2.0), (60, 1.25), (95, 3.5), (110, 0.9))
        ],
    ),
    "call_debit": five(
        "call_debit",
        [call_debit(*row) for row in ((100, 5, 3.9, 1.9), (80, 10, 6.0, 2.5), (50, 5, 2.2, 0.7), (120, 5, 4.4, 1.4), (95, 2.5, 1.8, 0.55))],
    ),
    "put_debit": five(
        "put_debit",
        [put_debit(*row) for row in ((100, 5, 3.6, 1.6), (80, 10, 5.5, 2.0), (60, 5, 2.4, 0.9), (110, 5, 4.1, 1.6), (90, 2.5, 1.7, 0.45))],
    ),
    "put_credit": five(
        "put_credit",
        [put_credit(*row) for row in ((100, 5, 2.5, 1.0), (90, 5, 1.8, 0.6), (80, 10, 3.2, 1.1), (110, 5, 2.2, 0.7), (70, 5, 1.5, 0.4))],
    ),
    "call_credit": five(
        "call_credit",
        [call_credit(*row) for row in ((105, 5, 2.4, 0.9), (95, 5, 1.7, 0.5), (120, 10, 3.0, 0.8), (80, 5, 2.1, 0.6), (100, 5, 1.4, 0.35))],
    ),
    "long_straddle": five(
        "long_straddle",
        [
            (
                [opt("buy", "call", k, c), opt("buy", "put", k, p)],
                [k - (c + p), k, k + (c + p), k - 15, k + 20],
                [round(k - (c + p), 2), round(k + (c + p), 2)],
            )
            for k, c, p in ((100, 3.0, 2.5), (80, 2.0, 2.0), (50, 1.5, 1.25), (120, 4.0, 3.5), (90, 1.1, 0.9))
        ],
    ),
    "long_strangle": five(
        "long_strangle",
        [
            (
                [opt("buy", "call", call_k, c), opt("buy", "put", put_k, p)],
                [put_k - (c + p), put_k, (put_k + call_k) / 2, call_k, call_k + (c + p)],
                [round(put_k - (c + p), 2), round(call_k + (c + p), 2)],
            )
            for put_k, call_k, c, p in ((95, 105, 1.2, 1.0), (80, 90, 1.5, 1.4), (70, 80, 0.8, 0.7), (100, 110, 2.0, 1.8), (90, 100, 0.6, 0.55))
        ],
    ),
    "short_straddle": five(
        "short_straddle",
        [
            (
                [opt("sell", "call", k, c), opt("sell", "put", k, p)],
                [k - (c + p), k, k + (c + p), k - 20, k + 25],
                [round(k - (c + p), 2), round(k + (c + p), 2)],
            )
            for k, c, p in ((100, 2.5, 2.2), (80, 1.8, 1.6), (60, 1.2, 1.1), (110, 3.0, 2.7), (90, 0.9, 0.8))
        ],
    ),
    "short_strangle": five(
        "short_strangle",
        [
            (
                [opt("sell", "call", call_k, c), opt("sell", "put", put_k, p)],
                [put_k - (c + p), put_k, (put_k + call_k) / 2, call_k, call_k + (c + p)],
                [round(put_k - (c + p), 2), round(call_k + (c + p), 2)],
            )
            for put_k, call_k, c, p in ((95, 105, 1.1, 0.9), (70, 90, 1.4, 1.2), (80, 100, 0.7, 0.6), (90, 110, 1.8, 1.5), (85, 95, 0.5, 0.45))
        ],
    ),
    "long_guts": five(
        "long_guts",
        [
            (
                [opt("buy", "call", call_k, c), opt("buy", "put", put_k, p)],
                [call_k, (call_k + put_k) / 2, put_k, max(call_k - 15, 0), put_k + 15],
                [],
            )
            for call_k, put_k, c, p in ((95, 105, 8.0, 7.5), (80, 90, 7.0, 6.5), (70, 80, 6.0, 5.5), (100, 110, 9.0, 8.5), (90, 100, 7.2, 6.8))
        ],
    ),
    "short_guts": five(
        "short_guts",
        [
            (
                [opt("sell", "call", call_k, c), opt("sell", "put", put_k, p)],
                [call_k, (call_k + put_k) / 2, put_k, max(call_k - 15, 0), put_k + 15],
                [],
            )
            for call_k, put_k, c, p in ((95, 105, 8.0, 7.5), (80, 90, 7.0, 6.5), (70, 80, 6.0, 5.5), (100, 110, 9.0, 8.5), (90, 100, 7.2, 6.8))
        ],
    ),
    "strip": five(
        "strip",
        [
            (
                [opt("buy", "call", k, c, 1), opt("buy", "put", k, p, 2)],
                [max(k - 20, 0), k, k + 10, k + 20, k - 5],
                [],
            )
            for k, c, p in ((100, 2.5, 2.0), (80, 1.8, 1.5), (60, 1.2, 1.0), (110, 3.0, 2.4), (90, 1.0, 0.8))
        ],
    ),
    "strap": five(
        "strap",
        [
            (
                [opt("buy", "call", k, c, 2), opt("buy", "put", k, p, 1)],
                [max(k - 20, 0), k, k + 10, k + 20, k - 5],
                [],
            )
            for k, c, p in ((100, 2.5, 2.0), (80, 1.8, 1.5), (60, 1.2, 1.0), (110, 3.0, 2.4), (90, 1.0, 0.8))
        ],
    ),
}

# Iron butterfly: sell ATM call and put, buy wings.
SCENARIOS["iron_butterfly"] = five(
    "iron_butterfly",
    [
        (
            [
                opt("sell", "put", body, sp),
                opt("buy", "put", body - wing, lp),
                opt("sell", "call", body, sc),
                opt("buy", "call", body + wing, lc),
            ],
            [body - wing - 5, body - wing, body, body + wing, body + wing + 10],
            [round(body - (sp + sc - lp - lc), 2), round(body + (sp + sc - lp - lc), 2)],
        )
        for body, wing, sp, lp, sc, lc in (
            (100, 5, 3.2, 1.4, 3.0, 1.2),
            (80, 5, 2.5, 1.0, 2.4, 0.9),
            (90, 10, 4.0, 1.5, 3.8, 1.3),
            (110, 5, 2.8, 1.1, 2.6, 1.0),
            (70, 5, 2.0, 0.7, 1.9, 0.6),
        )
    ],
)

SCENARIOS["short_iron_condor"] = five(
    "short_iron_condor",
    [
        condor(95, 90, 105, 110, mids)
        for mids in ((1.5, 0.5, 1.2, 0.4), (2.0, 0.8, 1.8, 0.6), (1.2, 0.3, 1.1, 0.25), (2.4, 1.0, 2.2, 0.9), (1.8, 0.7, 1.6, 0.5))
    ],
)

SCENARIOS["long_iron_condor"] = five(
    "long_iron_condor",
    [
        long_condor(95, 90, 105, 110, mids)
        for mids in ((2.2, 1.0, 2.0, 0.8), (1.8, 0.6, 1.6, 0.4), (2.6, 1.2, 2.4, 1.0), (1.5, 0.4, 1.4, 0.3), (3.0, 1.5, 2.8, 1.3))
    ],
)


def butterfly(side: str, lower: float, body: float, upper: float, mids: tuple[float, float, float], short: bool) -> tuple[list[dict], list[float], list[float]]:
    low, mid, high = mids
    if short:
        legs = [opt("sell", side, lower, low), opt("buy", side, body, mid, 2), opt("sell", side, upper, high)]
        credit = round(low + high - 2 * mid, 2)
        bes = [round(lower + credit, 2), round(upper - credit, 2)] if credit > 0 else []
    else:
        legs = [opt("buy", side, lower, low), opt("sell", side, body, mid, 2), opt("buy", side, upper, high)]
        debit = round(low + high - 2 * mid, 2)
        bes = [round(lower + debit, 2), round(upper - debit, 2)] if debit > 0 else []
    return legs, [max(lower - 10, 0), lower, body, upper, upper + 15], bes


SCENARIOS["long_call_butterfly"] = five(
    "long_call_butterfly",
    [butterfly("call", 100, 105, 110, mids, False) for mids in ((6.0, 3.5, 2.0), (5.0, 2.8, 1.4), (7.0, 4.0, 2.2), (4.5, 2.4, 1.1), (8.0, 4.6, 2.5))],
)
SCENARIOS["long_put_butterfly"] = five(
    "long_put_butterfly",
    [butterfly("put", 90, 95, 100, mids, False) for mids in ((2.0, 3.4, 6.0), (1.2, 2.6, 5.0), (1.5, 3.0, 5.5), (0.9, 2.2, 4.4), (2.4, 4.0, 7.0))],
)
SCENARIOS["short_call_butterfly"] = five(
    "short_call_butterfly",
    [butterfly("call", 100, 105, 110, mids, True) for mids in ((6.0, 3.5, 2.0), (5.0, 2.8, 1.4), (7.0, 4.0, 2.2), (4.5, 2.4, 1.1), (8.0, 4.6, 2.5))],
)
SCENARIOS["short_put_butterfly"] = five(
    "short_put_butterfly",
    [butterfly("put", 90, 95, 100, mids, True) for mids in ((2.0, 3.4, 6.0), (1.2, 2.6, 5.0), (1.5, 3.0, 5.5), (0.9, 2.2, 4.4), (2.4, 4.0, 7.0))],
)

# Broken wing: body is twice, upper wing is wider. No single closed breakeven is asserted.
SCENARIOS["broken_wing"] = five(
    "broken_wing",
    [
        (
            [opt("buy", "call", 100, low), opt("sell", "call", 105, mid, 2), opt("buy", "call", 115, high)],
            [90, 100, 105, 115, 130],
            [],
        )
        for low, mid, high in ((6.0, 3.4, 1.2), (5.5, 3.0, 0.9), (7.0, 4.0, 1.5), (4.8, 2.6, 0.7), (6.5, 3.6, 1.1))
    ],
)

SCENARIOS["call_condor"] = five(
    "call_condor",
    [
        (
            [opt("buy", "call", 90, a), opt("sell", "call", 95, b), opt("sell", "call", 105, c), opt("buy", "call", 110, d)],
            [80, 90, 100, 110, 125],
            [],
        )
        for a, b, c, d in ((8.0, 5.0, 2.0, 1.0), (7.0, 4.2, 1.6, 0.7), (9.0, 5.5, 2.4, 1.2), (6.5, 3.8, 1.4, 0.6), (8.5, 5.2, 2.1, 0.9))
    ],
)
SCENARIOS["put_condor"] = five(
    "put_condor",
    [
        (
            [opt("buy", "put", 110, a), opt("sell", "put", 105, b), opt("sell", "put", 95, c), opt("buy", "put", 90, d)],
            [80, 90, 100, 110, 120],
            [],
        )
        for a, b, c, d in ((8.0, 5.0, 2.0, 1.0), (7.0, 4.2, 1.6, 0.7), (9.0, 5.5, 2.4, 1.2), (6.5, 3.8, 1.4, 0.6), (8.5, 5.2, 2.1, 0.9))
    ],
)

SCENARIOS["long_iron_butterfly"] = five(
    "long_iron_butterfly",
    [
        (
            [
                opt("buy", "put", body, bp),
                opt("sell", "put", body - wing, sp),
                opt("buy", "call", body, bc),
                opt("sell", "call", body + wing, sc),
            ],
            [body - wing - 5, body, body + wing, body - 15, body + 20],
            [],
        )
        for body, wing, bp, sp, bc, sc in (
            (100, 5, 4.0, 1.5, 3.8, 1.4),
            (80, 5, 3.2, 1.1, 3.0, 1.0),
            (90, 10, 5.0, 1.6, 4.8, 1.5),
            (110, 5, 3.6, 1.2, 3.4, 1.1),
            (70, 5, 2.8, 0.9, 2.6, 0.8),
        )
    ],
)

SCENARIOS["christmas_tree"] = five(
    "christmas_tree",
    [
        (
            [opt("buy", "call", 100, a), opt("sell", "call", 105, b), opt("sell", "call", 110, c)],
            [90, 100, 105, 110, 140],
            [],
        )
        for a, b, c in ((6.0, 3.0, 1.5), (5.0, 2.4, 1.1), (7.0, 3.6, 1.8), (4.5, 2.0, 0.9), (6.5, 3.2, 1.6))
    ],
)

SCENARIOS["call_ratio_1x2"] = five(
    "call_ratio_1x2",
    [
        (
            [opt("buy", "call", 100, a), opt("sell", "call", 105, b, 2)],
            [90, 100, 105, 110, 130],
            [],
        )
        for a, b in ((4.0, 1.8), (5.0, 2.2), (3.5, 1.4), (6.0, 2.6), (4.5, 2.0))
    ],
)
SCENARIOS["put_ratio_1x2"] = five(
    "put_ratio_1x2",
    [
        (
            [opt("buy", "put", 100, a), opt("sell", "put", 95, b, 2)],
            [110, 100, 95, 90, 70],
            [],
        )
        for a, b in ((3.8, 1.6), (4.5, 2.0), (3.0, 1.2), (5.0, 2.3), (2.8, 1.1))
    ],
)
SCENARIOS["call_ratio_2x1"] = five(
    "call_ratio_2x1",
    [
        (
            [opt("buy", "call", 100, a, 2), opt("sell", "call", 110, b)],
            [90, 100, 110, 120, 140],
            [],
        )
        for a, b in ((3.0, 1.2), (4.0, 1.6), (2.5, 0.9), (5.0, 2.0), (3.5, 1.4))
    ],
)
SCENARIOS["call_backspread"] = five(
    "call_backspread",
    [
        (
            [opt("sell", "call", 100, a), opt("buy", "call", 105, b, 2)],
            [90, 100, 105, 115, 130],
            [],
        )
        for a, b in ((4.0, 1.6), (5.0, 2.0), (3.2, 1.2), (6.0, 2.4), (4.5, 1.8))
    ],
)
SCENARIOS["put_backspread"] = five(
    "put_backspread",
    [
        (
            [opt("sell", "put", 100, a), opt("buy", "put", 95, b, 2)],
            [110, 100, 95, 85, 70],
            [],
        )
        for a, b in ((3.6, 1.4), (4.2, 1.7), (2.8, 1.0), (5.0, 2.1), (3.2, 1.2))
    ],
)
SCENARIOS["jade_lizard"] = five(
    "jade_lizard",
    [
        (
            [opt("sell", "put", 95, p), opt("sell", "call", 105, sc), opt("buy", "call", 110, lc)],
            [80, 95, 100, 105, 120],
            [],
        )
        for p, sc, lc in ((1.5, 1.2, 0.4), (2.0, 1.6, 0.6), (1.1, 0.9, 0.25), (1.8, 1.4, 0.5), (2.4, 1.9, 0.7))
    ],
)
SCENARIOS["reverse_jade"] = five(
    "reverse_jade",
    [
        (
            [opt("sell", "call", 105, c), opt("sell", "put", 95, sp), opt("buy", "put", 90, lp)],
            [80, 95, 100, 105, 120],
            [],
        )
        for c, sp, lp in ((1.4, 1.6, 0.5), (1.8, 2.0, 0.7), (1.0, 1.2, 0.3), (2.2, 2.4, 0.9), (1.5, 1.7, 0.55))
    ],
)


def covered(price: float, strike: float, premium: float) -> tuple[list[dict], list[float], list[float]]:
    be = round(price - premium, 2)
    legs = [stock("buy", price), opt("sell", "call", strike, premium)]
    return legs, [0, be, price, strike, strike + 20], [be]


def protective(price: float, strike: float, premium: float) -> tuple[list[dict], list[float], list[float]]:
    be = round(price + premium, 2)
    legs = [stock("buy", price), opt("buy", "put", strike, premium)]
    return legs, [0, strike, price, be, price + 20], [be]


SCENARIOS["covered_call"] = five(
    "covered_call",
    [covered(*row) for row in ((100, 105, 2.0), (80, 90, 1.5), (150, 160, 4.0), (50, 55, 1.25), (120, 125, 2.75))],
)
SCENARIOS["covered_put"] = five(
    "covered_put",
    [
        (
            [stock("sell", price), opt("sell", "put", strike, premium)],
            [0, strike, price, round(price + premium, 2), price + 25],
            [round(price + premium, 2)],
        )
        for price, strike, premium in ((100, 95, 1.8), (80, 75, 1.4), (120, 110, 2.5), (60, 55, 1.1), (90, 85, 2.0))
    ],
)
SCENARIOS["protective_put"] = five(
    "protective_put",
    [protective(*row) for row in ((100, 95, 2.0), (80, 75, 1.5), (150, 140, 4.0), (50, 45, 1.25), (120, 110, 3.0))],
)
SCENARIOS["leveraged"] = five(
    "leveraged",
    [
        (
            [stock("buy", price), opt("buy", "call", strike, premium)],
            [0, price, round(price + premium, 2), strike, price + 30],
            [round(price + premium, 2)],
        )
        for price, strike, premium in ((100, 100, 3.0), (80, 80, 2.5), (50, 55, 1.5), (120, 120, 4.0), (90, 95, 2.0))
    ],
)
SCENARIOS["collar"] = five(
    "collar",
    [
        (
            [stock("buy", price), opt("buy", "put", put_k, put_p), opt("sell", "call", call_k, call_p)],
            [0, put_k, price, call_k, call_k + 15],
            [round(price + put_p - call_p, 2)],
        )
        for price, put_k, put_p, call_k, call_p in (
            (100, 95, 2.0, 105, 1.5),
            (80, 75, 1.6, 90, 1.1),
            (120, 110, 3.0, 130, 2.5),
            (50, 45, 1.4, 55, 0.9),
            (90, 85, 2.2, 100, 1.7),
        )
    ],
)
SCENARIOS["synthetic_long"] = five(
    "synthetic_long",
    [
        (
            [opt("buy", "call", k, c), opt("sell", "put", k, p)],
            [max(k - 20, 0), k, round(k + c - p, 2), k + 15, k + 30],
            [round(k + c - p, 2)],
        )
        for k, c, p in ((100, 3.0, 2.5), (80, 2.2, 2.0), (60, 1.8, 1.5), (120, 4.0, 3.6), (90, 2.5, 2.1))
    ],
)
SCENARIOS["synthetic_short"] = five(
    "synthetic_short",
    [
        (
            [opt("sell", "call", k, c), opt("buy", "put", k, p)],
            [max(k - 20, 0), k, round(k + c - p, 2), k + 15, k + 30],
            [round(k + c - p, 2)],
        )
        for k, c, p in ((100, 3.0, 2.5), (80, 2.2, 2.0), (60, 1.8, 1.5), (120, 4.0, 3.6), (90, 2.5, 2.1))
    ],
)
SCENARIOS["synthetic_put"] = five(
    "synthetic_put",
    [
        (
            [stock("sell", price), opt("buy", "call", strike, premium)],
            [0, price, strike, round(price - premium, 2), price + 20],
            [round(price - premium, 2)] if price - premium < strike else [strike],
        )
        for price, strike, premium in ((100, 100, 3.0), (80, 85, 2.0), (120, 120, 4.5), (60, 65, 1.5), (90, 90, 2.5))
    ],
)
SCENARIOS["conversion"] = five(
    "conversion",
    [
        (
            [stock("buy", price), opt("sell", "call", k, c), opt("buy", "put", k, p)],
            [max(k - 20, 0), k, price, k + 10, k + 25],
            [],
        )
        for price, k, c, p in ((100, 100, 3.0, 2.8), (80, 80, 2.4, 2.2), (120, 120, 4.0, 3.7), (50, 50, 1.8, 1.6), (90, 90, 2.6, 2.5))
    ],
)
SCENARIOS["reversal"] = five(
    "reversal",
    [
        (
            [stock("sell", price), opt("buy", "call", k, c), opt("sell", "put", k, p)],
            [max(k - 20, 0), k, price, k + 10, k + 25],
            [],
        )
        for price, k, c, p in ((100, 100, 3.0, 2.8), (80, 80, 2.4, 2.2), (120, 120, 4.0, 3.7), (50, 50, 1.8, 1.6), (90, 90, 2.6, 2.5))
    ],
)
SCENARIOS["box"] = five(
    "box",
    [
        (
            [
                opt("buy", "call", low, lc),
                opt("sell", "call", high, sc),
                opt("buy", "put", high, hp),
                opt("sell", "put", low, lp),
            ],
            [max(low - 10, 0), low, (low + high) / 2, high, high + 10],
            [],
        )
        for low, high, lc, sc, hp, lp in (
            (100, 105, 6.0, 3.0, 4.0, 1.5),
            (80, 90, 11.0, 4.0, 8.0, 2.0),
            (50, 55, 6.5, 3.2, 4.2, 1.4),
            (120, 130, 12.0, 5.0, 9.0, 2.5),
            (95, 100, 6.2, 3.1, 4.1, 1.6),
        )
    ],
)
SCENARIOS["risk_reversal"] = five(
    "risk_reversal",
    [
        (
            [opt("buy", "call", call_k, c), opt("sell", "put", put_k, p)],
            [max(put_k - 15, 0), put_k, (put_k + call_k) / 2, call_k, call_k + 20],
            [],
        )
        for put_k, call_k, c, p in ((95, 105, 1.5, 1.4), (80, 90, 1.2, 1.1), (70, 80, 0.9, 0.8), (100, 110, 2.0, 1.8), (90, 100, 1.1, 1.0))
    ],
)
SCENARIOS["skew"] = five(
    "skew",
    [
        (
            [opt("buy", "put", put_k, p), opt("sell", "call", call_k, c)],
            [max(put_k - 15, 0), put_k, (put_k + call_k) / 2, call_k, call_k + 20],
            [],
        )
        for put_k, call_k, p, c in ((95, 105, 1.6, 1.2), (80, 90, 1.4, 1.0), (70, 80, 1.1, 0.7), (100, 110, 2.0, 1.5), (90, 100, 1.3, 0.9))
    ],
)
SCENARIOS["synthetic_straddle"] = five(
    "synthetic_straddle",
    [
        (
            [stock("buy", price), opt("buy", "put", strike, premium, 2)],
            [0, strike, price, price + 15, max(strike - 10, 0)],
            [],
        )
        for price, strike, premium in ((100, 100, 2.5), (80, 80, 2.0), (120, 120, 3.5), (60, 60, 1.5), (90, 90, 2.2))
    ],
)

SHAPE_OF = {
    "long_call": "long_call",
    "apex_benchmark_greeks_strategy": "long_call",
    "long_call_leaps": "long_call",
    "deep_itm_call": "long_call",
    "atm_call": "long_call",
    "vix_call_hedge": "long_call",
    "long_put": "long_put",
    "long_put_leaps": "long_put",
    "deep_itm_put": "long_put",
    "naked_call": "short_call",
    "naked_put": "short_put",
    "wheel_strategy": "short_put",
    "bull_call_spread": "call_debit",
    "call_debit_spread": "call_debit",
    "wide_bull_call_spread": "call_debit",
    "bear_put_spread": "put_debit",
    "put_debit_spread": "put_debit",
    "wide_bear_put_spread": "put_debit",
    "bull_put_spread_credit": "put_credit",
    "put_credit_spread": "put_credit",
    "bear_call_spread_credit": "call_credit",
    "call_credit_spread": "call_credit",
    "long_straddle": "long_straddle",
    "long_straddle_leaps": "long_straddle",
    "long_straddle_pre_earnings": "long_straddle",
    "gamma_scalping": "long_straddle",
    "earnings_straddle": "long_straddle",
    "long_strangle": "long_strangle",
    "short_straddle": "short_straddle",
    "short_strangle": "short_strangle",
    "long_guts": "long_guts",
    "short_guts": "short_guts",
    "strip": "strip",
    "strap": "strap",
    "short_iron_butterfly_variant": "iron_butterfly",
    "iron_butterfly": "iron_butterfly",
    "short_iron_condor": "short_iron_condor",
    "iron_condor_wide": "short_iron_condor",
    "iv_crush_short_iron_condor": "short_iron_condor",
    "theta_harvest_iron_condor": "short_iron_condor",
    "iron_condor_monthly": "short_iron_condor",
    "long_iron_condor": "long_iron_condor",
    "reverse_iron_condor": "long_iron_condor",
    "long_call_butterfly": "long_call_butterfly",
    "long_put_butterfly": "long_put_butterfly",
    "short_call_butterfly": "short_call_butterfly",
    "short_put_butterfly": "short_put_butterfly",
    "broken_wing_butterfly": "broken_wing",
    "skip_strike_butterfly": "broken_wing",
    "condor_spread_call": "call_condor",
    "condor_spread_put": "put_condor",
    "long_iron_butterfly": "long_iron_butterfly",
    "christmas_tree_spread": "christmas_tree",
    "ratio_spread": "call_ratio_1x2",
    "call_ratio_spread": "call_ratio_1x2",
    "one_by_two_ratio_spread": "call_ratio_1x2",
    "put_ratio_spread": "put_ratio_1x2",
    "two_by_one_ratio_spread": "call_ratio_2x1",
    "back_ratio_spread": "call_backspread",
    "call_backspread": "call_backspread",
    "put_backspread": "put_backspread",
    "jade_lizard": "jade_lizard",
    "reverse_jade_lizard": "reverse_jade",
    "covered_call": "covered_call",
    "stock_short_call": "covered_call",
    "covered_put": "covered_put",
    "married_put": "protective_put",
    "stock_long_put": "protective_put",
    "synthetic_call": "protective_put",
    "leveraged_covered_call": "leveraged",
    "protective_collar": "collar",
    "collar": "collar",
    "synthetic_long_stock": "synthetic_long",
    "long_combo": "synthetic_long",
    "synthetic_short_stock": "synthetic_short",
    "short_combo": "synthetic_short",
    "synthetic_put": "synthetic_put",
    "conversion": "conversion",
    "reversal": "reversal",
    "box_spread": "box",
    "risk_reversal": "risk_reversal",
    "volatility_skew_trade": "skew",
    "synthetic_straddle": "synthetic_straddle",
}

LABELS_INCOMPLETE = {
    "gamma_trampoline": (
        "Change 11 published one European Black-Scholes table for this label "
        "(spot 100, strikes 94 and 106, debit about 0.617). "
        "That table is one model run, not five recorded chains. "
        + MULTI
    ),
    "apex_benchmark_greeks_sell": (
        "Rule 2 is not a separate chain. Its iron condor, bull put spread, and bear call spread "
        "each have five stated-premium scenarios under those structure ids. "
        "No recorded chain names Rule 2 as the scan winner."
    ),
}


def main() -> None:
    from app.strategies.registry import STRATEGY_REGISTRY

    ids = set(STRATEGY_REGISTRY)
    verified = set(SHAPE_OF)
    incomplete = set(INCOMPLETE)
    missing = ids - verified - incomplete
    extra = (verified | incomplete) - ids
    overlap = verified & incomplete
    if missing or extra or overlap:
        raise SystemExit(f"missing={sorted(missing)} extra={sorted(extra)} overlap={sorted(overlap)}")
    for shape, rows in SCENARIOS.items():
        if len(rows) != 5:
            raise SystemExit(f"{shape} has {len(rows)}")
        for row in rows:
            if len(row["checks"]) < 5:
                raise SystemExit(f"{shape} checks short")
    out = Path(__file__).with_name("stated_premiums.py")
    body = [
        '"""Stated-premium expiry identities for Change 12 D3.',
        "",
        "Premiums are the inputs of the OCC expiry identity. They are not recorded",
        "OPRA or Alpaca quotes. Strategies without five honest fixtures are listed",
        "in INCOMPLETE with the reason.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "INCOMPLETE: dict[str, str] = " + pprint.pformat(INCOMPLETE, width=100),
        "",
        "LABELS_INCOMPLETE: dict[str, str] = " + pprint.pformat(LABELS_INCOMPLETE, width=100),
        "",
        "SHAPE_OF: dict[str, str] = " + pprint.pformat(SHAPE_OF, width=100),
        "",
        "SCENARIOS: dict[str, list[dict]] = " + pprint.pformat(SCENARIOS, width=100),
        "",
    ]
    out.write_text("\n".join(body) + "\n")
    print(f"wrote {out} verified={len(verified)} incomplete={len(incomplete)} shapes={len(SCENARIOS)}")


if __name__ == "__main__":
    main()
