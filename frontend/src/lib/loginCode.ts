/** Wait after a sign-in email before another one can be requested. */
export const RESEND_COOLDOWN_MS = 30_000;

/** Digits only, capped at the six the sign-in form sends. */
export function signInDigits(value: string): string {
  return value.replace(/\D/g, "").slice(0, 6);
}

export function resendReadyAt(nowMs: number, cooldownMs = RESEND_COOLDOWN_MS): number {
  return nowMs + cooldownMs;
}

export function resendCooling(nowMs: number, readyAtMs: number): boolean {
  return readyAtMs > nowMs;
}

/** Shown when an account has no address to receive a sign-in code. */
export const NO_SIGNIN_EMAIL = "This account has no email for a sign-in code.";

/** Shown when the sign-in code could not be emailed. */
export const SIGNIN_CODE_NOT_SENT = "The sign-in code could not be sent.";

export type LoginCodeNotice = "no-email" | "send-failed" | "otp-invalid";

/** Map a code-delivery or code-check failure to a centered notice. */
export function loginCodeNotice(message: string): LoginCodeNotice | null {
  if (message.includes("no email for a sign-in code")) return "no-email";
  if (message.includes("sign-in code could not be sent")) return "send-failed";
  if (/invalid or expired code|password reset expired|code has expired/i.test(message)) return "otp-invalid";
  return null;
}
