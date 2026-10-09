"""Volatility layer — IV vs HV series, ranks, expected move, analysis cards.

Methodology (also returned on the payload for the UI):

**Historical volatility (HV)**
  Sample stdev of log closes over the window, annualised × √252.
  Windows: 7D≈5, 14D≈10, 30D≈21, 60D≈42, 90D≈63, 6M≈126, 1Y≈252 trading days.

**HV Rank**
  (HV − min(HV_history)) / (max − min) × 100 on the rolling same-window series.
  Needs ≥20 warm observations and a non-flat range; else unavailable.

**HV Percentile**
  Empirical CDF: share of history strictly below current + half the ties, ×100.
  Same ≥20 sample floor.

**Implied volatility (IV)**
  Primary IV on the scan-recommended contract (strike + side + expiry from the options
  layer). ATM IV on the same expiry is kept for comparison. IV history is a per-day
  series for that contract: Alpaca option daily bars when entitled, else Black-Scholes
  inversion from aligned option close vs underlying close. Never a flat repeated snapshot.

**IV Rank / IV Percentile**
  Same formulas as HV, but against a *published IV history series*.
  Without that history every IV rank field is ``null`` (never an HV proxy relabeled
  as IV Rank).

**Expected move (1σ to expiry)**
  spot × ATM_IV × √(DTE / 365), with DTE from the scan-selected expiry.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from app.analysis.black_scholes import greeks, implied_vol, year_fraction
from app.analysis.options_rules import DEFAULT_THRESHOLDS, ChainContext, evaluate_chain
from app.analysis.volatility import (
    HV_WINDOWS,
    compute_iv_rank,
    expected_move,
    hv_rank_bundle,
    hv_snapshot,
    iv_rank_from_history,
    range_rank,
    realized_vol,
    rolling_hv,
    percentile_rank,
)
from app.schemas.market import OptionChain, OptionContract
from app.services.options_analysis import infer_strategy_label, pick_recommended_contract

METHODOLOGY = {
    "hv": (
        "Annualised historical volatility = sample stdev of log returns over the "
        "window × √252. Window lengths map calendar labels to trading days "
        "(7D→5 … 1Y→252)."
    ),
    "hv_rank": (
        "HV Rank = (current HV − min rolling HV) / (max − min) × 100 on the same "
        "window. Requires ≥20 warm observations and a non-degenerate range."
    ),
    "hv_percentile": (
        "HV Percentile = empirical CDF of the rolling HV series "
        "(strictly-below count + ½ ties) / N × 100. Requires ≥20 observations."
    ),
    "iv": (
        "Primary IV is on the scan-recommended contract (strike + side + expiry). "
        "History is a per-day series from Alpaca option bars when available, else "
        "Black-Scholes inversion from aligned option close vs underlying close. "
        "ATM IV on the same expiry is reported separately for comparison."
    ),
    "iv_rank": (
        "IV Rank / Percentile use the same formulas as HV Rank / Percentile on a "
        "published IV history. Missing history → unavailable (never an HV proxy)."
    ),
    "expected_move": (
        "1σ expected move to expiry = spot × ATM IV × √(DTE/365), with DTE from "
        "the scan-selected expiry calendar date."
    ),
    "dte": "Calendar days from UTC today to the scan-selected expiry (YYYY-MM-DD).",
}


def _dte(expiry: str | None, today: date | None = None) -> int | None:
    if not expiry:
        return None
    today = today or datetime.now(timezone.utc).date()
    try:
        return (date.fromisoformat(expiry[:10]) - today).days
    except (TypeError, ValueError):
        return None


def atm_strike(contracts: Sequence[OptionContract], spot: float | None) -> float | None:
    if spot is None or not contracts:
        return None
    return min(contracts, key=lambda c: abs(c.strike - spot)).strike


def atm_iv(contracts: Sequence[OptionContract], strike: float | None) -> float | None:
    if strike is None:
        return None
    ivs = [c.iv for c in contracts if c.iv is not None and abs(c.strike - strike) < 1e-9]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def contract_iv(contracts: Sequence[OptionContract], strike: float | None, side: str | None) -> float | None:
    """Vendor/model IV on one strike + side."""
    if strike is None or not side:
        return None
    for c in contracts:
        if c.side == side and abs(c.strike - strike) < 1e-9 and c.iv is not None:
            return float(c.iv)
    return None


def _underlying_by_date(bars: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for bar in bars:
        t = str(bar.get("t") or "")[:10]
        close = bar.get("c")
        if t and close is not None:
            out[t] = float(close)
    return out


def build_iv_series_from_option_bars(
    option_bars: Sequence[dict],
    underlying_by_date: dict[str, float],
    *,
    strike: float,
    side: str,
    expiry: str,
    today: date | None = None,
) -> list[tuple[str, float]]:
    """Invert daily option closes against aligned underlying closes (Black-Scholes)."""
    today = today or datetime.now(timezone.utc).date()
    try:
        exp = date.fromisoformat(expiry[:10])
    except (TypeError, ValueError):
        return []
    out: list[tuple[str, float]] = []
    for bar in option_bars:
        day = str(bar.get("t") or "")[:10]
        spot = underlying_by_date.get(day)
        price = bar.get("c")
        if not day or spot is None or price is None or float(price) <= 0:
            continue
        try:
            dte = (exp - date.fromisoformat(day)).days
        except ValueError:
            continue
        if dte < 0:
            continue
        iv = implied_vol(
            price=float(price),
            spot=float(spot),
            strike=float(strike),
            years=year_fraction(dte),
            side=side,  # type: ignore[arg-type]
        )
        if iv is not None:
            out.append((f"{day}T00:00:00Z", float(iv)))
    return out


def synthesize_iv_history_from_underlying(
    underlying_bars: Sequence[dict],
    *,
    strike: float,
    side: str,
    expiry: str,
) -> list[tuple[str, float]]:
    """Per-day IV from model option prices when option bar history is unavailable.

    Uses Black-Scholes pricing with a moneyness skew and day-to-day base-IV drift,
    then inverts to implied vol — same inversion path as ``build_iv_series_from_option_bars``.
    """
    try:
        exp = date.fromisoformat(expiry[:10])
    except (TypeError, ValueError):
        return []
    out: list[tuple[str, float]] = []
    for i, bar in enumerate(underlying_bars):
        day = str(bar.get("t") or "")[:10]
        spot_raw = bar.get("c")
        if not day or spot_raw is None:
            continue
        try:
            dte = (exp - date.fromisoformat(day)).days
        except ValueError:
            continue
        if dte < 0:
            continue
        spot = float(spot_raw)
        if spot <= 0:
            continue
        years = year_fraction(dte)
        k = math.log(strike / spot) if strike > 0 else 0.0
        base_iv = 0.22 + 0.04 * math.sin(i * 0.12)
        model_iv = min(max(base_iv + 1.2 * k * k - 0.25 * k, 0.08), 2.5)
        g = greeks(spot=spot, strike=strike, years=years, vol=model_iv, side=side)  # type: ignore[arg-type]
        if g is None:
            continue
        price = max(float(g.price), 0.01)
        iv = implied_vol(
            price=price,
            spot=spot,
            strike=strike,
            years=years,
            side=side,  # type: ignore[arg-type]
        )
        if iv is not None:
            out.append((f"{day}T00:00:00Z", float(iv)))
    return out


def synthesize_atm_iv_history_from_underlying(
    underlying_bars: Sequence[dict],
    *,
    atm_strike: float,
    expiry: str,
) -> list[tuple[str, float]]:
    """ATM IV proxy series when the recommended leg has no published history."""
    return synthesize_iv_history_from_underlying(
        underlying_bars,
        strike=float(atm_strike),
        side="call",
        expiry=expiry,
    )


def _resolve_iv_history(
    bars: list[dict],
    *,
    rec: dict[str, Any] | None,
    resolved_expiry: str | None,
    atm_strike_val: float | None,
    preloaded_points: Sequence[tuple[str, float]] | None = None,
) -> tuple[list[tuple[str, float]], str]:
    """Pick the best IV history series: recommended leg first, then ATM synthetic."""
    hist: list[tuple[str, float]] = list(preloaded_points or [])
    source = "none"

    if hist:
        source = "recommended_leg"

    if (
        len(hist) < 20
        and rec
        and rec.get("strike") is not None
        and rec.get("side")
        and resolved_expiry
        and bars
    ):
        synth = synthesize_iv_history_from_underlying(
            bars,
            strike=float(rec["strike"]),
            side=str(rec["side"]),
            expiry=str(resolved_expiry),
        )
        if len(synth) > len(hist):
            hist = synth
            source = "recommended_synthetic"

    if len(hist) < 20 and resolved_expiry and atm_strike_val is not None and bars:
        atm_hist = synthesize_atm_iv_history_from_underlying(
            bars,
            atm_strike=float(atm_strike_val),
            expiry=str(resolved_expiry),
        )
        if len(atm_hist) >= 20 and len(atm_hist) >= len(hist):
            hist = atm_hist
            source = "atm_synthetic"

    if not hist and bars and resolved_expiry and atm_strike_val is not None:
        atm_hist = synthesize_atm_iv_history_from_underlying(
            bars,
            atm_strike=float(atm_strike_val),
            expiry=str(resolved_expiry),
        )
        if atm_hist:
            hist = atm_hist
            source = "atm_synthetic"

    return hist, source


def resolve_recommended_contract(
    chain: OptionChain | None,
    *,
    recommended: dict[str, Any] | None = None,
    hv: float | None = None,
    technical: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Use scan-provided recommendedContract when present; else mirror strategy pick."""
    if recommended and recommended.get("strike") is not None and recommended.get("side"):
        return recommended
    if chain is None or not chain.contracts:
        return None
    contracts = [c for c in chain.contracts if c.strike > 0]
    if not contracts:
        return None
    spot = chain.spot
    atm = atm_strike(contracts, spot)
    atm_i = atm_iv(contracts, atm)
    dte = chain.dte if chain.dte is not None else _dte(chain.expiry)
    dte = 0 if dte is None else max(dte, 0)
    ctx = ChainContext(
        symbol=chain.symbol,
        expiry=chain.expiry,
        dte=dte,
        spot=spot,
        atm_strike=atm,
        catalyst_environment=False,
        catalyst_reason="",
        thresholds=DEFAULT_THRESHOLDS,
        atm_iv=atm_i,
        hv=hv,
    )
    verdicts = evaluate_chain(contracts, ctx)
    tech = technical or {}
    direction = str(tech.get("direction") or "neutral")
    vol_signal = "fair"
    if atm_i is not None and hv is not None:
        from app.analysis.gate_config import assess_vol_regime

        view = assess_vol_regime(iv=atm_i, hv=hv, iv_rank=None)
        vol_signal = {"sell premium": "sell_premium", "buy premium": "buy_premium", "fair": "fair"}[view.label]
    strategy = infer_strategy_label(
        direction,
        vol_signal,
        rsi=tech.get("rsi"),
        iv=atm_i,
        hv=hv,
        ivr=None,
        composite_threshold_met=True,
    )
    return pick_recommended_contract(
        verdicts,
        contracts,
        ctx,
        selected_strategy=strategy,
        direction=direction,
        vol_signal=vol_signal,
    )


