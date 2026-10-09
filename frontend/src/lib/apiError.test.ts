import { describe, expect, it } from "vitest";
import {
  ACCOUNT_NOT_CREATED,
  CREDENTIALS_REJECTED,
  NETWORK_UNAVAILABLE,
  ORDER_NETWORK,
  ORDER_NOT_SUBMITTED,
  ORDER_SESSION,
  OTP_CODE_INVALID,
  RATE_LIMITED,
  SERVER_UNAVAILABLE,
  SESSION_ENDED,
  SIGNUP_NETWORK,
  SIGN_IN_INCOMPLETE,
  loginFailureDialog,
  signupFailureMessage,
  userFacingApiError,
} from "./apiError";

const JSON_ARRAY = '[{"type":"value_error","loc":["body","code"],"msg":"Invalid or expired code"}]';
const STACK = "Traceback (most recent call last):\n  File \"app.py\", line 10, in verify\nValueError: boom";

describe("userFacingApiError", () => {
  it("maps OTP, network, auth, rate limit, and server failures to one sentence", () => {
    expect(userFacingApiError("Invalid or expired code", "login")).toBe(OTP_CODE_INVALID);
    expect(userFacingApiError("Password reset expired — request a new code", "login")).toBe(OTP_CODE_INVALID);
    expect(userFacingApiError("Cannot reach APEX API. Make sure the backend is running on port 8000.", "login")).toBe(
      NETWORK_UNAVAILABLE,
    );
    expect(userFacingApiError("Failed to fetch", "login")).toBe(NETWORK_UNAVAILABLE);
    expect(userFacingApiError("Invalid username or password", "login")).toBe(CREDENTIALS_REJECTED);
    expect(userFacingApiError("Unauthorized", "login")).toBe(SESSION_ENDED);
    expect(userFacingApiError("Session expired — please sign in again.", "login")).toBe(SESSION_ENDED);
    expect(userFacingApiError("Invalid access token", "login")).toBe(SESSION_ENDED);
    expect(userFacingApiError("Too Many Requests", "login")).toBe(RATE_LIMITED);
    expect(userFacingApiError("HTTP 429", "signup")).toBe(RATE_LIMITED);
    expect(userFacingApiError("Internal Server Error", "login")).toBe(SERVER_UNAVAILABLE);
    expect(userFacingApiError("Brokerage service error. Try Refresh — if it persists, restart the backend.", "order")).toBe(
      SERVER_UNAVAILABLE,
    );
    expect(userFacingApiError("HTTP 500", "signup")).toBe(SERVER_UNAVAILABLE);
  });

  it("hides raw JSON and stack traces", () => {
    expect(userFacingApiError(JSON_ARRAY, "login")).toBe(SIGN_IN_INCOMPLETE);
    expect(userFacingApiError(STACK, "signup")).toBe(ACCOUNT_NOT_CREATED);
    expect(userFacingApiError(JSON_ARRAY, "order")).toBe(ORDER_NOT_SUBMITTED);
    for (const sentence of [
      userFacingApiError(JSON_ARRAY, "login"),
      userFacingApiError(STACK, "signup"),
      userFacingApiError(JSON_ARRAY, "order"),
    ]) {
      expect(sentence).not.toContain("{");
      expect(sentence).not.toContain("[");
      expect(sentence).not.toContain("Traceback");
      expect(sentence).not.toContain("loc");
    }
  });

  it("keeps a plain signup conflict and writes order transport as one sentence", () => {
    expect(signupFailureMessage("Username or email already registered")).toBe(
      "Username or email already registered.",
    );
    expect(signupFailureMessage("Cannot reach APEX API. Make sure the backend is running on port 8000.")).toBe(
      SIGNUP_NETWORK,
    );
    expect(userFacingApiError("Cannot reach APEX API. Make sure the backend is running on port 8000.", "order")).toBe(
      ORDER_NETWORK,
    );
    expect(userFacingApiError("Missing access token", "order")).toBe(ORDER_SESSION);
    expect(loginFailureDialog("Too Many Requests")).toEqual({
      title: "Too many attempts",
      message: RATE_LIMITED,
      testId: "login-rate-limit",
    });
  });
});
