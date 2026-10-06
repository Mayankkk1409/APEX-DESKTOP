import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ExpiryLoginCertificate } from "./ExpiryLoginCertificate";
import type { ExpiryLoginRow } from "../lib/expiryLoginNotice";

const escape = vi.fn();
const trap = vi.fn(() => ({ current: null }));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
  },
}));

vi.mock("../hooks/useFocusTrap", () => ({
  useFocusTrap: (...args: unknown[]) => trap(...args),
  useEscapeKey: (...args: unknown[]) => escape(...args),
}));

const row: ExpiryLoginRow = {
  key: "pos-1",
  symbol: "AAPL",
  strategy: "Bull Call Spread",
  expiryLabel: "Oct 9, 2026",
  strikeLabel: "150",
  right: "call",
  direction: "long",
};

describe("ExpiryLoginCertificate", () => {
  it("shows nothing when no position expires inside the window", () => {
    escape.mockClear();
    trap.mockClear();
    const html = renderToStaticMarkup(
      <ExpiryLoginCertificate items={[]} isPaper onDismiss={() => undefined} />,
    );
    expect(html).toBe("");
    expect(trap).toHaveBeenCalledWith(false);
    expect(escape).toHaveBeenCalledWith(false, expect.any(Function));
  });

  it("renders one labelled dialog with the contract row and the 16:00 New York close", () => {
    escape.mockClear();
    trap.mockClear();
    const onDismiss = () => undefined;
    const html = renderToStaticMarkup(
      <ExpiryLoginCertificate items={[row]} isPaper onDismiss={onDismiss} />,
    );
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-labelledby="expiry-login-title"');
    expect(html).toContain("Expiring positions");
    expect(html).toContain("PAPER TRADE");
    expect(html).toContain("These positions will be closed automatically at 16:00 America/New_York on the expiry day if still open.");
    expect(html).toContain("AAPL");
    expect(html).toContain("Bull Call Spread");
    expect(html).toContain("Oct 9, 2026");
    expect(html).toContain("150");
    expect(html).toContain("call");
    expect(html).toContain("long");
    expect(trap).toHaveBeenCalledWith(true);
    expect(escape).toHaveBeenCalledWith(true, onDismiss);
  });
});
