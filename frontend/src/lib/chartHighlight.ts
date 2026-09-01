import type { AnalysisCard } from "./analysisCards";
import { catalystIsDrawableOnChart, patternUsesBoxMark, type Catalyst } from "./patterns";
import { PLOT_COLORS, type PlotLayout, type PlotSeries } from "./plotChart";
import type { OhlcBar } from "./ta";

import { DEFAULT_USER_SETTINGS } from "./userSettings";

/** Composite / chain execution score bands (Full Document §8). */
export const SCORE_TIER_BLOCKED_MAX = 50;

export type ScoreTier = "blocked" | "caution" | "auto_exec";

export function scoreTier(
  score: number | null | undefined,
  autoExecMin: number = DEFAULT_USER_SETTINGS.autoExecMinScore,
): ScoreTier {
  if (score == null || !Number.isFinite(score)) return "caution";
  if (score <= SCORE_TIER_BLOCKED_MAX) return "blocked";
  if (score >= autoExecMin) return "auto_exec";
  return "caution";
}

export type GlowLine = { xs: number[]; ys: number[]; color: string; width: number };

export type GlowPane = { x: number; y: number; w: number; h: number; color: string; label?: string };

export type MarkShape =
  | { kind: "circle"; cx: number; cy: number; r: number; color: string }
  | { kind: "box"; x: number; y: number; w: number; h: number; color: string };

export type ChartHighlight = {
  id: string;
  glowLines?: GlowLine[];
  glowPanes?: GlowPane[];
  mark?: MarkShape;
};

/** Studies actually drawn on the desk / snapshot — the only cards that may glow. */
const GLOWABLE_STUDIES = new Set(["study-ema", "study-bb", "study-macd", "study-rsi", "study-volume"]);

function finiteLine(layout: PlotLayout, values: number[], mapY: (v: number) => number, color: string, width: number): GlowLine | null {
  const xs: number[] = [];
  const ys: number[] = [];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (!Number.isFinite(v)) continue;
    xs.push(layout.x(i));
    ys.push(mapY(v));
  }
  if (xs.length < 2) return null;
  return { xs, ys, color, width };
}

function macdBounds(series: PlotSeries) {
  const hist = series.macd.histogram.filter(Number.isFinite);
  const macdLine = series.macd.line.filter(Number.isFinite);
  const sigLine = series.macd.signal.filter(Number.isFinite);
  const lo = Math.min(...hist, ...macdLine, ...sigLine, 0);
  const hi = Math.max(...hist, ...macdLine, ...sigLine, 0);
  return { lo, hi };
}

function lastMacdCross(series: PlotSeries, from: number): number | null {
  const line = series.macd.line;
  const signal = series.macd.signal;
  for (let i = line.length - 1; i > from; i--) {
    if (!Number.isFinite(line[i]) || !Number.isFinite(signal[i]) || !Number.isFinite(line[i - 1]) || !Number.isFinite(signal[i - 1])) continue;
    const prev = line[i - 1] - signal[i - 1];
    const cur = line[i] - signal[i];
    if ((prev <= 0 && cur > 0) || (prev >= 0 && cur < 0)) return i;
  }
  return null;
}

function lastEmaCross(series: PlotSeries, from: number): number | null {
  const ema9 = series.ema9;
  const ema21 = series.ema21;
  for (let i = ema9.length - 1; i > from; i--) {
    if (!Number.isFinite(ema9[i]) || !Number.isFinite(ema21[i]) || !Number.isFinite(ema9[i - 1]) || !Number.isFinite(ema21[i - 1])) continue;
    const prev = ema9[i - 1] - ema21[i - 1];
    const cur = ema9[i] - ema21[i];
    if ((prev <= 0 && cur > 0) || (prev >= 0 && cur < 0)) return i;
  }
  return null;
}

/**
 * Fractional bar index + MACD value at the exact line/signal cross between i-1 and i.
 * Geometry maps onto the MACD pane via layout.x / layout.yMacd.
 */
export function macdCrossPoint(
  series: PlotSeries,
  i: number,
): { iFrac: number; value: number } | null {
  const line = series.macd.line;
  const signal = series.macd.signal;
  if (i < 1 || i >= line.length) return null;
  const l0 = line[i - 1];
  const l1 = line[i];
  const s0 = signal[i - 1];
  const s1 = signal[i];
  if (![l0, l1, s0, s1].every(Number.isFinite)) return null;
  const prev = l0 - s0;
  const cur = l1 - s1;
  const denom = prev - cur;
  const t = Math.abs(denom) < 1e-12 ? 1 : Math.min(1, Math.max(0, prev / denom));
  return {
    iFrac: i - 1 + t,
    value: l0 + t * (l1 - l0),
  };
}

