export type OrderProgressPhase = "submitting" | "filled" | "not-submitted";

export type OrderProgressFacts = {
  ticker?: string;
  strategy?: string;
  detail?: string;
};

type Props = {
  phase: OrderProgressPhase;
  facts?: OrderProgressFacts | null;
};

const TITLES: Record<OrderProgressPhase, string> = {
  submitting: "Submitting",
  filled: "Filled",
  "not-submitted": "Not submitted",
};

/** Compact certificate status while an order is in flight, then filled or refused. */
export function OrderSubmitProgress({ phase, facts }: Props) {
  const title = TITLES[phase];
  const rows = [
    facts?.ticker ? { label: "Ticker", value: facts.ticker } : null,
    facts?.strategy ? { label: "Strategy", value: facts.strategy } : null,
  ].filter((row): row is { label: string; value: string } => row != null);

  return (
    <div
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="status"
      aria-live="polite"
      aria-busy={phase === "submitting"}
      aria-label={title}
      data-testid="order-progress"
      data-phase={phase}
    >
      <div className="order-cert-card w-full max-w-xs">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-cert-stack">
            <p className="order-cert-eyebrow">Order</p>
            <h2 className="order-cert-title" data-testid="order-progress-title">
              {title}
            </h2>
            {rows.length ? (
              <dl className="order-cert-grid">
                {rows.map((row) => (
                  <div className="order-cert-row" key={row.label}>
                    <dt>{row.label}</dt>
                    <dd>{row.value}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            {facts?.detail ? <p className="order-cert-copy">{facts.detail}</p> : null}
          </div>
        </div>
      </div>
    </div>
  );
}
