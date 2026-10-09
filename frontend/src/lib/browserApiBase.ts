const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1"]);

/**
 * Call the API on the same loopback host as the page.
 * http://127.0.0.1 and http://localhost are different sites, so a SameSite
 * device cookie set by one is never sent to the other. A desk opened at
 * http://127.0.0.1:5173 therefore calls http://127.0.0.1:8000, not localhost.
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
  if (LOOPBACK.has(target.hostname) && LOOPBACK.has(page.hostname)) {
    const port = target.port ? `:${target.port}` : "";
    return `${target.protocol}//${page.hostname}${port}`;
  }
  return value.replace(/\/$/, "");
}
