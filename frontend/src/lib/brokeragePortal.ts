import { api } from "../api";

/** Hostname of a SnapTrade connection-portal URL, or null when it is not one. */
export function snapTradePortalHostname(url: string): string | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.toLowerCase();
  if (!host.includes("snaptrade")) return null;
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return null;
  return host;
}

/**
 * Register the SnapTrade user when needed, then leave this app for the
 * connection portal. SnapTrade's login link is a full-page redirectURI.
 */
export async function openSnapTradeConnectionPortal(
  assign: (url: string) => void = (url) => {
    window.location.assign(url);
  },
): Promise<void> {
  await api.brokerageRegister();
  const { url } = await api.brokeragePortalUrl();
  if (!snapTradePortalHostname(url)) {
    throw new Error("SnapTrade did not return a connection portal URL");
  }
  assign(url);
}
