import { describe, expect, it } from "vitest";
import {
  loginCodeNotice,
  NO_SIGNIN_EMAIL,
  RESEND_COOLDOWN_MS,
  resendCooling,
  resendReadyAt,
  SIGNIN_CODE_NOT_SENT,
  signInDigits,
} from "./loginCode";

describe("loginCodeNotice", () => {
  it("recognizes a missing email and a failed send", () => {
    expect(loginCodeNotice(NO_SIGNIN_EMAIL)).toBe("no-email");
    expect(loginCodeNotice(SIGNIN_CODE_NOT_SENT)).toBe("send-failed");
    expect(loginCodeNotice("Invalid username or password")).toBeNull();
    expect(loginCodeNotice("Invalid or expired code")).toBe("otp-invalid");
    expect(loginCodeNotice("Password reset expired — request a new code")).toBe("otp-invalid");
  });

  it("strips non-digits before a sign-in code is sent", () => {
    expect(signInDigits("12 34 56")).toBe("123456");
    expect(signInDigits("12-34-56")).toBe("123456");
    expect(signInDigits("12345699")).toBe("123456");
    expect(signInDigits("")).toBe("");
  });

  it("holds resend for 30 seconds", () => {
    const now = 1_000;
    const ready = resendReadyAt(now);
    expect(ready - now).toBe(RESEND_COOLDOWN_MS);
    expect(resendCooling(now, ready)).toBe(true);
    expect(resendCooling(ready, ready)).toBe(false);
  });
});
