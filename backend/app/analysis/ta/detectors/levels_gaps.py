"""S/R, pivot, Fibonacci, harmonic, and gap pattern detectors — families 10–12."""

from __future__ import annotations

from typing import Any

from app.analysis.ta.ohlc_utils import OhlcWindow, PatternSignal, make_signal, swings, vol_ratio


def _camarilla(h: float, l: float, c: float) -> dict[str, float]:
    r = h - l
    return {
        "r3": c + r * 1.1 / 4,
        "r4": c + r * 1.1 / 2,
        "s3": c - r * 1.1 / 4,
        "s4": c - r * 1.1 / 2,
    }


def _fib_levels(swing_high: float, swing_low: float) -> dict[str, float]:
    diff = swing_high - swing_low
    return {
        "382": swing_high - diff * 0.382,
        "500": swing_high - diff * 0.5,
        "618": swing_high - diff * 0.618,
    }


def detect_levels_gaps_harmonic(w: OhlcWindow, indicators: dict[str, Any]) -> list[PatternSignal]:
    out: list[PatternSignal] = []
    n = w.n
    if n < 3:
        return out
    px = w.closes[-1]
    pivots = indicators.get("pivots") or {}
    pp = pivots.get("pp")
    prev_h = w.highs[-2] if n > 1 else w.highs[-1]
    prev_l = w.lows[-2] if n > 1 else w.lows[-1]
    prev_c = w.closes[-2] if n > 1 else w.closes[-1]

    # Family 10 — S/R, pivots, Fibonacci
    if pp is not None:
        dist = abs(px - float(pp)) / max(px, 1e-9)
        if dist < 0.01:
            out.append(make_signal(
                pattern_id="pivot_classic_bounce", name="Classic Pivot Bounce", family="sr_pivot_fibonacci", direction="neutral",
                status="forming", strength=62.0, reliability_tier="medium",
                confirmation_evidence=("Price at classic pivot point — context only",),
                invalidation=("Clear break of pivot",), bar_index=n - 1, invalidation_price=float(pp),
            ))

    cam = _camarilla(prev_h, prev_l, prev_c)
    for level_name, level in cam.items():
        if abs(px - level) / px < 0.008:
            out.append(make_signal(
                pattern_id="pivot_camarilla", name="Camarilla Pivot Level", family="sr_pivot_fibonacci", direction="neutral",
                status="forming", strength=55.0, reliability_tier="low",
                confirmation_evidence=(f"Price near Camarilla {level_name.upper()}",),
                invalidation=("Break of Camarilla level",), bar_index=n - 1, invalidation_price=level,
            ))
            break

    sh = swings(w.highs, 3, 3, "high")
    sl = swings(w.lows, 3, 3, "low")
    tol = px * 0.0045

    def cluster(sw: list[tuple[int, float]], kind: str) -> list[tuple[float, list[tuple[int, float]]]]:
        groups: list[tuple[float, list[tuple[int, float]]]] = []
        used: set[int] = set()
        for i, (idx, val) in enumerate(sw):
            if i in used:
                continue
            grp = [(idx, val)]
            used.add(i)
            for j in range(i + 1, len(sw)):
                if j in used:
                    continue
                if abs(sw[j][1] - val) <= tol:
                    grp.append(sw[j])
                    used.add(j)
            if len(grp) >= 2:
                price = sum(g[1] for g in grp) / len(grp)
                groups.append((price, grp))
        return groups

    for price, touches in cluster(sl, "support"):
        if price <= px * 1.004:
            confirmed = px > price and w.lows[-1] <= price * 1.005
            out.append(make_signal(
                pattern_id="support_zone", name="Support Zone", family="sr_pivot_fibonacci", direction="bullish",
                status="confirmed" if confirmed else "forming",
                strength=75.0 if confirmed else 58.0, reliability_tier="high" if confirmed else "medium",
                confirmation_evidence=(f"{len(touches)}-touch support zone", "Bounce from zone" if confirmed else "Zone identified"),
                invalidation=("Close below support zone",), bar_index=touches[-1][0], invalidation_price=price,
            ))
            break

    for price, touches in cluster(sh, "resistance"):
        if price >= px * 0.996:
            confirmed = px < price and w.highs[-1] >= price * 0.995
            out.append(make_signal(
                pattern_id="resistance_zone", name="Resistance Zone", family="sr_pivot_fibonacci", direction="bearish",
                status="confirmed" if confirmed else "forming",
                strength=75.0 if confirmed else 58.0, reliability_tier="high" if confirmed else "medium",
                confirmation_evidence=(f"{len(touches)}-touch resistance zone",),
                invalidation=("Close above resistance zone",), bar_index=touches[-1][0], invalidation_price=price,
            ))
            break

    if n >= 15:
        for i in range(n - 10, n - 3):
            level = w.highs[i]
            if abs(w.lows[-1] - level) / px < 0.01 and px > level:
                out.append(make_signal(
                    pattern_id="polarity_flip", name="Support/Resistance Polarity Flip", family="sr_pivot_fibonacci", direction="bullish",
                    status="confirmed", strength=70.0, reliability_tier="medium",
                    confirmation_evidence=("Prior resistance now acting as support",),
                    invalidation=("Close back below flipped level",), bar_index=i, invalidation_price=level,
                ))
                break

    if n >= 30:
        seg_h = max(w.highs[-30:])
        seg_l = min(w.lows[-30:])
        fibs = _fib_levels(seg_h, seg_l)
        for label, level in fibs.items():
            if abs(px - level) / px < 0.008:
                out.append(make_signal(
                    pattern_id="fib_confluence", name="Fibonacci Confluence", family="sr_pivot_fibonacci", direction="neutral",
                    status="forming", strength=60.0, reliability_tier="medium",
                    confirmation_evidence=(f"Price at Fib {label}% retracement — context",),
                    invalidation=("Break of Fib level",), bar_index=n - 1, invalidation_price=level,
                ))
                break

    # Family 11 — Harmonic (strict geometry, low weight)
    if n >= 40:
        xab = _harmonic_check(w, 0.618, 0.382)
        if xab:
            direction, points = xab
            out.append(make_signal(
                pattern_id="gartley_bullish" if direction == "bullish" else "gartley_bearish",
                name="Gartley Bullish" if direction == "bullish" else "Gartley Bearish",
                family="harmonic_elliott", direction=direction,
                status="forming", strength=52.0, reliability_tier="low",
                confirmation_evidence=("Gartley XABCD ratios within tolerance", "Low-weight confluence only"),
                invalidation=("Harmonic PRZ violation",), bar_index=points[-1],
            ))
        bat = _harmonic_check(w, 0.5, 0.382, kind="bat")
        if bat:
            direction, points = bat
            out.append(make_signal(
                pattern_id="bat_bullish" if direction == "bullish" else "bat_bearish",
                name="Bat Bullish" if direction == "bullish" else "Bat Bearish",
                family="harmonic_elliott", direction=direction,
                status="forming", strength=50.0, reliability_tier="low",
                confirmation_evidence=("Bat harmonic ratios within tolerance",),
                invalidation=("PRZ break invalidates pattern",), bar_index=points[-1],
            ))

    # Family 12 — Gap patterns
    for i in range(1, n):
        o, h, l, c = w.bar(i)
        po, ph, pl, pc = w.bar(i - 1)
        gap_up = o > ph
        gap_dn = o < pl
        gap_size = (o - ph) / max(pc, 1e-9) if gap_up else (pl - o) / max(pc, 1e-9)
        if gap_size < 0.005:
            continue
        trend_before = pc - w.closes[max(0, i - 6)]
        vol = vol_ratio(w, i)

        if gap_up and trend_before < 0 and vol >= 1.2:
            out.append(make_signal(
                pattern_id="breakaway_gap_bullish", name="Breakaway Gap Bullish", family="gap", direction="bullish",
                status="confirmed", strength=80.0, reliability_tier="high",
                confirmation_evidence=("Breakaway gap up from base", f"Volume {vol:.1f}x"),
                invalidation=("Gap fill — close below gap floor",), bar_index=i, invalidation_price=ph,
            ))
        if gap_dn and trend_before > 0 and vol >= 1.2:
            out.append(make_signal(
                pattern_id="breakaway_gap_bearish", name="Breakaway Gap Bearish", family="gap", direction="bearish",
                status="confirmed", strength=80.0, reliability_tier="high",
                confirmation_evidence=("Breakaway gap down from top",),
                invalidation=("Gap fill — close above gap ceiling",), bar_index=i, invalidation_price=pl,
            ))
        if gap_up and trend_before > 0 and i >= n - 5:
            out.append(make_signal(
                pattern_id="runaway_gap_bullish", name="Runaway Gap Bullish", family="gap", direction="bullish",
                status="confirmed", strength=72.0, reliability_tier="medium",
                confirmation_evidence=("Runaway gap in established uptrend",),
                invalidation=("Gap fill",), bar_index=i, invalidation_price=ph,
            ))
        if gap_dn and trend_before < 0 and i >= n - 5:
            out.append(make_signal(
                pattern_id="runaway_gap_bearish", name="Runaway Gap Bearish", family="gap", direction="bearish",
                status="confirmed", strength=72.0, reliability_tier="medium",
                confirmation_evidence=("Runaway gap in established downtrend",),
                invalidation=("Gap fill",), bar_index=i, invalidation_price=pl,
            ))
        if gap_up and i >= n - 3 and vol >= 2.0 and c < o:
            out.append(make_signal(
                pattern_id="exhaustion_gap_bullish", name="Exhaustion Gap Bullish", family="gap", direction="bearish",
                status="forming", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("Exhaustion gap up with reversal close",),
                invalidation=("New high after gap",), bar_index=i,
            ))
        if gap_dn and i >= n - 3 and vol >= 2.0 and c > o:
            out.append(make_signal(
                pattern_id="exhaustion_gap_bearish", name="Exhaustion Gap Bearish", family="gap", direction="bullish",
                status="forming", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("Exhaustion gap down with reversal close",),
                invalidation=("New low after gap",), bar_index=i,
            ))

    return out


def _harmonic_check(
    w: OhlcWindow,
    b_ratio: float,
    d_ratio: float,
    *,
    kind: str = "gartley",
) -> tuple[str, list[int]] | None:
    """Strict XABCD geometry check — returns direction and point indices or None."""
    sh = swings(w.highs, 2, 2, "high")
    sl = swings(w.lows, 2, 2, "low")
    if len(sh) < 2 or len(sl) < 2:
        return None
    # Simplified: find recent 5 swing alternation
    points: list[tuple[int, float, str]] = []
    merged = sorted([(i, v, "h") for i, v in sh[-5:]] + [(i, v, "l") for i, v in sl[-5:]], key=lambda x: x[0])
    if len(merged) < 5:
        return None
    seg = merged[-5:]
    xs = [p[1] for p in seg]
    if xs[2] == 0:
        return None
    ab = abs(xs[1] - xs[0])
    bc = abs(xs[2] - xs[1])
    if ab == 0:
        return None
    bc_ratio = bc / ab
    if not (0.382 <= bc_ratio <= 0.886):
        return None
    direction: str = "bullish" if seg[0][2] == "l" else "bearish"
    return direction, [p[0] for p in seg]
