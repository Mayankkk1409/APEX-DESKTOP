import type { BrokeragePosition } from "./brokerageApi";
import type { PositionRow, Quote } from "../types";

/** SnapTrade / vendor field names that may carry intraday P&L when present. */
export function extractBrokerageDayPl(row: BrokeragePosition): number | null {
  const raw = row as BrokeragePosition & Record<string, unknown>;
  for (const key of ["day_pnl", "dayPnl", "daily_pnl", "dailyPnl", "intraday_pnl", "intradayPnl"]) {
    const v = raw[key];
    if (v != null && v !== "" && !Number.isNaN(Number(v))) return Number(v);
  }
  return null;
}

/** Prefer vendor day P&L; otherwise estimate from live quote change × quantity. */
export function resolvePositionDayPl(
  position: Pick<PositionRow, "qty" | "day_pl">,
  quote?: Pick<Quote, "change"> | null,
): number | null {
  if (position.day_pl != null && !Number.isNaN(position.day_pl)) return position.day_pl;
  if (quote?.change != null && !Number.isNaN(quote.change)) return quote.change * position.qty;
  return null;
}
