import type { PnlPoint } from "../types";

export const PNL_TIMEFRAMES = ["1D", "1M", "3M", "6M", "YTD", "1Y", "MAX"] as const;
export type PnlTimeframe = (typeof PNL_TIMEFRAMES)[number];

export function timeframeStart(timeframe: PnlTimeframe, now = new Date()): Date | null {
  if (timeframe === "MAX") return null;
  const start = new Date(now);
  switch (timeframe) {
    case "1D":
      start.setUTCDate(start.getUTCDate() - 1);
      return start;
    case "1M":
      start.setUTCMonth(start.getUTCMonth() - 1);
      return start;
    case "3M":
      start.setUTCMonth(start.getUTCMonth() - 3);
      return start;
    case "6M":
      start.setUTCMonth(start.getUTCMonth() - 6);
      return start;
    case "YTD":
      return new Date(Date.UTC(now.getUTCFullYear(), 0, 1));
    case "1Y":
      start.setUTCFullYear(start.getUTCFullYear() - 1);
      return start;
    default:
      return null;
  }
}

export function filterPnlPoints(points: PnlPoint[], timeframe: PnlTimeframe, now = new Date()): PnlPoint[] {
  const start = timeframeStart(timeframe, now);
  if (!start || points.length === 0) return points;
  const startMs = start.getTime();
  const filtered = points.filter((p) => {
    const ms = Date.parse(p.t);
    return Number.isFinite(ms) && ms >= startMs;
  });
  if (filtered.length >= 2) return filtered;
  if (points.length === 0) return filtered;
  const anchor = points.reduce((best, p) => {
    const ms = Date.parse(p.t);
    if (!Number.isFinite(ms) || ms > startMs) return best;
    return !best || ms > Date.parse(best.t) ? p : best;
  }, null as PnlPoint | null);
  const tail = points.filter((p) => Date.parse(p.t) >= startMs);
  const merged = anchor ? [anchor, ...tail] : tail;
  return merged.length >= 2 ? merged : points.length >= 2 ? [points[0], points[points.length - 1]] : points;
}
