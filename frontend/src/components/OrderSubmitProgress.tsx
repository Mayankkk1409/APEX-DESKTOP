import { useEffect, useRef } from "react";

export type OrderProgressPhase = "submitting" | "queued" | "recorded" | "not-submitted";

export type OrderProgressFacts = {
  ticker?: string;
  strategy?: string;
  detail?: string;
};

type Props = {
  phase: OrderProgressPhase;
  facts?: OrderProgressFacts | null;
  /** Called after a confirmed result has been shown. Not called while the request is still running. */
  onSettled?: () => void;
};

const TITLES: Record<OrderProgressPhase, string> = {
  submitting: "Submitting this paper order",
  queued: "Saved to the queue",
  recorded: "Order recorded",
  "not-submitted": "Not submitted",
};

/** Indeterminate while the request is in flight. The ring completes only after the result is known. */
export function OrderSubmitProgress({ phase, facts, onSettled }: Props) {
  const waiting = phase === "submitting";
  const settled = useRef(onSettled);
  settled.current = onSettled;
  useEffect(() => {
    if (waiting) return;
    const timer = window.setTimeout(() => settled.current?.(), 700);
    return () => window.clearTimeout(timer);
  }, [waiting, phase]);

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
      aria-busy={waiting}
      aria-label={title}
      data-testid="order-progress"
      data-phase={phase}
    >
      <div className="order-cert-card w-full max-w-xs">
        <div className="order-cert-frame">
          <div className="order-progress-inner order-cert-inner">
            <div className="order-progress-ring-wrap" data-testid="order-progress-ring" data-determinate={waiting ? "false" : "true"}>
              <svg className="order-progress-ring" viewBox="0 0 120 120" aria-hidden>
                <circle className="order-progress-track" cx="60" cy="60" r="46" />
                <circle className={`order-progress-value${waiting ? "" : " is-complete"}`} cx="60" cy="60" r="46" />
              </svg>
            </div>
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
