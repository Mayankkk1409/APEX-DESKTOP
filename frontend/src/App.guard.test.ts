import { afterEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, restoreSession, setAccessToken } from "./api";
import { resolveAuthGuard } from "./App";
import { useSession } from "./store";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("auth guard", () => {
  afterEach(() => {
    setAccessToken(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("waits for restoreSession before a missing token is logged out", async () => {
    let waited = false;
    const allowed = await resolveAuthGuard({
      token: null,
      restore: async () => {
        waited = true;
        return true;
      },
    });
    expect(waited).toBe(true);
    expect(allowed).toBe(true);
    const denied = await resolveAuthGuard({
      token: null,
      restore: async () => false,
    });
    expect(denied).toBe(false);
  });

  it("does not clear scan fields when restore succeeds", async () => {
    useSession.setState({ symbol: "AAPL", expiry: "2026-10-16" });
    setAccessToken(null);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ access_token: "restored-access", expires_in: 900, refresh_in: 840 })),
    );
    const allowed = await resolveAuthGuard({
      token: getAccessToken(),
      restore: restoreSession,
    });
    expect(allowed).toBe(true);
    expect(useSession.getState().symbol).toBe("AAPL");
    expect(useSession.getState().expiry).toBe("2026-10-16");
    expect(getAccessToken()).toBe("restored-access");
  });
});
