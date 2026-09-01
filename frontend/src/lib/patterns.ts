import type { PlotSeries } from "./plotChart";
import { supportResistance, type OhlcBar } from "./ta";

export type CatalystBias = "bullish" | "bearish";

export type MarkPoint = { i: number; price: number };

export type Catalyst = {
  id: string;
  name: string;
  bias: CatalystBias;
  kind: "candle" | "structure" | "trend" | "momentum" | "level";
  barIndex: number;
  barEnd?: number;
  price: number;
  price2?: number;
  points?: MarkPoint[];
  explain: string;
  confidence: number;
};

/** Large multi-candle structures (H&S, flags, channels) → rectangle on the snapshot. */
export function patternUsesBoxMark(c: Catalyst): boolean {
  if (c.kind !== "structure") return false;
  return /head\s*&\s*shoulders|inverse head|flag|channel|double top|double bottom|rounding bottom/i.test(c.name);
}

/** Catalysts that receive a visible mark when their analysis card is active. */
export function catalystIsDrawableOnChart(c: Catalyst): boolean {
  if (/supertrend|support|resistance|trendline|pivot|sma\b/i.test(c.name)) return false;
  if (c.kind === "level" || c.kind === "trend") return false;
  if (/macd.*cross|ema.*cross/i.test(c.name)) return true;
  if (patternUsesBoxMark(c)) return true;
  return c.kind === "candle";
}

function body(o: number, c: number) {
  return Math.abs(c - o);
}
function range(h: number, l: number) {
  return Math.max(h - l, 1e-9);
}
function midBody(o: number, c: number) {
  return (o + c) / 2;
}
function avgBody(bars: OhlcBar[], i: number, look = 14) {
  const a = Math.max(0, i - look);
  const slice = bars.slice(a, i);
  if (!slice.length) return body(bars[i].o, bars[i].c);
  return slice.reduce((s, b) => s + body(b.o, b.c), 0) / slice.length;
}
function localTrend(bars: OhlcBar[], i: number, look = 6): "up" | "down" | "flat" {
  const j = Math.max(0, i - look);
  const a = bars[j].c;
  const b = bars[Math.max(0, i - 1)].c;
  const pct = (b - a) / Math.max(a, 1e-9);
  if (pct > 0.012) return "up";
  if (pct < -0.012) return "down";
  return "flat";
}

type Swing = { i: number; v: number };

function swings(values: number[], left = 3, right = 3, kind: "high" | "low"): Swing[] {
  const out: Swing[] = [];
  for (let i = left; i < values.length - right; i++) {
    const v = values[i];
    let ok = true;
    for (let k = 1; k <= left && ok; k++) {
      ok = kind === "high" ? v >= values[i - k] : v <= values[i - k];
    }
    for (let k = 1; k <= right && ok; k++) {
      ok = kind === "high" ? v >= values[i + k] : v <= values[i + k];
    }
    if (ok) out.push({ i, v });
  }
  return out;
}

/** Textbook morning star — Project APEX / Full Document §4.1. */
export function isMorningStar(a: OhlcBar, m: OhlcBar, c: OhlcBar, meanBody = 0): boolean {
  const aBody = body(a.o, a.c);
  const mBody = body(m.o, m.c);
  const cBody = body(c.o, c.c);
  const aRng = range(a.h, a.l);
  const cRng = range(c.h, c.l);
  const floor = meanBody > 0 ? meanBody * 0.85 : aBody;
  if (a.c >= a.o) return false;
  if (aBody < aRng * 0.52) return false;
  if (aBody < floor * 0.7) return false;
  if (mBody > aBody * 0.45) return false;
  if (m.h > a.o - aBody * 0.05) return false;
  if (c.c <= c.o) return false;
  if (cBody < cRng * 0.48) return false;
  if (c.c <= midBody(a.o, a.c)) return false;
  if (c.c <= a.c) return false;
  return true;
}

/** Textbook evening star — documented bearish counterpart. */
export function isEveningStar(a: OhlcBar, m: OhlcBar, c: OhlcBar, meanBody = 0): boolean {
  const aBody = body(a.o, a.c);
  const mBody = body(m.o, m.c);
  const cBody = body(c.o, c.c);
  const aRng = range(a.h, a.l);
  const cRng = range(c.h, c.l);
  const floor = meanBody > 0 ? meanBody * 0.85 : aBody;
  if (a.c <= a.o) return false;
  if (aBody < aRng * 0.52) return false;
  if (aBody < floor * 0.7) return false;
  if (mBody > aBody * 0.45) return false;
  if (m.l < a.o + aBody * 0.05) return false;
  if (c.c >= c.o) return false;
  if (cBody < cRng * 0.48) return false;
  if (c.c >= midBody(a.o, a.c)) return false;
  if (c.c >= a.c) return false;
  return true;
}

