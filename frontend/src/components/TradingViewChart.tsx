import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { publishChartState, registerChartRoot } from "../chartCapture";
import { CHART_TIMEFRAMES, SNAPSHOT_STUDIES } from "../constants";
import { computeSeries, renderPlotPng, SNAPSHOT_SIZE, sliceSeries, viewportBars } from "../lib/plotChart";
import type { OhlcBar } from "../lib/ta";
import { mountAdvancedChart, tvSymbol, type ChartChrome } from "../lib/tv";
import { ChartOverlay } from "./ChartOverlay";

function uniqueBars(raw: OhlcBar[]): OhlcBar[] {
  const seen = new Set<string>();
  const out: OhlcBar[] = [];
  for (const b of raw) {
    if (!b?.t || b.c == null || seen.has(b.t)) continue;
    seen.add(b.t);
    out.push(b);
  }
  return out.sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
}

/**
 * Dashboard / scan chart: TradingView Advanced Chart free embed.
 * Five study slots: EMA 9, EMA 21, Bollinger 20/2, MACD, RSI (+ native volume).
 * EMA 50–200 are overlay-drawn on the price pane (no SuperTrend / pivots).
 * Remount key uses NASDAQ:AAPL-style mapped symbol so tickers are not stuck on SPY.
 */
function resizeEmbeddedChart(host: HTMLElement, commit: (box: { w: number; h: number }) => void) {
  const w = host.clientWidth;
  const h = host.clientHeight;
  commit({ w, h });
  const frame = host.querySelector("iframe");
  if (!(frame instanceof HTMLIFrameElement) || w < 2 || h < 2 || typeof window === "undefined") return;
  // Nudge the iframe box so the embed lays out at the post-transition size.
  // Remounting the iframe would drop the selected symbol's zoom.
  frame.style.width = `${Math.max(1, w - 1)}px`;
  frame.style.height = `${Math.max(1, h - 1)}px`;
  window.requestAnimationFrame(() => {
    frame.style.width = "100%";
    frame.style.height = "100%";
    window.dispatchEvent(new Event("resize"));
  });
}

