export type MoverRow = {
  symbol: string;
  unrealized_pl?: number | null;
};

/** Largest open P&L moves on the account currently being viewed. */
export function topMoverSymbols(positions: readonly MoverRow[], limit = 5): string[] {
  return [...positions]
    .filter((row) => row.symbol.trim().length > 0)
    .sort((a, b) => Math.abs(b.unrealized_pl ?? 0) - Math.abs(a.unrealized_pl ?? 0))
    .slice(0, limit)
    .map((row) => row.symbol);
}
