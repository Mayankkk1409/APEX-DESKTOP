export interface DailyPnlDay {
  date: string;
  pnl: number | null;
  status: "marked" | "unavailable";
}

export interface PositionDailyPnl {
  id: string;
  symbol: string;
  days: DailyPnlDay[];
}

export interface DailyPnlResponse {
  positions: PositionDailyPnl[];
  book: DailyPnlDay[];
}

/** A day's P&L when the API sent a finite mark. Missing marks stay null. */
export function markedPnl(day: DailyPnlDay | undefined): number | null {
  if (!day || day.status === "unavailable") return null;
  if (day.pnl == null || !Number.isFinite(day.pnl)) return null;
  return day.pnl;
}

export function daysForPosition(payload: DailyPnlResponse | undefined, id: string): DailyPnlDay[] | undefined {
  if (!payload) return undefined;
  return payload.positions.find((row) => row.id === id)?.days ?? [];
}

/**
 * Latest marked session when the series has one.
 * When that session has no price, keep the position unrealized P&L the portfolio already returned.
 */
export function dayPlOrUnrealized(
  days: DailyPnlDay[] | undefined,
  unrealized: number | null | undefined,
): number | null {
  if (days === undefined) return null;
  if (days.length > 0) {
    const marked = markedPnl(days[days.length - 1]);
    if (marked != null) return marked;
  }
  if (unrealized != null && Number.isFinite(unrealized)) return unrealized;
  return null;
}
