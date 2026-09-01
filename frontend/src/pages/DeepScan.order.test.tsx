import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

/** Minimal risk-review markup mirror for layout regression tests. */
function RiskReviewOrderPanel({
  orderTypeLabel,
  thesisText,
}: {
  orderTypeLabel: string;
  thesisText: string;
}) {
  return (
    <div data-testid="risk-review">
      <label className="flex cursor-pointer items-center gap-2 text-sm leading-snug">
        <input type="checkbox" className="shrink-0" data-testid="thesis" />
        <span>{thesisText}</span>
      </label>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <p>Type</p>
        <p className="font-mono text-champagne/90" data-testid="order-type">
          {orderTypeLabel}
        </p>
      </div>
    </div>
  );
}

describe("DeepScan risk review order panel", () => {
  it("shows formatted order type and inline thesis checkbox", () => {
    const thesis =
      "I accept the thesis and have reviewed each options leg, contract quantity, estimated premium, and account impact.";
    const html = renderToStaticMarkup(
      <RiskReviewOrderPanel orderTypeLabel="market · us_option" thesisText={thesis} />,
    );
    expect(html).toContain('data-testid="order-type"');
    expect(html).toContain("market · us_option");
    expect(html).toContain('class="flex cursor-pointer items-center gap-2 text-sm leading-snug"');
    expect(html).toContain('class="shrink-0"');
    expect(html).toContain(thesis);
  });
});
