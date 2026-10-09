const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1"]);

/**
 * Keep browser calls on the page origin when the configured API is another
 * loopback host. http://127.0.0.1 and http://localhost are different sites, so a
 * SameSite device cookie set by one is never sent to the other.
 */
export function browserApiBase(configured: string | undefined, pageOrigin: string): string {
  const value = (configured ?? "").trim();
  if (!value) return "";
  let target: URL;
  let page: URL;
  try {
    target = new URL(value);
    page = new URL(pageOrigin);
  } catch {
    return value;
  }
  if (target.origin === page.origin) return value.replace(/\/$/, "");
  if (LOOPBACK.has(target.hostname) && LOOPBACK.has(page.hostname)) return "";
  return value.replace(/\/$/, "");
}
