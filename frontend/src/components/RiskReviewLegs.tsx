import type { OptionReviewRow } from "../lib/orderTicket";

/** One options order row: OCC, side, contracts, type, premium, and account impact. */
export function RiskReviewLegs({ rows }: { rows: OptionReviewRow[] }) {
  return (
    <ul className="space-y-2 text-sm" data-testid="strategy-legs-review">
      {rows.map((leg) => (
        <li key={`${leg.side}-${leg.symbol}`} className="rounded border border-line/60 px-3 py-2 font-mono text-xs" data-testid="strategy-leg">
          <span data-testid="strategy-leg-side">{leg.sideLabel}</span>{" "}
          <span data-testid="strategy-leg-contracts">{leg.contracts}</span>
          {" × "}
          <span data-testid="strategy-leg-occ">{leg.symbol}</span>
          {leg.optionSide && leg.strike != null
            ? ` (${leg.optionSide} ${leg.strike}${leg.expiry ? ` · ${leg.expiry}` : ""})`
            : ""}
          {" · "}
          <span data-testid="strategy-leg-type">{leg.orderTypeLabel}</span>
          {leg.premiumLabel ? (
            <>
              {" · "}
              <span data-testid="strategy-leg-premium">{leg.premiumLabel}</span>
            </>
          ) : null}
          {leg.impactLabel ? (
            <>
              {" · "}
              <span data-testid="strategy-leg-impact">{leg.impactLabel}</span>
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
