import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { clampCardPoint } from "../lib/clampCardPoint";
import { ApexAssistant } from "./ApexAssistant";
import { AssistantPlans, AssistantPlansCard } from "./AssistantPlans";
import type { AssistantPlan } from "../lib/assistantTypes";

const equity: AssistantPlan = {
  id: "equity",
  name: "Equity",
  subtitle: null,
  description: "Stock research",
  monthly_price: "$14.99",
  annual_checkout: "$149.99",
  equivalent_monthly: "$12.50",
  twelve_monthly_total: "$179.88",
  memos: "Unlimited for entitled markets",
  horizon: "Short and long",
  indicators: "Ten",
  assistant: "50 questions a day",
  alerts: "25. Measurement period not confirmed",
  daily_questions: 50,
};

const separate = "Trading Access is proposed at $9.99 once, including for Elite. It is not sold here.\n\nA 14-day Pro trial appears in the pricing workbook. Card requirements, renewal, cancellation, refunds, and taxes are unresolved, so the trial is not offered here.";

describe("APEX AI", () => {
  it("uses the splash logo and an accessible launch button", () => {
    const html = renderToStaticMarkup(<ApexAssistant />);
    expect(html).toContain('aria-label="Open APEX AI"');
    expect(html).toContain('src="/brand/apex-splash.png"');
    expect(html).not.toContain('data-testid="apex-ai-panel"');
  });

  it("opens a panel without leaving the page", () => {
    const html = renderToStaticMarkup(<ApexAssistant startOpen />);
    expect(html).toContain('class="apex-ai-panel is-open"');
    expect(html).toContain('class="apex-ai-launch is-open"');
    expect(html).toContain('data-testid="apex-ai-panel"');
    expect(html).toContain("APEX AI");
    expect(html).toContain('aria-label="Close APEX AI"');
    expect(html).toContain("View plans");
    expect(html).toContain('src="/brand/apex-splash.png"');
    expect(html).not.toContain("Ask what a trading word means");
    expect(html).not.toContain("model key is not set");
    expect(html).not.toContain("New_York");
  });

  it("renders one draggable plans card", () => {
    const html = renderToStaticMarkup(
      <AssistantPlansCard
        plans={[equity]}
        period="monthly"
        onPeriod={() => undefined}
        separate={separate}
        onClose={() => undefined}
        position={null}
        onPosition={() => undefined}
      />,
    );
    expect(html.match(/data-testid="apex-ai-plans-card"/g)).toHaveLength(1);
    expect(html).toContain('data-testid="apex-ai-plans-drag"');
    expect(html).toContain(">Close<");
    expect(html).toContain("Proposed annual checkout: $149.99");
  });

  it("keeps a dragged card inside the window", () => {
    expect(clampCardPoint(-40, -10, 800, 600)).toEqual({ x: 8, y: 8 });
    expect(clampCardPoint(900, 700, 800, 600)).toEqual({ x: 704, y: 536 });
  });

  it("switches only the large price between monthly and annual", () => {
    const monthly = renderToStaticMarkup(
      <AssistantPlans plans={[equity]} period="monthly" onPeriod={() => undefined} separate={separate} currentPlanId="free" />,
    );
    const annual = renderToStaticMarkup(
      <AssistantPlans plans={[equity]} period="annual" onPeriod={() => undefined} separate={separate} currentPlanId="free" />,
    );
    expect(monthly).toContain(">$14.99<");
    expect(monthly).toContain("per month");
    expect(monthly).toContain("Proposed annual checkout: $149.99");
    expect(monthly).toContain("$12.50 equivalent per month, billed annually");
    expect(monthly).toContain("Twelve monthly payments would total $179.88");
    expect(annual).toContain(">$149.99<");
    expect(annual).toContain("billed annually");
    expect(annual).toContain("Proposed monthly price: $14.99");
    expect(annual).not.toContain(">$14.99<");
    expect(monthly).toContain("It is not sold here.");
    expect(monthly).toContain("the trial is not offered here.");
  });
});
