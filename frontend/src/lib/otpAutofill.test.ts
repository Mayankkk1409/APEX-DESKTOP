import { describe, expect, it } from "vitest";
import { resolveAutofillCode } from "./otpAutofill";

describe("resolveAutofillCode", () => {
  it("accepts a 6-digit dev autofill code", () => {
    expect(resolveAutofillCode("123456")).toBe("123456");
  });

  it("rejects missing or malformed codes", () => {
    expect(resolveAutofillCode(null)).toBe("");
    expect(resolveAutofillCode("12345")).toBe("");
    expect(resolveAutofillCode("abcdef")).toBe("");
  });
});
