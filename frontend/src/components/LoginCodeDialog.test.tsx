import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LoginCodeDialog } from "./LoginCodeDialog";
import { OTP_CODE_INVALID } from "../lib/apiError";
import { NO_SIGNIN_EMAIL, SIGNIN_CODE_NOT_SENT } from "../lib/loginCode";

describe("LoginCodeDialog", () => {
  it("centers the missing-email notice", () => {
    const html = renderToStaticMarkup(<LoginCodeDialog kind="no-email" onClose={() => undefined} />);
    expect(html).toContain('data-testid="login-no-email"');
    expect(html).toContain(NO_SIGNIN_EMAIL);
    expect(html).toContain("order-cert-stack");
    expect(html).toMatch(/order-cert-stack[\s\S]*order-cert-title[\s\S]*order-cert-copy[\s\S]*order-cert-dismiss/);
  });

  it("centers an invalid or expired code", () => {
    const html = renderToStaticMarkup(<LoginCodeDialog kind="otp-invalid" onClose={() => undefined} />);
    expect(html).toContain('data-testid="login-code-invalid"');
    expect(html).toContain("Code not accepted");
    expect(html).toContain(OTP_CODE_INVALID);
    expect(html).toContain("order-cert-stack");
    expect(html).not.toContain("{");
    expect(html).not.toContain("Proceed");
  });

  it("centers the send-failed notice", () => {
    const html = renderToStaticMarkup(<LoginCodeDialog kind="send-failed" onClose={() => undefined} />);
    expect(html).toContain('data-testid="login-code-not-sent"');
    expect(html).toContain(SIGNIN_CODE_NOT_SENT);
    expect(html).toContain("order-cert-stack");
    expect(html).toMatch(/order-cert-stack[\s\S]*order-cert-title[\s\S]*order-cert-copy[\s\S]*order-cert-dismiss/);
  });
});