function clusterLevels(sw: Swing[], lastPx: number, kind: "support" | "resistance"): { price: number; touches: Swing[] }[] {
  const used = new Set<number>();
  const out: { price: number; touches: Swing[] }[] = [];
  const tol = lastPx * 0.0045;
  for (let i = 0; i < sw.length; i++) {
    if (used.has(i)) continue;
    const group = [sw[i]];
    used.add(i);
    for (let j = i + 1; j < sw.length; j++) {
      if (used.has(j)) continue;
      if (Math.abs(sw[j].v - sw[i].v) <= tol) {
        group.push(sw[j]);
        used.add(j);
      }
    }
    if (group.length >= 2) {
      const price = group.reduce((s, g) => s + g.v, 0) / group.length;
      out.push({ price, touches: group });
    }
  }
  return out
    .filter((g) => (kind === "support" ? g.price <= lastPx * 1.004 : g.price >= lastPx * 0.996))
    .sort((a, b) => b.touches.length - a.touches.length || Math.abs(a.price - lastPx) - Math.abs(b.price - lastPx));
}

function fitRay(points: Swing[]): { a: Swing; b: Swing; err: number } | null {
  if (points.length < 2) return null;
  const a = points[0];
  const b = points[points.length - 1];
  if (b.i - a.i < 8) return null;
  const slope = (b.v - a.v) / (b.i - a.i);
  let err = 0;
  for (const p of points) {
    const y = a.v + slope * (p.i - a.i);
    err += Math.abs(p.v - y) / Math.max(Math.abs(p.v), 1e-9);
  }
  err /= points.length;
  if (err > 0.004) return null;
  return { a, b, err };
}

