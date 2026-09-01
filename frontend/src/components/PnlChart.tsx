import { AreaSeries, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { useEffectiveTheme } from "../hooks/useEffectiveTheme";
import { pnlAreaSeriesColors, pnlChartLayoutOptions } from "../lib/chartTheme";
import { fmtBalance } from "../lib/portfolioFormat";
import { PNL_TIMEFRAMES, type PnlTimeframe } from "../lib/pnlTimeframe";

export type PnlPoint = { t: string; portfolio_value: number; balance?: number; cumulative_pl?: number };

function toUnix(iso: string): number | null {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000);
}

function pointValue(p: PnlPoint): number {
  return p.portfolio_value;
}

function toSeries(points: PnlPoint[]) {
  const out: { time: Time; value: number }[] = [];
  for (const p of points) {
    const t = toUnix(p.t);
    const value = pointValue(p);
    if (t == null || !Number.isFinite(value)) continue;
    out.push({ time: t as Time, value });
  }
  return out;
}

export function PnlChart({
  points,
  fallbackBalance = 0,
  timeframe = "MAX",
  onTimeframeChange,
  valueLabel = "Portfolio value",
}: {
  points: PnlPoint[];
  fallbackBalance?: number;
  timeframe?: PnlTimeframe;
  onTimeframeChange?: (tf: PnlTimeframe) => void;
  valueLabel?: string;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const theme = useEffectiveTheme();

  useEffect(() => {
    if (!hostRef.current) return;
    const chart = createChart(hostRef.current, {
      ...pnlChartLayoutOptions(),
      height: 280,
    });
    const areaColors = pnlAreaSeriesColors();
    const area = chart.addSeries(AreaSeries, {
      ...areaColors,
      lineWidth: 2,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chartRef.current = chart;
    areaRef.current = area;

    const ro = new ResizeObserver(() => {
      if (hostRef.current) chart.applyOptions({ width: hostRef.current.clientWidth });
    });
    ro.observe(hostRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      areaRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current || !areaRef.current) return;
    chartRef.current.applyOptions(pnlChartLayoutOptions());
    areaRef.current.applyOptions(pnlAreaSeriesColors());
  }, [theme]);

  useEffect(() => {
    if (!areaRef.current || !chartRef.current) return;
    let data = toSeries(points);
    const flat = fallbackBalance;
    if (data.length === 0) {
      const now = Math.floor(Date.now() / 1000);
      const start = now - 86_400;
      data = [
        { time: start as Time, value: flat },
        { time: now as Time, value: flat },
      ];
    } else if (data.length === 1) {
      const lone = data[0];
      const end = typeof lone.time === "number" ? lone.time : Math.floor(Date.now() / 1000);
      data = [
        { time: (end - 86_400) as Time, value: lone.value },
        lone,
      ];
    }
    areaRef.current.setData(data);
    chartRef.current.timeScale().fitContent();
  }, [points, fallbackBalance]);

  const latest = points.length ? pointValue(points[points.length - 1]) : fallbackBalance;

  return (
    <div className="rounded-xl border border-line bg-panel p-4" data-testid="pnl-chart">
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
      <div ref={hostRef} className="w-full" style={{ minHeight: 280 }} />
    </div>
  );
}
