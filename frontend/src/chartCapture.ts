/**
 * Live chart state shared between the dashboard chart and Deep Scan.
 *
 * The chart publishes exactly what the user is looking at — symbol, interval,
 * the bars inside the visible logical range, and the active study set. Scan
 * reads that snapshot so every analysis number is reproducible from the same
 * bars the user had on screen when they clicked.
 */

import type { OhlcBar } from "./lib/ta";
import { SNAPSHOT_SIZE } from "./lib/plotChart";

export type ChartState = {
  symbol: string;
  timeframe: string;
  /** Bars inside the visible range at capture time — the analysis input. */
  visibleBars: OhlcBar[];
  /** Full loaded series, needed for warm-up of long studies such as EMA 200. */
  allBars: OhlcBar[];
  /** Daily series backing "Use daily-based values" pivots. */
  dailyBars: OhlcBar[];
  from: string;
  to: string;
  studies: string[];
  width: number;
  height: number;
  /** CSS pixel size used when rendering the frozen PNG (overlay layout must match). */
  layoutW: number;
  layoutH: number;
  png: string | null;
  capturedAt: string;
};

export const EMPTY_CHART_STATE: ChartState = {
  symbol: "",
  timeframe: "",
  visibleBars: [],
  allBars: [],
  dailyBars: [],
  from: "",
  to: "",
  studies: [],
  width: 0,
  height: 0,
  layoutW: SNAPSHOT_SIZE.w,
  layoutH: SNAPSHOT_SIZE.h,
  png: null,
  capturedAt: "",
};

let chartRoot: HTMLElement | null = null;
let screenshot: (() => string | null) | null = null;
let state: ChartState = EMPTY_CHART_STATE;
const listeners = new Set<() => void>();

function emitChartState() {
  for (const listener of listeners) listener();
}

export function subscribeChartState(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function registerChartRoot(el: HTMLElement | null, takeScreenshot?: () => string | null) {
  chartRoot = el;
  screenshot = el ? takeScreenshot ?? null : null;
}

export function getChartRoot() {
  return chartRoot;
}

export function publishChartState(next: Omit<ChartState, "png" | "capturedAt">) {
  // Always publish the locked visible window — never widen to the full series.
  const visibleBars = next.visibleBars;
  const from = visibleBars[0]?.t ?? next.from ?? "";
  const to = visibleBars[visibleBars.length - 1]?.t ?? next.to ?? "";
  state = {
    ...next,
    visibleBars,
    from,
    to,
    layoutW: next.layoutW || SNAPSHOT_SIZE.w,
    layoutH: next.layoutH || SNAPSHOT_SIZE.h,
    png: null,
    capturedAt: "",
  };
  emitChartState();
}

export function getChartState(): ChartState {
  return state;
}

export function resetChartState() {
  state = EMPTY_CHART_STATE;
  chartRoot = null;
  screenshot = null;
  emitChartState();
}

/**
 * Freeze the chart at Scan click. The bitmap comes from the chart's own canvas,
 * so there is no cross-origin iframe hole and no html2canvas guesswork.
 * Re-locks visibleBars to [from, to] against allBars when possible so the
 * snapshot never silently expands to the full loaded series.
 */
export function captureChartState(): ChartState {
  let png: string | null = null;
  try {
    png = screenshot?.() ?? null;
  } catch {
    png = null;
  }

  let visibleBars = state.visibleBars;
  if (state.from && state.to && state.allBars.length) {
    const locked = barsInRange(state.allBars, state.from, state.to);
    // Prefer the locked window when it is a real sub-range (or equal to published).
    if (locked.length > 0 && locked.length <= state.allBars.length) {
      visibleBars = locked;
    }
  }
  // Hard guard: never ship the full loaded series as the "visible" window when a
  // shorter published window already exists.
  if (
    state.visibleBars.length > 0 &&
    state.visibleBars.length < state.allBars.length &&
    visibleBars.length >= state.allBars.length
  ) {
    visibleBars = state.visibleBars;
  }

  const from = visibleBars[0]?.t ?? state.from;
  const to = visibleBars[visibleBars.length - 1]?.t ?? state.to;
  const captured: ChartState = {
    ...state,
    visibleBars,
    from,
    to,
    layoutW: state.layoutW || SNAPSHOT_SIZE.w,
    layoutH: state.layoutH || SNAPSHOT_SIZE.h,
    png,
    capturedAt: new Date().toISOString(),
  };
  state = captured;
  emitChartState();
  return captured;
}

/**
 * Bars whose timestamp falls inside `[from, to]`.
 * Invalid / empty range returns [] — never the full series — so callers cannot
 * accidentally analyse the entire load as a "visible window".
 */
export function barsInRange(bars: OhlcBar[], from: string, to: string): OhlcBar[] {
  if (!from || !to) return [];
  const a = Date.parse(from);
  const b = Date.parse(to);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return [];
  return bars.filter((x) => {
    const t = Date.parse(x.t);
    return Number.isFinite(t) && t >= a && t <= b;
  });
}

/** Human-readable description of the captured window shown on the scan header. */
export function describeWindow(bars: OhlcBar[], from: string, to: string): string {
  if (!bars.length) return "no bars captured";
  const day = (iso: string) => (iso ? iso.slice(0, 10) : "—");
  return `${bars.length} bars · ${day(from || bars[0].t)} → ${day(to || bars[bars.length - 1].t)}`;
}
