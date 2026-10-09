import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SignupNoticeDialog } from "./SignupNoticeDialog";
import { INVALID_SIGNUP_EMAIL_MESSAGE, signupEmailNotSentMessage } from "../lib/signupConfirmation";

describe("SignupNoticeDialog", () => {
  it("tells the user an invalid email did not create an account", () => {
    const html = renderToStaticMarkup(
      <SignupNoticeDialog
        title="Account not created"
        message={INVALID_SIGNUP_EMAIL_MESSAGE}
        testId="account-not-created"
        onClose={() => undefined}
      />,
    );
    expect(INVALID_SIGNUP_EMAIL_MESSAGE).toBe(
      "That email address is not valid, so the account was not created and no email was sent.",
    );
    expect(html).toContain('role="dialog"');
    expect(html).toContain("Account not created");
    expect(html).toContain("That email address is not valid, so the account was not created and no email was sent.");
    expect(html).toContain("order-cert-stack");
    expect(html).toContain("order-cert-title");
    expect(html).toContain("order-cert-copy");
    expect(html).toContain("order-cert-dismiss");
    expect(html).toContain("items-center");
    expect(html).toContain("justify-center");
    expect(html).toContain('data-testid="account-not-created-close"');
    expect(html).toContain(">Close<");
    expect(html).toMatch(/order-cert-stack[\s\S]*order-cert-title[\s\S]*order-cert-copy[\s\S]*order-cert-dismiss/);
    expect(html).not.toContain("{");
    expect(html).not.toContain("FormSubmit");
  });

  it("tells the user the account exists when the confirmation email fails", () => {
    const message = signupEmailNotSentMessage("ada@company.com");
    const html = renderToStaticMarkup(
      <SignupNoticeDialog
        title="Email not sent"
        message={message}
        testId="signup-email-not-sent"
        onClose={() => undefined}
      />,
    );
    expect(message).toBe(
      "Your account was created, and the confirmation email to ada@company.com could not be sent.",
    );
    expect(html).toContain('role="dialog"');
    expect(html).toContain("Email not sent");
    expect(html).toContain("Your account was created, and the confirmation email to ada@company.com could not be sent.");
    expect(html).toContain("order-cert-stack");
    expect(html).toContain("order-cert-title");
    expect(html).toContain("order-cert-copy");
    expect(html).toContain("order-cert-dismiss");
    expect(html).toContain("items-center");
    expect(html).toContain("justify-center");
    expect(html).toContain('data-testid="signup-email-not-sent-close"');
    expect(html).toContain(">Close<");
    expect(html).toMatch(/order-cert-stack[\s\S]*order-cert-title[\s\S]*order-cert-copy[\s\S]*order-cert-dismiss/);
    expect(html).not.toContain("{");
    expect(html).not.toContain("success");
    expect(html).not.toContain("status");
    expect(html).not.toContain("FormSubmit");
  });
});