function detectCandleMarks(bars: OhlcBar[]): Catalyst[] {
  const n = bars.length;
  const out: Catalyst[] = [];
  const start = Math.max(2, n - 18);

  const push = (c: Omit<Catalyst, "id">) => {
    if (out.some((x) => x.name === c.name && x.barIndex === c.barIndex)) return;
    out.push({ ...c, id: `${c.name}-${c.barIndex}`.replace(/\s+/g, "-").toLowerCase() });
  };

  for (let i = start; i < n; i++) {
    const b = bars[i];
    const rng = range(b.h, b.l);
    const bd = body(b.o, b.c);
    const upW = b.h - Math.max(b.o, b.c);
    const dnW = Math.min(b.o, b.c) - b.l;
    const mean = avgBody(bars, i);
    const trend = localTrend(bars, i);
    const px = b.c;

    if (dnW >= bd * 2.4 && upW <= rng * 0.16 && bd <= rng * 0.32 && Math.min(b.o, b.c) > b.l + rng * 0.58 && bd >= mean * 0.25) {
      const hammer = trend !== "up";
      push({
        name: hammer ? "Hammer" : "Hanging Man",
        bias: hammer ? "bullish" : "bearish",
        kind: "candle",
        barIndex: i,
        price: b.l,
        price2: b.h,
        confidence: hammer && trend === "down" ? 0.86 : 0.7,
        explain: hammer
          ? `Hammer at ${px.toFixed(2)} after a local decline: lower wick ${dnW.toFixed(2)} is ${(dnW / Math.max(bd, 1e-9)).toFixed(1)}× the body. Documented buy-at-support reversal.`
          : `Hanging man at ${px.toFixed(2)} after a local advance — same long lower wick, but it is a sell-at-resistance warning until a confirmation close.`,
      });
    }

    if (upW >= bd * 2.4 && dnW <= rng * 0.16 && bd <= rng * 0.32 && Math.max(b.o, b.c) < b.h - rng * 0.58 && bd >= mean * 0.25) {
      const star = trend !== "down";
      push({
        name: star ? "Shooting Star" : "Inverted Hammer",
        bias: star ? "bearish" : "bullish",
        kind: "candle",
        barIndex: i,
        price: b.h,
        price2: b.l,
        confidence: star && trend === "up" ? 0.86 : 0.68,
        explain: star
          ? `Shooting star at ${px.toFixed(2)}: upper wick ${upW.toFixed(2)} is ${(upW / Math.max(bd, 1e-9)).toFixed(1)}× the body after a local advance — documented sell-at-resistance reversal.`
          : `Inverted hammer at ${px.toFixed(2)} after a local decline — long upper wick that still requires a bullish confirmation close.`,
      });
    }

    if (bd <= rng * 0.08 && rng / px > 0.005 && i >= n - 8) {
      const dragon = dnW > upW * 2.2 && dnW > bd * 3;
      const grave = upW > dnW * 2.2 && upW > bd * 3;
      push({
        name: dragon ? "Dragonfly Doji" : grave ? "Gravestone Doji" : "Standard Doji",
        bias: dragon ? "bullish" : grave ? "bearish" : trend === "down" ? "bullish" : "bearish",
        kind: "candle",
        barIndex: i,
        price: b.c,
        price2: b.h,
        confidence: dragon || grave ? 0.72 : 0.48,
        explain: `Doji indecision at ${px.toFixed(2)}: body is ${((bd / rng) * 100).toFixed(0)}% of the bar range. Docs require a confirmation close; this is not a standalone breakout.`,
      });
    }

    if (bd > rng * 0.08 && bd <= rng * 0.28 && upW > rng * 0.25 && dnW > rng * 0.25 && i >= n - 6) {
      push({
        name: "Spinning Top",
        bias: trend === "down" ? "bullish" : "bearish",
        kind: "candle",
        barIndex: i,
        price: b.l,
        price2: b.h,
        confidence: 0.45,
        explain: `Spinning top at ${px.toFixed(2)} — documented indecision; wait for the next accepted close before treating it as reversal.`,
      });
    }

    if (i >= 1) {
      const p = bars[i - 1];
      const pBull = p.c > p.o;
      const bull = b.c > b.o;
      const pBd = body(p.o, p.c);
      if (!pBull && bull && b.o <= p.c && b.c >= p.o && body(b.o, b.c) > pBd * 1.12 && pBd >= mean * 0.55) {
        push({
          name: "Bullish Engulfing",
          bias: "bullish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: trend === "down" ? 0.9 : 0.72,
          explain: `Bullish engulfing: prior close ${p.c.toFixed(2)} fully absorbed by ${b.o.toFixed(2)}→${b.c.toFixed(2)}. Documented buy-at-support reversal.`,
        });
      }
      if (pBull && !bull && b.o >= p.c && b.c <= p.o && body(b.o, b.c) > pBd * 1.12 && pBd >= mean * 0.55) {
        push({
          name: "Bearish Engulfing",
          bias: "bearish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: trend === "up" ? 0.9 : 0.72,
          explain: `Bearish engulfing: prior close ${p.c.toFixed(2)} wrapped by ${b.o.toFixed(2)}→${b.c.toFixed(2)}. Documented sell-at-resistance reversal.`,
        });
      }
      if (!pBull && bull && b.o < p.l && b.c > midBody(p.o, p.c) && b.c < p.o && pBd >= mean * 0.8) {
        push({
          name: "Piercing Line",
          bias: "bullish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: 0.8,
          explain: `Piercing line: close ${b.c.toFixed(2)} reclaimed more than half of the prior bearish body ${p.c.toFixed(2)}→${p.o.toFixed(2)}.`,
        });
      }
      if (pBull && !bull && b.o > p.h && b.c < midBody(p.o, p.c) && b.c > p.o && pBd >= mean * 0.8) {
        push({
          name: "Dark Cloud Cover",
          bias: "bearish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: 0.8,
          explain: `Dark cloud cover: close ${b.c.toFixed(2)} cut through more than half of the prior bullish body.`,
        });
      }
      if (!pBull && bull && b.o >= p.c && b.c <= p.o && body(b.o, b.c) < pBd * 0.55 && pBd >= mean * 0.7) {
        push({
          name: "Bullish Harami",
          bias: "bullish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: 0.66,
          explain: `Bullish harami: small body inside the prior bearish candle — documented pause that still needs confirmation.`,
        });
      }
      if (pBull && !bull && b.o <= p.c && b.c >= p.o && body(b.o, b.c) < pBd * 0.55 && pBd >= mean * 0.7) {
        push({
          name: "Bearish Harami",
          bias: "bearish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: 0.66,
          explain: `Bearish harami: small body inside the prior bullish candle — documented pause that still needs confirmation.`,
        });
      }
      if (p.h < b.h && p.l > b.l && i >= n - 5) {
        push({
          name: "Inside Bar",
          bias: trend === "down" ? "bullish" : "bearish",
          kind: "candle",
          barIndex: i - 1,
          barEnd: i,
          price: Math.min(p.l, b.l),
          price2: Math.max(p.h, b.h),
          confidence: 0.5,
          explain: `Inside bar: the ${bars[i].t.slice(0, 10)} range is contained by the prior bar — documented compression, not a breakout.`,
        });
      }
    }

    if (i >= 2) {
      const a = bars[i - 2];
      const m = bars[i - 1];
      const mean2 = avgBody(bars, i - 2);
      if (isMorningStar(a, m, b, mean2)) {
        push({
          name: "Morning Star",
          bias: "bullish",
          kind: "candle",
          barIndex: i - 2,
          barEnd: i,
          price: Math.min(a.l, m.l, b.l),
          price2: Math.max(a.h, m.h, b.h),
          confidence: 0.93,
          explain: `Morning star across three bars ending at ${b.c.toFixed(2)} — long bearish body, small midpoint, then a bullish close through the first-bar midpoint. Documented bullish reversal.`,
        });
      }
      if (isEveningStar(a, m, b, mean2)) {
        push({
          name: "Evening Star",
          bias: "bearish",
          kind: "candle",
          barIndex: i - 2,
          barEnd: i,
          price: Math.min(a.l, m.l, b.l),
          price2: Math.max(a.h, m.h, b.h),
          confidence: 0.93,
          explain: `Evening star completing at ${b.c.toFixed(2)} — long bullish body, small midpoint, then a bearish close through the first-bar midpoint. Documented bearish reversal.`,
        });
      }
    }
  }

  if (n >= 5) {
    const w = bars.slice(-3);
    const i0 = n - 3;
    const mean = avgBody(bars, n - 1);
    const soldiers =
      w.every((b) => b.c > b.o && body(b.o, b.c) >= mean * 0.7 && body(b.o, b.c) >= range(b.h, b.l) * 0.5) &&
      w[1].c > w[0].c &&
      w[2].c > w[1].c &&
      w[1].o >= w[0].o &&
      w[2].o >= w[1].o &&
      localTrend(bars, i0) !== "up";
    if (soldiers) {
      push({
        name: "Three White Soldiers",
        bias: "bullish",
        kind: "candle",
        barIndex: i0,
        barEnd: n - 1,
        price: Math.min(...w.map((b) => b.l)),
        price2: Math.max(...w.map((b) => b.h)),
        confidence: 0.88,
        explain: `Three white soldiers: consecutive advancing bodies (${w.map((b) => b.c.toFixed(2)).join(" → ")}) — documented continuation.`,
      });
    }
    const crows =
      w.every((b) => b.c < b.o && body(b.o, b.c) >= mean * 0.7 && body(b.o, b.c) >= range(b.h, b.l) * 0.5) &&
      w[1].c < w[0].c &&
      w[2].c < w[1].c &&
      w[1].o <= w[0].o &&
      w[2].o <= w[1].o &&
      localTrend(bars, i0) !== "down";
    if (crows) {
      push({
        name: "Three Black Crows",
        bias: "bearish",
        kind: "candle",
        barIndex: i0,
        barEnd: n - 1,
        price: Math.min(...w.map((b) => b.l)),
        price2: Math.max(...w.map((b) => b.h)),
        confidence: 0.88,
        explain: `Three black crows: consecutive declining bodies (${w.map((b) => b.c.toFixed(2)).join(" → ")}) — documented bearish continuation.`,
      });
    }
  }

  return out;
}

