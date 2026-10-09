import { APEX_PIVOT_CONFIG, computePivotSets, computeStudies, traditionalPivots, type Maybe } from "./studies";
import type { ChartChrome } from "./tv";
import { pivotLadder, type OhlcBar, type PivotLevels, type SupertrendPoint } from "./ta";

/** TradingView-like orange used for every pivot level (screenshot 2). */
export const PIVOT_ORANGE = "#ff9800";

export const PLOT_COLORS = {
  bg: "#131722",
  grid: "rgba(240,243,250,0.06)",
  paneEdge: "rgba(240,243,250,0.12)",
  axis: "#9aa0b0",
  legend: "#d1d4dc",
  up: "#26a69a",
  down: "#ef5350",
  ema9: "#2962ff",
  ema21: "#26c6da",
  ema50: "#4caf50",
  ema100: "#ab47bc",
  ema200: "#ef5350",
  sma50: "#8fd4b0",
  sma200: "#f0a090",
  bb: "rgba(120,140,160,0.75)",
  bbFill: "rgba(120,140,160,0.08)",
  stBull: "#00c853",
  stBear: "#ff1744",
  pivot: PIVOT_ORANGE,
  r: "#e07a6a",
  s: "#7dcea0",
  macd: "#5dade2",
  signal: "#f5b041",
  rsi: "#c4a56a",
};

export type PlotPad = { l: number; r: number; t: number; b: number };

export type PlotLayout = {
  width: number;
  height: number;
  pad: PlotPad;
  priceTop: number;
  priceBottom: number;
  macdTop: number;
  macdBottom: number;
  rsiTop: number;
  rsiBottom: number;
  minP: number;
  maxP: number;
  barCount: number;
  x: (i: number) => number;
  y: (price: number) => number;
  yMacd: (v: number, lo: number, hi: number) => number;
  yRsi: (v: number) => number;
  candleW: number;
};

export type PlotSeries = {
  ema9: number[];
  ema21: number[];
  ema50: number[];
  ema100: number[];
  ema200: number[];
  sma50: number[];
  sma200: number[];
  bb: { mid: number[]; upper: number[]; lower: number[]; width: number[] };
  st: SupertrendPoint[];
  macd: { line: number[]; signal: number[]; histogram: number[] };
  rsi: number[];
  pivots: PivotLevels | null;
};

export type RenderPlotOpts = {
  dailyBars?: OhlcBar[];
  /** Full loaded series for EMA 200 warm-up; drawn window stays `bars`. */
  contextBars?: OhlcBar[];
  timeframe?: string;
  mode?: "snapshot" | "full";
  title?: string;
};

/** Core Traditional pivots that look clean on a price pane (skip far R4–S5 clutter). */
const CORE_PIVOT_KEYS = new Set(["P", "R1", "R2", "R3", "S1", "S2", "S3"]);

/**
 * Levels inside the visible price range only.
 * Prefer P / R1–R3 / S1–S3; only add R4/R5/S4/S5 when they fall inside the pane
 * and there is still room (max 7 lines).
 */
export function visiblePivotRows(pivots: PivotLevels | null, minP: number, maxP: number) {
  if (!pivots) return [];
  const all = pivotLadder(pivots).filter((row) => row.price >= minP && row.price <= maxP && Number.isFinite(row.price));
  const core = all.filter((row) => CORE_PIVOT_KEYS.has(row.label));
  if (core.length >= 3 || all.length <= 7) return core.length ? core : all.slice(0, 7);
  const extras = all.filter((row) => !CORE_PIVOT_KEYS.has(row.label));
  return [...core, ...extras].slice(0, 7);
}

/**
 * Study values behind the analysis cards.
 *
 * These delegate to the same TradingView-semantics math the chart renders, so a
 * number quoted in a scan card is the number on the chart legend. Undefined
 * warm-up values arrive as NaN and are reported as "n/a" rather than invented.
 */
