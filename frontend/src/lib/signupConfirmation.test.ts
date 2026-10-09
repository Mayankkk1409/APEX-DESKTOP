import { describe, expect, it } from "vitest";
import {
  isRejectedSignupEmail,
  maskSignupPassword,
  signupEmailNotSentMessage,
  signupEmailSentMessage,
} from "./signupConfirmation";

const PASSWORD = "test-abc";

describe("signup confirmation mail", () => {
  it("masks every character except the last three", () => {
    const masked = maskSignupPassword(PASSWORD);
    expect(masked).toBe("*****abc");
    expect(masked).toHaveLength(PASSWORD.length);
    expect(masked.endsWith(PASSWORD.slice(-3))).toBe(true);
    expect(new Set(masked.slice(0, -3))).toEqual(new Set(["*"]));
    expect(masked.includes(PASSWORD.slice(0, -3))).toBe(false);

    expect(maskSignupPassword("wxyz")).toBe("*xyz");
    expect(maskSignupPassword("abc")).toBe("abc");
    expect(maskSignupPassword("ab")).toBe("ab");
  });

  it("names only the address from that signup in the result dialogs", () => {
    const first = "ada.lovelace@company.com";
    const second = "grace.hopper@laboratory.org";
    const firstFailed = signupEmailNotSentMessage(first);
    const secondFailed = signupEmailNotSentMessage(second);
    const firstSent = signupEmailSentMessage(first);
    const secondSent = signupEmailSentMessage(second);
    expect(firstFailed).toContain(first);
    expect(firstFailed).not.toContain(second);
    expect(secondFailed).toContain(second);
    expect(secondFailed).not.toContain(first);
    expect(firstSent).not.toBe(secondSent);
    expect(firstSent).not.toContain(second);
    expect(secondSent).not.toContain(first);
    expect(firstFailed).not.toContain("formsubmit");
    expect(secondFailed).not.toContain("{");
  });

  it("does not call FormSubmit for a fake or invalid address", () => {
    const rejected = ["", "   ", "ada", "ada@", "ada@gmail", "ada @company.com", "test@test.com", "a@b.c", "name@fake.com", "asdf@asdf.com", "ada@123.456", "name@fake.com "];
    for (const email of rejected) {
      expect(isRejectedSignupEmail(email)).toBe(true);
    }
    expect(isRejectedSignupEmail("ada.lovelace@company.com")).toBe(false);
    expect(isRejectedSignupEmail("grace.hopper@laboratory.org")).toBe(false);
  });
});
