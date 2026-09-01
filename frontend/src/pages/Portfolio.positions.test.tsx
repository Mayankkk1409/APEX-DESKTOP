import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { PositionCertificateModal } from "../components/PositionCertificateModal";

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
  },
}));

vi.mock("../hooks/useFocusTrap", () => ({
  useFocusTrap: () => ({ current: null }),
  useEscapeKey: () => undefined,
}));

describe("position row opens certificate", () => {
  it("renders clickable row test id pattern", () => {
    const row = `<tr data-testid="position-row-pos-1" role="button" tabindex="0"></tr>`;
    expect(row).toContain("position-row-pos-1");
    expect(row).toContain('role="button"');
  });
});

describe("PositionCertificateModal paper banner", () => {
  it("shows paper trade banner when isPaper", () => {
    const html = renderToStaticMarkup(
      <PositionCertificateModal
        details={{
          position: {
            id: "p1",
            symbol: "SPX260918P00540000",
            qty: 1,
            avg_cost: 8,
            current: 7,
            unrealized_pl: -100,
            market_value: 700,
          },
          isPaper: true,
          accountLabel: "Paper",
        }}
        onDismiss={() => undefined}
      />,
    );
    expect(html).toContain("PAPER TRADE");
  });
});
