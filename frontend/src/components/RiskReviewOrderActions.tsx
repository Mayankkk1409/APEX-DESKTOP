import type { OrderPlacement } from "../lib/riskReview";
import { thesisCheckboxState } from "../lib/riskReview";

export const THESIS_ACCEPTANCE_TEXT =
  "I accept the thesis and have reviewed each option leg, the stock leg when this strategy includes shares, contract quantity, and account impact.";

/** Thesis checkbox versus Place Trade for the Deep Scan risk-review slide. */
export function RiskReviewOrderActions({
  placement,
  pending = false,
  thesisAccepted = false,
  onThesisChange,
  onPlace,
}: {
  placement: OrderPlacement;
  pending?: boolean;
  thesisAccepted?: boolean;
  onThesisChange?: (checked: boolean) => void;
  onPlace: () => void;
}) {
  const state = thesisCheckboxState(placement);
  const ready = thesisAccepted && !pending;
  const showOverrideActions = placement.overrideRequired && thesisAccepted;
  return (
    <>
      {!placement.overrideRequired && placement.note ? (
        <p className="text-sm text-champagne/70" data-testid="manual-confirmation-note" role="note">
          {placement.note}
        </p>
      ) : null}
      <label className="flex cursor-pointer items-center gap-2 text-sm leading-snug">
        <input
          type="checkbox"
          className="shrink-0"
          data-testid="thesis"
          disabled={pending}
          checked={thesisAccepted}
          onChange={(e) => {
            if (pending) return;
            onThesisChange?.(e.target.checked);
          }}
        />
        <span>{THESIS_ACCEPTANCE_TEXT}</span>
      </label>
      {!placement.overrideRequired && placement.acknowledgeEnabled && state.submitsOnAccept ? (
        <p className="text-sm text-champagne/70" data-testid="auto-exec-hint">
          Accepting the thesis submits these legs.
        </p>
      ) : null}
      {showOverrideActions ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="acknowledge-order"
            disabled={!ready}
            onClick={onPlace}
            className="rounded-md border border-gold px-4 py-2 text-champagne disabled:opacity-40"
          >
            Acknowledge
          </button>
          <button
            type="button"
            data-testid="submit-order"
            disabled={!ready}
            onClick={onPlace}
            className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
          >
            Place Trade
          </button>
        </div>
      ) : null}
      {!placement.overrideRequired && placement.placeTradeEnabled ? (
        <button
          type="button"
          data-testid="submit-order"
          disabled={!ready}
          onClick={onPlace}
          className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
        >
          Place Trade
        </button>
      ) : null}
    </>
  );
}
