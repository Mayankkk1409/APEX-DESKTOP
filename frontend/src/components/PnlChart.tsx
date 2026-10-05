import { AreaSeries, createChart, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";
import { useEffectiveTheme } from "../hooks/useEffectiveTheme";
import { pnlAreaSeriesColors, pnlChartLayoutOptions } from "../lib/chartTheme";
import { buildEquitySeries } from "../lib/pnlSeries";
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
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const theme = useEffectiveTheme();
  const series = useMemo(() => buildEquitySeries(points, headlineEquity), [points, headlineEquity]);
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
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chartRef.current = chart;
    areaRef.current = area;

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
    };
  }, [hasHistory]);

  useEffect(() => {
    if (!chartRef.current || !areaRef.current) return;
    chartRef.current.applyOptions(pnlChartLayoutOptions());
    areaRef.current.applyOptions(pnlAreaSeriesColors());
  }, [theme, hasHistory]);

  useEffect(() => {
    if (!areaRef.current || !chartRef.current || !hasHistory) return;
    areaRef.current.setData(series);
    chartRef.current.timeScale().fitContent();
  }, [series, hasHistory]);

  return (
    <div className="rounded-xl border border-line bg-panel p-4" data-testid="pnl-chart" data-chart-engine="apex-equity">
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
          No equity history yet.
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
