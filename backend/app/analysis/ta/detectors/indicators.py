"""Indicator-based pattern detectors — families 6–9."""

from __future__ import annotations

from typing import Any

from app.analysis.indicators import ema, macd, rsi as rsi_series
from app.analysis.ta.indicators_ext import (
    cci,
    divergence,
    find_cross,
    keltner,
    obv,
    percent_b,
    stochastic,
    vwap,
)
from app.analysis.ta.ohlc_utils import OhlcWindow, PatternSignal, make_signal, vol_ratio


def detect_indicator_patterns(w: OhlcWindow, indicators: dict[str, Any]) -> list[PatternSignal]:
    out: list[PatternSignal] = []
    n = w.n
    if n < 14:
        return out

    macd_data = macd(w.closes)
    rsi_vals = rsi_series(w.closes)
    stoch = stochastic(w.highs, w.lows, w.closes)
    cci_vals = cci(w.highs, w.lows, w.closes)
    obv_vals = obv(w.closes, w.volumes)
    vwap_vals = vwap(w.highs, w.lows, w.closes, w.volumes)
    bb = indicators.get("bollinger_series") or {}
    upper = bb.get("upper") or []
    lower = bb.get("lower") or []
    width = bb.get("width") or []
    kelt = keltner(w.highs, w.lows, w.closes)
    ema9 = ema(w.closes, 9)
    ema21 = ema(w.closes, 21)
    ema50 = ema(w.closes, 50)
    ema200 = ema(w.closes, 200)
    st_series = indicators.get("supertrend_series") or []
    px = w.closes[-1]
    vr = vol_ratio(w, n - 1)

    from_idx = max(8, n - 16)

    # Family 6 — momentum oscillators
    macd_x = find_cross(macd_data["line"], macd_data["signal"], from_idx)
    if macd_x:
        i, bull = macd_x
        out.append(make_signal(
            pattern_id="macd_bullish_cross" if bull else "macd_bearish_cross",
            name="MACD Bullish Crossover" if bull else "MACD Bearish Crossover",
            family="momentum_oscillator", direction="bullish" if bull else "bearish",
            status="confirmed", strength=82.0, reliability_tier="high",
            confirmation_evidence=("MACD line crossed signal", f"Histogram {'positive' if bull else 'negative'}"),
            invalidation=("MACD cross back through signal",), bar_index=i,
        ))
    if divergence(w.closes, macd_data["histogram"], 20, "bullish"):
        out.append(make_signal(
            pattern_id="macd_bullish_divergence", name="MACD Bullish Divergence", family="momentum_oscillator", direction="bullish",
            status="confirmed", strength=72.0, reliability_tier="medium",
            confirmation_evidence=("Price lower low, MACD higher low",), invalidation=("New price low on MACD",),
            bar_index=n - 1,
        ))
    if divergence(w.closes, macd_data["histogram"], 20, "bearish"):
        out.append(make_signal(
            pattern_id="macd_bearish_divergence", name="MACD Bearish Divergence", family="momentum_oscillator", direction="bearish",
            status="confirmed", strength=72.0, reliability_tier="medium",
            confirmation_evidence=("Price higher high, MACD lower high",), invalidation=("New price high on MACD",),
            bar_index=n - 1,
        ))

    if len(rsi_vals) >= 2:
        r = rsi_vals[-1]
        r_prev = rsi_vals[-2]
        if r_prev < 30 <= r:
            out.append(make_signal(
                pattern_id="rsi_oversold_bounce", name="RSI Oversold Bounce", family="momentum_oscillator", direction="bullish",
                status="confirmed", strength=78.0, reliability_tier="high",
                confirmation_evidence=("RSI reclaimed 30 from oversold",), invalidation=("RSI fails back below 30",),
                bar_index=n - 1,
            ))
        if r_prev > 70 >= r:
            out.append(make_signal(
                pattern_id="rsi_overbought_rejection", name="RSI Overbought Rejection", family="momentum_oscillator", direction="bearish",
                status="confirmed", strength=78.0, reliability_tier="high",
                confirmation_evidence=("RSI rejected from overbought",), invalidation=("RSI reclaims 70",),
                bar_index=n - 1,
            ))
    if divergence(w.closes, rsi_vals, 20, "bullish"):
        out.append(make_signal(
            pattern_id="rsi_bullish_divergence", name="RSI Bullish Divergence", family="momentum_oscillator", direction="bullish",
            status="confirmed", strength=70.0, reliability_tier="medium",
            confirmation_evidence=("Price lower low, RSI higher low",), invalidation=("Price breaks divergence low",),
            bar_index=n - 1,
        ))
    if divergence(w.closes, rsi_vals, 20, "bearish"):
        out.append(make_signal(
            pattern_id="rsi_bearish_divergence", name="RSI Bearish Divergence", family="momentum_oscillator", direction="bearish",
            status="confirmed", strength=70.0, reliability_tier="medium",
            confirmation_evidence=("Price higher high, RSI lower high",), invalidation=("Price breaks divergence high",),
            bar_index=n - 1,
        ))

    stoch_x = find_cross(stoch["k"], stoch["d"], from_idx)
    if stoch_x:
        i, bull = stoch_x
        k_val = stoch["k"][i]
        if bull and k_val < 30:
            out.append(make_signal(
                pattern_id="stoch_oversold_cross", name="Stochastic Oversold Cross", family="momentum_oscillator", direction="bullish",
                status="confirmed", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("%K crossed %D in oversold zone",), invalidation=("%K falls back below %D",),
                bar_index=i,
            ))
        if not bull and k_val > 70:
            out.append(make_signal(
                pattern_id="stoch_overbought_cross", name="Stochastic Overbought Cross", family="momentum_oscillator", direction="bearish",
                status="confirmed", strength=68.0, reliability_tier="medium",
                confirmation_evidence=("%K crossed below %D in overbought",), invalidation=("%K reclaims %D",),
                bar_index=i,
            ))

    if cci_vals[-1] < -100:
        out.append(make_signal(
            pattern_id="cci_oversold", name="CCI Oversold", family="momentum_oscillator", direction="bullish",
            status="forming", strength=60.0, reliability_tier="medium",
            confirmation_evidence=("CCI below -100",), invalidation=("CCI fails to recover",), bar_index=n - 1,
        ))
    if cci_vals[-1] > 100:
        out.append(make_signal(
            pattern_id="cci_overbought", name="CCI Overbought", family="momentum_oscillator", direction="bearish",
            status="forming", strength=60.0, reliability_tier="medium",
            confirmation_evidence=("CCI above 100",), invalidation=("CCI mean reverts",), bar_index=n - 1,
        ))

    # Family 7 — trend structure
    ema_stack = indicators.get("ema") or {}
    if indicators.get("ema_aligned_bullish"):
        out.append(make_signal(
            pattern_id="ema_stack_bullish", name="EMA Stack Bullish", family="trend_structure", direction="bullish",
            status="confirmed", strength=90.0, reliability_tier="high",
            confirmation_evidence=("9>21>50>100>200 EMA alignment",), invalidation=("Close below EMA 21",),
            bar_index=n - 1,
        ))
    elif indicators.get("ema_aligned_bearish"):
        out.append(make_signal(
            pattern_id="ema_stack_bearish", name="EMA Stack Bearish", family="trend_structure", direction="bearish",
            status="confirmed", strength=90.0, reliability_tier="high",
            confirmation_evidence=("9<21<50<100<200 EMA alignment",), invalidation=("Close above EMA 21",),
            bar_index=n - 1,
        ))
    if n >= 200 and ema50[-1] > ema200[-1] and ema50[-2] <= ema200[-2]:
        out.append(make_signal(
            pattern_id="golden_cross", name="Golden Cross", family="trend_structure", direction="bullish",
            status="confirmed", strength=86.0, reliability_tier="high",
            confirmation_evidence=("EMA 50 crossed above EMA 200",), invalidation=("EMA 50 crosses back below 200",),
            bar_index=n - 1,
        ))
    if n >= 200 and ema50[-1] < ema200[-1] and ema50[-2] >= ema200[-2]:
        out.append(make_signal(
            pattern_id="death_cross", name="Death Cross", family="trend_structure", direction="bearish",
            status="confirmed", strength=86.0, reliability_tier="high",
            confirmation_evidence=("EMA 50 crossed below EMA 200",), invalidation=("EMA 50 crosses back above 200",),
            bar_index=n - 1,
        ))

    if len(st_series) >= 2:
        for i in range(n - 1, from_idx, -1):
            if i >= len(st_series):
                continue
            prev = st_series[i - 1].get("direction") if isinstance(st_series[i - 1], dict) else getattr(st_series[i - 1], "direction", None)
            cur = st_series[i].get("direction") if isinstance(st_series[i], dict) else getattr(st_series[i], "direction", None)
            if prev is None or cur is None or prev == cur:
                continue
            bull = cur == 1 or cur == "bullish"
            out.append(make_signal(
                pattern_id="supertrend_bullish_flip" if bull else "supertrend_bearish_flip",
                name="SuperTrend Bullish Flip" if bull else "SuperTrend Bearish Flip",
                family="trend_structure", direction="bullish" if bull else "bearish",
                status="confirmed", strength=84.0, reliability_tier="high",
                confirmation_evidence=("SuperTrend direction flip with ATR filter",),
                invalidation=("SuperTrend flips back",), bar_index=i,
            ))
            break

    for period, ema_line, pid, label in (
        (21, ema21, "ema21_bounce", "EMA 21 Bounce"),
        (50, ema50, "ema50_bounce", "EMA 50 Bounce"),
        (200, ema200, "ema200_bounce", "EMA 200 Bounce"),
    ):
        if n < period + 2:
            continue
        e = ema_line[-1]
        if w.lows[-1] <= e * 1.005 and px > e and px > w.closes[-2]:
            out.append(make_signal(
                pattern_id=pid, name=label, family="trend_structure", direction="bullish",
                status="confirmed", strength=72.0, reliability_tier="medium",
                confirmation_evidence=(f"Price bounced off EMA {period}", "Close above EMA"),
                invalidation=(f"Close below EMA {period}",), bar_index=n - 1, invalidation_price=e,
            ))

    if n >= 50:
        spread_now = ema9[-1] - ema21[-1]
        spread_prev = ema9[-10] - ema21[-10]
        if abs(spread_now) > abs(spread_prev) * 1.3:
            out.append(make_signal(
                pattern_id="ma_ribbon_expansion", name="MA Ribbon Expansion", family="trend_structure", direction="neutral",
                status="confirmed", strength=65.0, reliability_tier="medium",
                confirmation_evidence=("EMA ribbon widening — trend acceleration",),
                invalidation=("Ribbon compression",), bar_index=n - 1,
            ))

    # Family 8 — volatility
    if width and len(width) >= 20:
        w_last = width[-1]
        squeeze = w_last < 0.04 or (width[-1] < sum(width[-20:]) / 20 * 0.7)
        breakout_up = upper and px > upper[-1]
        breakout_dn = lower and px < lower[-1]
        if squeeze and not (breakout_up or breakout_dn):
            out.append(make_signal(
                pattern_id="bollinger_squeeze", name="Bollinger Squeeze", family="volatility", direction="neutral",
                status="forming", strength=55.0, reliability_tier="medium",
                confirmation_evidence=("Band width compressed — vol precursor only",),
                invalidation=("Breakout with volume required for direction",), bar_index=n - 1,
            ))
        elif squeeze and breakout_up and vr >= 1.2:
            out.append(make_signal(
                pattern_id="bollinger_squeeze", name="Bollinger Squeeze", family="volatility", direction="bullish",
                status="confirmed", strength=78.0, reliability_tier="medium",
                confirmation_evidence=("Squeeze breakout above upper band", f"Volume {vr:.1f}x average"),
                invalidation=("Close back inside bands",), bar_index=n - 1,
            ))
        if upper and lower and len(upper) >= 5:
            walk_up = all(w.closes[-j] > upper[-j] * 0.998 for j in range(1, min(4, n)))
            walk_dn = all(w.closes[-j] < lower[-j] * 1.002 for j in range(1, min(4, n)))
            if walk_up:
                out.append(make_signal(
                    pattern_id="bollinger_walk_upper", name="Bollinger Walk Upper", family="volatility", direction="bullish",
                    status="confirmed", strength=74.0, reliability_tier="medium",
                    confirmation_evidence=("Price walking upper Bollinger band",),
                    invalidation=("Close below mid band",), bar_index=n - 1,
                ))
            if walk_dn:
                out.append(make_signal(
                    pattern_id="bollinger_walk_lower", name="Bollinger Walk Lower", family="volatility", direction="bearish",
                    status="confirmed", strength=74.0, reliability_tier="medium",
                    confirmation_evidence=("Price walking lower Bollinger band",),
                    invalidation=("Close above mid band",), bar_index=n - 1,
                ))
            pb = percent_b(w.closes, upper, lower)
            if len(pb) >= 5 and pb[-3] < 0.2 and pb[-1] > 0.5 and pb[-2] > pb[-3]:
                out.append(make_signal(
                    pattern_id="percent_b_w_bottom", name="%B W-Bottom", family="volatility", direction="bullish",
                    status="confirmed", strength=70.0, reliability_tier="medium",
                    confirmation_evidence=("%B double bottom in lower band",),
                    invalidation=("%B fails back below 0.2",), bar_index=n - 3,
                ))
            if len(pb) >= 5 and pb[-3] > 0.8 and pb[-1] < 0.5:
                out.append(make_signal(
                    pattern_id="percent_b_m_top", name="%B M-Top", family="volatility", direction="bearish",
                    status="confirmed", strength=70.0, reliability_tier="medium",
                    confirmation_evidence=("%B double top in upper band",),
                    invalidation=("%B reclaims 0.8",), bar_index=n - 3,
                ))

    if width and kelt["mid"]:
        bb_w = width[-1] if width else 1.0
        kc_w = (kelt["upper"][-1] - kelt["lower"][-1]) / max(kelt["mid"][-1], 1e-9)
        if bb_w < kc_w * 0.9:
            out.append(make_signal(
                pattern_id="keltner_squeeze", name="Keltner Channel Squeeze", family="volatility", direction="neutral",
                status="forming", strength=58.0, reliability_tier="medium",
                confirmation_evidence=("BB inside Keltner — compression",),
                invalidation=("Expansion breakout required",), bar_index=n - 1,
            ))
            out.append(make_signal(
                pattern_id="ttm_squeeze", name="TTM Squeeze", family="volatility", direction="neutral",
                status="forming", strength=58.0, reliability_tier="medium",
                confirmation_evidence=("TTM squeeze: BB/Keltner compression",),
                invalidation=("Momentum release needed",), bar_index=n - 1,
            ))

    from app.analysis.ta.indicators_ext import atr_series
    atr = atr_series(w.highs, w.lows, w.closes, 14)
    if len(atr) >= 20 and atr[-1] > sum(atr[-20:]) / 20 * 1.4 and vr >= 1.5:
        out.append(make_signal(
            pattern_id="atr_expansion_breakout", name="ATR Expansion Breakout", family="volatility", direction="neutral",
            status="confirmed", strength=72.0, reliability_tier="medium",
            confirmation_evidence=("ATR expansion with volume",), invalidation=("ATR contracts back",),
            bar_index=n - 1,
        ))

    # Family 9 — volume
    if divergence(w.closes, obv_vals, 20, "bullish"):
        out.append(make_signal(
            pattern_id="obv_bullish_divergence", name="OBV Bullish Divergence", family="volume", direction="bullish",
            status="confirmed", strength=70.0, reliability_tier="medium",
            confirmation_evidence=("Price lower low, OBV higher low",),
            invalidation=("OBV breaks divergence",), bar_index=n - 1,
        ))
    if divergence(w.closes, obv_vals, 20, "bearish"):
        out.append(make_signal(
            pattern_id="obv_bearish_divergence", name="OBV Bearish Divergence", family="volume", direction="bearish",
            status="confirmed", strength=70.0, reliability_tier="medium",
            confirmation_evidence=("Price higher high, OBV lower high",),
            invalidation=("OBV breaks divergence",), bar_index=n - 1,
        ))
    if len(vwap_vals) >= 2 and w.closes[-2] < vwap_vals[-2] <= px:
        out.append(make_signal(
            pattern_id="vwap_reclaim", name="VWAP Reclaim", family="volume", direction="bullish",
            status="confirmed", strength=68.0, reliability_tier="medium",
            confirmation_evidence=("Close reclaimed VWAP",), invalidation=("Close back below VWAP",),
            bar_index=n - 1,
        ))
    if len(vwap_vals) >= 2 and w.closes[-2] > vwap_vals[-2] >= px:
        out.append(make_signal(
            pattern_id="vwap_rejection", name="VWAP Rejection", family="volume", direction="bearish",
            status="confirmed", strength=68.0, reliability_tier="medium",
            confirmation_evidence=("Rejected at VWAP",), invalidation=("Close back above VWAP",),
            bar_index=n - 1,
        ))
    if vr >= 2.5 and px > w.closes[-2] and w.closes[-1] > w.opens[-1]:
        out.append(make_signal(
            pattern_id="volume_climax_bullish", name="Volume Climax Bullish", family="volume", direction="bullish",
            status="confirmed", strength=76.0, reliability_tier="high",
            confirmation_evidence=(f"Climax volume {vr:.1f}x average with bullish close",),
            invalidation=("Follow-through failure next bar",), bar_index=n - 1,
        ))
    if vr >= 1.5 and n >= 21:
        range20 = max(w.highs[-21:-1]) - min(w.lows[-21:-1])
        if px > max(w.highs[-21:-1]) and range20 / px > 0.02:
            out.append(make_signal(
                pattern_id="volume_breakout_confirm", name="Volume Breakout Confirmation", family="volume", direction="neutral",
                status="confirmed", strength=80.0, reliability_tier="high",
                confirmation_evidence=("Breakout above 20-bar range with elevated volume",),
                invalidation=("Close back inside range",), bar_index=n - 1,
            ))

    return out
