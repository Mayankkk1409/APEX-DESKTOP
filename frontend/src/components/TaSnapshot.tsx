import { useEffect, useMemo, useRef, useState } from "react";
import { describeWindow } from "../chartCapture";
import { ChartSnapshotOverlay } from "./ChartSnapshotOverlay";
import { buildAnalysisCards } from "../lib/analysisCards";
import { resolveChartHighlight } from "../lib/chartHighlight";
import { computeSeries, layoutPlot, renderPlotPng, SNAPSHOT_SIZE } from "../lib/plotChart";
import type { OhlcBar } from "../lib/ta";

/**
 * Deep Scan technical layer — a clean frozen chart snapshot of the captured
 * OHLC window (candles + EMA/BB + MACD + RSI). Prefer the PNG captured on
 * the desk; otherwise rebuild from bars. Never mounts TradingView chrome.
 */
export function TaSnapshot({
  symbol,
  timeframe,
  bars,
  contextBars,
  dailyBars,
  from,
  to,
  chartImage,
}: {
  symbol: string;
  timeframe: string;
  bars: OhlcBar[];
  contextBars?: OhlcBar[];
  dailyBars?: OhlcBar[];
  from?: string;
  to?: string;
  chartImage?: string | null;
}) {
  const { cards, catalysts, series } = useMemo(
    () => buildAnalysisCards(symbol, timeframe, bars, { contextBars, dailyBars }),
    [symbol, timeframe, bars, contextBars, dailyBars],
  );
  const [idx, setIdx] = useState(0);
  const frameRef = useRef<HTMLDivElement>(null);
  const [fallbackPng, setFallbackPng] = useState<string | null>(null);
  // Overlay layout MUST use the same CSS size the PNG was drawn with (SNAPSHOT_SIZE),
  // never img.naturalWidth (that is canvas×dpr and shifts every mark).
  const [plotSize, setPlotSize] = useState({ w: SNAPSHOT_SIZE.w, h: SNAPSHOT_SIZE.h });

  const frozenSrc = chartImage || fallbackPng;

  useEffect(() => {
    setIdx(0);
  }, [symbol, timeframe, bars]);

  // Rebuild a full-width professional snapshot if Scan missed the desk bitmap.
  useEffect(() => {
    if (chartImage || !bars.length) {
      setFallbackPng(null);
      setPlotSize({ w: SNAPSHOT_SIZE.w, h: SNAPSHOT_SIZE.h });
      return;
    }
    const el = frameRef.current;
    const w = Math.max(SNAPSHOT_SIZE.w, el?.clientWidth || SNAPSHOT_SIZE.w);
    const h = SNAPSHOT_SIZE.h;
    setPlotSize({ w, h });
    setFallbackPng(
      renderPlotPng(bars, w, h, Math.min(2, window.devicePixelRatio || 1), {
        dailyBars,
        contextBars,
        timeframe,
        mode: "snapshot",
        title: `${symbol} · ${timeframe} · captured window`,
      }),
    );
  }, [chartImage, bars, contextBars, dailyBars, timeframe, symbol]);

  const highlight = useMemo(() => {
    if (!bars.length) return null;
    const layout = layoutPlot(bars, series, plotSize.w, plotSize.h, "snapshot");
    return resolveChartHighlight(cards[idx], bars, series, layout, catalysts);
  }, [bars, cards, catalysts, idx, plotSize.h, plotSize.w, series]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setIdx((i) => Math.min(i + 1, Math.max(cards.length - 1, 0)));
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setIdx((i) => Math.max(i - 1, 0));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cards.length]);

  const active = cards[idx];

  function go(delta: number) {
    setIdx((i) => Math.min(cards.length - 1, Math.max(0, i + delta)));
  }

  return (
    <div className="ta-stage" data-testid="ta-stage">
      <p className="mb-2 font-mono text-[11px] text-bronze" data-testid="captured-window" data-bar-count={bars.length} data-from={from ?? ""} data-to={to ?? ""}>
        {symbol} · {timeframe} · {describeWindow(bars, from ?? "", to ?? "")}
      </p>
      <div className="ta-snapshot-frame" data-testid="chart-snapshot" ref={frameRef}>
        {frozenSrc ? (
          <div className="ta-snapshot-media">
            <img
              src={frozenSrc}
              alt={`${symbol} ${timeframe} frozen chart snapshot`}
              className="ta-snapshot-img"
              data-testid="chart"
              data-chart-engine="snapshot"
              data-tv-symbol={symbol}
              data-bar-count={bars.length}
              data-frozen="true"
              data-layout-w={plotSize.w}
              data-layout-h={plotSize.h}
              draggable={false}
            />
            <ChartSnapshotOverlay key={`${idx}-${highlight?.id ?? "none"}`} highlight={highlight} width={plotSize.w} height={plotSize.h} />
          </div>
        ) : (
          <div
            className="ta-snapshot-empty"
            data-testid="chart"
            data-chart-engine="snapshot"
            data-tv-symbol={symbol}
            data-bar-count={bars.length}
            data-frozen="true"
          >
            {bars.length ? "Rendering frozen snapshot…" : "No bars were captured for this scan."}
          </div>
        )}
      </div>

      <div
        className="ta-carousel"
        data-testid="ta-carousel"
        data-card-count={cards.length}
        onWheel={(e) => {
          if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && Math.abs(e.deltaX) > 24) {
            e.preventDefault();
            go(e.deltaX > 0 ? 1 : -1);
          }
        }}
        onTouchStart={(e) => {
          (e.currentTarget as HTMLDivElement).dataset.x = String(e.touches[0].clientX);
        }}
        onTouchEnd={(e) => {
          const start = Number((e.currentTarget as HTMLDivElement).dataset.x ?? 0);
          const dx = e.changedTouches[0].clientX - start;
          if (dx < -40) go(1);
          if (dx > 40) go(-1);
        }}
      >
        <button type="button" aria-label="Previous analysis" data-testid="ta-prev" className="ta-arrow" onClick={() => go(-1)}>
          ‹
        </button>
        <article className="ta-card" data-testid="ta-card" data-bias={active?.bias ?? "neutral"}>
          <p className="ta-card-kicker">
            {active?.kind === "catalyst" ? "Catalyst" : "Study"} · {idx + 1} of {cards.length}
          </p>
          <h2 className="ta-card-title">{active?.name ?? "Analysis"}</h2>
          <p className="ta-card-body">{active?.body ?? "Loading captured series…"}</p>
        </article>
        <button type="button" aria-label="Next analysis" data-testid="ta-next" className="ta-arrow" onClick={() => go(1)}>
          ›
        </button>
      </div>
    </div>
  );
}
