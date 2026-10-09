import { fmtMoney } from "../lib/portfolioFormat";

/** Signed account P&L. Up/down color only when the figure is non-zero. */
export function OverallPnlTotal({ value }: { value: number | null }) {
  const tone = value != null && value > 0 ? "num-up" : value != null && value < 0 ? "num-down" : "";
  return (
    <div className="flex items-baseline justify-between gap-3" data-testid="overall-pnl-total">
      <span className="text-sm text-subtle">Overall total P&amp;L</span>
      <span className={`font-mono text-lg ${tone}`} data-testid="overall-pnl-total-value">
        {fmtMoney(value)}
      </span>
    </div>
  );
}
