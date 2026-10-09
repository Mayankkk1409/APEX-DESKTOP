import { useId, useMemo } from "react";
import { OVERLAY_EMA, overlayLayout, type PlotLayout, type PlotSeries } from "../lib/plotChart";
import type { OhlcBar } from "../lib/ta";
import type { ChartChrome } from "../lib/tv";

/** Contiguous finite points are M then L. A non-finite gap lifts the pen. */
export function poly(xs: number[], ys: number[]) {
  let d = "";
  let open = false;
  for (let i = 0; i < xs.length; i++) {
    if (!Number.isFinite(xs[i]) || !Number.isFinite(ys[i])) {
      open = false;
      continue;
    }
    d += `${open ? "L" : "M"}${xs[i].toFixed(1)} ${ys[i].toFixed(1)} `;
    open = true;
  }
  return d.trim();
}

function inPane(layout: PlotLayout, price: number) {
  return price >= layout.minP && price <= layout.maxP;
}

function spreadLabelY<T extends { labelY: number }>(items: T[], gap: number): T[] {
  const ordered = [...items].sort((a, b) => a.labelY - b.labelY);
  for (let i = 1; i < ordered.length; i++) {
    if (ordered[i].labelY - ordered[i - 1].labelY < gap) {
      ordered[i] = { ...ordered[i], labelY: ordered[i - 1].labelY + gap };
    }
  }
  return ordered;
}

/**
 * Price-pane overlays aligned to the native Advanced Chart.
 * Native TV slots already render EMA 9, EMA 21, Bollinger, MACD pane, RSI pane, volume.
 * This layer only adds EMA 50/100/200. No SuperTrend, pivots, or S/R rays.
 */
export function ChartOverlay({
  bars,
  series,
  width,
  height,
  chrome,
}: {
  bars: OhlcBar[];
  series: PlotSeries;
  width: number;
  height: number;
  chrome: ChartChrome;
}) {
  const uid = useId();
  const clipId = `tv-pane-${uid.replace(/:/g, "")}`;
  const layout = useMemo(() => overlayLayout(bars, series, width, height, chrome), [bars, series, width, height, chrome]);
  const last = bars.length - 1;
  if (last < 0 || width < 32 || height < 32) return null;

  const xs = bars.map((_, i) => layout.x(i));
  const y = layout.y;

  const emaLines = OVERLAY_EMA.map((s) => ({ ...s, values: series[s.key] }));
  const tags = spreadLabelY(
    emaLines
      .map((s) => ({ label: s.label, color: s.color, labelY: y(s.values[last]), v: s.values[last] }))
      .filter((t) => Number.isFinite(t.labelY) && inPane(layout, t.v)),
    12,
  );

  return (
    <svg
      className="tv-study-overlay"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="none"
      data-testid="chart-overlay"
      aria-hidden
    >
      <clipPath id={clipId}>
        <rect
          x={layout.pad.l}
          y={layout.priceTop}
          width={Math.max(0, width - layout.pad.l - layout.pad.r)}
          height={Math.max(0, layout.priceBottom - layout.priceTop)}
        />
      </clipPath>

      <g clipPath={`url(#${clipId})`}>
        {emaLines.map((s) => (
          <path
            key={s.key}
            d={poly(xs, s.values.map(y))}
            fill="none"
            stroke={s.color}
            strokeWidth={s.width}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={0.94}
            data-testid={`overlay-${s.key}`}
          />
        ))}
      </g>

      {tags.map((t) => (
        <g key={t.label}>
          <rect x={width - layout.pad.r + 1} y={t.labelY - 7} width={layout.pad.r - 4} height={13} rx={1} fill={t.color} opacity={0.92} />
          <text
            x={width - 6}
            y={t.labelY + 3}
            textAnchor="end"
            fill="#131722"
            fontSize={9}
            fontFamily="IBM Plex Mono, ui-monospace, monospace"
            fontWeight={400}
          >
            {t.v.toFixed(2)}
          </text>
        </g>
      ))}
    </svg>
  );
}
