"""Black-Scholes pricing, Greeks and implied volatility.

Full Document Appendix E lists "Options Pricing & Greeks Calculation" as a platform
capability. Everything produced here is **model-computed**, never vendor-published, and
callers must tag it as ``greeks_source="model"`` so the UI can label it as such.

Conventions match how brokers publish Greeks so vendor and model numbers are comparable:

* ``delta``  — change in option price per $1 of underlying (call 0..1, put -1..0)
* ``gamma``  — change in delta per $1 of underlying
* ``theta``  — change in option price per **calendar day** (negative for long options)
* ``vega``   — change in option price per **1 percentage point** of IV
* ``rho``    — change in option price per **1 percentage point** of rate
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Side = Literal["call", "put"]

_SQRT_2PI = math.sqrt(2.0 * math.pi)
#: Minimum year fraction. Expiry day itself is treated as a few hours of life so
#: 0-DTE strikes still produce finite Greeks instead of dividing by zero.
MIN_YEARS = 1.0 / (365.0 * 24.0)
DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class ModelGreeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def year_fraction(dte_days: float) -> float:
    return max(float(dte_days) / DAYS_PER_YEAR, MIN_YEARS)


def greeks(
    *,
    spot: float,
    strike: float,
    years: float,
    vol: float,
    side: Side,
    rate: float = 0.0,
    carry: float = 0.0,
) -> ModelGreeks | None:
    """Generalised Black-Scholes-Merton. ``carry`` is the continuous dividend/carry yield.

    Returns ``None`` when the inputs cannot support a model value (non-positive spot,
    strike, or volatility) rather than emitting a plausible-looking zero.
    """
    if spot <= 0 or strike <= 0 or vol <= 0:
        return None
    t = max(float(years), MIN_YEARS)
    sig_t = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - carry + 0.5 * vol * vol) * t) / sig_t
    d2 = d1 - sig_t
    disc_r = math.exp(-rate * t)
    disc_q = math.exp(-carry * t)
    nd1, nd2 = _cdf(d1), _cdf(d2)
    pdf_d1 = _pdf(d1)

    if side == "call":
        price = spot * disc_q * nd1 - strike * disc_r * nd2
        delta = disc_q * nd1
        theta_year = (
            -spot * disc_q * pdf_d1 * vol / (2.0 * math.sqrt(t))
            - rate * strike * disc_r * nd2
            + carry * spot * disc_q * nd1
        )
        rho_pt = strike * t * disc_r * nd2 / 100.0
    else:
        price = strike * disc_r * _cdf(-d2) - spot * disc_q * _cdf(-d1)
        delta = -disc_q * _cdf(-d1)
        theta_year = (
            -spot * disc_q * pdf_d1 * vol / (2.0 * math.sqrt(t))
            + rate * strike * disc_r * _cdf(-d2)
            - carry * spot * disc_q * _cdf(-d1)
        )
        rho_pt = -strike * t * disc_r * _cdf(-d2) / 100.0

    gamma = disc_q * pdf_d1 / (spot * sig_t)
    vega_pt = spot * disc_q * pdf_d1 * math.sqrt(t) / 100.0
    return ModelGreeks(
        price=price,
        delta=delta,
        gamma=gamma,
        theta=theta_year / DAYS_PER_YEAR,
        vega=vega_pt,
        rho=rho_pt,
    )


def implied_vol(
    *,
    price: float,
    spot: float,
    strike: float,
    years: float,
    side: Side,
    rate: float = 0.0,
    carry: float = 0.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Bisection solve for IV. ``None`` when the target price is outside model bounds.

    Bisection (not Newton) because vega collapses on deep wings and a Newton step there
    diverges. The bracket is wide enough for meme-stock event vol.
    """
    if price <= 0 or spot <= 0 or strike <= 0:
        return None
    t = max(float(years), MIN_YEARS)
    intrinsic = max(0.0, (spot - strike) if side == "call" else (strike - spot)) * math.exp(-rate * t)
    if price < intrinsic - tol:
        return None
    lo, hi = 1e-4, 8.0
    g_hi = greeks(spot=spot, strike=strike, years=t, vol=hi, side=side, rate=rate, carry=carry)
    if g_hi is None or g_hi.price < price:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        g = greeks(spot=spot, strike=strike, years=t, vol=mid, side=side, rate=rate, carry=carry)
        if g is None:
            return None
        if abs(g.price - price) < tol:
            return mid
        if g.price > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
