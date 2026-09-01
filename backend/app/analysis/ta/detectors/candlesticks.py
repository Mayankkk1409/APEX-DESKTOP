"""Candlestick pattern detectors — families 1–3 (38 patterns)."""

from __future__ import annotations

from app.analysis.ta.ohlc_utils import (
    OhlcWindow,
    PatternSignal,
    avg_body,
    bar_range,
    body,
    is_bearish,
    is_bullish,
    local_trend,
    lower_wick,
    make_signal,
    upper_wick,
    vol_ratio,
)


def _mid_body(o: float, c: float) -> float:
    return (o + c) / 2.0


def _is_morning_star(a: tuple[float, float, float, float], m: tuple, c: tuple, mean_body: float) -> bool:
    ao, ah, al, ac = a
    mo, mh, ml, mc = m
    co, ch, cl, cc = c
    a_body = body(ao, ac)
    m_body = body(mo, mc)
    c_body = body(co, cc)
    a_rng = bar_range(ah, al)
    c_rng = bar_range(ch, cl)
    floor = mean_body * 0.85 if mean_body > 0 else a_body
    if ac >= ao or a_body < a_rng * 0.52 or a_body < floor * 0.7:
        return False
    if m_body > a_body * 0.45 or mh > ao - a_body * 0.05:
        return False
    if cc <= co or c_body < c_rng * 0.48:
        return False
    return cc > _mid_body(ao, ac) and cc > ac


def _is_evening_star(a: tuple, m: tuple, c: tuple, mean_body: float) -> bool:
    ao, ah, al, ac = a
    mo, mh, ml, mc = m
    co, ch, cl, cc = c
    a_body = body(ao, ac)
    m_body = body(mo, mc)
    c_body = body(co, cc)
    a_rng = bar_range(ah, al)
    c_rng = bar_range(ch, cl)
    floor = mean_body * 0.85 if mean_body > 0 else a_body
    if ac <= ao or a_body < a_rng * 0.52 or a_body < floor * 0.7:
        return False
    if m_body > a_body * 0.45 or ml < ao + a_body * 0.05:
        return False
    if cc >= co or c_body < c_rng * 0.48:
        return False
    return cc < _mid_body(ao, ac) and cc < ac


