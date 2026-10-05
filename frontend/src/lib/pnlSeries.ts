import type { Time } from "lightweight-charts";
import type { PnlPoint } from "../types";

export type EquityBar = { time: Time; value: number };

/**
 * Bars for the portfolio graph.
 *
 *   bar value = portfolio_value (cash + marked positions on that observation)
 *
 * Invalid timestamps and non-finite values are dropped. No bar is inserted for a
 * missing time. When headline equity is supplied and at least one bar exists, the
 * last bar's value is that equity and its timestamp stays the last observation.
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
    series[series.length - 1] = { time: last.time, value: headlineEquity };
  }
  return series;
}
