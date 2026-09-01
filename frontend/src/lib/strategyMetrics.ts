/** Client-side payoff helpers — mirrors backend strategy_engine for tests and display fallbacks. */

export type StrategyLegRow = {
  side: "call" | "put";
  strike: number;
  bid?: number | null;
  ask?: number | null;
  delta?: number | null;
};

export type StrategyMetricsView = {
  max_loss: number | null;
  max_profit: number | null;
  net_debit_credit: number | null;
  net_type: "debit" | "credit" | null;
  breakevens: number[];
  legs: { action: string; side: string; strike: number; mid: number | null }[];
};

function mid(c: StrategyLegRow): number {
  if (c.bid != null && c.ask != null && c.bid > 0 && c.ask > 0) return (c.bid + c.ask) / 2;
  return 0;
}

export function bullCallSpreadMetrics(
  contracts: StrategyLegRow[],
  recommended: { strike: number; side: "call" | "put" },
  spot: number,
  multiplier = 100,
): StrategyMetricsView {
  const longC =
    contracts.find((c) => c.side === "call" && c.strike === recommended.strike) ??
    contracts.filter((c) => c.side === "call").sort((a, b) => Math.abs((a.delta ?? 0) - 0.55) - Math.abs((b.delta ?? 0) - 0.55))[0];
  const shortC = contracts
    .filter((c) => c.side === "call" && longC && c.strike > longC.strike)
    .sort((a, b) => a.strike - b.strike)[0];
  if (!longC || !shortC) {
    return { max_loss: null, max_profit: null, net_debit_credit: null, net_type: null, breakevens: [], legs: [] };
  }
  const longMid = mid(longC);
  const shortMid = mid(shortC);
  const net = longMid - shortMid;
  const width = shortC.strike - longC.strike;
  return {
    net_debit_credit: Math.round(net * 100) / 100,
    net_type: "debit",
    max_loss: Math.round(net * multiplier * 100) / 100,
    max_profit: Math.round((width - net) * multiplier * 100) / 100,
    breakevens: [Math.round((longC.strike + net) * 100) / 100],
    legs: [
      { action: "buy", side: "call", strike: longC.strike, mid: longMid },
      { action: "sell", side: "call", strike: shortC.strike, mid: shortMid },
    ],
  };
}