export function TradingViewChart({
  symbol,
  timeframe,
  chrome = "desk",
  onTimeframeChange,
  bars: barsOverride,
  fullscreen = false,
  fullscreenBusy = false,
  onFullscreenToggle,
}: {
  symbol: string;
  timeframe: string;
  chrome?: ChartChrome;
  onTimeframeChange?: (tf: string) => void;
  /** When set (scan freeze), overlay math uses these captured bars; TV still remounts for symbol/tf. */
  bars?: OhlcBar[];
  fullscreen?: boolean;
  fullscreenBusy?: boolean;
  onFullscreenToggle?: () => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<HTMLDivElement>(null);
  const barsRef = useRef<OhlcBar[]>([]);
  const dailyRef = useRef<OhlcBar[]>([]);
  const viewRef = useRef<{ bars: OhlcBar[]; from: string; to: string } | null>(null);
  const mapped = useMemo(() => tvSymbol(symbol), [symbol]);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const overrideBars = useMemo(() => (barsOverride ? uniqueBars(barsOverride) : null), [barsOverride]);

  const barsQ = useQuery({
    queryKey: ["bars", symbol, timeframe],
    queryFn: () => api.bars(symbol, timeframe, 600),
    refetchInterval: chrome === "desk" ? 20_000 : false,
    enabled: !overrideBars,
  });

  const dailyQ = useQuery({
    queryKey: ["bars", symbol, "1D", "pivot-source"],
    queryFn: () => api.bars(symbol, "1D", 600),
    staleTime: 60_000,
  });

  const bars = useMemo(
    () => overrideBars ?? uniqueBars((barsQ.data?.bars ?? []) as OhlcBar[]),
    [overrideBars, barsQ.data],
  );
  const dailyBars = useMemo(() => uniqueBars((dailyQ.data?.bars ?? []) as OhlcBar[]), [dailyQ.data]);
  const series = useMemo(
    () => (bars.length ? computeSeries(bars, { dailyBars, timeframe }) : null),
    [bars, dailyBars, timeframe],
  );
  const view = useMemo(() => {
    if (!bars.length || !series || box.w < 32) return null;
    const vp = viewportBars(bars, box.w, chrome);
    return {
      bars: vp.bars,
      series: sliceSeries(series, vp.start),
      start: vp.start,
      from: vp.bars[0]?.t ?? "",
      to: vp.bars[vp.bars.length - 1]?.t ?? "",
    };
  }, [bars, series, box.w, chrome]);

  barsRef.current = bars;
  dailyRef.current = dailyBars;
  viewRef.current = view ? { bars: view.bars, from: view.from, to: view.to } : null;

  useEffect(() => {
    if (chrome !== "desk") return;
    const host = hostRef.current;
    // Freeze the visible window the trader is looking at — not the full loaded series.
    // Cross-origin TV iframe cannot be screenshotted; same-origin plot mirrors the studies.
    registerChartRoot(host, () => {
      const v = viewRef.current;
      if (!host || !v?.bars.length) return null;
      // Dedicated clean snapshot canvas — CSS size must match overlay layout (not canvas×dpr).
      const w = SNAPSHOT_SIZE.w;
      const h = SNAPSHOT_SIZE.h;
      return renderPlotPng(v.bars, w, h, Math.min(2, window.devicePixelRatio || 1), {
        dailyBars: dailyRef.current,
        contextBars: barsRef.current,
        timeframe,
        mode: "snapshot",
        title: `${symbol} · ${timeframe} · captured window`,
      });
    });
    return () => registerChartRoot(null);
  }, [chrome, symbol, timeframe]);

  useEffect(() => {
    const mount = widgetRef.current;
    if (!mount) return;
    mountAdvancedChart(mount, symbol, timeframe, chrome);
    return () => {
      mount.innerHTML = "";
    };
  }, [symbol, timeframe, chrome, mapped]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const measure = () => setBox({ w: host.clientWidth, h: host.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(host);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || chrome !== "desk") return;
    const desk = host.closest(".desk");
    if (!desk) return;
    const onEnd = (event: Event) => {
      const e = event as TransitionEvent;
      const target = e.target instanceof HTMLElement ? e.target : null;
      if (!target) return;
      const slot = host.closest(".desk-chart-slot");
      const motionDone = target.hasAttribute("data-desk-motion") && e.propertyName === "opacity";
      const sizeDone = slot != null && target === slot && (e.propertyName === "height" || e.propertyName === "min-height");
      if (!motionDone && !sizeDone) return;
      resizeEmbeddedChart(host, setBox);
    };
    desk.addEventListener("transitionend", onEnd);
    return () => desk.removeEventListener("transitionend", onEnd);
  }, [chrome]);

  useEffect(() => {
    if (chrome !== "desk") return;
    const host = hostRef.current;
    if (!host || !view || !bars.length) return;
    // Publish the locked visible slice only — allBars stays available for warm-up.
    publishChartState({
      symbol,
      timeframe,
      visibleBars: view.bars,
      allBars: bars,
      dailyBars,
      from: view.from,
      to: view.to,
      studies: [...SNAPSHOT_STUDIES],
      width: host.clientWidth,
      height: host.clientHeight,
      layoutW: SNAPSHOT_SIZE.w,
      layoutH: SNAPSHOT_SIZE.h,
    });
  }, [bars, dailyBars, view, chrome, symbol, timeframe]);

  return (
    <div className={`apex-chart h-full ${chrome === "frozen" ? "apex-chart--frozen" : ""}`}>
      {chrome === "desk" && onFullscreenToggle && (
        <button
          type="button"
          className="apex-chart-fullscreen"
          data-testid="chart-fullscreen"
          aria-label={fullscreen ? "Exit chart fullscreen" : "Enter chart fullscreen"}
          aria-pressed={fullscreen}
          onClick={() => {
            if (fullscreenBusy) return;
            onFullscreenToggle();
          }}
        >
          {fullscreen ? (
            <span aria-hidden="true">×</span>
          ) : (
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path
                d="M3 6V3h3M10 3h3v3M13 10v3h-3M6 13H3v-3"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          )}
        </button>
      )}
      {chrome === "desk" && (
        <div className="apex-chart-toolbar">
          <span className="apex-chart-symbol" data-testid="chart-symbol">
            {symbol}
          </span>
          <div className="apex-chart-tf" data-testid="chart-timeframe" role="group" aria-label="Chart timeframe">
            {CHART_TIMEFRAMES.map((tf) => (
              <button
                key={tf.code}
                type="button"
                className={`apex-tf-btn ${timeframe === tf.code ? "is-active" : ""}`}
                aria-pressed={timeframe === tf.code}
                aria-label={tf.label}
                onClick={() => onTimeframeChange?.(tf.code)}
              >
                {tf.short}
              </button>
            ))}
          </div>
        </div>
      )}
      <div
        ref={hostRef}
        className={`apex-chart-body tv-host relative min-h-0 flex-1 overflow-hidden rounded-xl border border-line bg-chart-panel ${chrome === "frozen" ? "tv-host--frozen" : ""}`}
        data-testid="chart"
        data-chart-engine="tradingview"
        data-tv-symbol={mapped}
        data-loaded-symbol={view && bars.length ? symbol : ""}
        data-bar-count={bars.length}
        data-visible-bars={view?.bars.length ?? 0}
      >
        <div
          key={`${mapped}:${timeframe}:${chrome}`}
          ref={widgetRef}
          className="tradingview-widget-container absolute inset-0 z-[1] h-full w-full"
          data-testid="tv-embed"
        />
        {view && box.w > 32 && box.h > 32 && (
          <ChartOverlay bars={view.bars} series={view.series} width={box.w} height={box.h} chrome={chrome} />
        )}
        <div className="tv-logo-cover" aria-hidden />
        {barsQ.isLoading && !bars.length && (
          <p className="pointer-events-none absolute inset-0 z-[4] flex items-center justify-center text-sm text-faint">Loading chart…</p>
        )}
      </div>
    </div>
  );
}

/** Compatibility alias — dashboard historically imported ApexChart. */
export function ApexChart(props: {
  symbol: string;
  timeframe: string;
  chrome?: ChartChrome;
  onTimeframeChange?: (tf: string) => void;
  bars?: OhlcBar[];
  fullscreen?: boolean;
  fullscreenBusy?: boolean;
  onFullscreenToggle?: () => void;
}) {
  return <TradingViewChart {...props} />;
}