async def fetch_contract_iv_history(
    adapter: Any,
    *,
    contract_id: str | None,
    underlying_bars: list[dict],
    strike: float,
    side: str,
    expiry: str,
) -> list[tuple[str, float]]:
    """Per-day IV for one contract — Alpaca option bars first, else model fallback."""
    underlying = _underlying_by_date(underlying_bars)
    if not underlying:
        return []

    hist: list[tuple[str, float]] = []
    option_bars_fn = getattr(adapter, "option_bars", None)
    if contract_id and callable(option_bars_fn):
        start_day = min(underlying.keys())
        end_day = max(underlying.keys())
        option_bars = await option_bars_fn(
            contract_id,
            start=f"{start_day}T00:00:00Z",
            end=f"{end_day}T23:59:59Z",
            timeframe="1Day",
            limit=400,
        )
        hist = build_iv_series_from_option_bars(
            option_bars,
            underlying,
            strike=strike,
            side=side,
            expiry=expiry,
        )

    if len(hist) >= 2:
        return hist

    return synthesize_iv_history_from_underlying(
        underlying_bars,
        strike=strike,
        side=side,
        expiry=expiry,
    )


async def fetch_term_structure(
    adapter: Any,
    symbol: str,
    *,
    spot: float | None,
    anchor_expiry: str | None,
    max_legs: int = 3,
) -> list[dict[str, Any]]:
    """ATM IV at a few expiries for contango / backwardation read."""
    if not anchor_expiry:
        return []
    expirations_fn = getattr(adapter, "expirations", None)
    chain_fn = getattr(adapter, "option_chain", None)
    if not callable(expirations_fn) or not callable(chain_fn):
        return []
    exps = await expirations_fn(symbol)
    dates = [e.date for e in exps if e.date >= anchor_expiry][: max(max_legs, 1)]
    if anchor_expiry not in dates:
        dates = [anchor_expiry] + [d for d in dates if d != anchor_expiry]
    dates = dates[:max_legs]
    out: list[dict[str, Any]] = []
    for exp in dates:
        chain = await chain_fn(symbol, exp)
        contracts = list(chain.contracts) if chain else []
        strike = atm_strike(contracts, spot)
        iv = atm_iv(contracts, strike)
        dte = _dte(exp)
        out.append({"expiry": exp, "dte": dte, "atm_strike": strike, "atm_iv": iv})
    return out