def detect_candlestick_patterns(w: OhlcWindow) -> list[PatternSignal]:
    """Detect families 1–3 candlestick patterns on the full window."""
    if w.n < 2:
        return []
    out: list[PatternSignal] = []
    start = max(2, w.n - 18)
    seen: set[tuple[str, int]] = set()

    def add(sig: PatternSignal) -> None:
        key = (sig.id, sig.bar_index)
        if key in seen:
            return
        seen.add(key)
        out.append(sig)

    for i in range(start, w.n):
        o, h, l, c = w.bar(i)
        rng = bar_range(h, l)
        bd = body(o, c)
        up_w = upper_wick(o, c, h)
        dn_w = lower_wick(o, c, l)
        mean = avg_body(w, i)
        trend = local_trend(w, i)
        vr = vol_ratio(w, i)
        ts = w.timestamps[i] if i < len(w.timestamps) else None

        # Family 1 — single candle
        if dn_w >= bd * 2.4 and up_w <= rng * 0.16 and bd <= rng * 0.32 and min(o, c) > l + rng * 0.58:
            hammer_ctx = trend != "up"
            if hammer_ctx:
                confirmed = is_bullish(o, c) and (i == 0 or c > w.closes[i - 1]) and vr >= 1.0
                add(make_signal(
                    pattern_id="hammer", name="Hammer", family="single_candle_reversal", direction="bullish",
                    status="confirmed" if confirmed else "forming",
                    strength=78.0 if confirmed else 52.0,
                    reliability_tier="high" if confirmed else "medium",
                    confirmation_evidence=("Close above open", "Higher close vs prior bar") if confirmed else ("Long lower wick",),
                    invalidation=("Close below hammer low",),
                    bar_index=i, invalidation_price=l, timestamp=ts,
                ))
            else:
                confirmed = is_bearish(o, c) and trend == "up"
                add(make_signal(
                    pattern_id="hanging_man", name="Hanging Man", family="single_candle_reversal", direction="bearish",
                    status="confirmed" if confirmed else "forming",
                    strength=74.0 if confirmed else 50.0,
                    reliability_tier="high" if confirmed else "medium",
                    confirmation_evidence=("Bearish close after advance",) if confirmed else ("Long lower wick at highs",),
                    invalidation=("Close above hanging man high",),
                    bar_index=i, invalidation_price=h, timestamp=ts,
                ))

        if up_w >= bd * 2.4 and dn_w <= rng * 0.16 and bd <= rng * 0.32 and max(o, c) < h - rng * 0.58:
            star_ctx = trend != "down"
            if star_ctx:
                confirmed = is_bearish(o, c) and trend == "up"
                add(make_signal(
                    pattern_id="shooting_star", name="Shooting Star", family="single_candle_reversal", direction="bearish",
                    status="confirmed" if confirmed else "forming",
                    strength=76.0 if confirmed else 50.0,
                    reliability_tier="high" if confirmed else "medium",
                    confirmation_evidence=("Close below open after advance",) if confirmed else ("Long upper wick",),
                    invalidation=("Close above shooting star high",),
                    bar_index=i, invalidation_price=h, timestamp=ts,
                ))
            else:
                confirmed = is_bullish(o, c) and c > w.closes[i - 1]
                add(make_signal(
                    pattern_id="inverted_hammer", name="Inverted Hammer", family="single_candle_reversal", direction="bullish",
                    status="confirmed" if confirmed else "forming",
                    strength=72.0 if confirmed else 48.0,
                    reliability_tier="medium",
                    confirmation_evidence=("Bullish confirmation close",) if confirmed else ("Long upper wick after decline",),
                    invalidation=("Close below inverted hammer low",),
                    bar_index=i, invalidation_price=l, timestamp=ts,
                ))

        if bd <= rng * 0.08 and rng / max(c, 1e-9) > 0.005:
            dragon = dn_w > up_w * 2.2 and dn_w > bd * 3
            grave = up_w > dn_w * 2.2 and up_w > bd * 3
            long_legs = up_w > rng * 0.35 and dn_w > rng * 0.35
            if dragon:
                confirmed = i + 1 < w.n and w.closes[i + 1] > c
                add(make_signal(
                    pattern_id="dragonfly_doji", name="Dragonfly Doji", family="single_candle_reversal", direction="bullish",
                    status="confirmed" if confirmed else "forming",
                    strength=70.0 if confirmed else 45.0, reliability_tier="medium",
                    confirmation_evidence=("Follow-through close higher",) if confirmed else ("Dragonfly wick dominance",),
                    invalidation=("Close below doji low",), bar_index=i, invalidation_price=l, timestamp=ts,
                ))
            elif grave:
                confirmed = i + 1 < w.n and w.closes[i + 1] < c
                add(make_signal(
                    pattern_id="gravestone_doji", name="Gravestone Doji", family="single_candle_reversal", direction="bearish",
                    status="confirmed" if confirmed else "forming",
                    strength=70.0 if confirmed else 45.0, reliability_tier="medium",
                    confirmation_evidence=("Follow-through close lower",) if confirmed else ("Gravestone wick dominance",),
                    invalidation=("Close above doji high",), bar_index=i, invalidation_price=h, timestamp=ts,
                ))
            elif long_legs:
                add(make_signal(
                    pattern_id="long_legged_doji", name="Long-Legged Doji", family="single_candle_reversal", direction="neutral",
                    status="forming", strength=42.0, reliability_tier="low",
                    confirmation_evidence=("Long wicks both sides",), invalidation=("Requires directional follow-through",),
                    bar_index=i, timestamp=ts,
                ))
            else:
                add(make_signal(
                    pattern_id="doji", name="Doji", family="single_candle_reversal", direction="neutral",
                    status="forming", strength=42.0, reliability_tier="low",
                    confirmation_evidence=("Small body relative to range",), invalidation=("Requires follow-through bar",),
                    bar_index=i, timestamp=ts,
                ))

        if bd > rng * 0.08 and bd <= rng * 0.28 and up_w > rng * 0.25 and dn_w > rng * 0.25:
            add(make_signal(
                pattern_id="spinning_top", name="Spinning Top", family="single_candle_reversal", direction="neutral",
                status="forming", strength=44.0, reliability_tier="low",
                confirmation_evidence=("Balanced upper and lower wicks",), invalidation=("Wait for next close",),
                bar_index=i, timestamp=ts,
            ))

        if bd >= rng * 0.85:
            if is_bullish(o, c):
                add(make_signal(
                    pattern_id="bullish_marubozu", name="Bullish Marubozu", family="single_candle_reversal", direction="bullish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Full bullish body, minimal wicks",), invalidation=("Close below marubozu low",),
                    bar_index=i, invalidation_price=l, timestamp=ts,
                ))
            elif is_bearish(o, c):
                add(make_signal(
                    pattern_id="bearish_marubozu", name="Bearish Marubozu", family="single_candle_reversal", direction="bearish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Full bearish body, minimal wicks",), invalidation=("Close above marubozu high",),
                    bar_index=i, invalidation_price=h, timestamp=ts,
                ))

        if dn_w >= bd * 3 and up_w <= bd * 0.5 and trend == "down":
            add(make_signal(
                pattern_id="takuri", name="Takuri Line", family="single_candle_reversal", direction="bullish",
                status="confirmed" if is_bullish(o, c) else "forming",
                strength=75.0 if is_bullish(o, c) else 50.0, reliability_tier="medium",
                confirmation_evidence=("Extreme lower shadow at support",), invalidation=("Close below takuri low",),
                bar_index=i, invalidation_price=l, timestamp=ts,
            ))

        # Family 2 — multi-candle (2-bar)
        if i >= 1:
            po, ph, pl, pc = w.bar(i - 1)
            p_bull = is_bullish(po, pc)
            bull = is_bullish(o, c)
            p_bd = body(po, pc)

            if not p_bull and bull and o <= pc and c >= po and bd > p_bd * 1.12 and p_bd >= mean * 0.55:
                confirmed = vr >= 1.0 or trend == "down"
                add(make_signal(
                    pattern_id="bullish_engulfing", name="Bullish Engulfing", family="multi_candle_reversal", direction="bullish",
                    status="confirmed" if confirmed else "forming",
                    strength=82.0 if confirmed else 58.0, reliability_tier="high" if confirmed else "medium",
                    confirmation_evidence=("Body engulfs prior bearish candle", "Volume confirmation" if vr >= 1.0 else "Structure complete"),
                    invalidation=("Close back below engulfing open",), bar_index=i, invalidation_price=min(pl, l), timestamp=ts,
                ))
            if p_bull and not bull and o >= pc and c <= po and bd > p_bd * 1.12 and p_bd >= mean * 0.55:
                confirmed = vr >= 1.0 or trend == "up"
                add(make_signal(
                    pattern_id="bearish_engulfing", name="Bearish Engulfing", family="multi_candle_reversal", direction="bearish",
                    status="confirmed" if confirmed else "forming",
                    strength=80.0 if confirmed else 58.0, reliability_tier="high" if confirmed else "medium",
                    confirmation_evidence=("Body engulfs prior bullish candle",),
                    invalidation=("Close back above engulfing open",), bar_index=i, invalidation_price=max(ph, h), timestamp=ts,
                ))
            if not p_bull and bull and o < pl and c > _mid_body(po, pc) and c < po and p_bd >= mean * 0.8:
                add(make_signal(
                    pattern_id="piercing_line", name="Piercing Line", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=78.0, reliability_tier="medium",
                    confirmation_evidence=("Close pierced midpoint of prior bearish body",),
                    invalidation=("Close below piercing line low",), bar_index=i, timestamp=ts,
                ))
            if p_bull and not bull and o > ph and c < _mid_body(po, pc) and c > po and p_bd >= mean * 0.8:
                add(make_signal(
                    pattern_id="dark_cloud_cover", name="Dark Cloud Cover", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=78.0, reliability_tier="medium",
                    confirmation_evidence=("Close pierced midpoint of prior bullish body",),
                    invalidation=("Close above dark cloud high",), bar_index=i, timestamp=ts,
                ))
            if not p_bull and bull and o >= pc and c <= po and bd < p_bd * 0.55 and p_bd >= mean * 0.7:
                add(make_signal(
                    pattern_id="bullish_harami", name="Bullish Harami", family="multi_candle_reversal", direction="bullish",
                    status="forming", strength=58.0, reliability_tier="medium",
                    confirmation_evidence=("Small body inside prior bearish range",),
                    invalidation=("Close below harami low",), bar_index=i, timestamp=ts,
                ))
            if p_bull and not bull and o <= pc and c >= po and bd < p_bd * 0.55 and p_bd >= mean * 0.7:
                add(make_signal(
                    pattern_id="bearish_harami", name="Bearish Harami", family="multi_candle_reversal", direction="bearish",
                    status="forming", strength=58.0, reliability_tier="medium",
                    confirmation_evidence=("Small body inside prior bullish range",),
                    invalidation=("Close above harami high",), bar_index=i, timestamp=ts,
                ))
            if bd <= rng * 0.1 and p_bd > mean * 0.5 and o >= pc and c <= po:
                add(make_signal(
                    pattern_id="harami_cross", name="Harami Cross", family="multi_candle_reversal", direction="neutral",
                    status="forming", strength=55.0, reliability_tier="medium",
                    confirmation_evidence=("Doji inside prior body",), invalidation=("Break of parent range",),
                    bar_index=i, timestamp=ts,
                ))
            if abs(ph - h) / max(c, 1e-9) < 0.003 and p_bull and not bull and trend == "up":
                add(make_signal(
                    pattern_id="tweezer_top", name="Tweezer Top", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=72.0, reliability_tier="medium",
                    confirmation_evidence=("Matching highs at resistance", "Bearish follow bar"),
                    invalidation=("Close above tweezer highs",), bar_index=i, timestamp=ts,
                ))
            if abs(pl - l) / max(c, 1e-9) < 0.003 and not p_bull and bull and trend == "down":
                add(make_signal(
                    pattern_id="tweezer_bottom", name="Tweezer Bottom", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=72.0, reliability_tier="medium",
                    confirmation_evidence=("Matching lows at support", "Bullish follow bar"),
                    invalidation=("Close below tweezer lows",), bar_index=i, timestamp=ts,
                ))
            if not p_bull and bull and abs(o - pc) / max(c, 1e-9) < 0.002 and c > po:
                add(make_signal(
                    pattern_id="counterattack_bullish", name="Counterattack Bullish", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=70.0, reliability_tier="medium",
                    confirmation_evidence=("Matching opens, bullish close recovery",),
                    invalidation=("Close below counterattack low",), bar_index=i, timestamp=ts,
                ))
            if p_bull and bd >= rng * 0.85 and not bull and o > pc * 1.001:
                add(make_signal(
                    pattern_id="kicking_bullish", name="Kicking Bullish", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=85.0, reliability_tier="high",
                    confirmation_evidence=("Bearish marubozu followed by bullish marubozu with gap",),
                    invalidation=("Close below kicking pattern low",), bar_index=i, timestamp=ts,
                ))
            if not p_bull and bd >= rng * 0.85 and p_bull and o < pc * 0.999:
                add(make_signal(
                    pattern_id="kicking_bearish", name="Kicking Bearish", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=85.0, reliability_tier="high",
                    confirmation_evidence=("Bullish marubozu followed by bearish marubozu with gap",),
                    invalidation=("Close above kicking pattern high",), bar_index=i, timestamp=ts,
                ))
            if bull and o > po and c > pc and o < pl and c > ph:
                add(make_signal(
                    pattern_id="separating_lines_bullish", name="Separating Lines Bullish", family="continuation_candlestick", direction="bullish",
                    status="confirmed", strength=68.0, reliability_tier="medium",
                    confirmation_evidence=("Same-direction opens, expanding bullish close",),
                    invalidation=("Close below separating lines low",), bar_index=i, timestamp=ts,
                ))

        # Family 2 — 3-bar patterns
        if i >= 2:
            a = w.bar(i - 2)
            m = w.bar(i - 1)
            mean2 = avg_body(w, i - 2)
            if _is_morning_star(a, m, w.bar(i), mean2):
                add(make_signal(
                    pattern_id="morning_star", name="Morning Star", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=88.0, reliability_tier="high",
                    confirmation_evidence=("Three-bar bullish reversal structure", "Close through first-bar midpoint"),
                    invalidation=("Close below star low",), bar_index=i - 2, timestamp=ts,
                ))
            if _is_evening_star(a, m, w.bar(i), mean2):
                add(make_signal(
                    pattern_id="evening_star", name="Evening Star", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=86.0, reliability_tier="high",
                    confirmation_evidence=("Three-bar bearish reversal structure",),
                    invalidation=("Close above star high",), bar_index=i - 2, timestamp=ts,
                ))
            ao, ah, al, ac = a
            po, ph, pl, pc = w.bar(i - 1)
            if not is_bullish(ao, ac) and is_bullish(po, pc) and bd < body(po, pc) * 0.55 and is_bullish(o, c) and c > ah:
                add(make_signal(
                    pattern_id="three_inside_up", name="Three Inside Up", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Harami followed by breakout close",),
                    invalidation=("Close below pattern low",), bar_index=i - 2, timestamp=ts,
                ))
            if is_bullish(ao, ac) and not is_bullish(po, pc) and bd < body(po, pc) * 0.55 and is_bearish(o, c) and c < al:
                add(make_signal(
                    pattern_id="three_inside_down", name="Three Inside Down", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=80.0, reliability_tier="high",
                    confirmation_evidence=("Harami followed by breakdown close",),
                    invalidation=("Close above pattern high",), bar_index=i - 2, timestamp=ts,
                ))
            mo, mh, ml, mc = m
            if is_bearish(ao, ac) and body(mo, mc) <= rng * 0.1 and mh < ao and ml > ac and is_bullish(o, c):
                add(make_signal(
                    pattern_id="abandoned_baby_bullish", name="Abandoned Baby Bullish", family="multi_candle_reversal", direction="bullish",
                    status="confirmed", strength=84.0, reliability_tier="high",
                    confirmation_evidence=("Doji gapped from surrounding bodies", "Bullish third bar"),
                    invalidation=("Close below abandoned baby low",), bar_index=i - 2, timestamp=ts,
                ))
            if is_bullish(ao, ac) and body(mo, mc) <= bar_range(mh, ml) * 0.1 and ml > ao and mh < ac and is_bearish(o, c):
                add(make_signal(
                    pattern_id="abandoned_baby_bearish", name="Abandoned Baby Bearish", family="multi_candle_reversal", direction="bearish",
                    status="confirmed", strength=84.0, reliability_tier="high",
                    confirmation_evidence=("Doji gapped from surrounding bodies", "Bearish third bar"),
                    invalidation=("Close above abandoned baby high",), bar_index=i - 2, timestamp=ts,
                ))

        # Gap continuation (tasuki)
        if i >= 2:
            p2o, p2h, p2l, p2c = w.bar(i - 2)
            p1o, p1h, p1l, p1c = w.bar(i - 1)
            if p2c > p2o and p1o > p2h and is_bearish(o, c) and o < p1c and c > p2h:
                add(make_signal(
                    pattern_id="upside_tasuki_gap", name="Upside Tasuki Gap", family="continuation_candlestick", direction="bullish",
                    status="confirmed", strength=72.0, reliability_tier="medium",
                    confirmation_evidence=("Gap held by partial fill without close below gap",),
                    invalidation=("Close below gap floor",), bar_index=i, timestamp=ts,
                ))
            if p2c < p2o and p1o < p2l and is_bullish(o, c) and o > p1c and c < p2l:
                add(make_signal(
                    pattern_id="downside_tasuki_gap", name="Downside Tasuki Gap", family="continuation_candlestick", direction="bearish",
                    status="confirmed", strength=72.0, reliability_tier="medium",
                    confirmation_evidence=("Gap held by partial fill without close above gap",),
                    invalidation=("Close above gap ceiling",), bar_index=i, timestamp=ts,
                ))

    # Family 3 — continuation (window-level)
    if w.n >= 5:
        w3 = [w.bar(w.n - 3 + j) for j in range(3)]
        mean = avg_body(w, w.n - 1)
        i0 = w.n - 3
        soldiers = all(
            is_bullish(b[0], b[3]) and body(b[0], b[3]) >= mean * 0.7 and body(b[0], b[3]) >= bar_range(b[1], b[2]) * 0.5
            for b in w3
        ) and w3[1][3] > w3[0][3] and w3[2][3] > w3[1][3] and local_trend(w, i0) != "up"
        if soldiers:
            add(make_signal(
                pattern_id="three_white_soldiers", name="Three White Soldiers", family="continuation_candlestick", direction="bullish",
                status="confirmed", strength=85.0, reliability_tier="high",
                confirmation_evidence=("Three consecutive strong bullish bodies",),
                invalidation=("Break of first soldier low",), bar_index=i0,
            ))
        crows = all(
            is_bearish(b[0], b[3]) and body(b[0], b[3]) >= mean * 0.7 and body(b[0], b[3]) >= bar_range(b[1], b[2]) * 0.5
            for b in w3
        ) and w3[1][3] < w3[0][3] and w3[2][3] < w3[1][3] and local_trend(w, i0) != "down"
        if crows:
            add(make_signal(
                pattern_id="three_black_crows", name="Three Black Crows", family="continuation_candlestick", direction="bearish",
                status="confirmed", strength=85.0, reliability_tier="high",
                confirmation_evidence=("Three consecutive strong bearish bodies",),
                invalidation=("Break of first crow high",), bar_index=i0,
            ))

        if w.n >= 5:
            b0 = [w.bar(w.n - 5 + j) for j in range(5)]
            long_bull = is_bullish(b0[0][0], b0[0][3]) and body(b0[0][0], b0[0][3]) > mean
            inside_pullback = all(
                max(b[1], b[2]) <= b0[0][1] and min(b[1], b[2]) >= b0[0][2] for b in b0[1:4]
            )
            strong_finish = is_bullish(b0[4][0], b0[4][3]) and b0[4][3] > b0[0][3]
            if long_bull and inside_pullback and strong_finish:
                add(make_signal(
                    pattern_id="rising_three_methods", name="Rising Three Methods", family="continuation_candlestick", direction="bullish",
                    status="confirmed", strength=74.0, reliability_tier="medium",
                    confirmation_evidence=("Long candle, three inside bars, bullish continuation",),
                    invalidation=("Close below rising three methods low",), bar_index=w.n - 5,
                ))
            long_bear = is_bearish(b0[0][0], b0[0][3]) and body(b0[0][0], b0[0][3]) > mean
            if long_bear and inside_pullback and is_bearish(b0[4][0], b0[4][3]) and b0[4][3] < b0[0][3]:
                add(make_signal(
                    pattern_id="falling_three_methods", name="Falling Three Methods", family="continuation_candlestick", direction="bearish",
                    status="confirmed", strength=74.0, reliability_tier="medium",
                    confirmation_evidence=("Long candle, three inside bars, bearish continuation",),
                    invalidation=("Close above falling three methods high",), bar_index=w.n - 5,
                ))
            if long_bull and inside_pullback and strong_finish and b0[4][3] > b0[0][1]:
                add(make_signal(
                    pattern_id="mat_hold", name="Mat Hold", family="continuation_candlestick", direction="bullish",
                    status="confirmed", strength=76.0, reliability_tier="medium",
                    confirmation_evidence=("Strong bullish mat-hold continuation",),
                    invalidation=("Close below mat hold base",), bar_index=w.n - 5,
                ))

    return out
