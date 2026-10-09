/** Signup confirmation checks. The API sends the mail; this module does not call FormSubmit. */

export const INVALID_SIGNUP_EMAIL_MESSAGE =
  "That email address is not valid, so the account was not created and no email was sent.";

const PLACEHOLDER_LOCALS = new Set([
  "abc",
  "asdf",
  "asdfasdf",
  "asdfg",
  "bar",
  "email",
  "example",
  "fake",
  "foo",
  "name",
  "none",
  "null",
  "qwerty",
  "qwertyuiop",
  "temp",
  "test",
  "tmp",
  "user",
  "xxx",
]);

const PLACEHOLDER_DOMAIN_LABELS = new Set([
  "abc",
  "asdf",
  "asdfasdf",
  "asdfg",
  "bar",
  "email",
  "example",
  "fake",
  "foo",
  "invalid",
  "localhost",
  "mail",
  "none",
  "null",
  "qwerty",
  "temp",
  "test",
  "tmp",
  "xxx",
]);

/** Last three characters stay visible. Each earlier character is one asterisk. */
export function maskSignupPassword(password: string): string {
  if (password.length <= 3) return password;
  return `${"*".repeat(password.length - 3)}${password.slice(-3)}`;
}

/** Strict format and placeholder check. This does not look up MX or DNS. */
export function isRejectedSignupEmail(raw: string): boolean {
  if (!raw || !raw.trim()) return true;
  if (/\s/.test(raw)) return true;
  const email = raw.trim();
  const at = email.indexOf("@");
  if (at <= 0 || email.lastIndexOf("@") !== at) return true;
  const local = email.slice(0, at);
  const domain = email.slice(at + 1);
  if (!local || local.length < 2 || !domain.includes(".")) return true;
  if (!/[a-z]/i.test(domain)) return true;
  const labels = domain.split(".");
  if (labels.some((label) => label.length < 2)) return true;
  if (!/[a-z]/i.test(labels[labels.length - 1] ?? "")) return true;
  const localKey = local.toLowerCase();
  const stem = labels[0]?.toLowerCase() ?? "";
  if (PLACEHOLDER_LOCALS.has(localKey)) return true;
  if (labels.some((label) => PLACEHOLDER_DOMAIN_LABELS.has(label.toLowerCase()))) return true;
  if (localKey === stem) return true;
  return false;
}

export function signupEmailNotSentMessage(email: string): string {
  return `Your account was created, and the confirmation email to ${email.trim()} could not be sent.`;
}

export function signupEmailSentMessage(email: string): string {
  return `A confirmation email was sent to ${email.trim()}.`;
}
