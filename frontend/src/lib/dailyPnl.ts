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
