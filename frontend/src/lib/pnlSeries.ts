import type { Time } from "lightweight-charts";
import type { PnlPoint } from "../types";

export type EquityBar = { time: Time; value: number };

/** Same greens and reds the portfolio chart already uses for up and down P&L. */
export const PNL_LINE_UP = "#7dcea0";
export const PNL_LINE_DOWN = "#d46a6a";

export type ProfitBar = EquityBar & { color: string };

/**
 * Bars for the portfolio graph.
 *
 *   bar value = portfolio_value (cash + marked positions on that observation)
 *
 * Invalid timestamps and non-finite values are dropped. No bar is inserted for a
 * missing time. A headline close to the last observation updates that bar.
 * A current account value on a different scale is its own later point.
 */
export function buildEquitySeries(points: PnlPoint[], headlineEquity?: number | null): EquityBar[] {
  const byTime = new Map<number, number>();
  for (const point of points) {
    const ms = Date.parse(point.t);
    const value = point.portfolio_value;
    if (!Number.isFinite(ms) || !Number.isFinite(value)) continue;
    byTime.set(Math.floor(ms / 1000), value);
  }
  const series: EquityBar[] = [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as Time, value }));
  if (series.length > 0 && headlineEquity != null && Number.isFinite(headlineEquity)) {
    const last = series[series.length - 1];
    const scale = Math.max(Math.abs(last.value), Math.abs(headlineEquity), 1);
    if (Math.abs(headlineEquity - last.value) / scale <= 0.25) {
      series[series.length - 1] = { time: last.time, value: headlineEquity };
    } else {
      const now = Math.floor(Date.now() / 1000);
      const lastTime = Number(last.time);
      series.push({ time: (now > lastTime ? now : lastTime + 1) as Time, value: headlineEquity });
    }
  }
  return series;
}

export function buildProfitSeries(
  points: PnlPoint[],
  overallTotal?: number | null,
): EquityBar[] {
  const byTime = new Map<number, number>();
  for (const point of points) {
    const ms = Date.parse(point.t);
    const value = point.cumulative_pl;
    if (!Number.isFinite(ms) || value == null || !Number.isFinite(value)) continue;
    byTime.set(Math.floor(ms / 1000), value);
  }
  const series = [...byTime.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time: time as Time, value }));
  if (series.length > 0 && overallTotal != null && Number.isFinite(overallTotal)) {
    const last = series[series.length - 1];
    series[series.length - 1] = { time: last.time, value: overallTotal };
  }
  return series;
}

/**
 * Color each P&L point green at or above zero and red below it.
 * A zero point is inserted on a crossing so the line changes color at zero,
 * not at the next observation. The inserted point takes the color of the side
 * being entered, because the chart paints each segment with the color of its start.
 */
export function colorProfitLine(series: EquityBar[]): ProfitBar[] {
  const out: ProfitBar[] = [];
  for (let i = 0; i < series.length; i++) {
    const cur = series[i];
    const prev = i > 0 ? series[i - 1] : null;
    if (prev && prev.value !== 0 && cur.value !== 0 && prev.value > 0 !== cur.value > 0) {
      const t0 = Number(prev.time);
      const t1 = Number(cur.time);
      const span = cur.value - prev.value;
      if (Number.isFinite(t0) && Number.isFinite(t1) && t1 > t0 && span !== 0) {
        let crossTime = Math.round(t0 + (t1 - t0) * ((0 - prev.value) / span));
        if (crossTime <= t0) crossTime = t0 + 1;
        if (crossTime >= t1) crossTime = t1 - 1;
        if (crossTime > t0 && crossTime < t1) {
          out.push({
            time: crossTime as Time,
            value: 0,
            color: cur.value < 0 ? PNL_LINE_DOWN : PNL_LINE_UP,
          });
        }
      }
    }
    const next = series[i + 1];
    const color =
      cur.value < 0 || (cur.value === 0 && next != null && next.value < 0) ? PNL_LINE_DOWN : PNL_LINE_UP;
    out.push({ time: cur.time, value: cur.value, color });
  }
  return out;
}