export function computeSeries(bars: OhlcBar[], opts?: { dailyBars?: OhlcBar[]; timeframe?: string }): PlotSeries {
  const s = computeStudies(bars);
  const dense = (v: Maybe[]) => v.map((x) => (x == null ? Number.NaN : x));
  const prev = bars.length >= 2 ? bars[bars.length - 2] : bars[bars.length - 1];
  const daily = opts?.dailyBars ?? [];
  const sets = daily.length ? computePivotSets(daily, opts?.timeframe ?? "1D", APEX_PIVOT_CONFIG) : [];
  const levels = sets[0]?.levels ?? (prev ? traditionalPivots(prev.h, prev.l, prev.c) : null);
  return {
    ema9: dense(s.ema[9]),
    ema21: dense(s.ema[21]),
    ema50: dense(s.ema[50]),
    ema100: dense(s.ema[100]),
    ema200: dense(s.ema[200]),
    sma50: dense(s.sma50),
    sma200: dense(s.sma200),
    bb: { mid: dense(s.bb.basis), upper: dense(s.bb.upper), lower: dense(s.bb.lower), width: dense(s.bb.width) },
    st: bars.map((_, i) => ({
      value: s.supertrend.value[i] ?? Number.NaN,
      direction: (s.supertrend.direction[i] ?? 1) as 1 | -1,
      atr: s.supertrend.atr[i] ?? Number.NaN,
    })),
    macd: { line: dense(s.macd.line), signal: dense(s.macd.signal), histogram: dense(s.macd.histogram) },
    rsi: dense(s.rsi),
    pivots: levels
      ? {
          pp: levels.p,
          r1: levels.r1,
          r2: levels.r2,
          r3: levels.r3,
          r4: levels.r4,
          r5: levels.r5,
          s1: levels.s1,
          s2: levels.s2,
          s3: levels.s3,
          s4: levels.s4,
          s5: levels.s5,
        }
      : null,
  };
}

/**
 * Snapshot / capture layout: price pane + MACD + RSI with breathing room.
 * `full` and `snapshot` both include oscillators — scan needs readable studies.
 */
export function layoutPlot(
  bars: OhlcBar[],
  series: PlotSeries,
  width: number,
  height: number,
  mode: "snapshot" | "full" = "snapshot",
): PlotLayout {
  const pad: PlotPad = mode === "snapshot" ? { l: 14, r: 72, t: 36, b: 28 } : { l: 10, r: 64, t: 8, b: 26 };
  const gap = mode === "snapshot" ? 10 : 6;
  const innerH = Math.max(80, height - pad.t - pad.b);
  // Price ~62%, MACD ~18%, RSI ~16% with gaps — matches a clean TV multi-pane read.
  const priceFrac = 0.62;
  const macdFrac = 0.18;
  const rsiFrac = 0.16;
  const usable = innerH - gap * 2;
  const priceH = usable * priceFrac;
  const macdH = usable * macdFrac;
  const rsiH = usable * rsiFrac;
  const priceTop = pad.t;
  const priceBottom = pad.t + priceH;
  const macdTop = priceBottom + gap;
  const macdBottom = macdTop + macdH;
  const rsiTop = macdBottom + gap;
  const rsiBottom = Math.min(height - pad.b, rsiTop + rsiH);

  const n = Math.max(bars.length, 1);
  const plotW = Math.max(10, width - pad.l - pad.r);
  const candleW = Math.max(2.4, Math.min(10, (plotW / n) * 0.68));
  const x = (i: number) => pad.l + ((i + 0.5) / n) * plotW;

  let minP = Infinity;
  let maxP = -Infinity;
  for (let i = 0; i < bars.length; i++) {
    minP = Math.min(minP, bars[i].l, series.bb.lower[i] || bars[i].l);
    maxP = Math.max(maxP, bars[i].h, series.bb.upper[i] || bars[i].h);
  }
  if (!Number.isFinite(minP) || !Number.isFinite(maxP) || minP === maxP) {
    minP = (bars[0]?.c ?? 0) * 0.98;
    maxP = (bars[0]?.c ?? 1) * 1.02;
  }
  const padP = (maxP - minP) * 0.05;
  minP -= padP;
  maxP += padP;
  const y = (price: number) => priceBottom - ((price - minP) / (maxP - minP)) * (priceBottom - priceTop);
  const yMacd = (v: number, lo: number, hi: number) => {
    const span = hi - lo || 1;
    return macdBottom - ((v - lo) / span) * (macdBottom - macdTop);
  };
  const yRsi = (v: number) => rsiBottom - (Math.min(100, Math.max(0, v)) / 100) * (rsiBottom - rsiTop);

  return {
    width,
    height,
    pad,
    priceTop,
    priceBottom,
    macdTop,
    macdBottom,
    rsiTop,
    rsiBottom,
    minP,
    maxP,
    barCount: n,
    x,
    y,
    yMacd,
    yRsi,
    candleW,
  };
}

