import { describe, expect, it } from "vitest";
import { loginCodeNotice, NO_SIGNIN_EMAIL, SIGNIN_CODE_NOT_SENT } from "./loginCode";

describe("loginCodeNotice", () => {
  it("recognizes a missing email and a failed send", () => {
    expect(loginCodeNotice(NO_SIGNIN_EMAIL)).toBe("no-email");
    expect(loginCodeNotice(SIGNIN_CODE_NOT_SENT)).toBe("send-failed");
    expect(loginCodeNotice("Invalid username or password")).toBeNull();
    expect(loginCodeNotice("Invalid or expired code")).toBe("otp-invalid");
    expect(loginCodeNotice("Password reset expired — request a new code")).toBe("otp-invalid");
  });
});
