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

/** Short session label such as Oct 6. Date-only strings stay on that calendar day. */
export function formatSessionDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return iso;
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/**
 * The one session to show. Prefer the latest day with a numeric P&L.
 * When every day is unmarked, keep the latest date so the row can say unavailable.
 */
export function displaySessionDay(days: DailyPnlDay[] | null | undefined): DailyPnlDay | undefined {
  if (!days || days.length === 0) return undefined;
  let latestAny: DailyPnlDay | undefined;
  let latestMarked: DailyPnlDay | undefined;
  for (const day of days) {
    if (!day?.date) continue;
    if (!latestAny || day.date > latestAny.date) latestAny = day;
    if (markedPnl(day) != null && (!latestMarked || day.date > latestMarked.date)) {
      latestMarked = day;
    }
  }
  return latestMarked ?? latestAny;
}

export function daysForPosition(payload: DailyPnlResponse | undefined, id: string): DailyPnlDay[] | undefined {
  if (!payload) return undefined;
  return payload.positions.find((row) => row.id === id)?.days ?? [];
}

/**
 * Dollar P&L for the session {@link displaySessionDay} selects.
 * When that day has no price, keep the position unrealized P&L the portfolio already returned.
 */
export function dayPlOrUnrealized(
  days: DailyPnlDay[] | undefined,
  unrealized: number | null | undefined,
): number | null {
  if (days === undefined) return null;
  const marked = markedPnl(displaySessionDay(days));
  if (marked != null) return marked;
  if (unrealized != null && Number.isFinite(unrealized)) return unrealized;
  return null;
}