function detectStructure(bars: OhlcBar[]): Catalyst[] {
  const n = bars.length;
  if (n < 24) return [];
  const highs = bars.map((b) => b.h);
  const lows = bars.map((b) => b.l);
  const closes = bars.map((b) => b.c);
  const px = closes[n - 1];
  const sh = swings(highs, 4, 4, "high");
  const sl = swings(lows, 4, 4, "low");
  const out: Catalyst[] = [];

  const push = (c: Omit<Catalyst, "id">) => {
    out.push({ ...c, id: `${c.name}-${c.barIndex}`.replace(/\s+/g, "-").toLowerCase() });
  };

  if (sh.length >= 3) {
    for (let k = sh.length - 1; k >= 2; k--) {
      const L = sh[k - 2];
      const H = sh[k - 1];
      const R = sh[k];
      if (H.i - L.i < 6 || R.i - H.i < 6) continue;
      if (!(H.v > L.v * 1.018 && H.v > R.v * 1.018)) continue;
      if (Math.abs(L.v - R.v) / H.v > 0.055) continue;
      const t1 = sl.filter((s) => s.i > L.i && s.i < H.i).sort((a, b) => a.v - b.v)[0];
      const t2 = sl.filter((s) => s.i > H.i && s.i < R.i).sort((a, b) => a.v - b.v)[0];
      if (!t1 || !t2) continue;
      if (Math.abs(t1.v - t2.v) / px > 0.03) continue;
      const neck = (t1.v + t2.v) / 2;
      if ((H.v - neck) / px < 0.028) continue;
      push({
        name: "Head & Shoulders",
        bias: "bearish",
        kind: "structure",
        barIndex: L.i,
        barEnd: R.i,
        price: neck,
        price2: H.v,
        confidence: 0.9,
        points: [
          { i: L.i, price: L.v },
          { i: t1.i, price: t1.v },
          { i: H.i, price: H.v },
          { i: t2.i, price: t2.v },
          { i: R.i, price: R.v },
        ],
        explain: `Head & shoulders: left ${L.v.toFixed(2)}, head ${H.v.toFixed(2)}, right ${R.v.toFixed(2)}, neckline ~${neck.toFixed(2)}. Geometry is in this viewport — not a canned overlay.`,
      });
      break;
    }
  }

  if (sl.length >= 3 && !out.some((c) => c.name === "Head & Shoulders")) {
    for (let k = sl.length - 1; k >= 2; k--) {
      const L = sl[k - 2];
      const H = sl[k - 1];
      const R = sl[k];
      if (H.i - L.i < 6 || R.i - H.i < 6) continue;
      if (!(H.v < L.v * 0.982 && H.v < R.v * 0.982)) continue;
      if (Math.abs(L.v - R.v) / Math.max(L.v, 1e-9) > 0.055) continue;
      const p1 = sh.filter((s) => s.i > L.i && s.i < H.i).sort((a, b) => b.v - a.v)[0];
      const p2 = sh.filter((s) => s.i > H.i && s.i < R.i).sort((a, b) => b.v - a.v)[0];
      if (!p1 || !p2) continue;
      if (Math.abs(p1.v - p2.v) / px > 0.03) continue;
      const neck = (p1.v + p2.v) / 2;
      if ((neck - H.v) / px < 0.028) continue;
      push({
        name: "Inverse Head & Shoulders",
        bias: "bullish",
        kind: "structure",
        barIndex: L.i,
        barEnd: R.i,
        price: H.v,
        price2: neck,
        confidence: 0.9,
        points: [
          { i: L.i, price: L.v },
          { i: p1.i, price: p1.v },
          { i: H.i, price: H.v },
          { i: p2.i, price: p2.v },
          { i: R.i, price: R.v },
        ],
        explain: `Inverse head & shoulders: left ${L.v.toFixed(2)}, head ${H.v.toFixed(2)}, right ${R.v.toFixed(2)}, neckline ~${neck.toFixed(2)}.`,
      });
      break;
    }
  }

  if (sh.length >= 2) {
    const a = sh[sh.length - 2];
    const b = sh[sh.length - 1];
    if (b.i - a.i >= 10 && Math.abs(a.v - b.v) / px < 0.01) {
      const valley = Math.min(...lows.slice(a.i, b.i + 1));
      if ((a.v - valley) / px > 0.035 && px < Math.min(a.v, b.v)) {
        push({
          name: "Double Top",
          bias: "bearish",
          kind: "structure",
          barIndex: a.i,
          barEnd: b.i,
          price: valley,
          price2: Math.max(a.v, b.v),
          confidence: 0.82,
          points: [
            { i: a.i, price: a.v },
            { i: a.i + Math.floor((b.i - a.i) / 2), price: valley },
            { i: b.i, price: b.v },
          ],
          explain: `Double top at ${a.v.toFixed(2)} / ${b.v.toFixed(2)} with trough ${valley.toFixed(2)}.`,
        });
      }
    }
  }
  if (sl.length >= 2) {
    const a = sl[sl.length - 2];
    const b = sl[sl.length - 1];
    if (b.i - a.i >= 10 && Math.abs(a.v - b.v) / px < 0.01) {
      const peak = Math.max(...highs.slice(a.i, b.i + 1));
      if ((peak - a.v) / px > 0.035 && px > Math.max(a.v, b.v)) {
        push({
          name: "Double Bottom",
          bias: "bullish",
          kind: "structure",
          barIndex: a.i,
          barEnd: b.i,
          price: Math.min(a.v, b.v),
          price2: peak,
          confidence: 0.82,
          points: [
            { i: a.i, price: a.v },
            { i: a.i + Math.floor((b.i - a.i) / 2), price: peak },
            { i: b.i, price: b.v },
          ],
          explain: `Double bottom at ${a.v.toFixed(2)} / ${b.v.toFixed(2)} with intervening peak ${peak.toFixed(2)}.`,
        });
      }
    }
  }

  if (n >= 36 && !out.some((c) => c.kind === "structure")) {
    const win = Math.min(48, n);
    const from = n - win;
    const windowLows = lows.slice(from);
    let minI = 0;
    for (let i = 1; i < windowLows.length; i++) if (windowLows[i] < windowLows[minI]) minI = i;
    const frac = minI / (win - 1);
    if (frac > 0.32 && frac < 0.68) {
      const left = closes.slice(from, from + minI + 1);
      const right = closes.slice(from + minI);
      const leftDrop = left[0] - windowLows[minI];
      const rightLift = right[right.length - 1] - windowLows[minI];
      if (leftDrop / px > 0.04 && rightLift > leftDrop * 0.55 && rightLift / px > 0.03) {
        const mid = from + minI;
        push({
          name: "Rounding Bottom",
          bias: "bullish",
          kind: "structure",
          barIndex: from,
          barEnd: n - 1,
          price: windowLows[minI],
          price2: Math.max(left[0], right[right.length - 1]),
          confidence: 0.78,
          points: [
            { i: from, price: highs[from] },
            { i: mid, price: lows[mid] },
            { i: n - 1, price: closes[n - 1] },
          ],
          explain: `Rounding bottom over ${win} visible bars: trough ${windowLows[minI].toFixed(2)} near bar ${mid + 1}, recovery to ${closes[n - 1].toFixed(2)}.`,
        });
      }
    }
  }

  const recentLows = sl.slice(-4);
  const recentHighs = sh.slice(-4);
  const supportRay = fitRay(recentLows);
  const resistRay = fitRay(recentHighs);
  if (supportRay && resistRay) {
    const sSlope = (supportRay.b.v - supportRay.a.v) / (supportRay.b.i - supportRay.a.i);
    const rSlope = (resistRay.b.v - resistRay.a.v) / (resistRay.b.i - resistRay.a.i);
    if (Math.abs(sSlope - rSlope) / px < 0.00035 && resistRay.a.v > supportRay.a.v) {
      push({
        name: rSlope > 0 ? "Rising Channel" : rSlope < 0 ? "Falling Channel" : "Horizontal Channel",
        bias: rSlope >= 0 ? "bullish" : "bearish",
        kind: "structure",
        barIndex: Math.min(supportRay.a.i, resistRay.a.i),
        barEnd: Math.max(supportRay.b.i, resistRay.b.i),
        price: supportRay.b.v,
        price2: resistRay.b.v,
        confidence: 0.76,
        points: [
          { i: supportRay.a.i, price: supportRay.a.v },
          { i: supportRay.b.i, price: supportRay.b.v },
          { i: resistRay.a.i, price: resistRay.a.v },
          { i: resistRay.b.i, price: resistRay.b.v },
        ],
        explain: `Parallel channel fitted to swing highs/lows in this viewport (support ${supportRay.a.v.toFixed(2)}→${supportRay.b.v.toFixed(2)}, resistance ${resistRay.a.v.toFixed(2)}→${resistRay.b.v.toFixed(2)}).`,
      });
    }
  }

  if (n >= 20 && !out.some((c) => /Channel|Flag/.test(c.name))) {
    const pole = bars.slice(-18, -8);
    const flag = bars.slice(-8);
    if (pole.length >= 6 && flag.length >= 6) {
      const poleMove = pole[pole.length - 1].c - pole[0].c;
      const flagMove = flag[flag.length - 1].c - flag[0].c;
      const poleHigh = Math.max(...pole.map((b) => b.h));
      const poleLow = Math.min(...pole.map((b) => b.l));
      const compact = (Math.max(...flag.map((b) => b.h)) - Math.min(...flag.map((b) => b.l))) / (poleHigh - poleLow || 1);
      if (Math.abs(poleMove) / px > 0.045 && compact < 0.55 && poleMove * flagMove < 0) {
        const bull = poleMove > 0;
        push({
          name: bull ? "Bull Flag" : "Bear Flag",
          bias: bull ? "bullish" : "bearish",
          kind: "structure",
          barIndex: n - 18,
          barEnd: n - 1,
          price: Math.min(...flag.map((b) => b.l)),
          price2: Math.max(...pole.map((b) => b.h)),
          confidence: 0.74,
          points: [
            { i: n - 18, price: pole[0].c },
            { i: n - 9, price: pole[pole.length - 1].c },
            { i: n - 1, price: flag[flag.length - 1].c },
          ],
          explain: `${bull ? "Bull" : "Bear"} flag: ${((Math.abs(poleMove) / px) * 100).toFixed(1)}% pole then a counter-trend coil inside this window.`,
        });
      }
    }
  }

  return out.sort((a, b) => b.confidence - a.confidence).slice(0, 1);
}

