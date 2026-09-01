/**
 * TradingView-equivalent study math.
 *
 * Every series here follows Pine semantics: values are `null` until the study
 * has enough history (Pine `na`), so a 200-period EMA on 60 bars renders
 * nothing instead of a garbage line anchored to the first close.
 */

import type { OhlcBar } from "./ta";

export type Maybe = number | null;

function isNum(v: Maybe): v is number {
  return v != null && Number.isFinite(v);
}

/** Pine `ta.sma` — null until `period` samples exist. */
export function smaSeries(values: number[], period: number): Maybe[] {
  const out: Maybe[] = new Array(values.length).fill(null);
  if (period <= 0) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/** Pine `ta.ema` — seeded with the SMA of the first `period` samples. */
export function emaSeries(values: number[], period: number): Maybe[] {
  const out: Maybe[] = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  const alpha = 2 / (period + 1);
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * alpha + prev * (1 - alpha);
    out[i] = prev;
  }
  return out;
}

/** EMA over a series that may start with nulls (Pine propagates `na`). */
function emaOfMaybe(values: Maybe[], period: number): Maybe[] {
  const out: Maybe[] = new Array(values.length).fill(null);
  const first = values.findIndex(isNum);
  if (first < 0) return out;
  const dense = values.slice(first).map((v) => (isNum(v) ? v : 0));
  const inner = emaSeries(dense, period);
  for (let i = 0; i < inner.length; i++) out[first + i] = inner[i];
  return out;
}

/** Wilder's smoothing (Pine `ta.rma`) — SMA seed, then 1/period decay. */
export function rmaSeries(values: number[], period: number): Maybe[] {
  const out: Maybe[] = new Array(values.length).fill(null);
  if (period <= 0 || values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = (prev * (period - 1) + values[i]) / period;
    out[i] = prev;
  }
  return out;
}

/** Pine `ta.rsi` — Wilder RSI, null for the first `period` bars. */
export function rsiSeries(closes: number[], period = 14): Maybe[] {
  const out: Maybe[] = new Array(closes.length).fill(null);
  if (closes.length < period + 1) return out;
  const gains: number[] = [];
  const losses: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0));
    losses.push(Math.max(-d, 0));
  }
  const avgG = rmaSeries(gains, period);
  const avgL = rmaSeries(losses, period);
  for (let i = 0; i < gains.length; i++) {
    const g = avgG[i];
    const l = avgL[i];
    if (!isNum(g) || !isNum(l)) continue;
    // gains[k] describes the move into closes[k + 1]
    out[i + 1] = l === 0 ? 100 : g === 0 ? 0 : 100 - 100 / (1 + g / l);
  }
  return out;
}

export type MacdSeries = { line: Maybe[]; signal: Maybe[]; histogram: Maybe[] };

/** Pine `ta.macd` — MACD line is null until the slow EMA exists. */
export function macdSeries(closes: number[], fast = 12, slow = 26, signalLen = 9): MacdSeries {
  const f = emaSeries(closes, fast);
  const s = emaSeries(closes, slow);
  const line: Maybe[] = closes.map((_, i) => (isNum(f[i]) && isNum(s[i]) ? (f[i] as number) - (s[i] as number) : null));
  const signal = emaOfMaybe(line, signalLen);
  const histogram: Maybe[] = line.map((v, i) => (isNum(v) && isNum(signal[i]) ? v - (signal[i] as number) : null));
  return { line, signal, histogram };
}

export type BollingerSeries = { basis: Maybe[]; upper: Maybe[]; lower: Maybe[]; width: Maybe[] };

/** Pine `ta.bb` — SMA basis with population standard deviation. */
export function bollingerSeries(closes: number[], period = 20, mult = 2): BollingerSeries {
  const basis = smaSeries(closes, period);
  const upper: Maybe[] = new Array(closes.length).fill(null);
  const lower: Maybe[] = new Array(closes.length).fill(null);
  const width: Maybe[] = new Array(closes.length).fill(null);
  for (let i = 0; i < closes.length; i++) {
    const mid = basis[i];
    if (!isNum(mid)) continue;
    let acc = 0;
    for (let k = i - period + 1; k <= i; k++) acc += (closes[k] - mid) ** 2;
    const sd = Math.sqrt(acc / period);
    upper[i] = mid + mult * sd;
    lower[i] = mid - mult * sd;
    width[i] = mid ? (2 * mult * sd) / mid : 0;
  }
  return { basis, upper, lower, width };
}

