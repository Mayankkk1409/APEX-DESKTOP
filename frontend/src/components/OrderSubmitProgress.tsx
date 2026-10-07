type Props = {
  /** True only after the order request has returned. */
  complete: boolean;
};

/** Gold ring shown while an order request is in flight. 100% is the server response. */
export function OrderSubmitProgress({ complete }: Props) {
  return (
    <div
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="progressbar"
      aria-label="Submitting order"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={complete ? 100 : undefined}
      data-testid="order-progress"
      data-complete={complete ? "true" : "false"}
    >
      <div className="order-cert-card w-full max-w-xs">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-progress-inner">
            <svg className="order-progress-ring" viewBox="0 0 120 120" aria-hidden>
              <circle className="order-progress-track" cx="60" cy="60" r="52" />
              <circle className={complete ? "order-progress-value is-complete" : "order-progress-value"} cx="60" cy="60" r="52" />
            </svg>
            <p className="order-cert-eyebrow">{complete ? "Order received" : "Submitting order"}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
