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
  const locked = state.disabled || pending;
  return (
    <>
      {state.disabled && state.reason ? (
        <p className="text-sm text-champagne/80" data-testid="order-blocked-reason" role="note">
          {state.reason}
        </p>
      ) : null}
      {!state.disabled && placement.note ? (
        <p className="text-sm text-champagne/70" data-testid="manual-confirmation-note" role="note">
          {placement.note}
        </p>
      ) : null}
      <label
        className={
          state.disabled
            ? "flex cursor-not-allowed items-center gap-2 text-sm leading-snug text-champagne/50"
            : "flex cursor-pointer items-center gap-2 text-sm leading-snug"
        }
      >
        <input
          type="checkbox"
          className="shrink-0"
          data-testid="thesis"
          disabled={locked}
          checked={thesisAccepted}
          onChange={(e) => {
            if (locked) return;
            onThesisChange?.(e.target.checked);
          }}
        />
        <span>{THESIS_ACCEPTANCE_TEXT}</span>
      </label>
      {placement.acknowledgeEnabled ? (
        <p className="text-sm text-champagne/70" data-testid="auto-exec-hint">
          Accepting the thesis submits these legs.
        </p>
      ) : null}
      {placement.placeTradeEnabled ? (
        <button
          data-testid="submit-order"
          disabled={pending}
          onClick={onPlace}
          className="rounded-md bg-gold px-4 py-2 text-ink disabled:opacity-40"
        >
          Place Trade
        </button>
      ) : null}
    </>
  );
}