function detectLevels(bars: OhlcBar[]): Catalyst[] {
  const n = bars.length;
  if (n < 16) return [];
  const px = bars[n - 1].c;
  const highs = bars.map((b) => b.h);
  const lows = bars.map((b) => b.l);
  const sh = swings(highs, 3, 3, "high");
  const sl = swings(lows, 3, 3, "low");
  const out: Catalyst[] = [];

  const resists = clusterLevels(sh, px, "resistance").slice(0, 2);
  const supports = clusterLevels(sl, px, "support").slice(0, 2);
  for (const g of supports) {
    const lo = Math.min(...g.touches.map((t) => t.i));
    out.push({
      id: `support-${g.price.toFixed(2)}`.replace(/\./g, "-"),
      name: "Support",
      bias: "bullish",
      kind: "level",
      barIndex: lo,
      barEnd: n - 1,
      price: g.price,
      confidence: Math.min(0.92, 0.55 + g.touches.length * 0.12),
      explain: `Horizontal support at ${g.price.toFixed(2)} with ${g.touches.length} swing-low touches in this viewport.`,
    });
  }
  for (const g of resists) {
    const lo = Math.min(...g.touches.map((t) => t.i));
    out.push({
      id: `resistance-${g.price.toFixed(2)}`.replace(/\./g, "-"),
      name: "Resistance",
      bias: "bearish",
      kind: "level",
      barIndex: lo,
      barEnd: n - 1,
      price: g.price,
      confidence: Math.min(0.92, 0.55 + g.touches.length * 0.12),
      explain: `Horizontal resistance at ${g.price.toFixed(2)} with ${g.touches.length} swing-high touches in this viewport.`,
    });
  }

  const supportRay = fitRay(sl.slice(-3));
  if (supportRay && (supportRay.b.v - supportRay.a.v) / px < 0.08) {
    out.push({
      id: `trend-support-${supportRay.a.i}`,
      name: "Support trendline",
      bias: "bullish",
      kind: "trend",
      barIndex: supportRay.a.i,
      barEnd: n - 1,
      price: supportRay.a.v,
      price2: supportRay.b.v,
      points: [
        { i: supportRay.a.i, price: supportRay.a.v },
        { i: supportRay.b.i, price: supportRay.b.v },
      ],
      confidence: 0.7,
      explain: `Rising/flat support trendline from ${supportRay.a.v.toFixed(2)} (bar ${supportRay.a.i + 1}) through ${supportRay.b.v.toFixed(2)}.`,
    });
  }
  const resistRay = fitRay(sh.slice(-3));
  if (resistRay && (resistRay.a.v - resistRay.b.v) / px < 0.08) {
    out.push({
      id: `trend-resist-${resistRay.a.i}`,
      name: "Resistance trendline",
      bias: "bearish",
      kind: "trend",
      barIndex: resistRay.a.i,
      barEnd: n - 1,
      price: resistRay.a.v,
      price2: resistRay.b.v,
      points: [
        { i: resistRay.a.i, price: resistRay.a.v },
        { i: resistRay.b.i, price: resistRay.b.v },
      ],
      confidence: 0.7,
      explain: `Falling/flat resistance trendline from ${resistRay.a.v.toFixed(2)} through ${resistRay.b.v.toFixed(2)}.`,
    });
  }

  if (!out.length) {
    const zones = supportResistance(bars);
    for (const z of zones.slice(0, 2)) {
      out.push({
        id: `vp-${z.kind}-${z.price.toFixed(2)}`.replace(/\./g, "-"),
        name: z.kind === "support" ? "Support" : "Resistance",
        bias: z.kind === "support" ? "bullish" : "bearish",
        kind: "level",
        barIndex: 0,
        barEnd: n - 1,
        price: z.price,
        confidence: 0.55,
        explain: `Volume-cluster ${z.kind} at ${z.price.toFixed(2)} on this captured window.`,
      });
    }
  }

  return out.sort((a, b) => b.confidence - a.confidence).slice(0, 3);
}

