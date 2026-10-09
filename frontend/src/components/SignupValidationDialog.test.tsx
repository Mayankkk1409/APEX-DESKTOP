import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SignupValidationDialog } from "./SignupValidationDialog";

const EMPTY_SIGNUP_422 = [
  {
    type: "string_too_short",
    loc: ["body", "full_name"],
    msg: "String should have at least 2 characters",
    input: "",
    ctx: { min_length: 2 },
  },
  {
    type: "string_too_short",
    loc: ["body", "username"],
    msg: "String should have at least 3 characters",
    input: "",
    ctx: { min_length: 3 },
  },
  {
    type: "value_error",
    loc: ["body", "email"],
    msg: "value is not a valid email address: An email address must have an @-sign.",
    input: "",
    ctx: { reason: "An email address must have an @-sign." },
  },
  {
    type: "string_too_short",
    loc: ["body", "password"],
    msg: "String should have at least 8 characters",
    input: "",
    ctx: { min_length: 8 },
  },
];

describe("SignupValidationDialog", () => {
  it("renders the empty-field 422 body as four plain sentences", () => {
    const html = renderToStaticMarkup(<SignupValidationDialog detail={EMPTY_SIGNUP_422} onClose={() => undefined} />);
    expect(html).toContain('role="dialog"');
    expect(html).toContain("Account not created");
    expect(html).toContain("Full name needs at least 2 characters.");
    expect(html).toContain("Username needs at least 3 characters.");
    expect(html).toContain("Email must include an @.");
    expect(html).toContain("Password needs at least 8 characters.");
    expect(html).toContain('data-testid="account-not-created-close"');
    expect(html).toContain(">Close<");
    expect(html.match(/data-testid="account-not-created-reason"/g)).toHaveLength(4);
    expect(html).toContain("order-cert-stack");
    expect(html).toContain("order-cert-lines");
    expect(html).toContain("items-center");
    expect(html).toContain("justify-center");
    expect(html).toMatch(
      /order-cert-stack[\s\S]*order-cert-title[\s\S]*order-cert-lines[\s\S]*order-cert-dismiss/,
    );
    expect(html).not.toContain("string_too_short");
    expect(html).not.toContain("loc");
    expect(html).not.toContain("value_error");
  });

  it("lists only the fields that failed", () => {
    const html = renderToStaticMarkup(
      <SignupValidationDialog detail={[EMPTY_SIGNUP_422[1]]} onClose={() => undefined} />,
    );
    expect(html).toContain("Username needs at least 3 characters.");
    expect(html).not.toContain("Full name needs");
    expect(html).not.toContain("Email must");
    expect(html).not.toContain("Password needs");
    expect(html.match(/data-testid="account-not-created-reason"/g)).toHaveLength(1);
  });
});
