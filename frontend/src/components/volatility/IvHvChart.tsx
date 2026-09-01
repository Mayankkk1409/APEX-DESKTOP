import { createChart, LineSeries, type IChartApi, type IPriceLine, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

export type HvPoint = { t: string; hv: number | null };
export type IvPoint = { t: string; iv: number | null };

const WINDOW_ORDER = ["7D", "14D", "30D", "60D", "90D", "6M", "1Y"] as const;

const HV_COLORS: Record<string, string> = {
  "7D": "#6fd3c7",
  "14D": "#5dade2",
  "30D": "#e0b568",
  "60D": "#c4a56a",
  "90D": "#ab47bc",
  "6M": "#ef8a87",
  "1Y": "#8fd4b0",
};

function toUnix(iso: string): number | null {
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  return Math.floor(ms / 1000);
}

function toLineData(points: HvPoint[]) {
  const out: { time: Time; value: number }[] = [];
  for (const p of points) {
    if (p.hv == null || !Number.isFinite(p.hv)) continue;
    const t = toUnix(p.t);
    if (t == null) continue;
    out.push({ time: t as Time, value: p.hv * 100 });
  }
  return out;
}

function toIvLineData(points: IvPoint[]) {
  const byTime = new Map<number, number>();
  for (const p of points) {
    if (p.iv == null || !Number.isFinite(p.iv)) continue;
    const t = toUnix(p.t);
    if (t == null) continue;
    byTime.set(t, p.iv * 100);
  }
  return [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as Time, value }));
}

export function IvHvChart({
  hvSeries,
  windowsAvailable,
  currentIv,
  ivSeries,
  contractLabel,
}: {
  hvSeries: Record<string, HvPoint[]>;
  windowsAvailable: string[];
  currentIv: number | null;
  ivSeries?: IvPoint[];
  contractLabel?: string;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<Map<string, ISeriesApi<"Line">>>(new Map());
  const ivLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const priceLineRef = useRef<{ series: ISeriesApi<"Line">; line: IPriceLine } | null>(null);
  const [active, setActive] = useState<string[]>([]);
  const [hover, setHover] = useState<string>("");
  const [ivLineActive, setIvLineActive] = useState(false);

  const ivLegend = contractLabel ?? "Contract IV";
  const ivPts = useMemo(() => toIvLineData(ivSeries ?? []), [ivSeries]);

  const available = useMemo(
    () => WINDOW_ORDER.filter((w) => windowsAvailable.includes(w) && (hvSeries[w]?.length ?? 0) > 0),
    [windowsAvailable, hvSeries],
  );

  useEffect(() => {
    setActive((prev) => {
      const avail = available as readonly string[];
      const kept = prev.filter((w) => avail.includes(w));
      if (kept.length) return kept;
      if (avail.includes("30D")) return ["30D"];
      return available.slice(0, 1);
    });
  }, [available]);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const chart = createChart(el, {
      layout: {
        background: { color: "#0b0d12" },
        textColor: "rgba(206,191,156,0.75)",
        fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(240,243,250,0.05)" },
        horzLines: { color: "rgba(240,243,250,0.05)" },
      },
      rightPriceScale: {
        borderColor: "rgba(240,243,250,0.1)",
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "rgba(240,243,250,0.1)",
        timeVisible: false,
      },
      crosshair: {
        vertLine: { color: "rgba(224,181,104,0.35)", labelBackgroundColor: "#2a2110" },
        horzLine: { color: "rgba(224,181,104,0.35)", labelBackgroundColor: "#2a2110" },
      },
      width: el.clientWidth,
      height: 320,
    });
    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (!hostRef.current || !chartRef.current) return;
      chartRef.current.applyOptions({ width: hostRef.current.clientWidth });
    });
    ro.observe(el);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.seriesData.size) {
        setHover("");
        return;
      }
      const bits: string[] = [];
      param.seriesData.forEach((data, series) => {
        const name = (series as ISeriesApi<"Line">).options().title || "";
        const val = (data as { value?: number }).value;
        if (val != null && name) bits.push(`${name} ${val.toFixed(1)}%`);
      });
      setHover(bits.join(" · "));
    });

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current.clear();
      ivLineRef.current = null;
      priceLineRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (priceLineRef.current) {
      priceLineRef.current.series.removePriceLine(priceLineRef.current.line);
      priceLineRef.current = null;
    }
    if (ivLineRef.current) {
      chart.removeSeries(ivLineRef.current);
      ivLineRef.current = null;
    }
    for (const series of seriesRef.current.values()) {
      chart.removeSeries(series);
    }
    seriesRef.current.clear();

    for (const win of active) {
      const pts = toLineData(hvSeries[win] ?? []);
      if (!pts.length) continue;
      const series = chart.addSeries(LineSeries, {
        color: HV_COLORS[win] ?? "#cebf9c",
        lineWidth: 2,
        title: `HV ${win}`,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      series.setData(pts);
      seriesRef.current.set(win, series);
    }

    const ivPtsLocal = ivPts;

    if (ivPtsLocal.length >= 2) {
      const ivApi = chart.addSeries(LineSeries, {
        color: "#f2f4f8",
        lineWidth: 2,
        lineStyle: 2,
        title: ivLegend,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      ivApi.setData(ivPtsLocal);
      ivLineRef.current = ivApi;
      setIvLineActive(true);
    } else if (currentIv != null) {
      setIvLineActive(false);
      const first = seriesRef.current.values().next().value as ISeriesApi<"Line"> | undefined;
      if (first) {
        const line = first.createPriceLine({
          price: currentIv * 100,
          color: "rgba(242,244,248,0.85)",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: ivLegend,
        });
        priceLineRef.current = { series: first, line };
      }
    } else {
      setIvLineActive(false);
    }

    chart.timeScale().fitContent();
  }, [active, hvSeries, currentIv, ivPts, ivLegend]);

  function toggle(win: string) {
    setActive((prev) => {
      if (prev.includes(win)) {
        if (prev.length === 1) return prev;
        return prev.filter((w) => w !== win);
      }
      return [...prev, win];
    });
  }

  return (
    <div
      className="vol-chart"
      data-testid="iv-hv-chart"
      data-iv-line={ivLineActive ? "series" : currentIv != null ? "reference" : "none"}
      data-iv-points={ivPts.length}
    >
      <div className="vol-chart-toolbar">
        <span className="vol-chart-label">IV vs HV</span>
        <div className="vol-chart-tfs" role="group" aria-label="HV lookback windows">
          {WINDOW_ORDER.map((win) => {
            const on = available.includes(win);
            const selected = active.includes(win);
            return (
              <button
                key={win}
                type="button"
                disabled={!on}
                className={`vol-tf-btn ${selected ? "is-active" : ""}`}
                style={selected ? { ["--vol-tf" as string]: HV_COLORS[win] } : undefined}
                onClick={() => on && toggle(win)}
                title={on ? `Toggle HV ${win}` : `${win} needs more daily closes`}
              >
                {win}
              </button>
            );
          })}
        </div>
        <span className="vol-chart-legend">
          {ivLineActive
            ? `${ivLegend} series (${ivPts.length} pts)`
            : currentIv != null
              ? `${ivLegend} ${(currentIv * 100).toFixed(1)}%`
              : `${ivLegend} unavailable`}
          {hover ? ` · ${hover}` : ""}
        </span>
      </div>
      <div ref={hostRef} className="vol-chart-body" />
      {!available.length && (
        <p className="vol-chart-empty">Not enough daily closes to plot historical volatility yet.</p>
      )}
    </div>
  );
}
