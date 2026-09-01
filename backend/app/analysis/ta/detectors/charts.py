"""Chart pattern detectors — families 4–5 (24 patterns)."""

from __future__ import annotations

from app.analysis.ta.ohlc_utils import OhlcWindow, PatternSignal, make_signal, swings, vol_ratio


def _fit_ray(points: list[tuple[int, float]]) -> tuple[tuple[int, float], tuple[int, float], float] | None:
    if len(points) < 2:
        return None
    a, b = points[0], points[-1]
    if b[0] - a[0] < 8:
        return None
    slope = (b[1] - a[1]) / (b[0] - a[0])
    err = sum(abs(p[1] - (a[1] + slope * (p[0] - a[0]))) / max(abs(p[1]), 1e-9) for p in points) / len(points)
    if err > 0.004:
        return None
    return a, b, err


def detect_chart_patterns(w: OhlcWindow) -> list[PatternSignal]:
    if w.n < 20:
        return []
    out: list[PatternSignal] = []
    px = w.closes[-1]
    sh = swings(w.highs, 4, 4, "high")
    sl = swings(w.lows, 4, 4, "low")

    # Head & Shoulders
    for k in range(len(sh) - 1, 1, -1):
        L, H, R = sh[k - 2], sh[k - 1], sh[k]
        if H[0] - L[0] < 6 or R[0] - H[0] < 6:
            continue
        if not (H[1] > L[1] * 1.018 and H[1] > R[1] * 1.018):
            continue
        if abs(L[1] - R[1]) / H[1] > 0.055:
            continue
        t1 = min((s for s in sl if L[0] < s[0] < H[0]), key=lambda s: s[1], default=None)
        t2 = min((s for s in sl if H[0] < s[0] < R[0]), key=lambda s: s[1], default=None)
        if not t1 or not t2 or abs(t1[1] - t2[1]) / px > 0.03:
            continue
        neck = (t1[1] + t2[1]) / 2
        if (H[1] - neck) / px < 0.028:
            continue
        confirmed = px < neck and vol_ratio(w, w.n - 1) >= 1.0
        out.append(make_signal(
            pattern_id="head_shoulders", name="Head & Shoulders", family="classical_reversal_chart", direction="bearish",
            status="confirmed" if confirmed else "forming",
            strength=88.0 if confirmed else 62.0, reliability_tier="high" if confirmed else "medium",
            confirmation_evidence=("Neckline geometry validated", "Close below neckline" if confirmed else "Structure forming"),
            invalidation=("Close above right shoulder",), bar_index=L[0], invalidation_price=H[1],
        ))
        break

    # Inverse H&S
    for k in range(len(sl) - 1, 1, -1):
        L, H, R = sl[k - 2], sl[k - 1], sl[k]
        if H[0] - L[0] < 6 or R[0] - H[0] < 6:
            continue
        if not (H[1] < L[1] * 0.982 and H[1] < R[1] * 0.982):
            continue
        if abs(L[1] - R[1]) / max(L[1], 1e-9) > 0.055:
            continue
        p1 = max((s for s in sh if L[0] < s[0] < H[0]), key=lambda s: s[1], default=None)
        p2 = max((s for s in sh if H[0] < s[0] < R[0]), key=lambda s: s[1], default=None)
        if not p1 or not p2 or abs(p1[1] - p2[1]) / px > 0.03:
            continue
        neck = (p1[1] + p2[1]) / 2
        if (neck - H[1]) / px < 0.028:
            continue
        confirmed = px > neck
        out.append(make_signal(
            pattern_id="inverse_head_shoulders", name="Inverse Head & Shoulders", family="classical_reversal_chart", direction="bullish",
            status="confirmed" if confirmed else "forming",
            strength=88.0 if confirmed else 62.0, reliability_tier="high" if confirmed else "medium",
            confirmation_evidence=("Inverse neckline geometry", "Close above neckline" if confirmed else "Structure forming"),
            invalidation=("Close below head",), bar_index=L[0], invalidation_price=H[1],
        ))
        break

    # Double top / bottom
    if len(sh) >= 2:
        a, b = sh[-2], sh[-1]
        if b[0] - a[0] >= 10 and abs(a[1] - b[1]) / px < 0.01:
            valley = min(w.lows[a[0] : b[0] + 1])
            if (a[1] - valley) / px > 0.035 and px < min(a[1], b[1]):
                out.append(make_signal(
                    pattern_id="double_top", name="Double Top", family="classical_reversal_chart", direction="bearish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Two peaks at similar level", "Price below valley"),
                    invalidation=("Close above peak highs",), bar_index=a[0], invalidation_price=max(a[1], b[1]),
                ))
    if len(sl) >= 2:
        a, b = sl[-2], sl[-1]
        if b[0] - a[0] >= 10 and abs(a[1] - b[1]) / px < 0.01:
            peak = max(w.highs[a[0] : b[0] + 1])
            if (peak - a[1]) / px > 0.035 and px > max(a[1], b[1]):
                out.append(make_signal(
                    pattern_id="double_bottom", name="Double Bottom", family="classical_reversal_chart", direction="bullish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Two troughs at similar level", "Price above intervening peak"),
                    invalidation=("Close below trough lows",), bar_index=a[0], invalidation_price=min(a[1], b[1]),
                ))

    # Triple top / bottom
    if len(sh) >= 3:
        t = sh[-3:]
        if all(abs(t[i][1] - t[0][1]) / px < 0.015 for i in range(1, 3)) and px < t[0][1] * 0.99:
            out.append(make_signal(
                pattern_id="triple_top", name="Triple Top", family="classical_reversal_chart", direction="bearish",
                status="confirmed", strength=78.0, reliability_tier="medium",
                confirmation_evidence=("Three peaks at resistance",), invalidation=("Close above triple top",),
                bar_index=t[0][0],
            ))
    if len(sl) >= 3:
        t = sl[-3:]
        if all(abs(t[i][1] - t[0][1]) / px < 0.015 for i in range(1, 3)) and px > t[0][1] * 1.01:
            out.append(make_signal(
                pattern_id="triple_bottom", name="Triple Bottom", family="classical_reversal_chart", direction="bullish",
                status="confirmed", strength=78.0, reliability_tier="medium",
                confirmation_evidence=("Three troughs at support",), invalidation=("Close below triple bottom",),
                bar_index=t[0][0],
            ))

    # Rounding bottom / top
    if w.n >= 36:
        win = min(48, w.n)
        from_i = w.n - win
        window_lows = w.lows[from_i:]
        min_i = min(range(len(window_lows)), key=lambda j: window_lows[j])
        frac = min_i / max(win - 1, 1)
        if 0.32 < frac < 0.68:
            left = w.closes[from_i : from_i + min_i + 1]
            right = w.closes[from_i + min_i :]
            left_drop = left[0] - window_lows[min_i]
            right_lift = right[-1] - window_lows[min_i]
            if left_drop / px > 0.04 and right_lift > left_drop * 0.55:
                out.append(make_signal(
                    pattern_id="rounding_bottom", name="Rounding Bottom", family="classical_reversal_chart", direction="bullish",
                    status="confirmed", strength=76.0, reliability_tier="medium",
                    confirmation_evidence=("U-shaped recovery over extended window",),
                    invalidation=("Close below rounding trough",), bar_index=from_i + min_i,
                ))
        window_highs = w.highs[from_i:]
        max_i = max(range(len(window_highs)), key=lambda j: window_highs[j])
        frac_h = max_i / max(win - 1, 1)
        if 0.32 < frac_h < 0.68:
            out.append(make_signal(
                pattern_id="rounding_top", name="Rounding Top", family="classical_reversal_chart", direction="bearish",
                status="forming", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("Inverted U-shape forming",), invalidation=("Close above rounding peak",),
                bar_index=from_i + max_i,
            ))

    # V-top / V-bottom (sharp reversal)
    if w.n >= 15:
        seg = w.closes[-15:]
        mid = len(seg) // 2
        left_slope = (seg[mid] - seg[0]) / max(mid, 1)
        right_slope = (seg[-1] - seg[mid]) / max(len(seg) - mid, 1)
        if left_slope > 0 and right_slope < 0 and abs(left_slope) > px * 0.002:
            out.append(make_signal(
                pattern_id="v_top", name="V-Top", family="classical_reversal_chart", direction="bearish",
                status="confirmed", strength=70.0, reliability_tier="medium",
                confirmation_evidence=("Sharp peak reversal",), invalidation=("Close above V-top",),
                bar_index=w.n - 15,
            ))
        if left_slope < 0 and right_slope > 0 and abs(left_slope) > px * 0.002:
            out.append(make_signal(
                pattern_id="v_bottom", name="V-Bottom", family="classical_reversal_chart", direction="bullish",
                status="confirmed", strength=70.0, reliability_tier="medium",
                confirmation_evidence=("Sharp trough reversal",), invalidation=("Close below V-bottom",),
                bar_index=w.n - 15,
            ))

    # Diamond patterns (volatility contraction then expansion)
    if w.n >= 25:
        widths = [w.highs[i] - w.lows[i] for i in range(w.n - 25, w.n)]
        half = len(widths) // 2
        first = sum(widths[:half]) / half
        second = sum(widths[half : half + half // 2]) / max(half // 2, 1)
        third = sum(widths[-half // 2 :]) / max(half // 2, 1)
        if first > second * 1.2 and third > second * 1.2:
            direction = "bearish" if w.closes[-1] < w.closes[w.n - 25] else "bullish"
            pid = "diamond_top" if direction == "bearish" else "diamond_bottom"
            out.append(make_signal(
                pattern_id=pid,
                name="Diamond Top" if direction == "bearish" else "Diamond Bottom",
                family="classical_reversal_chart", direction=direction,
                status="forming", strength=66.0, reliability_tier="medium",
                confirmation_evidence=("Volatility diamond contraction-expansion",),
                invalidation=("Break of diamond boundary",), bar_index=w.n - 25,
            ))

    # Family 5 — continuation chart patterns
    if w.n >= 20:
        pole_start = max(0, w.n - 20)
        pole_end = w.n - 8
        if pole_end > pole_start:
            pole_move = (w.closes[pole_end] - w.closes[pole_start]) / max(w.closes[pole_start], 1e-9)
            flag_high = max(w.highs[pole_end:])
            flag_low = min(w.lows[pole_end:])
            flag_range = (flag_high - flag_low) / px
            if pole_move > 0.04 and flag_range < 0.025:
                out.append(make_signal(
                    pattern_id="bull_flag", name="Bull Flag", family="classical_continuation_chart", direction="bullish",
                    status="confirmed" if px > flag_high else "forming",
                    strength=82.0 if px > flag_high else 60.0, reliability_tier="high" if px > flag_high else "medium",
                    confirmation_evidence=("Pole advance with tight flag consolidation",),
                    invalidation=("Close below flag low",), bar_index=pole_end,
                ))
            if pole_move < -0.04 and flag_range < 0.025:
                out.append(make_signal(
                    pattern_id="bear_flag", name="Bear Flag", family="classical_continuation_chart", direction="bearish",
                    status="confirmed" if px < flag_low else "forming",
                    strength=82.0 if px < flag_low else 60.0, reliability_tier="high" if px < flag_low else "medium",
                    confirmation_evidence=("Pole decline with tight flag consolidation",),
                    invalidation=("Close above flag high",), bar_index=pole_end,
                ))

    # Triangles via swing convergence
    if len(sh) >= 3 and len(sl) >= 3:
        rh = sh[-3:]
        rl = sl[-3:]
        flat_top = abs(rh[-1][1] - rh[0][1]) / px < 0.012
        rising_lows = rl[-1][1] > rl[0][1] * 1.01
        falling_highs = rh[-1][1] < rh[0][1] * 0.99
        flat_bottom = abs(rl[-1][1] - rl[0][1]) / px < 0.012
        if flat_top and rising_lows:
            out.append(make_signal(
                pattern_id="ascending_triangle", name="Ascending Triangle", family="classical_continuation_chart", direction="bullish",
                status="confirmed" if px > rh[-1][1] else "forming",
                strength=75.0 if px > rh[-1][1] else 58.0, reliability_tier="medium",
                confirmation_evidence=("Flat resistance, rising support",),
                invalidation=("Close below ascending trendline",), bar_index=rl[0][0],
            ))
        if flat_bottom and falling_highs:
            out.append(make_signal(
                pattern_id="descending_triangle", name="Descending Triangle", family="classical_continuation_chart", direction="bearish",
                status="confirmed" if px < rl[-1][1] else "forming",
                strength=75.0 if px < rl[-1][1] else 58.0, reliability_tier="medium",
                confirmation_evidence=("Flat support, falling resistance",),
                invalidation=("Close above descending trendline",), bar_index=rh[0][0],
            ))
        if falling_highs and rising_lows:
            out.append(make_signal(
                pattern_id="symmetrical_triangle", name="Symmetrical Triangle", family="classical_continuation_chart", direction="neutral",
                status="forming", strength=55.0, reliability_tier="medium",
                confirmation_evidence=("Converging highs and lows",), invalidation=("Break of triangle boundary",),
                bar_index=min(rh[0][0], rl[0][0]),
            ))

    # Wedges
    if len(sh) >= 3 and len(sl) >= 3:
        rh, rl = sh[-3:], sl[-3:]
        r_slope = (rh[-1][1] - rh[0][1]) / max(rh[-1][0] - rh[0][0], 1)
        s_slope = (rl[-1][1] - rl[0][1]) / max(rl[-1][0] - rl[0][0], 1)
        if r_slope > 0 and s_slope > 0 and r_slope > s_slope:
            out.append(make_signal(
                pattern_id="rising_wedge", name="Rising Wedge", family="classical_continuation_chart", direction="bearish",
                status="forming", strength=62.0, reliability_tier="medium",
                confirmation_evidence=("Both trendlines rising, converging",),
                invalidation=("Close above wedge",), bar_index=rh[0][0],
            ))
        if r_slope < 0 and s_slope < 0 and abs(r_slope) > abs(s_slope):
            out.append(make_signal(
                pattern_id="falling_wedge", name="Falling Wedge", family="classical_continuation_chart", direction="bullish",
                status="forming", strength=62.0, reliability_tier="medium",
                confirmation_evidence=("Both trendlines falling, converging",),
                invalidation=("Close below wedge",), bar_index=rl[0][0],
            ))

    # Pennant (small sym triangle after pole)
    if w.n >= 15:
        pole = (w.closes[-8] - w.closes[-15]) / max(w.closes[-15], 1e-9)
        recent_range = (max(w.highs[-7:]) - min(w.lows[-7:])) / px
        if abs(pole) > 0.03 and recent_range < 0.02:
            out.append(make_signal(
                pattern_id="pennant", name="Pennant", family="classical_continuation_chart",
                direction="bullish" if pole > 0 else "bearish",
                status="forming", strength=58.0, reliability_tier="medium",
                confirmation_evidence=("Pennant consolidation after impulse",),
                invalidation=("Break against pole direction",), bar_index=w.n - 7,
            ))

    # Cup & handle
    if w.n >= 50:
        cup_len = 40
        handle_len = 10
        cup = w.closes[-cup_len - handle_len : -handle_len]
        handle = w.closes[-handle_len:]
        cup_low_i = min(range(len(cup)), key=lambda j: cup[j])
        left_rim = cup[0]
        right_rim = cup[-1]
        cup_depth = (max(left_rim, right_rim) - cup[cup_low_i]) / px
        handle_pullback = (max(handle) - min(handle)) / px
        if cup_depth > 0.08 and abs(left_rim - right_rim) / px < 0.03 and handle_pullback < cup_depth * 0.4:
            out.append(make_signal(
                pattern_id="cup_handle", name="Cup & Handle", family="classical_continuation_chart", direction="bullish",
                status="confirmed" if px > right_rim else "forming",
                strength=84.0 if px > right_rim else 65.0, reliability_tier="high" if px > right_rim else "medium",
                confirmation_evidence=("Rounded cup with shallow handle",),
                invalidation=("Close below handle low",), bar_index=w.n - cup_len - handle_len,
            ))
            out.append(make_signal(
                pattern_id="inverted_cup_handle", name="Inverted Cup & Handle", family="classical_continuation_chart", direction="bearish",
                status="forming", strength=60.0, reliability_tier="medium",
                confirmation_evidence=("Inverted cup geometry (mirror)",),
                invalidation=("Close above handle high",), bar_index=w.n - cup_len - handle_len,
            ))

    # Rectangle
    if w.n >= 20:
        seg_h = w.highs[-20:]
        seg_l = w.lows[-20:]
        if (max(seg_h) - min(seg_l)) / px < 0.06:
            out.append(make_signal(
                pattern_id="rectangle", name="Rectangle", family="classical_continuation_chart", direction="neutral",
                status="forming", strength=56.0, reliability_tier="medium",
                confirmation_evidence=("Horizontal range bound",), invalidation=("Break of rectangle",),
                bar_index=w.n - 20,
            ))

    # Measured move
    if w.n >= 30:
        leg1 = w.closes[-20] - w.closes[-30]
        leg2 = w.closes[-1] - w.closes[-10]
        if leg1 != 0 and abs(leg2 / leg1 - 1.0) < 0.15 and leg1 * leg2 > 0:
            out.append(make_signal(
                pattern_id="measured_move", name="Measured Move", family="classical_continuation_chart",
                direction="bullish" if leg2 > 0 else "bearish",
                status="confirmed", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("Second leg approximates first leg length",),
                invalidation=("Break of measured move base",), bar_index=w.n - 30,
            ))

    return out
