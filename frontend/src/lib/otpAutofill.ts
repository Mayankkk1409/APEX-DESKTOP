/** Dev OTP autofill: accept only a 6-digit code from the API. */
export function resolveAutofillCode(code: string | null | undefined): string {
  return code && /^\d{6}$/.test(code) ? code : "";
}
