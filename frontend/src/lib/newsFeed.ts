/** Alpaca news rate-limit copy. The desk retries later and never prints this string. */
const RATE_LIMIT_MS = 60_000;

const retryAt = new Map<string, number>();

export function isNewsRateLimitMessage(text: string | null | undefined): boolean {
  if (!text) return false;
  return /HTTP\s*429\b/i.test(text) || (/\b429\b/.test(text) && /news feed|too many requests|rate limit/i.test(text));
}

/** Drop rate-limit sentences. Other provider errors stay visible. */
export function scrubRateLimitCopy(text: string | null | undefined): string {
  if (!text) return "";
  if (!isNewsRateLimitMessage(text)) return text;
  return text
    .split(/(?<=[.!?])\s+/)
    .filter((sentence) => !isNewsRateLimitMessage(sentence))
    .join(" ")
    .trim();
}

export function visibleNewsError(error: string | null | undefined): string | null {
  if (!error || isNewsRateLimitMessage(error)) return null;
  return error;
}

export function noteNewsRateLimit(key: string): void {
  const existing = retryAt.get(key);
  if (existing != null && existing > Date.now()) return;
  retryAt.set(key, Date.now() + RATE_LIMIT_MS);
}

export function clearNewsRetry(key: string): void {
  retryAt.delete(key);
}

/** Wait at least a minute between attempts so a 429 is not polled in a tight loop. */
export function newsRetryDelay(key: string): number | false {
  const at = retryAt.get(key);
  if (at == null) return false;
  const wait = at - Date.now();
  return wait > 1000 ? wait : RATE_LIMIT_MS;
}
