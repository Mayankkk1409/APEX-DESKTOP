import type { OptionReviewRow } from "../lib/orderTicket";

/** Option legs side by side on a wide screen, stacked when the screen is narrow. */
export function RiskReviewLegs({ rows }: { rows: OptionReviewRow[] }) {
  return (
    <ul className="rr-legs" data-testid="strategy-legs-review">
      {rows.map((leg) => (
        <li key={`${leg.side}-${leg.symbol}`} className="rr-leg" data-testid="strategy-leg">
          <p className="rr-leg-side" data-testid="strategy-leg-side">
            {leg.sideLabel}
          </p>
          <p>
            <span data-testid="strategy-leg-contracts">{leg.contracts}</span>
            {leg.optionSide ? " contract" : ""}
            {leg.optionSide ? ` ${leg.optionSide}` : ""}
            {leg.strike != null ? ` ${leg.strike}` : ""}
          </p>
          {leg.expiry ? <p>Expiry {leg.expiry}</p> : null}
          <p className="rr-leg-symbol" data-testid="strategy-leg-occ">
            {leg.symbol}
          </p>
          <p data-testid="strategy-leg-type">{leg.orderTypeLabel}</p>
          {leg.premiumLabel ? <p data-testid="strategy-leg-premium">{leg.premiumLabel}</p> : null}
          {leg.impactLabel ? <p data-testid="strategy-leg-impact">{leg.impactLabel}</p> : null}
        </li>
      ))}
    </ul>
  );
}