/** @deprecated Use catalystIsDrawableOnChart from patterns.ts */
export function catalystIsDrawable(c: Catalyst): boolean {
  return catalystIsDrawableOnChart(c);
}

function patternBarRange(bars: OhlcBar[], c: Catalyst): { i0: number; i1: number; hi: number; lo: number } | null {
  if (!bars.length) return null;
  const i0 = Math.max(0, Math.min(bars.length - 1, c.barIndex));
  const i1 = Math.max(i0, Math.min(bars.length - 1, c.barEnd ?? c.barIndex));
  let hi = -Infinity;
  let lo = Infinity;
  for (let i = i0; i <= i1; i++) {
    const b = bars[i];
    if (!b) continue;
    hi = Math.max(hi, b.h);
    lo = Math.min(lo, b.l);
  }
  if (Number.isFinite(c.price)) {
    hi = Math.max(hi, c.price);
    lo = Math.min(lo, c.price);
  }
  if (c.price2 != null && Number.isFinite(c.price2)) {
    hi = Math.max(hi, c.price2);
    lo = Math.min(lo, c.price2);
  }
  if (!Number.isFinite(hi) || !Number.isFinite(lo)) return null;
  return { i0, i1, hi, lo };
}

/**
 * Rectangle spanning the detected bar range for large multi-candle structures
 * (head & shoulders, flags, channels, double tops/bottoms).
 */
export function patternEnclosingBox(bars: OhlcBar[], layout: PlotLayout, c: Catalyst): MarkShape | null {
  const range = patternBarRange(bars, c);
  if (!range) return null;
  const { i0, i1, hi, lo } = range;
  const x = layout.x(i0) - layout.candleW / 2;
  const w = layout.x(i1) + layout.candleW / 2 - x;
  const y = layout.y(hi);
  const h = layout.y(lo) - layout.y(hi);
  const color = c.bias === "bullish" ? PLOT_COLORS.up : PLOT_COLORS.down;
  return { kind: "box", x, y, w, h, color };
}

/** Circle tightly enclosing every candle in the pattern bar range (small prints). */
export function patternEnclosingCircle(bars: OhlcBar[], layout: PlotLayout, c: Catalyst): MarkShape | null {
  const range = patternBarRange(bars, c);
  if (!range) return null;
  const { i0, i1, hi, lo } = range;
  const x0 = layout.x(i0) - layout.candleW / 2;
  const x1 = layout.x(i1) + layout.candleW / 2;
  const yTop = layout.y(hi);
  const yBot = layout.y(lo);
  const cx = (x0 + x1) / 2;
  const cy = (yTop + yBot) / 2;
  const rx = Math.max(1, (x1 - x0) / 2);
  const ry = Math.max(1, Math.abs(yBot - yTop) / 2);
  const r = Math.sqrt(rx * rx + ry * ry) + 1;
  const color = c.bias === "bullish" ? PLOT_COLORS.up : PLOT_COLORS.down;
  return { kind: "circle", cx, cy, r, color };
}

/** Pick rectangle vs circle from pattern kind/name. */
export function resolvePatternMarkShape(bars: OhlcBar[], layout: PlotLayout, c: Catalyst): MarkShape | null {
  if (patternUsesBoxMark(c)) return patternEnclosingBox(bars, layout, c);
  return patternEnclosingCircle(bars, layout, c);
}

function macdCrossMark(_bars: OhlcBar[], layout: PlotLayout, series: PlotSeries, barHint?: number): MarkShape | null {
  let i: number | null = null;
  if (barHint != null && barHint >= 1 && barHint < series.macd.line.length && macdCrossPoint(series, barHint)) {
    i = barHint;
  }
  if (i == null) {
    const from = Math.max(8, series.macd.line.length - 16);
    i = lastMacdCross(series, from);
  }
  if (i == null) return null;
  const pt = macdCrossPoint(series, i);
  if (!pt) return null;
  const { lo, hi } = macdBounds(series);
  const cx = layout.x(pt.iFrac);
  const cy = layout.yMacd(pt.value, lo, hi);
  return { kind: "circle", cx, cy, r: Math.max(9, layout.candleW * 1.15), color: PLOT_COLORS.macd };
}

/**
 * Fractional bar index + EMA value at the exact 9/21 cross between i-1 and i.
 * Geometry maps onto the price pane via layout.x / layout.y.
 */
export function emaCrossPoint(series: PlotSeries, i: number): { iFrac: number; value: number } | null {
  const ema9 = series.ema9;
  const ema21 = series.ema21;
  if (i < 1 || i >= ema9.length) return null;
  const e0 = ema9[i - 1];
  const e1 = ema9[i];
  const f0 = ema21[i - 1];
  const f1 = ema21[i];
  if (![e0, e1, f0, f1].every(Number.isFinite)) return null;
  const prev = e0 - f0;
  const cur = e1 - f1;
  const denom = prev - cur;
  const t = Math.abs(denom) < 1e-12 ? 1 : Math.min(1, Math.max(0, prev / denom));
  return {
    iFrac: i - 1 + t,
    value: e0 + t * (e1 - e0),
  };
}