/** Pine `ta.tr(true)`. */
export function trueRange(bars: OhlcBar[]): number[] {
  return bars.map((b, i) => {
    if (i === 0) return b.h - b.l;
    const pc = bars[i - 1].c;
    return Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc));
  });
}

/** Pine `ta.atr` = rma(tr, length). */
export function atrSeries(bars: OhlcBar[], period = 10): Maybe[] {
  return rmaSeries(trueRange(bars), period);
}

export type SupertrendSeries = {
  /** Trailing stop level, null before ATR exists. */
  value: Maybe[];
  /** 1 = uptrend (line under price), -1 = downtrend (line over price). */
  direction: (1 | -1 | null)[];
  atr: Maybe[];
};

/** Pine `ta.supertrend(factor, atrPeriod)` with APEX defaults ATR 10 / factor 3. */
export function supertrendSeries(bars: OhlcBar[], atrPeriod = 10, factor = 3): SupertrendSeries {
  const n = bars.length;
  const atr = atrSeries(bars, atrPeriod);
  const value: Maybe[] = new Array(n).fill(null);
  const direction: (1 | -1 | null)[] = new Array(n).fill(null);
  let prevUpper = Number.NaN;
  let prevLower = Number.NaN;
  let prevSt = Number.NaN;
  let prevDir: 1 | -1 | null = null;
  for (let i = 0; i < n; i++) {
    const a = atr[i];
    if (!isNum(a)) continue;
    const hl2 = (bars[i].h + bars[i].l) / 2;
    let upper = hl2 + factor * a;
    let lower = hl2 - factor * a;
    const prevClose = i > 0 ? bars[i - 1].c : bars[i].c;
    if (Number.isFinite(prevLower)) lower = lower > prevLower || prevClose < prevLower ? lower : prevLower;
    if (Number.isFinite(prevUpper)) upper = upper < prevUpper || prevClose > prevUpper ? upper : prevUpper;

    let dir: 1 | -1;
    if (prevDir == null) {
      dir = 1;
    } else if (prevSt === prevUpper) {
      dir = bars[i].c > upper ? 1 : -1;
    } else {
      dir = bars[i].c < lower ? -1 : 1;
    }
    const st = dir === 1 ? lower : upper;
    value[i] = st;
    direction[i] = dir;
    prevUpper = upper;
    prevLower = lower;
    prevSt = st;
    prevDir = dir;
  }
  return { value, direction, atr };
}

/* ------------------------------------------------------------------ */
/* Pivot Points Standard                                               */
/* ------------------------------------------------------------------ */

export type PivotResolution = "D" | "W" | "M" | "12M";
export type PivotsTimeframe = "AUTO" | PivotResolution;
export type LabelsPosition = "Left" | "Right";

/** Inputs of TradingView's built-in "Pivot Points Standard" study. */
export type PivotConfig = {
  type: "Traditional";
  pivotsTimeframe: PivotsTimeframe;
  numberOfPivotsBack: number;
  useDailyBasedValues: boolean;
  showLabels: boolean;
  showPrices: boolean;
  labelsPosition: LabelsPosition;
  lineWidth: number;
};

/**
 * Exactly the settings dialog the desk signed off on:
 * Traditional · Auto · 1 back · daily-based · labels + prices · Left · width 1.
 */
export const APEX_PIVOT_CONFIG: PivotConfig = {
  type: "Traditional",
  pivotsTimeframe: "AUTO",
  numberOfPivotsBack: 1,
  useDailyBasedValues: true,
  showLabels: true,
  showPrices: true,
  labelsPosition: "Left",
  lineWidth: 1,
};

