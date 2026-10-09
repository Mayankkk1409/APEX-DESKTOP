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
    expect(html).toContain("The account cannot cover the order.");
    expect(html).not.toContain("Insufficient buying power");
  });

  it("explains a spread refusal and a leg-count refusal with the fact and a why", () => {
    const spreadHtml = renderToStaticMarkup(<OrderRefusalDialog reason={SPREAD} onClose={() => undefined} />);
    expect(spreadHtml).toContain("Order not submitted");
    expect(spreadHtml).toContain("order-cert-stack");
    expect(spreadHtml).toContain("10.2%");
    expect(spreadHtml).toContain("$2578.50");
    expect(spreadHtml).toContain("The price you would pay is not reliable.");
    expect(spreadHtml).not.toContain("{");
    expect(spreadHtml).not.toContain("Proceed");
    expect(spreadHtml).not.toContain("Place Trade");

    const legCount =
      "{'strategy_id': 'short_iron_condor', 'ticker': 'TSLA', 'check': 'leg_count', 'expected': '4', 'actual': '3'}";
    const legHtml = renderToStaticMarkup(<OrderRefusalDialog reason={legCount} onClose={() => undefined} />);
    expect(legHtml).toContain("leg count");
    expect(legHtml).toContain("expected 4, got 3");
    expect(legHtml).toContain("This is not the strategy on the card.");
    expect(legHtml).not.toContain("{");
    expect(legHtml).not.toContain("strategy_id");
    expect(legHtml).not.toContain("Proceed");
  });

  it("maps raw JSON, a stack trace, and a network failure to one sentence", () => {
    const json = '[{"type":"value_error","loc":["body","legs"],"msg":"boom"}]';
    const jsonHtml = renderToStaticMarkup(<OrderRefusalDialog reason={json} onClose={() => undefined} />);
    expect(jsonHtml).toContain("The order was not submitted.");
    expect(jsonHtml).not.toContain("{");
    expect(jsonHtml).not.toContain("value_error");
    expect(jsonHtml).not.toContain("Proceed");

    const stack = 'Traceback (most recent call last):\n  File "fills.py", line 4, in place\nValueError: boom';
    const stackHtml = renderToStaticMarkup(<OrderRefusalDialog reason={stack} onClose={() => undefined} />);
    expect(stackHtml).toContain("The order was not submitted.");
    expect(stackHtml).not.toContain("Traceback");
    expect(stackHtml).not.toContain("fills.py");

    const network = "Cannot reach APEX API. Make sure the backend is running on port 8000.";
    const networkHtml = renderToStaticMarkup(<OrderRefusalDialog reason={network} onClose={() => undefined} />);
    expect(networkHtml).toContain("The connection failed, so the order was not submitted.");
    expect(networkHtml).not.toContain("port 8000");
    expect(networkHtml).not.toContain("Proceed");
  });
});