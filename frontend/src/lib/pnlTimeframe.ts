import type { PnlPoint } from "../types";

export const PNL_TIMEFRAMES = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "MAX"] as const;
export type PnlTimeframe = (typeof PNL_TIMEFRAMES)[number];

export function timeframeStart(timeframe: PnlTimeframe, now = new Date()): Date | null {
  if (timeframe === "MAX") return null;
  const start = new Date(now);
  switch (timeframe) {
    case "1D":
      start.setUTCDate(start.getUTCDate() - 1);
      return start;
    case "1W":
      start.setUTCDate(start.getUTCDate() - 7);
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

/** How long after the last real point a short range may still show that point. */
const RECENT_GAP_MS: Partial<Record<PnlTimeframe, number>> = {
  "1D": 4 * 24 * 60 * 60 * 1000,
};

export function filterPnlPoints(points: PnlPoint[], timeframe: PnlTimeframe, now = new Date()): PnlPoint[] {
  const start = timeframeStart(timeframe, now);
  if (!start || points.length === 0) return points;
  const startMs = start.getTime();
  const ordered = [...points].sort((a, b) => Date.parse(a.t) - Date.parse(b.t));
  const inWindow: PnlPoint[] = [];
  for (const point of ordered) {
    const ms = Date.parse(point.t);
    if (!Number.isFinite(ms) || ms < startMs) continue;
    inWindow.push(point);
  }
  if (inWindow.length >= 2) return inWindow;

  const latest = ordered[ordered.length - 1];
  const latestMs = Date.parse(latest?.t ?? "");
  const grace = RECENT_GAP_MS[timeframe];
  // A weekend 1D window can fall after the last session close. Keep that close
  // and the one before it so both lines still have a segment. A distant gap stays empty.
  if (
    inWindow.length === 0 &&
    grace != null &&
    Number.isFinite(latestMs) &&
    latestMs < startMs &&
    startMs - latestMs <= grace
  ) {
    return ordered.slice(-2);
  }

  if (inWindow.length === 1) {
    const index = ordered.indexOf(inWindow[0]);
    const previous = index > 0 ? ordered[index - 1] : undefined;
    const previousMs = previous ? Date.parse(previous.t) : Number.NaN;
    const windowMs = Math.max(now.getTime() - startMs, 0);
    if (previous && Number.isFinite(previousMs) && startMs - previousMs <= windowMs) {
      return [previous, inWindow[0]];
    }
  }
  return inWindow;
}