function emaCrossMark(_bars: OhlcBar[], layout: PlotLayout, series: PlotSeries, barHint?: number): MarkShape | null {
  let i: number | null = null;
  if (barHint != null && barHint >= 1 && barHint < series.ema9.length && emaCrossPoint(series, barHint)) {
    i = barHint;
  }
  if (i == null) {
    const from = Math.max(8, series.ema9.length - 16);
    i = lastEmaCross(series, from);
  }
  if (i == null) return null;
  const pt = emaCrossPoint(series, i);
  if (!pt) return null;
  const cx = layout.x(pt.iFrac);
  const cy = layout.y(pt.value);
  return { kind: "circle", cx, cy, r: Math.max(9, layout.candleW * 1.15), color: PLOT_COLORS.ema21 };
}

function resolveCatalystMark(bars: OhlcBar[], layout: PlotLayout, series: PlotSeries, c: Catalyst): MarkShape | null {
  if (/macd/i.test(c.name)) {
    return macdCrossMark(bars, layout, series, c.barIndex) ?? resolvePatternMarkShape(bars, layout, c);
  }
  if (/ema.*cross/i.test(c.name)) {
    return emaCrossMark(bars, layout, series, c.barIndex) ?? resolvePatternMarkShape(bars, layout, c);
  }
  return resolvePatternMarkShape(bars, layout, c);
}

/** One active highlight for the frozen snapshot — indicator glow OR a pattern / crossover mark. */
export function resolveChartHighlight(
  card: AnalysisCard | undefined,
  bars: OhlcBar[],
  series: PlotSeries,
  layout: PlotLayout,
  catalysts: Catalyst[],
): ChartHighlight | null {
  if (!card || !bars.length) return null;

  if (card.kind === "catalyst" && card.markId) {
    const c = catalysts.find((x) => x.id === card.markId);
    if (!c || !catalystIsDrawableOnChart(c)) return null;
    const mark = resolveCatalystMark(bars, layout, series, c);
    return mark ? { id: card.id, mark } : null;
  }

  // Pivots, SMA, SuperTrend, S/R — analysis cards only; never glow (not on the graph).
  if (!GLOWABLE_STUDIES.has(card.id)) return null;

  const glowLines: GlowLine[] = [];
  const glowPanes: GlowPane[] = [];
  const pad = layout.pad;
  const plotW = layout.width - pad.l - pad.r;

  switch (card.id) {
    case "study-ema": {
      for (const [values, color, width] of [
        [series.ema9, PLOT_COLORS.ema9, 2.4],
        [series.ema21, PLOT_COLORS.ema21, 2.2],
        [series.ema50, PLOT_COLORS.ema50, 2.2],
      ] as const) {
        const line = finiteLine(layout, values, layout.y, color, width);
        if (line) glowLines.push(line);
      }
      const mark = emaCrossMark(bars, layout, series);
      return { id: card.id, glowLines, mark: mark ?? undefined };
    }
    case "study-bb": {
      for (const [values, width] of [
        [series.bb.upper, 1.8],
        [series.bb.mid, 1.6],
        [series.bb.lower, 1.8],
      ] as const) {
        const line = finiteLine(layout, values, layout.y, PLOT_COLORS.bb, width);
        if (line) glowLines.push(line);
      }
      break;
    }
    case "study-macd": {
      const mark = macdCrossMark(bars, layout, series);
      glowPanes.push({
        x: pad.l,
        y: layout.macdTop,
        w: plotW,
        h: layout.macdBottom - layout.macdTop,
        color: PLOT_COLORS.macd,
        label: "MACD",
      });
      return { id: card.id, glowPanes, mark: mark ?? undefined };
    }
    case "study-rsi":
      glowPanes.push({
        x: pad.l,
        y: layout.rsiTop,
        w: plotW,
        h: layout.rsiBottom - layout.rsiTop,
        color: PLOT_COLORS.rsi,
        label: "RSI",
      });
      break;
    case "study-volume": {
      const volTop = layout.priceBottom - (layout.priceBottom - layout.priceTop) * 0.2;
      glowPanes.push({
        x: pad.l,
        y: volTop,
        w: plotW,
        h: layout.priceBottom - volTop,
        color: PLOT_COLORS.up,
        label: "Volume",
      });
      break;
    }
    default:
      return null;
  }

  if (!glowLines.length && !glowPanes.length) return null;
  return { id: card.id, glowLines, glowPanes };
}
