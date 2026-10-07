import { useEffect, useState } from "react";

type Props = {
  /** True only after the order request has returned. */
  complete: boolean;
};

const RING_RADIUS = 52;
const RING_CIRCUMFERENCE = 326.73;
/** In-flight cap. 100 is reserved for the server response. */
const IN_FLIGHT_CAP = 72;
const CREEP_MS = 1600;

/** Gold ring shown while an order request is in flight. 100% is the server response. */
export function OrderSubmitProgress({ complete }: Props) {
  const [pct, setPct] = useState(complete ? 100 : 0);

  useEffect(() => {
    if (complete) {
      setPct(100);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / CREEP_MS);
      const eased = 1 - (1 - t) ** 3;
      setPct(Math.round(eased * IN_FLIGHT_CAP));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [complete]);

  const offset = RING_CIRCUMFERENCE * (1 - pct / 100);

  return (
    <div
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="progressbar"
      aria-label="Submitting order"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      aria-valuetext={`${pct}%`}
      data-testid="order-progress"
      data-complete={complete ? "true" : "false"}
    >
      <div className="order-cert-card w-full max-w-xs">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-progress-inner">
            <div className="order-progress-ring-wrap">
              <svg className="order-progress-ring" viewBox="0 0 120 120" aria-hidden>
                <circle className="order-progress-track" cx="60" cy="60" r={RING_RADIUS} />
                <circle
                  className={complete ? "order-progress-value is-complete" : "order-progress-value"}
                  cx="60"
                  cy="60"
                  r={RING_RADIUS}
                  style={{ strokeDashoffset: offset }}
                />
              </svg>
              <p className="order-progress-pct" data-testid="order-progress-pct">
                {pct}%
              </p>
            </div>
            <p className="order-cert-eyebrow">{complete ? "Order received" : "Submitting order"}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
