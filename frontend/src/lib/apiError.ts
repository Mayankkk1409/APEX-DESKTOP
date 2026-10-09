/** One plain sentence for an API failure. Measured order checks stay in orderRefusal. */

export const OTP_CODE_INVALID = "That code is invalid or expired.";
export const NETWORK_UNAVAILABLE = "The connection failed, so the request did not go through.";
export const SESSION_ENDED = "Sign in again to continue.";
export const CREDENTIALS_REJECTED = "That username or password was not accepted.";
export const RATE_LIMITED = "Too many attempts — wait a moment and try again.";
export const SERVER_UNAVAILABLE = "APEX could not complete that request.";
export const SIGN_IN_INCOMPLETE = "Sign-in did not complete.";
export const ACCOUNT_NOT_CREATED = "The account was not created.";
export const SIGNUP_NETWORK = "The connection failed, so the account was not created.";
export const ORDER_NOT_SUBMITTED = "The order was not submitted.";
export const ORDER_NETWORK = "The connection failed, so the order was not submitted.";
export const ORDER_SESSION = "Sign in again before submitting this order.";

export type ApiErrorScope = "login" | "signup" | "order";
export type ApiErrorKind = "otp" | "network" | "unauthorized" | "credentials" | "rate-limit" | "server" | "opaque";

export type LoginFailureDialog = {
  title: string;
  message: string;
  testId: string;
};

const ORDER_SENTENCES = new Set<string>([
  ORDER_NOT_SUBMITTED,
  ORDER_NETWORK,
  ORDER_SESSION,
  RATE_LIMITED,
  SERVER_UNAVAILABLE,
  OTP_CODE_INVALID,
]);

const LOGIN_DIALOG: Record<ApiErrorKind, LoginFailureDialog> = {
  otp: { title: "Code not accepted", message: OTP_CODE_INVALID, testId: "login-code-invalid" },
  network: { title: "Could not reach APEX", message: NETWORK_UNAVAILABLE, testId: "login-network" },
  unauthorized: { title: "Sign in again", message: SESSION_ENDED, testId: "login-session" },
  credentials: { title: "Sign in not completed", message: CREDENTIALS_REJECTED, testId: "login-credentials" },
  "rate-limit": { title: "Too many attempts", message: RATE_LIMITED, testId: "login-rate-limit" },
  server: { title: "Request not completed", message: SERVER_UNAVAILABLE, testId: "login-server" },
  opaque: { title: "Sign in not completed", message: SIGN_IN_INCOMPLETE, testId: "login-api-notice" },
};

export function classifyApiError(raw: string): ApiErrorKind | null {
  const text = raw.trim();
  if (!text) return "opaque";
  if (isOpaquePayload(text)) return "opaque";
  if (isOtp(text)) return "otp";
  if (isNetwork(text)) return "network";
  if (isRateLimit(text)) return "rate-limit";
  if (isServer(text)) return "server";
  if (isCredentials(text)) return "credentials";
  if (isUnauthorized(text)) return "unauthorized";
  return null;
}

export function isSettledOrderSentence(raw: string): boolean {
  return ORDER_SENTENCES.has(raw.trim());
}

/** Null when the text is already a sentence the screen can show. */
export function apiErrorSentence(raw: string, scope: ApiErrorScope): string | null {
  const kind = classifyApiError(raw);
  if (!kind) return null;
  if (scope === "order") return orderSentence(kind);
  if (scope === "signup") return signupSentence(kind);
  return LOGIN_DIALOG[kind].message;
}

export function userFacingApiError(raw: string, scope: ApiErrorScope): string {
  return apiErrorSentence(raw, scope) ?? polishPlain(raw) ?? fallback(scope);
}

/** Certificate copy for a sign-in failure that is not a missing-email or send failure. */
export function loginFailureDialog(raw: string): LoginFailureDialog {
  const kind = classifyApiError(raw);
  if (kind) return LOGIN_DIALOG[kind];
  return {
    title: "Sign in not completed",
    message: polishPlain(raw) ?? SIGN_IN_INCOMPLETE,
    testId: "login-api-notice",
  };
}

export function signupFailureMessage(raw: string): string {
  return userFacingApiError(raw, "signup");
}

function orderSentence(kind: ApiErrorKind): string {
  if (kind === "network") return ORDER_NETWORK;
  if (kind === "unauthorized" || kind === "credentials") return ORDER_SESSION;
  if (kind === "rate-limit") return RATE_LIMITED;
  if (kind === "server") return SERVER_UNAVAILABLE;
  if (kind === "otp") return OTP_CODE_INVALID;
  return ORDER_NOT_SUBMITTED;
}

function signupSentence(kind: ApiErrorKind): string {
  if (kind === "network") return SIGNUP_NETWORK;
  if (kind === "rate-limit") return RATE_LIMITED;
  if (kind === "server") return SERVER_UNAVAILABLE;
  if (kind === "otp") return OTP_CODE_INVALID;
  if (kind === "unauthorized" || kind === "credentials") return SESSION_ENDED;
  return ACCOUNT_NOT_CREATED;
}

function fallback(scope: ApiErrorScope): string {
  if (scope === "order") return ORDER_NOT_SUBMITTED;
  if (scope === "signup") return ACCOUNT_NOT_CREATED;
  return SIGN_IN_INCOMPLETE;
}

function polishPlain(raw: string): string | null {
  const text = raw.replace(/\s+/g, " ").trim();
  if (!text || isOpaquePayload(text)) return null;
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function isOtp(text: string): boolean {
  return /invalid or expired code|password reset expired|code has expired|expired code/i.test(text);
}

function isNetwork(text: string): boolean {
  return /cannot reach apex|failed to fetch|networkerror|network error|load failed|econnrefused|the connection failed/i.test(text);
}

function isRateLimit(text: string): boolean {
  return /too many requests|rate limit|\bHTTP\s*429\b|\bstatus(?: code)?\s*429\b/i.test(text);
}

function isServer(text: string): boolean {
  return /internal server error|brokerage service error|bad gateway|service unavailable|gateway timeout|\bHTTP\s*5\d\d\b|\bstatus(?: code)?\s*5\d\d\b/i.test(text);
}

function isCredentials(text: string): boolean {
  return /invalid username or password|username or password was not accepted/i.test(text);
}

function isUnauthorized(text: string): boolean {
  return /unauthorized|missing access token|invalid access token|session expired|missing refresh|invalid refresh|refresh revoked|sign in again/i.test(text);
}

function isOpaquePayload(text: string): boolean {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return true;
  if (/traceback \(most recent call last\)/i.test(trimmed)) return true;
  if (/\n\s*at\s+.+\(.+:\d+:\d+\)/.test(trimmed)) return true;
  if (/[{[][\s\S]*[}\]]/.test(trimmed)) return true;
  return false;
}