/**
 * High-confidence drawings for THIS viewport’s OHLC only.
 * Candlestick prints feed analysis cards; S/R is horizontals/trendlines;
 * H&S / rounding / flags only when geometry is real.
 */
export function detectChartMarks(bars: OhlcBar[], _series?: PlotSeries): Catalyst[] {
  if (bars.length < 8) return [];
  const candles = detectCandleMarks(bars)
    .filter((c) => c.confidence >= 0.66)
    .sort((a, b) => b.confidence - a.confidence || b.barIndex - a.barIndex)
    .slice(0, 2);
  const structure = detectStructure(bars);
  const levels = detectLevels(bars);
  const merged = [...candles, ...structure, ...levels];
  const seen = new Set<string>();
  return merged.filter((c) => {
    const key = `${c.kind}:${c.name}:${c.barIndex}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Snapshot extra drawings: S/R trendlines and horizontals only — no pattern boxes. */
export function detectSrMarks(bars: OhlcBar[], series?: PlotSeries): Catalyst[] {
  return detectChartMarks(bars, series).filter((c) => c.kind === "level" || c.kind === "trend");
}

function lastCross(a: number[], b: number[], from: number): { i: number; bull: boolean } | null {
  for (let i = a.length - 1; i > from; i--) {
    if (!Number.isFinite(a[i]) || !Number.isFinite(b[i]) || !Number.isFinite(a[i - 1]) || !Number.isFinite(b[i - 1])) continue;
    const prev = a[i - 1] - b[i - 1];
    const cur = a[i] - b[i];
    if (prev <= 0 && cur > 0) return { i, bull: true };
    if (prev >= 0 && cur < 0) return { i, bull: false };
  }
  return null;
}

/**
 * Future-trend signals that actually printed on this captured window
 * (EMA 9/21 cross, MACD cross, SuperTrend flip, RSI 30/70 rail).
 */
export function detectTrendSignals(bars: OhlcBar[], series: PlotSeries): Catalyst[] {
  const n = bars.length;
  if (n < 22 || !series) return [];
  const out: Catalyst[] = [];
  const push = (c: Omit<Catalyst, "id">) => {
    out.push({ ...c, id: `${c.name}-${c.barIndex}`.replace(/\s+/g, "-").toLowerCase() });
  };
  const from = Math.max(8, n - 16);

  const emaX = lastCross(series.ema9, series.ema21, from);
  if (emaX) {
    const b = bars[emaX.i];
    push({
      name: emaX.bull ? "EMA 9/21 bullish cross" : "EMA 9/21 bearish cross",
      bias: emaX.bull ? "bullish" : "bearish",
      kind: "momentum",
      barIndex: emaX.i,
      price: b.c,
      confidence: 0.84,
      explain: emaX.bull
        ? `EMA 9 crossed above EMA 21 at ${b.c.toFixed(2)} on ${b.t.slice(0, 10)}. That impulse print projects continuation while the 9 holds the 21; a close back through EMA 21 would cancel the forecast.`
        : `EMA 9 crossed below EMA 21 at ${b.c.toFixed(2)} on ${b.t.slice(0, 10)}. That impulse print projects continuation lower while the 9 stays under the 21; reclaiming EMA 21 would cancel the forecast.`,
    });
  }

  const macdX = lastCross(series.macd.line, series.macd.signal, from);
  if (macdX) {
    const b = bars[macdX.i];
    const hist = series.macd.histogram[macdX.i];
    push({
      name: macdX.bull ? "MACD bullish signal cross" : "MACD bearish signal cross",
      bias: macdX.bull ? "bullish" : "bearish",
      kind: "momentum",
      barIndex: macdX.i,
      price: b.c,
      confidence: 0.82,
      explain: macdX.bull
        ? `MACD line crossed above signal at histogram ${hist.toFixed(4)} with price ${b.c.toFixed(2)}. Forward path is continuation as long as histogram stays non-negative; a flip below zero is the first failure of that forecast.`
        : `MACD line crossed below signal at histogram ${hist.toFixed(4)} with price ${b.c.toFixed(2)}. Forward path is continuation lower as long as histogram stays non-positive; a reclaim of zero is the first repair.`,
    });
  }

  for (let i = n - 1; i > from; i--) {
    const a = series.st[i - 1];
    const b = series.st[i];
    if (!a || !b || a.direction === b.direction) continue;
    const bar = bars[i];
    const bull = b.direction === 1;
    push({
      name: bull ? "SuperTrend bullish flip" : "SuperTrend bearish flip",
      bias: bull ? "bullish" : "bearish",
      kind: "momentum",
      barIndex: i,
      price: bar.c,
      price2: b.value,
      confidence: 0.88,
      explain: bull
        ? `SuperTrend flipped bullish at ${b.value.toFixed(2)} on close ${bar.c.toFixed(2)}. The new line is the trailing support; the forecast stays long until a close through ${b.value.toFixed(2)}.`
        : `SuperTrend flipped bearish at ${b.value.toFixed(2)} on close ${bar.c.toFixed(2)}. The new line is the trailing cap; the forecast stays short until a close through ${b.value.toFixed(2)}.`,
    });
    break;
  }

  const rsi = series.rsi;
  for (let i = n - 1; i > from; i--) {
    const prev = rsi[i - 1];
    const cur = rsi[i];
    if (!Number.isFinite(prev) || !Number.isFinite(cur)) continue;
    if (prev < 30 && cur >= 30) {
      push({
        name: "RSI reclaim of 30",
        bias: "bullish",
        kind: "momentum",
        barIndex: i,
        price: bars[i].c,
        confidence: 0.78,
        explain: `RSI14 reclaimed 30 (${prev.toFixed(1)} → ${cur.toFixed(1)}) at ${bars[i].c.toFixed(2)}. Documented bounce path while SuperTrend is not a rigid ceiling; a drop back through 30 cancels it.`,
      });
      break;
    }
    if (prev > 70 && cur <= 70) {
      push({
        name: "RSI fail of 70",
        bias: "bearish",
        kind: "momentum",
        barIndex: i,
        price: bars[i].c,
        confidence: 0.78,
        explain: `RSI14 failed back through 70 (${prev.toFixed(1)} → ${cur.toFixed(1)}) at ${bars[i].c.toFixed(2)}. Documented late-trend fade; a reclaim of 70 and hold would cancel the short-side forecast.`,
      });
      break;
    }
  }

  return out.sort((a, b) => b.confidence - a.confidence).slice(0, 3);
}

/** Alias used by analysis cards — viewport engine plus real momentum prints. No canned patterns. */
export function detectCatalysts(bars: OhlcBar[], series?: PlotSeries): Catalyst[] {
  const marks = detectChartMarks(bars, series).filter((c) => c.kind === "candle" || c.kind === "structure" || (c.kind === "trend" && c.confidence >= 0.7));
  const signals = series ? detectTrendSignals(bars, series) : [];
  const merged = [...marks, ...signals];
  const seen = new Set<string>();
  return merged.filter((c) => {
    const key = `${c.kind}:${c.name}:${c.barIndex}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
