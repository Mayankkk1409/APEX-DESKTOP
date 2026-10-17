import { useEffect, useRef } from "react";
import { clampCardPoint } from "../lib/clampCardPoint";
import type { AssistantPlan, BillingPeriod } from "../lib/assistantTypes";

const ROWS: { label: string; key: "memos" | "horizon" | "indicators" | "assistant" | "alerts" }[] = [
  { label: "Memos", key: "memos" },
  { label: "Horizon", key: "horizon" },
  { label: "Indicators", key: "indicators" },
  { label: "Assistant", key: "assistant" },
  { label: "Alerts", key: "alerts" },
];

export function AssistantPlansCard({
  plans,
  period,
  onPeriod,
  currentPlanId,
  separate,
  onClose,
  position,
  onPosition,
}: {
  plans: AssistantPlan[];
  period: BillingPeriod;
  onPeriod: (period: BillingPeriod) => void;
  currentPlanId?: string;
  separate: string;
  onClose: () => void;
  position: { x: number; y: number } | null;
  onPosition: (position: { x: number; y: number }) => void;
}) {
  const cardRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

  useEffect(() => {
    const onResize = () => {
      if (!position) return;
      onPosition(clampCardPoint(position.x, position.y, window.innerWidth, window.innerHeight));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [position, onPosition]);

  return (
    <aside
      ref={cardRef}
      className="apex-ai-plans-card"
      role="dialog"
      aria-label="Plans"
      data-testid="apex-ai-plans-card"
      style={position ? { left: position.x, top: position.y } : undefined}
    >
      <div
        className="apex-ai-plans-drag"
        data-testid="apex-ai-plans-drag"
        onPointerDown={(event) => {
          if ((event.target as HTMLElement).closest("button")) return;
          event.preventDefault();
          const card = cardRef.current;
          if (!card) return;
          const rect = card.getBoundingClientRect();
          dragRef.current = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
          card.classList.add("is-dragging");
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!dragRef.current || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
          event.preventDefault();
          onPosition(clampCardPoint(event.clientX - dragRef.current.dx, event.clientY - dragRef.current.dy, window.innerWidth, window.innerHeight));
        }}
        onPointerUp={(event) => {
          dragRef.current = null;
          cardRef.current?.classList.remove("is-dragging");
          if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          dragRef.current = null;
          cardRef.current?.classList.remove("is-dragging");
        }}
      >
        <p>Plans</p>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="apex-ai-plans-body">
        <AssistantPlans plans={plans} period={period} onPeriod={onPeriod} currentPlanId={currentPlanId} separate={separate} />
      </div>
    </aside>
  );
}

export function AssistantPlans({
  plans,
  period,
  onPeriod,
  currentPlanId,
  separate,
}: {
  plans: AssistantPlan[];
  period: BillingPeriod;
  onPeriod: (period: BillingPeriod) => void;
  currentPlanId?: string;
  separate: string;
}) {
  return (
    <div className="apex-ai-plans" data-testid="apex-ai-plans">
      <div className="apex-ai-period" role="group" aria-label="Billing period">
        <button type="button" aria-pressed={period === "monthly"} onClick={() => onPeriod("monthly")}>
          Monthly
        </button>
        <button type="button" aria-pressed={period === "annual"} onClick={() => onPeriod("annual")}>
          Annual
        </button>
      </div>
      <p className="apex-ai-plan-note">These prices are proposed. This screen does not take payment or change your plan.</p>
      <ul className="apex-ai-plan-list">
        {plans.map((plan) => {
          const headline = period === "monthly" ? plan.monthly_price : plan.annual_checkout;
          const cadence = period === "monthly" ? "per month" : "billed annually";
          return (
            <li key={plan.id} data-testid={`apex-ai-plan-${plan.id}`}>
              <div className="apex-ai-plan-name">
                <strong>{plan.name}</strong>
                {plan.id === currentPlanId ? <span className="apex-ai-current">Current plan</span> : null}
              </div>
              {plan.subtitle ? <p className="apex-ai-plan-sub">{plan.subtitle}</p> : null}
              <p>{plan.description}</p>
              <p className="apex-ai-plan-price" data-testid={`apex-ai-price-${plan.id}`}>
                <span>{headline}</span> {cadence}
              </p>
              <ul className="apex-ai-plan-facts">
                <li>Proposed monthly price: {plan.monthly_price}</li>
                <li>Proposed annual checkout: {plan.annual_checkout}</li>
                <li>{plan.equivalent_monthly} equivalent per month, billed annually</li>
                <li>Twelve monthly payments would total {plan.twelve_monthly_total}</li>
              </ul>
              <dl>
                {ROWS.map((row) => (
                  <div key={row.key}>
                    <dt>{row.label}</dt>
                    <dd>{plan[row.key]}</dd>
                  </div>
                ))}
              </dl>
            </li>
          );
        })}
      </ul>
      <section className="apex-ai-separate" data-testid="apex-ai-separate">
        <h3>Separate from every plan</h3>
        {separate.split("\n\n").map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </section>
    </div>
  );
}
