import { AreaSeries, LineSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import { useEffectiveTheme } from "../hooks/useEffectiveTheme";
import { pnlAreaSeriesColors, pnlChartLayoutOptions } from "../lib/chartTheme";
import { buildEquitySeries, buildProfitSeries } from "../lib/pnlSeries";
import { fmtBalance } from "../lib/portfolioFormat";
import { PNL_TIMEFRAMES, type PnlTimeframe } from "../lib/pnlTimeframe";
import type { PnlPoint } from "../types";
import { OverallPnlTotal } from "./OverallPnlTotal";

export type { PnlPoint };

const CHART_HEIGHT = 280;

export function PnlChart({
  points,
  fallbackBalance = 0,
  headlineEquity,
  timeframe = "MAX",
  onTimeframeChange,
  valueLabel = "Portfolio value",
  pending = false,
  overallTotal,
  emptyLabel = "No equity history yet.",
}: {
  points: PnlPoint[];
  fallbackBalance?: number;
  /** Displayed account equity. When history exists, the last plotted point matches it. */
  headlineEquity?: number | null;
  timeframe?: PnlTimeframe;
  onTimeframeChange?: (tf: PnlTimeframe) => void;
  valueLabel?: string;
  pending?: boolean;
  /** Account overall P&L. Omit to hide the row. `null` renders an em dash. */
  overallTotal?: number | null;
  /** Shown when this range has no points. Missing history is not drawn as zero. */
  emptyLabel?: string;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const profitRef = useRef<ISeriesApi<"Line"> | null>(null);
  const theme = useEffectiveTheme();
  const series = useMemo(() => buildEquitySeries(points, headlineEquity), [points, headlineEquity]);
  const profit = useMemo(() => buildProfitSeries(points, overallTotal), [points, overallTotal]);
  const lastProfit = profit.length === 0 ? null : profit[profit.length - 1].value;
  const profitUp = lastProfit == null || lastProfit === 0 ? null : lastProfit > 0;
  const hasHistory = series.length > 0;
  const latest = hasHistory
    ? series[series.length - 1].value
    : headlineEquity != null && Number.isFinite(headlineEquity)
      ? headlineEquity
      : fallbackBalance;

  useEffect(() => {
    if (!hasHistory || !hostRef.current) return;
    const host = hostRef.current;
    const width = host.clientWidth;
    const chart = createChart(host, {
      ...pnlChartLayoutOptions(),
      height: CHART_HEIGHT,
      ...(width > 0 ? { width } : {}),
    });
    const area = chart.addSeries(AreaSeries, {
      ...pnlAreaSeriesColors(),
      lineWidth: 2,
      title: "Portfolio Value",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    const profitLine = chart.addSeries(LineSeries, {
      priceScaleId: "left",
      color: "#7dcea0",
      lineWidth: 2,
      title: "P&L",
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chart.priceScale("right").applyOptions({ visible: true });
    chart.priceScale("left").applyOptions({ visible: true });
    chartRef.current = chart;
    areaRef.current = area;
    profitRef.current = profitLine;

    const ro = new ResizeObserver(() => {
      const width = host.clientWidth;
      if (width > 0) chart.applyOptions({ width, height: CHART_HEIGHT });
    });
    ro.observe(host);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      areaRef.current = null;
      profitRef.current = null;
    };
  }, [hasHistory]);

  useEffect(() => {
    if (!chartRef.current || !areaRef.current) return;
    chartRef.current.applyOptions(pnlChartLayoutOptions());
    areaRef.current.applyOptions(pnlAreaSeriesColors());
  }, [theme, hasHistory]);

  useEffect(() => {
    if (!areaRef.current || !chartRef.current || !hasHistory) return;
    // On a short range the two series often move by the same dollars, so a shared
    // full-height scale stacks them into one line. Max keeps both series full height.
    const split = timeframe !== "MAX";
    chartRef.current.priceScale("right").applyOptions({
      visible: true,
      scaleMargins: split ? { top: 0.06, bottom: 0.46 } : { top: 0.08, bottom: 0.08 },
    });
    chartRef.current.priceScale("left").applyOptions({
      visible: true,
      scaleMargins: split ? { top: 0.52, bottom: 0.06 } : { top: 0.08, bottom: 0.08 },
    });
    areaRef.current.setData(series);
    if (profitRef.current) {
      const last = profit.length === 0 ? null : profit[profit.length - 1].value;
      const color = last == null || last === 0 ? "#8d8d8d" : last > 0 ? "#7dcea0" : "#d46a6a";
      profitRef.current.applyOptions({ color });
      profitRef.current.setData(profit);
    }
    chartRef.current.timeScale().fitContent();
  }, [series, profit, hasHistory, timeframe]);

  return (
    <div className="rounded-xl border border-line bg-panel p-4" data-testid="pnl-chart" data-chart-engine="apex-equity" data-pnl-sign={profitUp == null ? "flat" : profitUp ? "up" : "down"}>
      <div className="mb-2 flex flex-wrap gap-4 text-xs" data-testid="pnl-chart-legend">
        <span className="text-champagne">Portfolio Value</span>
        <span className={profitUp == null ? "text-faint" : profitUp ? "num-up" : "num-down"}>P&amp;L</span>
      </div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wider text-bronze">{valueLabel}</p>
          <p className="font-mono text-2xl text-champagne" data-testid="pnl-chart-value">
            {fmtBalance(latest)}
          </p>
        </div>
        {onTimeframeChange && (
          <div className="apex-chart-tf" data-testid="pnl-chart-timeframe" role="group" aria-label="Chart timeframe">
            {PNL_TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                type="button"
                className={`apex-tf-btn ${timeframe === tf ? "is-active" : ""}`}
                aria-pressed={timeframe === tf}
                data-testid={`pnl-tf-${tf}`}
                onClick={() => onTimeframeChange(tf)}
              >
                {tf}
              </button>
            ))}
          </div>
        )}
      </div>
      {hasHistory ? (
        <div ref={hostRef} className="apex-equity-chart" data-testid="pnl-chart-canvas" />
      ) : pending ? (
        <p className="apex-equity-empty" data-testid="portfolio-chart-loading">
          Loading portfolio history…
        </p>
      ) : (
        <p className="apex-equity-empty" data-testid="pnl-chart-empty">
          {emptyLabel}
        </p>
      )}
      {overallTotal !== undefined && (
        <div className="mt-3 border-t border-line pt-3" data-testid="pnl-chart-overall-total">
          <OverallPnlTotal value={overallTotal} />
        </div>
      )}
    </div>
  );
}
