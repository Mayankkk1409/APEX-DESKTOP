/** Documented TA studies — Full Document §4.2–4.8, Project APEX §4, CONTRACT.md. */

export type OhlcBar = { t: string; o: number; h: number; l: number; c: number; v: number };

export type SupertrendPoint = { value: number; direction: 1 | -1; atr: number };

export type PivotLevels = {
  pp: number;
  r1: number;
  r2: number;
  r3: number;
  r4: number;
  r5: number;
  s1: number;
  s2: number;
  s3: number;
  s4: number;
  s5: number;
};

export type SrZone = { price: number; kind: "support" | "resistance"; strength: number };

export function ema(values: number[], period: number): number[] {
  if (!values.length) return [];
  const k = 2 / (period + 1);
  const out = [values[0]];
  for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
  return out;
}

export function sma(values: number[], period: number): number[] {
  const out: number[] = [];
  let running = 0;
  for (let i = 0; i < values.length; i++) {
    running += values[i];
    if (i >= period) running -= values[i - period];
    const denom = i >= period - 1 ? period : i + 1;
    out.push(running / denom);
  }
  return out;
}

export function rsi(closes: number[], period = 14): number[] {
  if (closes.length < 2) return closes.map(() => 50);
  const gains = [0];
  const losses = [0];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0));
    losses.push(Math.max(-d, 0));
  }
  let avgG = gains.slice(1, period + 1).reduce((a, b) => a + b, 0) / Math.max(period, 1);
  let avgL = losses.slice(1, period + 1).reduce((a, b) => a + b, 0) / Math.max(period, 1);
  if (gains.length <= period) {
    avgG = gains.reduce((a, b) => a + b, 0) / Math.max(gains.length - 1, 1);
    avgL = losses.reduce((a, b) => a + b, 0) / Math.max(losses.length - 1, 1);
  }
  const out = [50];
  for (let i = 1; i < closes.length; i++) {
    if (i >= period) {
      avgG = (avgG * (period - 1) + gains[i]) / period;
      avgL = (avgL * (period - 1) + losses[i]) / period;
    }
    const rs = avgL ? avgG / avgL : 100;
    out.push(100 - 100 / (1 + rs));
  }
  return out;
}

export function macd(closes: number[], fast = 12, slow = 26, signalPeriod = 9) {
  const f = ema(closes, fast);
  const s = ema(closes, slow);
  const line = f.map((v, i) => v - s[i]);
  const signal = ema(line, signalPeriod);
  const histogram = line.map((v, i) => v - signal[i]);
  return { line, signal, histogram };
}

export function bollinger(closes: number[], period = 20, stdev = 2) {
  const mid = sma(closes, period);
  const upper: number[] = [];
  const lower: number[] = [];
  const width: number[] = [];
  for (let i = 0; i < mid.length; i++) {
    const window = closes.slice(Math.max(0, i - period + 1), i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / window.length;
    const sd = Math.sqrt(window.reduce((a, x) => a + (x - mean) ** 2, 0) / window.length);
    const u = mid[i] + stdev * sd;
    const l = mid[i] - stdev * sd;
    upper.push(u);
    lower.push(l);
    width.push(mid[i] ? (u - l) / mid[i] : 0);
  }
  return { mid, upper, lower, width };
}

/** SuperTrend ATR length 10 / factor 3 — Full Document §4.5. */
export function supertrend(highs: number[], lows: number[], closes: number[], atrLength = 10, factor = 3): SupertrendPoint[] {
  const n = closes.length;
  if (!n) return [];
  const trs: number[] = [];
  for (let i = 0; i < n; i++) {
    const prev = i ? closes[i - 1] : closes[i];
    trs.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - prev), Math.abs(lows[i] - prev)));
  }
  const atrs: number[] = [];
  for (let i = 0; i < n; i++) {
    if (i < atrLength) atrs.push(trs.slice(0, i + 1).reduce((a, b) => a + b, 0) / (i + 1));
    else atrs.push((atrs[i - 1] * (atrLength - 1) + trs[i]) / atrLength);
  }
  const points: SupertrendPoint[] = [];
  let finalUpper = 0;
  let finalLower = 0;
  let direction: 1 | -1 = 1;
  for (let i = 0; i < n; i++) {
    const mid = (highs[i] + lows[i]) / 2;
    const basicUpper = mid + factor * atrs[i];
    const basicLower = mid - factor * atrs[i];
    if (i === 0) {
      finalUpper = basicUpper;
      finalLower = basicLower;
    } else {
      finalUpper = basicUpper < finalUpper || closes[i - 1] > finalUpper ? basicUpper : finalUpper;
      finalLower = basicLower > finalLower || closes[i - 1] < finalLower ? basicLower : finalLower;
    }
    const prevDir: 1 | -1 = direction;
    if (closes[i] > finalUpper) direction = 1;
    else if (closes[i] < finalLower) direction = -1;
    else {
      direction = prevDir;
      const prevSt = points.length ? points[points.length - 1].value : finalLower;
      if (direction === 1 && finalLower < prevSt) finalLower = prevSt;
      if (direction === -1 && finalUpper > prevSt) finalUpper = prevSt;
    }
    points.push({ atr: atrs[i], value: direction === 1 ? finalLower : finalUpper, direction });
  }
  return points;
}

