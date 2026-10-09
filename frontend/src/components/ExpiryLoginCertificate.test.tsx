import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ExpiryLoginCertificate } from "./ExpiryLoginCertificate";
import {
  EXPIRY_LOGIN_AUTO_CLOSE,
  EXPIRY_LOGIN_BROKER_SETTLES,
  EXPIRY_LOGIN_NONE,
  type ExpiryLoginRow,
} from "../lib/expiryLoginNotice";

const escape = vi.fn((_active: boolean, _onClose: () => void) => undefined);
const trap = vi.fn((_active: boolean) => ({ current: null }));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({
      children,
      initial: _initial,
      animate: _animate,
      transition: _transition,
      ...props
    }: React.ComponentProps<"div"> & { initial?: unknown; animate?: unknown; transition?: unknown }) => (
      <div {...props}>{children}</div>
    ),
  },
  useReducedMotion: () => true,
}));

vi.mock("../hooks/useFocusTrap", () => ({
  useFocusTrap: (active: boolean) => trap(active),
  useEscapeKey: (active: boolean, onClose: () => void) => escape(active, onClose),
}));

const row: ExpiryLoginRow = {
  key: "pos-1",
  positionId: "pos-1",
  symbol: "AAPL",
  strategy: "Bull Call Spread",
  expiryLabel: "Oct 9, 2026",
  strikeLabel: "150",
  right: "call",
  direction: "long",
};

describe("ExpiryLoginCertificate", () => {
  it("still shows the certificate when no position expires inside the window", () => {
    escape.mockClear();
    trap.mockClear();
    const html = renderToStaticMarkup(
      <ExpiryLoginCertificate items={[]} isPaper onDismiss={() => undefined} />,
    );
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-labelledby="expiry-login-title"');
    expect(html).toContain("expiry-login-card");
    expect(html).toContain("expiry-login-body");
    expect(html).not.toMatch(/min-h-screen|h-screen|100vh|flex-grow|flex-1/);
    expect(html).toContain("Expiring positions");
    expect(html).toContain(EXPIRY_LOGIN_NONE);
    expect(html).toContain('data-testid="expiry-login-empty"');
    expect(html).not.toContain("AAPL");
    expect(html).not.toContain('data-testid="expiry-login-list"');
    expect(trap).toHaveBeenCalledWith(true);
    expect(escape).toHaveBeenCalledWith(true, expect.any(Function));
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
    expect(html).toContain('data-testid="expiry-login-right-pos-1">Call<');
    expect(html).toContain('data-testid="expiry-login-direction-pos-1">Long<');
    expect(html).toContain('data-testid="expiry-login-settles-pos-1">APEX auto-close<');
    expect(html).not.toContain(EXPIRY_LOGIN_BROKER_SETTLES);
    expect(trap).toHaveBeenCalledWith(true);
    expect(escape).toHaveBeenCalledWith(true, onDismiss);
  });

  it("does not promise an auto-close for a read-only brokerage row", () => {
    const external: ExpiryLoginRow = { ...row, key: "NVDA", positionId: null, symbol: "NVDA" };
    const html = renderToStaticMarkup(
      <ExpiryLoginCertificate items={[external]} isPaper onDismiss={() => undefined} />,
    );
    expect(html).toContain(EXPIRY_LOGIN_BROKER_SETTLES);
    expect(html).not.toContain(EXPIRY_LOGIN_AUTO_CLOSE);
    expect(html).toContain('data-testid="expiry-login-settles-NVDA">Your broker<');
  });

  it("keeps the auto-close promise off a real brokerage account", () => {
    const html = renderToStaticMarkup(
      <ExpiryLoginCertificate items={[row]} isPaper={false} onDismiss={() => undefined} />,
    );
    expect(html).not.toContain("PAPER TRADE");
    expect(html).not.toContain(EXPIRY_LOGIN_AUTO_CLOSE);
    expect(html).toContain(EXPIRY_LOGIN_BROKER_SETTLES);
  });
});
