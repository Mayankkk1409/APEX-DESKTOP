import type { OrderPlacement } from "../lib/riskReview";

/** Acknowledge hint versus Place Trade for the Deep Scan risk-review slide. */
export function RiskReviewOrderActions({
  placement,
  pending = false,
  onPlace,
}: {
  placement: OrderPlacement;
  pending?: boolean;
  onPlace: () => void;
}) {
  return (
    <>
      {placement.note ? (
        <p className="text-sm text-champagne/70" data-testid="manual-confirmation-note" role="note">
          {placement.note}
        </p>
      ) : null}
      {placement.autoSubmitOnAck ? (
        <p className="text-sm text-champagne/70" data-testid="auto-exec-hint">
          Acknowledge — accepting the thesis submits these options legs.
        </p>
      ) : (
        <button
          data-testid="submit-order"
          disabled={pending || !placement.placeTradeEnabled}
          onClick={onPlace}
          className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
        >
          Place Trade
        </button>
      )}
    </>
  );
}
