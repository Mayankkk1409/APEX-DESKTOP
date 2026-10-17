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

export type HoldingsDayTotal = {
  total: number;
  covered: number;
  missing: number;
};

/**
 * Sum of the same day-change figures already shown on open holdings.
 * A holding with no day figure is left out and counted as missing. It is not zero.
 * Closed positions, deposits, and fees are not in this sum.
 */
export function holdingsDayTotal(
  positions: Array<Pick<PositionRow, "qty" | "day_pl" | "symbol">>,
  quoteBySymbol: Map<string, Pick<Quote, "change"> | null | undefined>,
): HoldingsDayTotal | null {
  if (positions.length === 0) return null;
  let total = 0;
  let covered = 0;
  let missing = 0;
  for (const position of positions) {
    const value = resolvePositionDayPl(position, quoteBySymbol.get(position.symbol) ?? null);
    if (value == null) {
      missing += 1;
      continue;
    }
    total += value;
    covered += 1;
  }
  if (covered === 0) return null;
  return { total, covered, missing };
}

export function holdingsDayNote(result: HoldingsDayTotal): string {
  const partial =
    result.missing > 0
      ? ` ${result.missing} open holding${result.missing === 1 ? "" : "s"} had no day change and ${result.missing === 1 ? "is" : "are"} not included.`
      : "";
  return (
    "Daily P&L is the sum of open holdings’ day changes. Positions closed today, deposits, withdrawals, and fees are not included. This is not Overall P&L." +
    partial
  );
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