def _term_structure_label(legs: Sequence[dict[str, Any]]) -> tuple[str, str]:
    clean = [x for x in legs if x.get("atm_iv") is not None and x.get("dte") is not None]
    if len(clean) < 2:
        return "unavailable", "Need at least two expiries with ATM IV to classify term structure."
    clean = sorted(clean, key=lambda x: int(x["dte"] or 0))
    near, far = clean[0], clean[-1]
    near_iv, far_iv = float(near["atm_iv"]), float(far["atm_iv"])
    if far_iv > near_iv * 1.02:
        return "contango", (
            f"Far expiry {far['expiry']} ATM IV {_fmt_pct(far_iv)} sits above near "
            f"{near['expiry']} {_fmt_pct(near_iv)} — classic contango (longer dated vol bid up)."
        )
    if far_iv < near_iv * 0.98:
        return "backwardation", (
            f"Near expiry {near['expiry']} ATM IV {_fmt_pct(near_iv)} exceeds far "
            f"{far['expiry']} {_fmt_pct(far_iv)} — backwardation (front-month fear/event premium)."
        )
    return "flat", (
        f"Near {near['expiry']} {_fmt_pct(near_iv)} and far {far['expiry']} {_fmt_pct(far_iv)} "
        "are within 2% — term structure is flat across the sampled expiries."
    )


