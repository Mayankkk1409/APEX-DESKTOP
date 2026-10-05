/**
 * Account overall P&L, in integer cents.
 *
 *   overall_cents = Σ realized_cents + Σ unrealized_cents − Σ fee_cents
 *   overall_dollars = overall_cents / 100
 *
 * A loss is a negative realized or unrealized amount and reduces overall_cents.
 * fee_cents is included only when that row reports a fee. A missing fee is not
 * treated as zero and is not invented.
 *
 * Position mark, used for the short-option sign:
 *   unrealized_cents = (mark_cents − average_cents) × qty × multiplier
 * qty is negative for a short, so a mark below the sale price is a gain.
 *
 * Cents use half away from zero. The dollar amount is scaled by 100 and nudged
 * by 1e-8 before rounding so binary values such as 1.005 and 6.95 land on the
 * cent a decimal would use.
 *
 * When starting capital, deposits, and withdrawals are all known:
 *   overall_cents = portfolio_cents − (starting_cents + deposits_cents − withdrawals_cents)
 * This file does not invent deposits or withdrawals. `overallPnlFromCapitalFlows`
 * is only for a book that already has those figures. Settings and Portfolio both
 * call `displayedOverallTotal` on the same overall-P&L rows, so the numbers
 * labeled total P&L stay on one cent total.
 */

export type OverallPnlSourceRow = {
  realized_pl?: number | null;
  unrealized_pl?: number | null;
  /** Present only when the source reported a fee. Omitted means no fee was provided. */
  fees?: number | null;
};

export type PnlContribution = {
  realized?: number | null;
  unrealized?: number | null;
  fees?: number | null;
};

const CENT_NUDGE = 1e-8;

export function toCents(dollars: number): number {
  if (!Number.isFinite(dollars)) return Number.NaN;
  const negative = dollars < 0;
  const scaled = (Math.abs(dollars) + CENT_NUDGE) * 100;
  const cents = Math.round(scaled);
  return negative ? -cents : cents;
}

export function centsToDollars(cents: number): number {
  return cents / 100;
}

/** (mark − average) × qty × multiplier, in cents. Short qty is negative. */
export function positionUnrealizedCents(mark: number, average: number, qty: number, multiplier: number): number {
  const priceDiffCents = toCents(mark) - toCents(average);
  const units = qty * multiplier;
  if (!Number.isFinite(priceDiffCents) || !Number.isFinite(units)) return Number.NaN;
  if (Number.isInteger(units)) return priceDiffCents * units;
  const negative = units < 0;
  const cents = Math.round(Math.abs(priceDiffCents * units));
  return negative ? -cents : cents;
}

function addDollars(totalCents: number, dollars: number | null | undefined, sign: 1 | -1): number {
  if (dollars == null || !Number.isFinite(dollars)) return totalCents;
  return totalCents + sign * toCents(dollars);
}

export function overallPnlCents(rows: readonly PnlContribution[]): number {
  let total = 0;
  for (const row of rows) {
    total = addDollars(total, row.realized, 1);
    total = addDollars(total, row.unrealized, 1);
    if (row.fees != null && Number.isFinite(row.fees)) {
      total = addDollars(total, row.fees, -1);
    }
  }
  return total;
}

/** Shared overall P&L in dollars. */
export function overallTotalPnl(rows: readonly PnlContribution[]): number {
  return centsToDollars(overallPnlCents(rows));
}

/**
 * Account total both Settings and Portfolio display.
 * Reads realized_pl, unrealized_pl, and fees from `/api/portfolio/overall-pnl`
 * (or the same shape built from open positions). Does not use equity minus
 * starting capital.
 */
export function displayedOverallTotal(rows: readonly OverallPnlSourceRow[]): number {
  return overallTotalPnl(
    rows.map((row) => ({
      realized: row.realized_pl,
      unrealized: row.unrealized_pl,
      fees: row.fees,
    })),
  );
}

export function overallPnlFromCapitalFlows(input: {
  portfolioValue: number;
  startingCapital: number;
  deposits: number;
  withdrawals: number;
}): number {
  const cents =
    toCents(input.portfolioValue) -
    (toCents(input.startingCapital) + toCents(input.deposits) - toCents(input.withdrawals));
  return centsToDollars(cents);
}
