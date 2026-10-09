type Issue = {
  type?: string;
  loc?: unknown;
  msg?: string;
  ctx?: {
    min_length?: number;
    max_length?: number;
    reason?: string;
  };
};

const FIELD_LABELS: Record<string, string> = {
  full_name: "Full name",
  username: "Username",
  email: "Email",
  password: "Password",
  confirm_password: "Confirm password",
  starting_balance: "Starting balance",
  account_mode: "Account mode",
};

/** Plain sentences for a FastAPI 422 `detail` array. Empty when the payload is not that shape. */
export function signupValidationLines(input: unknown): string[] {
  const issues = coerceIssues(input);
  if (!issues) return [];
  const lines: string[] = [];
  const seen = new Set<string>();
  for (const issue of issues) {
    const line = toPlainLine(issue);
    if (!line || seen.has(line)) continue;
    seen.add(line);
    lines.push(line);
  }
  return lines;
}

export function isSignupValidationPayload(input: unknown): boolean {
  return signupValidationLines(input).length > 0;
}

function coerceIssues(input: unknown): Issue[] | null {
  const value = unwrap(input);
  if (!Array.isArray(value)) return null;
  const issues = value.filter(isIssue);
  return issues.length ? issues : null;
}

function unwrap(input: unknown): unknown {
  if (typeof input === "string") {
    const trimmed = input.trim();
    if (!trimmed.startsWith("[") && !trimmed.startsWith("{")) return null;
    try {
      return unwrap(JSON.parse(trimmed) as unknown);
    } catch {
      return null;
    }
  }
  if (input && typeof input === "object" && !Array.isArray(input) && "detail" in input) {
    return (input as { detail: unknown }).detail;
  }
  return input;
}

function isIssue(value: unknown): value is Issue {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function fieldKey(issue: Issue): string | null {
  if (!Array.isArray(issue.loc)) return null;
  for (let i = issue.loc.length - 1; i >= 0; i -= 1) {
    const part = issue.loc[i];
    if (typeof part === "string" && part !== "body" && part !== "query" && part !== "path") return part;
  }
  return null;
}

function labelFor(field: string | null): string | null {
  if (!field) return null;
  const known = FIELD_LABELS[field];
  if (known) return known;
  const words = field.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function toPlainLine(issue: Issue): string | null {
  const field = fieldKey(issue);
  const label = labelFor(field);
  const type = typeof issue.type === "string" ? issue.type : "";
  const msg = typeof issue.msg === "string" ? issue.msg : "";
  const reason = typeof issue.ctx?.reason === "string" ? issue.ctx.reason : "";
  const blob = `${msg} ${reason}`;
  const min = numeric(issue.ctx?.min_length) ?? lengthFromMsg(msg, "at least");
  const max = numeric(issue.ctx?.max_length) ?? lengthFromMsg(msg, "at most");

  if (isTooShort(type, msg) && label && min != null) {
    return `${label} needs at least ${min} ${unit(min)}.`;
  }
  if (isTooLong(type, msg) && label && max != null) {
    return `${label} must be at most ${max} ${unit(max)}.`;
  }
  if (field === "email" || /email address/i.test(msg)) {
    if (/must have an @-sign/i.test(blob)) return "Email must include an @.";
    if (/after the @-sign/i.test(blob)) return "Email must include a valid domain after the @.";
    return "Email must be a valid email address.";
  }
  if (field === "username" && (type === "string_pattern_mismatch" || /match pattern/i.test(msg))) {
    return "Username can only include letters, numbers, periods, underscores, and hyphens.";
  }
  if (/passwords do not match/i.test(msg)) return "Passwords do not match.";
  if (/starting_balance is not accepted/i.test(msg)) {
    return "Starting balance is not accepted for a real brokerage account.";
  }
  if (/starting_balance must be at least/i.test(msg)) {
    const amount = msg.match(/at least (\d+)/i)?.[1] ?? "1000";
    return `Starting balance must be at least ${amount}.`;
  }
  if (type === "missing" && label) return `${label} is required.`;
  if (field === "account_mode") return "Account mode must be paper funded or real brokerage.";

  const cleaned = cleanMsg(msg);
  if (cleaned) return cleaned.endsWith(".") ? cleaned : `${cleaned}.`;
  if (label) return `${label} is not valid.`;
  return null;
}

function isTooShort(type: string, msg: string): boolean {
  return type === "string_too_short" || /at least \d+ character/i.test(msg);
}

function isTooLong(type: string, msg: string): boolean {
  return type === "string_too_long" || /at most \d+ character/i.test(msg);
}

function unit(count: number): string {
  return count === 1 ? "character" : "characters";
}

function numeric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function lengthFromMsg(msg: string, phrase: "at least" | "at most"): number | null {
  const match = msg.match(new RegExp(`${phrase} (\\d+)`, "i"));
  if (!match) return null;
  return Number(match[1]);
}

function cleanMsg(msg: string): string {
  return msg
    .replace(/^Value error,\s*/i, "")
    .replace(/^value is not a valid email address:\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
}
