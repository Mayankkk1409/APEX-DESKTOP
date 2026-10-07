import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OrderRefusalDialog } from "./OrderRefusalDialog";

const SPREAD =
  "Bid/ask spread is 10.2% of mid, wider than the 10% cap. Estimated slippage $2578.50.";
const BUYING_POWER = "insufficient options buying power";

describe("OrderRefusalDialog", () => {
  it("shows the server spread refusal without rewriting it", () => {
    const html = renderToStaticMarkup(<OrderRefusalDialog reason={SPREAD} onClose={() => undefined} />);
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("Order not submitted");
    expect(html).toContain(SPREAD);
    expect(html).toContain("10.2%");
    expect(html).toContain("$2578.50");
    expect(html).toContain('data-testid="order-refusal-close"');
    expect(html).toContain(">Close<");
    expect(html).not.toContain("Proceed");
    expect(html).not.toContain("Place Trade");
  });

  it("shows the broker buying-power sentence unchanged", () => {
    const html = renderToStaticMarkup(<OrderRefusalDialog reason={BUYING_POWER} onClose={() => undefined} />);
    expect(html).toContain('data-testid="order-refusal-reason"');
    expect(html).toContain(BUYING_POWER);
    expect(html).not.toContain("Insufficient buying power");
  });
});