/**
 * Standard floor-trader pivots — Full Document §4.7 / Project APEX §4.
 * R4/R5 and S4/S5 extend the same classic identity as R3/S3:
 *   Rn = High + n * (PP − Low),  Sn = Low − n * (High − PP)
 */
export function pivotPoints(high: number, low: number, close: number): PivotLevels {
  const pp = (high + low + close) / 3;
  return {
    pp,
    r1: pp * 2 - low,
    r2: pp + (high - low),
    r3: high + 2 * (pp - low),
    r4: high + 3 * (pp - low),
    r5: high + 4 * (pp - low),
    s1: pp * 2 - high,
    s2: pp - (high - low),
    s3: low - 2 * (high - pp),
    s4: low - 3 * (high - pp),
    s5: low - 4 * (high - pp),
  };
}

export type PivotRow = { key: string; label: string; price: number };

/** R5→S5 ladder with screenshot labels (`P`, not `PP`). */
export function pivotLadder(pivots: PivotLevels): PivotRow[] {
  return [
    { key: "R5", label: "R5", price: pivots.r5 },
    { key: "R4", label: "R4", price: pivots.r4 },
    { key: "R3", label: "R3", price: pivots.r3 },
    { key: "R2", label: "R2", price: pivots.r2 },
    { key: "R1", label: "R1", price: pivots.r1 },
    { key: "P", label: "P", price: pivots.pp },
    { key: "S1", label: "S1", price: pivots.s1 },
    { key: "S2", label: "S2", price: pivots.s2 },
    { key: "S3", label: "S3", price: pivots.s3 },
    { key: "S4", label: "S4", price: pivots.s4 },
    { key: "S5", label: "S5", price: pivots.s5 },
  ];
}

export function pivotCaption(label: string, price: number) {
  return `${label} (${price.toFixed(2)})`;
}

/** Volume-cluster S/R from available bars (Full Document §4.8). */
export function supportResistance(bars: OhlcBar[], buckets = 28): SrZone[] {
  if (bars.length < 8) return [];
  const lows = bars.map((b) => b.l);
  const highs = bars.map((b) => b.h);
  const min = Math.min(...lows);
  const max = Math.max(...highs);
  const span = max - min || 1;
  const vol = new Array(buckets).fill(0);
  for (const b of bars) {
    const idx = Math.min(buckets - 1, Math.max(0, Math.floor(((b.c - min) / span) * buckets)));
    vol[idx] += b.v || 1;
  }
  const last = bars[bars.length - 1].c;
  const ranked = vol
    .map((v, i) => ({ i, v, price: min + ((i + 0.5) / buckets) * span }))
    .sort((a, b) => b.v - a.v)
    .slice(0, 6);
  return ranked.map((r) => ({
    price: r.price,
    kind: r.price <= last ? "support" : "resistance",
    strength: r.v,
  }));
}

/** Accumulation/Distribution — CONTRACT.md volume A/D. */
export function accumulationDistribution(bars: OhlcBar[]): number[] {
  const out: number[] = [];
  let acc = 0;
  for (const b of bars) {
    const range = b.h - b.l;
    const mfm = range ? ((b.c - b.l) - (b.h - b.c)) / range : 0;
    acc += mfm * (b.v || 0);
    out.push(acc);
  }
  return out;
}

export function atr(highs: number[], lows: number[], closes: number[], period = 10): number[] {
  const trs: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    const prev = i ? closes[i - 1] : closes[i];
    trs.push(Math.max(highs[i] - lows[i], Math.abs(highs[i] - prev), Math.abs(lows[i] - prev)));
  }
  return sma(trs, period);
}