/**
 * TradingView "Auto" pivot resolution:
 * intraday ≤ 15m → daily, intraday > 15m → weekly, daily → monthly, weekly+ → yearly.
 */
export function autoPivotResolution(timeframe: string): PivotResolution {
  const tf = timeframe.trim().toUpperCase();
  const m = /^(\d+)\s*(M|MIN|H|HR)$/.exec(tf);
  if (m) {
    const n = Number(m[1]);
    const minutes = m[2] === "H" || m[2] === "HR" ? n * 60 : n;
    return minutes <= 15 ? "D" : "W";
  }
  if (tf === "1D" || tf === "D") return "M";
  return "12M";
}

export function resolvePivotResolution(timeframe: string, config: PivotConfig = APEX_PIVOT_CONFIG): PivotResolution {
  return config.pivotsTimeframe === "AUTO" ? autoPivotResolution(timeframe) : config.pivotsTimeframe;
}

export type PivotLevels = {
  p: number;
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

/**
 * TradingView "Traditional" pivot formula.
 *   P  = (H + L + C) / 3
 *   R1 = 2P − L               S1 = 2P − H
 *   R2 = P + (H − L)          S2 = P − (H − L)
 *   R3 = 2P + (H − 2L)        S3 = 2P − (2H − L)
 *   R4 = 3P + (H − 3L)        S4 = 3P − (3H − L)
 *   R5 = 4P + (H − 4L)        S5 = 4P − (4H − L)
 */
export function traditionalPivots(high: number, low: number, close: number): PivotLevels {
  const p = (high + low + close) / 3;
  return {
    p,
    r1: 2 * p - low,
    r2: p + (high - low),
    r3: 2 * p + (high - 2 * low),
    r4: 3 * p + (high - 3 * low),
    r5: 4 * p + (high - 4 * low),
    s1: 2 * p - high,
    s2: p - (high - low),
    s3: 2 * p - (2 * high - low),
    s4: 3 * p - (3 * high - low),
    s5: 4 * p - (4 * high - low),
  };
}

export type PivotRow = { key: keyof PivotLevels; label: string; price: number };

/** R5 → S5, top to bottom, with TradingView's `P` label for the central pivot. */
export function pivotRows(levels: PivotLevels): PivotRow[] {
  return [
    { key: "r5", label: "R5", price: levels.r5 },
    { key: "r4", label: "R4", price: levels.r4 },
    { key: "r3", label: "R3", price: levels.r3 },
    { key: "r2", label: "R2", price: levels.r2 },
    { key: "r1", label: "R1", price: levels.r1 },
    { key: "p", label: "P", price: levels.p },
    { key: "s1", label: "S1", price: levels.s1 },
    { key: "s2", label: "S2", price: levels.s2 },
    { key: "s3", label: "S3", price: levels.s3 },
    { key: "s4", label: "S4", price: levels.s4 },
    { key: "s5", label: "S5", price: levels.s5 },
  ];
}

/** Renders "P (5,123.45)" / "P" / "" depending on Show labels + Show prices. */
export function pivotLabel(row: PivotRow, config: PivotConfig = APEX_PIVOT_CONFIG, digits = 2): string {
  const price = row.price.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (config.showLabels && config.showPrices) return `${row.label} (${price})`;
  if (config.showLabels) return row.label;
  if (config.showPrices) return price;
  return "";
}

function periodKey(date: Date, resolution: PivotResolution): string {
  const y = date.getUTCFullYear();
  switch (resolution) {
    case "D":
      return `${y}-${date.getUTCMonth() + 1}-${date.getUTCDate()}`;
    case "W": {
      // ISO week bucket keyed by the Monday of that week.
      const d = new Date(Date.UTC(y, date.getUTCMonth(), date.getUTCDate()));
      const shift = (d.getUTCDay() + 6) % 7;
      d.setUTCDate(d.getUTCDate() - shift);
      return `W${d.toISOString().slice(0, 10)}`;
    }
    case "M":
      return `${y}-${date.getUTCMonth() + 1}`;
    case "12M":
      return `${y}`;
  }
}

export type PivotPeriod = { key: string; start: number; end: number; high: number; low: number; close: number };

/**
 * Aggregate bars into pivot periods. With "Use daily-based values" on, callers
 * pass the daily series so an intraday chart still gets true daily H/L/C —
 * which is what the TradingView checkbox does.
 */
export function aggregatePivotPeriods(bars: OhlcBar[], resolution: PivotResolution): PivotPeriod[] {
  const out: PivotPeriod[] = [];
  for (const b of bars) {
    const ts = Date.parse(b.t);
    if (!Number.isFinite(ts)) continue;
    const key = periodKey(new Date(ts), resolution);
    const last = out[out.length - 1];
    if (last && last.key === key) {
      last.high = Math.max(last.high, b.h);
      last.low = Math.min(last.low, b.l);
      last.close = b.c;
      last.end = ts;
      continue;
    }
    out.push({ key, start: ts, end: ts, high: b.h, low: b.l, close: b.c });
  }
  return out;
}

export type PivotSet = {
  resolution: PivotResolution;
  /** Period whose H/L/C produced the levels. */
  source: PivotPeriod;
  /** Epoch ms where these levels start being drawn (start of the period they govern). */
  activeFrom: number;
  levels: PivotLevels;
};

/**
 * `Number of pivots back = n` yields n level sets: the newest is projected from
 * the last completed period onto the period in progress, and each older set is
 * projected onto the period that followed it.
 */
export function computePivotSets(
  dailyBars: OhlcBar[],
  timeframe: string,
  config: PivotConfig = APEX_PIVOT_CONFIG,
): PivotSet[] {
  const resolution = resolvePivotResolution(timeframe, config);
  const periods = aggregatePivotPeriods(dailyBars, resolution);
  if (periods.length < 2) return [];
  const back = Math.max(1, Math.floor(config.numberOfPivotsBack));
  const sets: PivotSet[] = [];
  for (let k = 0; k < back; k++) {
    const sourceIdx = periods.length - 2 - k;
    const activeIdx = sourceIdx + 1;
    if (sourceIdx < 0 || activeIdx >= periods.length) break;
    const source = periods[sourceIdx];
    sets.push({
      resolution,
      source,
      activeFrom: periods[activeIdx].start,
      levels: traditionalPivots(source.high, source.low, source.close),
    });
  }
  return sets;
}

/* ------------------------------------------------------------------ */
/* Bundle used by the chart and by scan analysis                       */
/* ------------------------------------------------------------------ */

export const EMA_LENGTHS = [9, 21, 50, 100, 200] as const;
export type EmaLength = (typeof EMA_LENGTHS)[number];

export type StudyBundle = {
  bars: OhlcBar[];
  ema: Record<EmaLength, Maybe[]>;
  sma50: Maybe[];
  sma200: Maybe[];
  bb: BollingerSeries;
  macd: MacdSeries;
  rsi: Maybe[];
  supertrend: SupertrendSeries;
  atr10: Maybe[];
};

export function computeStudies(bars: OhlcBar[]): StudyBundle {
  const closes = bars.map((b) => b.c);
  const ema = {} as Record<EmaLength, Maybe[]>;
  for (const len of EMA_LENGTHS) ema[len] = emaSeries(closes, len);
  return {
    bars,
    ema,
    sma50: smaSeries(closes, 50),
    sma200: smaSeries(closes, 200),
    bb: bollingerSeries(closes, 20, 2),
    macd: macdSeries(closes, 12, 26, 9),
    rsi: rsiSeries(closes, 14),
    supertrend: supertrendSeries(bars, 10, 3),
    atr10: atrSeries(bars, 10),
  };
}

/** Last non-null value of a study series (the value TradingView shows on the legend). */
export function lastValue(series: Maybe[]): Maybe {
  for (let i = series.length - 1; i >= 0; i--) if (isNum(series[i])) return series[i];
  return null;
}

/** True when the study never becomes defined on this history — do not draw it. */
export function isEmptySeries(series: Maybe[]): boolean {
  return !series.some(isNum);
}