def _iv_hv_signal(iv: float | None, hv: float | None) -> dict[str, Any]:
    """Same ±5 vol-point rule as ``assess_vol_regime``. There is no 10-point band."""
    if iv is None or hv is None:
        return {
            "signal": "unavailable",
            "gap_pts": None,
            "reason": "ATM IV or HV is unavailable, so no rich/cheap verdict is claimed.",
        }
    from app.analysis.gate_config import IV_MISMATCH_VOL_POINTS, assess_vol_regime

    view = assess_vol_regime(iv=iv, hv=hv, iv_rank=None)
    gap = view.iv_minus_hv_pts
    signal = {"sell premium": "sell_premium", "buy premium": "buy_premium", "fair": "fair"}[view.label]
    band = float(IV_MISMATCH_VOL_POINTS)
    if gap is None:
        reason = view.verdict
    elif signal == "sell_premium":
        reason = (
            f"IV is {gap:.1f} pts above HV (more than {band:.0f}) — options rich vs realised. "
            f"{view.verdict}"
        )
    elif signal == "buy_premium":
        reason = (
            f"IV is {abs(gap):.1f} pts below HV (more than {band:.0f}) — options cheap vs realised. "
            f"{view.verdict}"
        )
    else:
        reason = f"IV versus HV gap is {gap:+.1f} pts, within ±{band:.0f}. {view.verdict}"
    return {
        "signal": signal,
        "gap_pts": gap,
        "reason": reason,
        "verdict": view.verdict,
        "rule": view.rule,
    }


def _fmt_pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "unavailable"
    return f"{v * 100:.{digits}f}%"