function line(ctx: CanvasRenderingContext2D, xs: number[], ys: number[], color: string, width: number, dash?: number[]) {
  ctx.save();
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash ?? []);
  let started = false;
  for (let i = 0; i < xs.length; i++) {
    if (!Number.isFinite(ys[i])) {
      started = false;
      continue;
    }
    if (!started) {
      ctx.moveTo(xs[i], ys[i]);
      started = true;
    } else ctx.lineTo(xs[i], ys[i]);
  }
  ctx.stroke();
  ctx.restore();
}

function hline(ctx: CanvasRenderingContext2D, y: number, x0: number, x1: number, color: string, dash?: number[], width = 1) {
  ctx.save();
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash ?? [4, 4]);
  ctx.moveTo(x0, y);
  ctx.lineTo(x1, y);
  ctx.stroke();
  ctx.restore();
}

function paneSep(ctx: CanvasRenderingContext2D, y: number, x0: number, x1: number) {
  hline(ctx, y, x0, x1, PLOT_COLORS.paneEdge, [], 1);
}

export function drawPlot(
  ctx: CanvasRenderingContext2D,
  bars: OhlcBar[],
  series: PlotSeries,
  layout: PlotLayout,
  opts?: { title?: string },
) {
  const { width, height, pad, x, y, candleW, priceTop, priceBottom, macdTop, macdBottom, rsiTop, rsiBottom } = layout;
  ctx.fillStyle = PLOT_COLORS.bg;
  ctx.fillRect(0, 0, width, height);

  if (opts?.title) {
    ctx.fillStyle = PLOT_COLORS.legend;
    ctx.font = "800 13px Telegraf, system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(opts.title, pad.l, 10);
  }

  // Price grid
  ctx.strokeStyle = PLOT_COLORS.grid;
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i++) {
    const gy = priceTop + ((priceBottom - priceTop) * i) / 5;
    ctx.beginPath();
    ctx.moveTo(pad.l, gy);
    ctx.lineTo(width - pad.r, gy);
    ctx.stroke();
  }

  const maxV = Math.max(...bars.map((b) => b.v), 1);
  const volTop = priceBottom - (priceBottom - priceTop) * 0.2;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const cx = x(i);
    const up = b.c >= b.o;
    ctx.fillStyle = up ? "rgba(38,166,154,0.22)" : "rgba(239,83,80,0.22)";
    const vh = ((b.v / maxV) * (priceBottom - volTop)) | 0;
    ctx.fillRect(cx - candleW / 2, priceBottom - vh, candleW, vh);
  }

  const xs = bars.map((_, i) => x(i));

  // Soft BB fill between upper/lower
  ctx.save();
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < bars.length; i++) {
    const uy = y(series.bb.upper[i]);
    if (!Number.isFinite(uy)) continue;
    if (!started) {
      ctx.moveTo(xs[i], uy);
      started = true;
    } else ctx.lineTo(xs[i], uy);
  }
  for (let i = bars.length - 1; i >= 0; i--) {
    const ly = y(series.bb.lower[i]);
    if (!Number.isFinite(ly)) continue;
    ctx.lineTo(xs[i], ly);
  }
  ctx.closePath();
  ctx.fillStyle = PLOT_COLORS.bbFill;
  ctx.fill();
  ctx.restore();

  line(ctx, xs, series.bb.upper.map(y), PLOT_COLORS.bb, 1, [3, 3]);
  line(ctx, xs, series.bb.mid.map(y), PLOT_COLORS.bb, 1, [5, 4]);
  line(ctx, xs, series.bb.lower.map(y), PLOT_COLORS.bb, 1, [3, 3]);
  // EMA stack only (no SMA clutter) — matches desk TV studies + overlays
  line(ctx, xs, series.ema200.map(y), PLOT_COLORS.ema200, 1.7);
  line(ctx, xs, series.ema100.map(y), PLOT_COLORS.ema100, 1.2);
  line(ctx, xs, series.ema50.map(y), PLOT_COLORS.ema50, 1.25);
  line(ctx, xs, series.ema21.map(y), PLOT_COLORS.ema21, 1.55);
  line(ctx, xs, series.ema9.map(y), PLOT_COLORS.ema9, 1.7);

  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const cx = x(i);
    const up = b.c >= b.o;
    ctx.strokeStyle = up ? PLOT_COLORS.up : PLOT_COLORS.down;
    ctx.fillStyle = up ? PLOT_COLORS.up : PLOT_COLORS.down;
    ctx.beginPath();
    ctx.moveTo(cx, y(b.h));
    ctx.lineTo(cx, y(b.l));
    ctx.stroke();
    const top = y(Math.max(b.o, b.c));
    const bot = y(Math.min(b.o, b.c));
    ctx.fillRect(cx - candleW / 2, top, candleW, Math.max(1, bot - top));
  }

  // Legend strip on price pane
  const last = bars.length - 1;
  const legend = [
    { label: "EMA9", color: PLOT_COLORS.ema9, v: series.ema9[last] },
    { label: "EMA21", color: PLOT_COLORS.ema21, v: series.ema21[last] },
    { label: "EMA50", color: PLOT_COLORS.ema50, v: series.ema50[last] },
    { label: "BB", color: PLOT_COLORS.bb, v: series.bb.mid[last] },
  ];
  ctx.font = "10px 'IBM Plex Mono', ui-monospace, monospace";
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  let lx = pad.l + 4;
  const ly = priceTop + 12;
  for (const item of legend) {
    if (!Number.isFinite(item.v)) continue;
    ctx.fillStyle = item.color;
    ctx.fillRect(lx, ly - 4, 8, 8);
    lx += 12;
    ctx.fillStyle = PLOT_COLORS.legend;
    const text = `${item.label} ${Number(item.v).toFixed(2)}`;
    ctx.fillText(text, lx, ly);
    lx += ctx.measureText(text).width + 14;
  }

  paneSep(ctx, macdTop - 1, pad.l, width - pad.r);
  paneSep(ctx, rsiTop - 1, pad.l, width - pad.r);

  if (rsiBottom > macdTop + 8) {
    const hist = series.macd.histogram.filter(Number.isFinite);
    const macdLine = series.macd.line.filter(Number.isFinite);
    const sigLine = series.macd.signal.filter(Number.isFinite);
    const macdLo = Math.min(...hist, ...macdLine, ...sigLine, 0);
    const macdHi = Math.max(...hist, ...macdLine, ...sigLine, 0);
    const zeroY = layout.yMacd(0, macdLo, macdHi);
    hline(ctx, zeroY, pad.l, width - pad.r, "rgba(255,255,255,0.18)", [2, 3]);
    for (let i = 0; i < bars.length; i++) {
      const h = series.macd.histogram[i];
      if (!Number.isFinite(h)) continue;
      const cx = x(i);
      const hy = layout.yMacd(h, macdLo, macdHi);
      ctx.fillStyle = h >= 0 ? "rgba(38,166,154,0.75)" : "rgba(239,83,80,0.75)";
      ctx.fillRect(cx - candleW / 2, Math.min(hy, zeroY), candleW, Math.abs(hy - zeroY) || 1);
    }
    line(
      ctx,
      xs,
      series.macd.line.map((v) => layout.yMacd(v, macdLo, macdHi)),
      PLOT_COLORS.macd,
      1.35,
    );
    line(
      ctx,
      xs,
      series.macd.signal.map((v) => layout.yMacd(v, macdLo, macdHi)),
      PLOT_COLORS.signal,
      1.35,
    );
    ctx.fillStyle = PLOT_COLORS.axis;
    ctx.font = "10px 'IBM Plex Mono', ui-monospace, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    const mLast = series.macd.line[last];
    const sLast = series.macd.signal[last];
    const hLast = series.macd.histogram[last];
    ctx.fillText(
      `MACD  ${Number.isFinite(mLast) ? mLast.toFixed(3) : "—"}  Sig ${Number.isFinite(sLast) ? sLast.toFixed(3) : "—"}  Hist ${Number.isFinite(hLast) ? hLast.toFixed(3) : "—"}`,
      pad.l + 4,
      macdTop + 4,
    );

    hline(ctx, layout.yRsi(70), pad.l, width - pad.r, "rgba(239,83,80,0.4)", [4, 4]);
    hline(ctx, layout.yRsi(50), pad.l, width - pad.r, "rgba(255,255,255,0.12)", [2, 4]);
    hline(ctx, layout.yRsi(30), pad.l, width - pad.r, "rgba(38,166,154,0.4)", [4, 4]);
    line(ctx, xs, series.rsi.map(layout.yRsi), PLOT_COLORS.rsi, 1.5);
    const rLast = series.rsi[last];
    ctx.fillStyle = PLOT_COLORS.axis;
    ctx.fillText(`RSI 14  ${Number.isFinite(rLast) ? rLast.toFixed(1) : "—"}`, pad.l + 4, rsiTop + 4);
  }

  // Price axis
  ctx.fillStyle = PLOT_COLORS.axis;
  ctx.font = "10px 'IBM Plex Mono', ui-monospace, monospace";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= 4; i++) {
    const p = layout.minP + ((layout.maxP - layout.minP) * (4 - i)) / 4;
    ctx.fillText(p.toFixed(2), width - 8, priceTop + ((priceBottom - priceTop) * i) / 4);
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const step = Math.max(1, Math.floor(bars.length / 7));
  for (let i = 0; i < bars.length; i += step) {
    const d = new Date(bars[i].t);
    const label = Number.isNaN(d.getTime()) ? "" : `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
    ctx.fillText(label, x(i), height - 20);
  }
}

/** Ideal capture size for Deep Scan — wide, readable, not cramped host chrome. */
export const SNAPSHOT_SIZE = { w: 1280, h: 760 };

export function renderPlotPng(
  bars: OhlcBar[],
  cssWidth: number,
  cssHeight: number,
  dpr = 2,
  opts?: RenderPlotOpts,
): string | null {
  if (!bars.length || cssWidth < 8 || cssHeight < 8) return null;
  // Warm studies on context (full load truncated at window end), then draw only the visible bars.
  const ctxBars = opts?.contextBars;
  let series: PlotSeries;
  if (ctxBars && ctxBars.length > bars.length) {
    const endT = bars[bars.length - 1]?.t;
    const endIdx = endT ? ctxBars.findIndex((b) => b.t === endT) : -1;
    const evalBars = endIdx >= 0 ? ctxBars.slice(0, endIdx + 1) : ctxBars;
    const full = computeSeries(evalBars, { dailyBars: opts?.dailyBars, timeframe: opts?.timeframe });
    const startT = bars[0]?.t;
    const startIdx = startT ? evalBars.findIndex((b) => b.t === startT) : -1;
    series = startIdx > 0 ? sliceSeries(full, startIdx) : full;
    // If slice length drifted, fall back to visible-only compute.
    if (series.ema9.length !== bars.length) {
      series = computeSeries(bars, { dailyBars: opts?.dailyBars, timeframe: opts?.timeframe });
    }
  } else {
    series = computeSeries(bars, { dailyBars: opts?.dailyBars, timeframe: opts?.timeframe });
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(dpr, dpr);
  const mode = opts?.mode ?? "snapshot";
  // Layout is always in CSS pixels — overlay highlights must use the same size, not canvas×dpr.
  const layout = layoutPlot(bars, series, cssWidth, cssHeight, mode);
  drawPlot(ctx, bars, series, layout, { title: opts?.title });
  try {
    return canvas.toDataURL("image/png");
  } catch {
    return null;
  }
}

/**
 * TradingView Advanced Chart price-pane geometry.
 * Desk keeps TV chrome (top toolbar + left drawing bar + bottom range).
 * Frozen scan hides those. MACD + RSI are native full panes (~38–40% of the
 * body); overlays must clip to the price pane so they never cover oscillators.
 */
export function overlayChromePad(chrome: ChartChrome = "frozen") {
  if (chrome === "desk") {
    return { l: 54, r: 66, t: 46, osc: 0.385, time: 36 };
  }
  return { l: 8, r: 66, t: 28, osc: 0.4, time: 26 };
}

/**
 * Locked visible window for capture / overlay.
 * Trailing slice sized to the desk plot width — never the full loaded series
 * when more history is available. Optional from/to timestamps pin an exact range.
 */
export function viewportBars(
  bars: OhlcBar[],
  width: number,
  chrome: ChartChrome = "desk",
  locked?: { from?: string; to?: string },
) {
  if (locked?.from && locked?.to) {
    const a = Date.parse(locked.from);
    const b = Date.parse(locked.to);
    if (Number.isFinite(a) && Number.isFinite(b) && b >= a) {
      const sliced = bars.filter((x) => {
        const t = Date.parse(x.t);
        return Number.isFinite(t) && t >= a && t <= b;
      });
      if (sliced.length) {
        const start = Math.max(0, bars.findIndex((x) => x.t === sliced[0].t));
        return { start, bars: sliced };
      }
    }
  }
  const pad = overlayChromePad(chrome);
  const plotW = Math.max(48, width - pad.l - pad.r);
  // Match Advanced Chart default candle density (~6–7px per bar including gap).
  const n = Math.max(36, Math.min(bars.length, Math.round(plotW / 6.8)));
  const start = Math.max(0, bars.length - n);
  return { start, bars: bars.slice(start) };
}

export function sliceSeries(series: PlotSeries, start: number): PlotSeries {
  if (start <= 0) return series;
  return {
    ema9: series.ema9.slice(start),
    ema21: series.ema21.slice(start),
    ema50: series.ema50.slice(start),
    ema100: series.ema100.slice(start),
    ema200: series.ema200.slice(start),
    sma50: series.sma50.slice(start),
    sma200: series.sma200.slice(start),
    bb: {
      mid: series.bb.mid.slice(start),
      upper: series.bb.upper.slice(start),
      lower: series.bb.lower.slice(start),
      width: series.bb.width.slice(start),
    },
    st: series.st.slice(start),
    macd: {
      line: series.macd.line.slice(start),
      signal: series.macd.signal.slice(start),
      histogram: series.macd.histogram.slice(start),
    },
    rsi: series.rsi.slice(start),
    pivots: series.pivots,
  };
}

/** Geometry for the TradingView price pane (MACD/RSI occupy the lower oscillator stack). */
export function overlayLayout(
  bars: OhlcBar[],
  _series: PlotSeries,
  width: number,
  height: number,
  chrome: ChartChrome = "frozen",
): PlotLayout {
  const chromePad = overlayChromePad(chrome);
  const pad: PlotPad = { l: chromePad.l, r: chromePad.r, t: chromePad.t, b: 4 };
  const bodyH = Math.max(40, height - chromePad.t - chromePad.time);
  const priceH = bodyH * (1 - chromePad.osc);
  const priceTop = pad.t;
  const priceBottom = pad.t + priceH - pad.b;
  const n = Math.max(bars.length, 1);
  const plotW = Math.max(10, width - pad.l - pad.r);
  const candleW = Math.max(2.2, Math.min(12, (plotW / n) * 0.62));
  const x = (i: number) => pad.l + ((i + 0.5) / n) * plotW;
  let minP = Infinity;
  let maxP = -Infinity;
  for (let i = 0; i < bars.length; i++) {
    minP = Math.min(minP, bars[i].l);
    maxP = Math.max(maxP, bars[i].h);
  }
  if (!Number.isFinite(minP) || !Number.isFinite(maxP) || minP === maxP) {
    minP = (bars[0]?.c ?? 0) * 0.98;
    maxP = (bars[0]?.c ?? 1) * 1.02;
  }
  const padP = (maxP - minP) * 0.05;
  minP -= padP;
  maxP += padP;
  const y = (price: number) => priceBottom - ((price - minP) / (maxP - minP)) * (priceBottom - priceTop);
  return {
    width,
    height,
    pad,
    priceTop,
    priceBottom,
    macdTop: priceBottom,
    macdBottom: priceBottom,
    rsiTop: priceBottom,
    rsiBottom: priceBottom,
    minP,
    maxP,
    barCount: n,
    x,
    y,
    yMacd: () => priceBottom,
    yRsi: () => priceBottom,
    candleW,
  };
}

/** Extra studies drawn on the TV price pane (native slots already hold EMA 9/21 + BB). */
export const OVERLAY_EMA = [
  { key: "ema50" as const, label: "EMA 50", color: PLOT_COLORS.ema50, width: 1.25 },
  { key: "ema100" as const, label: "EMA 100", color: PLOT_COLORS.ema100, width: 1.2 },
  { key: "ema200" as const, label: "EMA 200", color: PLOT_COLORS.ema200, width: 1.55 },
];

/** Canvas mirror of ChartOverlay — EMA 50/100/200 only (no SuperTrend / pivots). */
export function drawOverlayStudies(ctx: CanvasRenderingContext2D, bars: OhlcBar[], series: PlotSeries, layout: PlotLayout) {
  ctx.clearRect(0, 0, layout.width, layout.height);
  const xs = bars.map((_, i) => layout.x(i));
  const y = layout.y;
  line(ctx, xs, series.ema50.map(y), PLOT_COLORS.ema50, 1.25);
  line(ctx, xs, series.ema100.map(y), PLOT_COLORS.ema100, 1.2);
  line(ctx, xs, series.ema200.map(y), PLOT_COLORS.ema200, 1.55);
}
