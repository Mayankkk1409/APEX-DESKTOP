import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { PositionCertificateModal } from "./PositionCertificateModal";
import type { PositionRow } from "../types";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
  },
}));

vi.mock("../hooks/useFocusTrap", () => ({
  useFocusTrap: () => ({ current: null }),
  useEscapeKey: () => undefined,
}));

const position: PositionRow = {
  id: "pos-1",
  symbol: "AAPL270115C00150000",
  qty: 2,
  avg_cost: 4.5,
  current: 5.1,
  unrealized_pl: 120,
  market_value: 1020,
  asset_class: "us_option",
};

describe("PositionCertificateModal", () => {
  it("renders APEX Strategy name and expiration per leg", () => {
    const html = renderToStaticMarkup(
      <PositionCertificateModal
        details={{
          position,
          strategyName: "Gamma Trampoline™",
          entryScore: 78.5,
          accountLabel: "Paper · @trader",
          isPaper: true,
        }}
        onDismiss={() => undefined}
      />,
    );
    expect(html).toContain('data-testid="position-certificate-modal"');
    expect(html).toContain('role="dialog"');
    expect(html).toContain('data-testid="position-cert-strategy"');
    expect(html).toContain("APEX Strategy");
    expect(html).not.toContain("Gamma Trampoline");
    expect(html).toContain('data-testid="position-cert-paper-banner"');
    expect(html).toContain('data-testid="cert-leg-expiration"');
    expect(html).toContain("Jan 15, 2027");
    expect(html).toContain('data-testid="position-cert-dismiss"');
  });
});