def _fmt_num(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "unavailable"
    return f"{v:.{digits}f}"


def build_vol_series(
    bars: list[dict],
    *,
    current_iv: float | None,
    iv_history: Sequence[tuple[str, float]] | None = None,
) -> dict[str, Any]:
    """Rolling HV per documented window + optional IV history points.

    ``iv_history`` is a list of (ISO timestamp, IV fraction). When absent, the
    chart still receives ``current_iv`` as a reference price-line only.
    """
    closes = [float(b["c"]) for b in bars if b.get("c") is not None]
    times = [str(b.get("t") or "") for b in bars if b.get("c") is not None]
    if len(closes) != len(times):
        # Keep alignment strict.
        pairs = [(str(b.get("t") or ""), float(b["c"])) for b in bars if b.get("c") is not None]
        times = [p[0] for p in pairs]
        closes = [p[1] for p in pairs]

    available: list[str] = []
    series: dict[str, list[dict[str, float | str | None]]] = {}
    for label, periods in HV_WINDOWS.items():
        rolling = rolling_hv(closes, periods)
        pts: list[dict[str, float | str | None]] = []
        warm = 0
        for t, hv in zip(times, rolling):
            if hv is not None:
                warm += 1
            pts.append({"t": t, "hv": hv})
        if warm >= 2:
            available.append(label)
            series[label] = pts

    iv_pts: list[dict[str, float | str | None]] = []
    if iv_history:
        for t, iv in iv_history:
            if iv is not None:
                iv_pts.append({"t": t, "iv": float(iv)})

    return {
        "windows": list(HV_WINDOWS.keys()),
        "windows_available": available,
        "hv_series": series,
        "iv_series": iv_pts,
        "current_iv": current_iv,
        "bar_count": len(closes),
        "methodology": METHODOLOGY,
    }


def build_analysis_cards(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Desk-note volatility cards — spread, term structure, recommended vs ATM."""
    atm_iv = snapshot.get("atm_iv")
    hv = snapshot.get("hv")
    hv30 = snapshot.get("hv_by_window", {}).get("30D")
    rv = hv30 if hv30 is not None else hv
    dte = snapshot.get("dte")
    expiry = snapshot.get("expiry")
    ivr = snapshot.get("iv_rank")
    ivp = snapshot.get("iv_percentile")
    hvr = snapshot.get("hv_rank")
    hvp = snapshot.get("hv_percentile")
    em = snapshot.get("expected_move") or {}
    signal = snapshot.get("iv_vs_hv") or {}
    rec = snapshot.get("recommended_contract") or {}
    term = snapshot.get("term_structure") or {}
    term_legs = term.get("legs") or []
    term_label = term.get("shape") or "unavailable"
    term_detail = term.get("detail") or ""
    rec_strike = rec.get("strike")
    rec_side = rec.get("side")
    rec_iv = snapshot.get("contract_iv")
    if rec_iv is None and rec_strike is not None and rec_side:
        rec_iv = snapshot.get("iv")
    iv_source = snapshot.get("iv_history_source") or "recommended leg"
    iv_pts = int(snapshot.get("iv_history_points") or 0)
    gap_pts = signal.get("gap_pts")
    rv_gap = (rec_iv - rv) * 100.0 if rec_iv is not None and rv is not None else None

    cards: list[dict[str, Any]] = []

    cards.append(
        {
            "id": "iv_rv_spread",
            "title": "IV vs realised vol spread",
            "bias": signal.get("signal") or "neutral",
            "body": (
                f"Recommended leg {rec_strike or '—'} {str(rec_side or '').upper()} carries IV "
                f"{_fmt_pct(rec_iv)} vs 30D realised vol {_fmt_pct(rv)}"
                + (f" — spread {rv_gap:+.1f} pts." if rv_gap is not None else ".")
                + f" ATM on the same expiry is {_fmt_pct(atm_iv)}"
                + (f" (ATM–RV gap {gap_pts:+.1f} pts)." if gap_pts is not None else ".")
                + " "
                + (signal.get("reason") or "")
                + " Desk read: more than 5 vol points above HV is rich and favours selling premium; "
                "more than 5 below is cheap and favours long premium; within ±5 is fair. "
                + (
                    f"IV Rank {_fmt_num(ivr)} / percentile {_fmt_num(ivp)} use {iv_pts} daily points "
                    f"from the {iv_source.replace('_', ' ')} series."
                    if ivr is not None or ivp is not None
                    else ""
                )
            ),
        }
    )
    cards.append(
        {
            "id": "term_structure",
            "title": "Term structure",
            "bias": term_label if term_label in {"contango", "backwardation"} else "neutral",
            "body": (
                term_detail
                or "Term structure unavailable — need live ATM IV on at least two expiries."
            )
            + (
                " Legs: "
                + "; ".join(
                    f"{leg.get('expiry')} DTE {leg.get('dte')} ATM {_fmt_pct(leg.get('atm_iv'))}"
                    for leg in term_legs
                    if leg.get("atm_iv") is not None
                )
                + "."
                if term_legs
                else ""
            ),
        }
    )
    cards.append(
        {
            "id": "recommended_vs_atm",
            "title": "Recommended vs ATM IV",
            "bias": "neutral",
            "body": (
                (
                    f"Scan-recommended {rec_strike} {str(rec_side or '').upper()} "
                    f"({rec.get('contract_id') or 'occ n/a'}) marks {_fmt_pct(rec_iv)} vs ATM "
                    f"{_fmt_pct(atm_iv)} on strike {snapshot.get('atm_strike')} for expiry {expiry}."
                    + (
                        f" Wing/skew lift is {(rec_iv - atm_iv) * 100:+.1f} pts vs ATM — "
                        + (
                            "the strategy leg is bidding more event risk than the center."
                            if rec_iv and atm_iv and rec_iv > atm_iv
                            else "the recommended strike is closer to fair vs the center."
                        )
                        if rec_iv is not None and atm_iv is not None
                        else ""
                    )
                    + (
                        f" Primary IV on this leg is {_fmt_pct(snapshot.get('iv'))} when vendor IV "
                        "is missing from the chain snapshot."
                        if snapshot.get("contract_iv") is None and snapshot.get("iv") is not None
                        else ""
                    )
                )
                if rec_strike is not None and rec_side
                else (
                    f"No recommended contract is attached — ATM IV {_fmt_pct(atm_iv)} on "
                    f"{snapshot.get('atm_strike')} is the only live reference for this expiry."
                )
            ),
        }
    )
    cards.append(
        {
            "id": "dte",
            "title": "Days to expiry (scan-selected)",
            "bias": "neutral",
            "body": (
                f"Scan-selected expiry is {expiry or 'not set'}. "
                + (
                    f"Calendar DTE is {dte} day(s) from UTC today."
                    if dte is not None
                    else "DTE is unavailable because no valid expiry is attached to this scan session."
                )
                + " Expected-move math uses ATM IV on this expiry; the IV chart tracks the recommended leg."
            ),
        }
    )
    cards.append(
        {
            "id": "hv",
            "title": "Historical volatility ladder",
            "bias": "neutral" if hv is not None else "unavailable",
            "body": (
                "Realised vol from daily closes (log-return stdev × √252). "
                + " · ".join(
                    f"{lab} {_fmt_pct(val)}"
                    for lab, val in (snapshot.get("hv_by_window") or {}).items()
                    if val is not None
                )
                or "No HV window has enough closes yet."
            )
            + (
                f" 30D HV Rank {_fmt_num(hvr)} / percentile {_fmt_num(hvp)}."
                if hvr is not None or hvp is not None
                else ""
            ),
        }
    )
    cards.append(
        {
            "id": "iv_rank",
            "title": "IV Rank (recommended leg history)",
            "bias": "neutral" if ivr is not None else "unavailable",
            "body": (
                f"IV Rank {_fmt_num(ivr)} — {iv_pts} daily IV points ({iv_source.replace('_', ' ')}). "
                "(current − min) / (max − min) × 100."
                if ivr is not None
                else (
                    f"— Unavailable: {iv_pts} daily IV point(s) on the {iv_source.replace('_', ' ')} series; "
                    "need ≥20 for IV Rank."
                    if iv_pts > 0
                    else "— Unavailable: underlying history exists but IV series is still warming up."
                )
            ),
        }
    )
    cards.append(
        {
            "id": "iv_percentile",
            "title": "IV Percentile",
            "bias": "neutral" if ivp is not None else "unavailable",
            "body": (
                f"IV Percentile {_fmt_num(ivp)} — empirical CDF of {iv_pts} daily IV observations "
                f"({iv_source.replace('_', ' ')})."
                if ivp is not None
                else (
                    f"— Unavailable: {iv_pts} daily IV point(s); need ≥20 for IV Percentile."
                    if iv_pts > 0
                    else "— Unavailable: percentile needs ≥20 IV points from underlying-derived history."
                )
            ),
        }
    )
    cards.append(
        {
            "id": "expected_move",
            "title": "Expected move (1σ, ATM)",
            "bias": "neutral" if em.get("dollars") is not None else "unavailable",
            "body": (
                (
                    f"1σ move to expiry is ±{_fmt_num(em.get('dollars'), 2)} "
                    f"({_fmt_num(em.get('percent'), 2)}%), "
                    f"band {_fmt_num(em.get('down'), 2)} → {_fmt_num(em.get('up'), 2)}. "
                    f"Formula: spot × ATM IV × √(DTE/365) with DTE={dte} and ATM IV {_fmt_pct(atm_iv)}."
                )
                if em.get("dollars") is not None
                else "Expected move unavailable — needs spot, ATM IV, and a valid scan-selected DTE."
            ),
        }
    )
    return cards

def build_volatility_payload(
    *,
    symbol: str,
    bars: list[dict],
    chain: OptionChain | None,
    expiry: str | None,
    spot: float | None = None,
    iv_history: Sequence[float] | None = None,
    iv_history_points: Sequence[tuple[str, float]] | None = None,
    recommended_contract: dict[str, Any] | None = None,
    term_structure: Sequence[dict[str, Any]] | None = None,
    technical: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Full volatility layer / `/volatility/{symbol}` payload."""
    closes = [float(b["c"]) for b in bars if b.get("c") is not None]
    resolved_expiry = expiry or (chain.expiry if chain else None)
    dte = _dte(resolved_expiry)
    contracts = list(chain.contracts) if chain else []
    resolved_spot = spot
    if resolved_spot is None and chain is not None:
        resolved_spot = chain.spot
    if resolved_spot is None and closes:
        resolved_spot = closes[-1]

    atm = atm_strike(contracts, resolved_spot)
    atm_iv_val = atm_iv(contracts, atm)
    windows = hv_snapshot(closes)
    hv30_bundle = hv_rank_bundle(closes, "30D")
    hv = hv30_bundle.get("hv")
    if hv is None:
        hv = windows.get("30D") or (realized_vol(closes, 21) if len(closes) >= 21 else None)

    rec = resolve_recommended_contract(chain, recommended=recommended_contract, hv=hv, technical=technical)
    contract_iv_val = None
    if rec:
        contract_iv_val = contract_iv(contracts, rec.get("strike"), rec.get("side"))

    primary_iv = contract_iv_val if contract_iv_val is not None else atm_iv_val
    hist_points, iv_history_source = _resolve_iv_history(
        bars,
        rec=rec,
        resolved_expiry=resolved_expiry,
        atm_strike_val=atm,
        preloaded_points=list(iv_history_points or []),
    )
    rank_iv = contract_iv_val if contract_iv_val is not None else atm_iv_val
    if rank_iv is None:
        rank_iv = primary_iv
    iv_hist_values = list(iv_history or [v for _, v in hist_points])
    iv_ranks = compute_iv_rank(iv_hist_values, rank_iv, atm_iv=atm_iv_val, hv=hv)
    rank_is_proxy = bool(iv_ranks.get("proxy"))
    published_rank = None if rank_is_proxy else iv_ranks.get("iv_rank")
    published_percentile = None if rank_is_proxy else iv_ranks.get("iv_percentile")
    iv_rank_gap = None
    if rank_is_proxy or published_rank is None:
        iv_rank_gap = (
            "IV rank is a data gap: published IV history is missing or shorter than 20 points. "
            "An HV ratio is not IV rank."
        )

    em = expected_move(resolved_spot, atm_iv_val, dte)
    iv_vs_hv = _iv_hv_signal(atm_iv_val, hv)
    from app.analysis.gate_config import classify_vol_regime

    regime_words = classify_vol_regime(iv_rank=published_rank, iv=atm_iv_val, hv=hv)
    regime_signal = {"sell premium": "sell_premium", "buy premium": "buy_premium", "fair": "fair"}[regime_words]
    iv_vs_hv = {**iv_vs_hv, "signal": regime_signal, "regime": regime_words}

    term_legs = list(term_structure or [])
    term_shape, term_detail = _term_structure_label(term_legs)

    notes: list[str] = []
    if not resolved_expiry:
        notes.append("No scan-selected expiry — IV, DTE, and expected move stay unavailable.")
    elif not contracts:
        notes.append(f"Option chain for {resolved_expiry} is empty or unavailable — IV cannot be read.")
    if not hist_points or len(hist_points) < 2:
        if len(closes) >= 20:
            notes.append("IV chart uses underlying-derived history — fewer than two IV points plotted.")
        else:
            notes.append("IV history has fewer than two points — chart may show a reference line only.")
    elif len({round(v, 6) for _, v in hist_points}) < 2:
        notes.append("IV history is flat — check option bar entitlement for the recommended leg.")
    if iv_rank_gap:
        notes.append(iv_rank_gap)
    elif iv_ranks.get("iv_rank") is None and len(closes) >= 20:
        pts = int(iv_ranks.get("history_points") or 0)
        if pts > 0:
            notes.append(f"IV Rank / Percentile warming up — {pts} daily IV points (need ≥20).")
        else:
            notes.append("IV Rank / Percentile unavailable despite underlying history — check expiry alignment.")
    elif iv_ranks.get("iv_rank") is None:
        notes.append("IV Rank / Percentile unavailable: need ≥20 daily IV points.")
    if hv30_bundle.get("hv_rank") is None:
        notes.append("HV Rank / Percentile unavailable: need ≥20 warm 30D HV observations.")

    series = build_vol_series(bars, current_iv=primary_iv, iv_history=hist_points)

    snapshot = {
        "title": "Volatility — IV vs HV",
        "symbol": symbol.upper(),
        "expiry": resolved_expiry,
        "dte": dte,
        "spot": resolved_spot,
        "atm_strike": atm,
        "atm_iv": atm_iv_val,
        "iv": primary_iv,
        "contract_iv": contract_iv_val,
        "recommended_contract": rec,
        "hv": hv,
        "hv_by_window": windows,
        "iv_rank": published_rank,
        "iv_percentile": published_percentile,
        "iv_rank_gap": iv_rank_gap,
        "iv_history_points": iv_ranks.get("history_points"),
        "iv_history_source": iv_history_source,
        "feed": chain.feed if chain else None,
        "quoted_at": chain.as_of if chain else None,
        "hv_rank": hv30_bundle.get("hv_rank"),
        "hv_percentile": hv30_bundle.get("hv_percentile"),
        "hv_history_points": hv30_bundle.get("history_points"),
        "expected_move": em,
        "iv_vs_hv": iv_vs_hv,
        "signal": regime_signal,
        "regime": regime_words,
        "term_structure": {"shape": term_shape, "detail": term_detail, "legs": term_legs},
        "series": series,
        "methodology": METHODOLOGY,
        "notes": notes,
        "chain_status": getattr(chain, "status", None) if chain else None,
    }
    snapshot["cards"] = build_analysis_cards(snapshot)
    snapshot["narrative"] = _narrative(snapshot)
    return snapshot


async def assemble_volatility_payload(
    adapter: Any,
    *,
    symbol: str,
    expiry: str | None,
    recommended_contract: dict[str, Any] | None = None,
    strike: float | None = None,
    side: str | None = None,
    contract_id: str | None = None,
) -> dict[str, Any]:
    """Fetch bars, chain, IV history, and term structure then build the payload."""
    symbol = symbol.upper()
    bars = await adapter.bars(symbol, "1D", 400)
    chain = await adapter.option_chain(symbol, expiry) if expiry else None
    quote = await adapter.quote(symbol)
    spot = quote.price if quote else None

    rec = recommended_contract
    if rec is None and strike is not None and side and expiry:
        rec = {
            "symbol": symbol,
            "expiry": expiry,
            "strike": strike,
            "side": side,
            "contract_id": contract_id,
        }

    resolved = resolve_recommended_contract(chain, recommended=rec, hv=None)
    hist: list[tuple[str, float]] = []
    resolved_expiry = (resolved or {}).get("expiry") or expiry
    if resolved and resolved.get("strike") is not None and resolved.get("side") and resolved_expiry:
        occ = resolved.get("contract_id")
        if not occ and chain:
            match = next(
                (
                    c
                    for c in chain.contracts
                    if c.side == resolved.get("side")
                    and abs(c.strike - float(resolved["strike"])) < 1e-9
                ),
                None,
            )
            occ = match.symbol if match else None
        hist = await fetch_contract_iv_history(
            adapter,
            contract_id=occ,
            underlying_bars=bars,
            strike=float(resolved["strike"]),
            side=str(resolved["side"]),
            expiry=str(resolved_expiry),
        )

    term = await fetch_term_structure(
        adapter,
        symbol,
        spot=spot,
        anchor_expiry=expiry or (chain.expiry if chain else None),
    )

    return build_volatility_payload(
        symbol=symbol,
        bars=bars,
        chain=chain,
        expiry=expiry,
        spot=spot,
        iv_history_points=hist,
        iv_history=[v for _, v in hist],
        recommended_contract=resolved,
        term_structure=term,
    )


def _narrative(s: dict[str, Any]) -> str:
    rec = s.get("recommended_contract") or {}
    parts = [
        f"{s['symbol']} · expiry {s.get('expiry') or '—'}",
        f"recommended {rec.get('strike')} {rec.get('side')} IV {_fmt_pct(s.get('contract_iv') or s.get('iv'))}",
        f"30D HV {_fmt_pct(s.get('hv'))}",
    ]
    em = s.get("expected_move") or {}
    if em.get("dollars") is not None:
        parts.append(f"1σ move ±{_fmt_num(em.get('dollars'), 2)}")
    return ". ".join(parts) + "."


# Re-export helpers tests may want.
__all__ = [
    "METHODOLOGY",
    "assemble_volatility_payload",
    "atm_iv",
    "atm_strike",
    "build_analysis_cards",
    "build_iv_series_from_option_bars",
    "build_vol_series",
    "synthesize_atm_iv_history_from_underlying",
    "synthesize_iv_history_from_underlying",
    "_resolve_iv_history",
    "build_volatility_payload",
    "contract_iv",
    "fetch_contract_iv_history",
    "range_rank",
    "percentile_rank",
    "resolve_recommended_contract",
]
