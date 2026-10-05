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
  orderType: "limit",
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
    expect(html).toContain("limit");
    expect(html).not.toContain("us_option");
    expect(html).toContain('data-testid="order-cert-account"');
    expect(html).toContain("Paper · @trader1 · usr-pape");
    expect(html).toContain('data-testid="order-cert-order-ids"');
    expect(html).toContain("ord-1, ord-2");
    expect(html).toContain('data-testid="order-cert-legs"');
    expect(html).toContain("AAPL270115C00150000");
    expect(html).toContain('data-testid="order-cert-dismiss"');
  });

  it("no positions means no modal", () => {
    const html = renderToStaticMarkup(
      <OrderConfirmationCertificate
        variant="expiry"
        details={{ items: [], isPaper: true }}
        onDismiss={() => undefined}
      />,
    );
    expect(html).not.toContain('data-testid="expiry-notice-modal"');
    expect(html).toBe("");
  });

  it("lists expiring trades soonest first with the auto-close notice and Close only when one exists", () => {
    const html = renderToStaticMarkup(
      <OrderConfirmationCertificate
        variant="expiry"
        details={{
          isPaper: true,
          items: [
            {
              position_id: "later",
              symbol: "MSFT261009C00400000",
              strategy: "Bear Put Spread",
              expiry: "2026-10-09",
              days_left: 7,
              can_close: false,
            },
            {
              position_id: "soon",
              symbol: "AAPL261002C00150000",
              strategy: "Bull Call Spread",
              expiry: "2026-10-02",
              days_left: 0,
              can_close: true,
            },
          ],
        }}
        onDismiss={() => undefined}
        onClosePosition={() => undefined}
      />,
    );
    expect(html).toContain('data-testid="expiry-notice-modal"');
    expect(html).toContain("Positions still open at the cutoff on their expiry day will be closed automatically.");
    expect(html).toContain("PAPER TRADE");
    expect(html).toContain("Bull Call Spread");
    expect(html).toContain("0 days left");
    expect(html).toContain("7 days left");
    expect(html).toContain('data-testid="expiry-close-soon"');
    expect(html).toContain(">Close<");
    expect(html).not.toContain('data-testid="expiry-close-later"');
    const soon = html.indexOf("AAPL261002C00150000");
    const later = html.indexOf("MSFT261009C00400000");
    expect(soon).toBeGreaterThan(-1);
    expect(soon).toBeLessThan(later);
  });
});
