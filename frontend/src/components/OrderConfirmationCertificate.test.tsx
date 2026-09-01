import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { OrderConfirmationCertificate } from "./OrderConfirmationCertificate";
import type { OrderConfirmationDetails } from "../types";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
  },
}));

vi.mock("../hooks/useFocusTrap", () => ({
  useFocusTrap: () => ({ current: null }),
  useEscapeKey: () => undefined,
}));

const sampleDetails: OrderConfirmationDetails = {
  orderIds: ["ord-1", "ord-2"],
  legs: [
    { id: "ord-1", symbol: "AAPL270115C00150000", side: "buy", qty: 1, fill_price: 4.25 },
    { id: "ord-2", symbol: "AAPL270115C00155000", side: "sell", qty: 1, fill_price: 2.1 },
  ],
  strategyName: "Gamma Trampoline™",
  accountLabel: "Paper · @trader1 · usr-pape",
  accountMode: "paper_funded",
  ticker: "AAPL",
  orderType: "market",
  assetClass: "us_option",
  status: "filled",
};

describe("OrderConfirmationCertificate", () => {
  it("renders certificate fields from order response", () => {
    const html = renderToStaticMarkup(
      <OrderConfirmationCertificate details={sampleDetails} onDismiss={() => undefined} />,
    );
    expect(html).toContain('data-testid="order-confirmation-modal"');
    expect(html).toContain("Order Confirmation");
    expect(html).toContain('data-testid="order-cert-ticker"');
    expect(html).toContain("AAPL");
    expect(html).toContain('data-testid="order-cert-strategy"');
    expect(html).toContain("APEX Strategy");
    expect(html).toContain('data-testid="cert-leg-expiration"');
    expect(html).toMatch(/Jan 15, 2027/);
    expect(html).toContain('data-testid="order-cert-order-type"');
    expect(html).toContain("market · us_option");
    expect(html).toContain('data-testid="order-cert-account"');
    expect(html).toContain("Paper · @trader1 · usr-pape");
    expect(html).toContain('data-testid="order-cert-order-ids"');
    expect(html).toContain("ord-1, ord-2");
    expect(html).toContain('data-testid="order-cert-legs"');
    expect(html).toContain("AAPL270115C00150000");
    expect(html).toContain('data-testid="order-cert-dismiss"');
  });
});
