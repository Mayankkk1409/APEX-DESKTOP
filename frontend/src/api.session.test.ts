import { afterEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, refreshDelayMs, restoreSession, setAccessToken } from "./api";
import { pathAfterSessionRestore } from "./pages/Login";
import { useSession } from "./store";

const SCREENS = ["/dashboard", "/app", "/scan", "/portfolio", "/settings"] as const;
const ACCESS_TTL_SEC = 900;
const REFRESH_IN_SEC = 840;

function jwt(expSeconds: number): string {
  const payload = Buffer.from(JSON.stringify({ exp: expSeconds, typ: "access", sub: "user" })).toString("base64url");
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.sig`;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("silent session refresh", () => {
  afterEach(() => {
    setAccessToken(null);
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("refreshes through a simulated two-hour session without logging out", async () => {
    vi.useFakeTimers();
    const assign = vi.fn();
    const localWrites: string[] = [];
    vi.stubGlobal("window", { location: { pathname: "/scan", assign } });
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: (key: string, value: string) => {
        localWrites.push(`${key}=${value}`);
      },
      removeItem: () => undefined,
    });

    let refreshes = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = String(input);
        expect(init?.credentials).toBe("include");
        expect(new Headers(init?.headers).get("authorization")).toBeNull();
        refreshes += 1;
        const exp = Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC;
        expect(url).toContain("/auth/refresh");
        return jsonResponse({
          access_token: jwt(exp),
          expires_in: ACCESS_TTL_SEC,
          refresh_in: REFRESH_IN_SEC,
        });
      }),
    );

    setAccessToken(jwt(Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC), ACCESS_TTL_SEC, REFRESH_IN_SEC);
    for (let minute = 0; minute < 120; minute += 1) {
      await vi.advanceTimersByTimeAsync(60_000);
      expect(getAccessToken(), `still signed in after ${minute + 1} minutes`).toBeTruthy();
    }
    expect(assign).not.toHaveBeenCalled();
    expect(refreshes).toBe(8);
    const token = getAccessToken() ?? "";
    expect(localWrites.join("\n")).not.toContain(token);
    expect(refreshDelayMs({ refreshInSec: REFRESH_IN_SEC })).toBe(REFRESH_IN_SEC * 1000);
  });

  it("reloads every screen from the refresh cookie without a memory token", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/portfolio", assign } });
    const next = jwt(Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ access_token: next, expires_in: ACCESS_TTL_SEC, refresh_in: REFRESH_IN_SEC })),
    );
    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
    await expect(restoreSession()).resolves.toBe(true);
    expect(getAccessToken()).toBe(next);
    for (const screen of SCREENS) {
      expect(pathAfterSessionRestore(screen)).toBe(screen);
      expect(getAccessToken()).toBe(next);
    }
    expect(assign).not.toHaveBeenCalled();
  });

  it("retries an expired access token mid-scan and keeps the scan", async () => {
    const assign = vi.fn();
    const localWrites: string[] = [];
    vi.stubGlobal("window", { location: { pathname: "/scan", assign } });
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: (key: string, value: string) => {
        localWrites.push(`${key}=${value}`);
      },
      removeItem: () => undefined,
    });
    const bars = [{ t: "2026-10-01T00:00:00Z", o: 1, h: 2, l: 0.5, c: 1.5, v: 10 }];
    const recommendation = {
      symbol: "AAPL",
      expiry: "2026-10-16",
      strike: 320,
      side: "put" as const,
      contract_id: null,
    };
    useSession.getState().setSymbol("AAPL");
    useSession.getState().setExpiry("2026-10-16");
    useSession.getState().setRecommendedContract(recommendation);
    useSession.getState().captureSnapshot(
      {
        symbol: "AAPL",
        timeframe: "1D",
        visible_from: "2026-01-01T00:00:00+00:00",
        visible_to: "2026-10-05T00:00:00+00:00",
        studies: [],
        captured_at: "2026-10-05T00:00:00+00:00",
      },
      null,
      false,
      bars,
    );

    const fresh = jwt(Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC);
    let scans = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        const url = String(input);
        if (url.includes("/auth/refresh")) {
          return jsonResponse({ access_token: fresh, expires_in: ACCESS_TTL_SEC, refresh_in: REFRESH_IN_SEC });
        }
        scans += 1;
        if (scans === 1) return jsonResponse({ detail: "Invalid access token" }, 401);
        return jsonResponse({ ok: true, symbol: "AAPL" });
      }),
    );

    setAccessToken(jwt(Math.floor(Date.now() / 1000) - 30), ACCESS_TTL_SEC, REFRESH_IN_SEC);
    const { api } = await import("./api");
    const body = await api.scan(
      {
        symbol: "AAPL",
        timeframe: "1D",
        visible_from: "2026-01-01T00:00:00+00:00",
        visible_to: "2026-10-05T00:00:00+00:00",
        studies: [],
        captured_at: "2026-10-05T00:00:00+00:00",
      },
      "2026-10-16",
    );
    expect(body).toMatchObject({ ok: true, symbol: "AAPL" });
    expect(scans).toBe(2);
    expect(useSession.getState().symbol).toBe("AAPL");
    expect(useSession.getState().expiry).toBe("2026-10-16");
    expect(useSession.getState().capturedBars).toEqual(bars);
    expect(useSession.getState().recommendedContract).toEqual(recommendation);
    expect(assign).not.toHaveBeenCalled();
    expect(localWrites.join("\n")).not.toContain(fresh);
  });

  it("logs out when the refresh cookie is rejected", async () => {
    const assign = vi.fn();
    const mem = new Map<string, string>();
    vi.stubGlobal("window", { location: { pathname: "/settings", assign } });
    vi.stubGlobal("sessionStorage", {
      getItem: (key: string) => mem.get(key) ?? null,
      setItem: (key: string, value: string) => {
        mem.set(key, value);
      },
      removeItem: (key: string) => {
        mem.delete(key);
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        if (String(input).includes("/auth/refresh")) return jsonResponse({ detail: "Invalid refresh" }, 401);
        return jsonResponse({ detail: "Invalid access token" }, 401);
      }),
    );
    setAccessToken("old-access");
    const { api } = await import("./api");
    await expect(api.me()).rejects.toThrow("Invalid access token");
    expect(getAccessToken()).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
    expect(mem.get("apex_auth_redirect")).toBe("Invalid access token");
  });

  it("stays signed in when a portfolio refresh is rejected and the access token is still valid", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/app", assign } });
    const token = jwt(Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo) => {
        if (String(input).includes("/auth/refresh")) return jsonResponse({ detail: "Invalid refresh" }, 401);
        return jsonResponse({ detail: "Invalid access token" }, 401);
      }),
    );
    setAccessToken(token, ACCESS_TTL_SEC, REFRESH_IN_SEC);
    const { api } = await import("./api");
    await expect(api.portfolio()).rejects.toThrow("Invalid access token");
    expect(getAccessToken()).toBe(token);
    expect(assign).not.toHaveBeenCalled();
  });

  it("does not clear the session when a sign-in code is rejected", async () => {
    const assign = vi.fn();
    vi.stubGlobal("window", { location: { pathname: "/login", assign } });
    const token = jwt(Math.floor(Date.now() / 1000) + ACCESS_TTL_SEC);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "Invalid or expired code" }, 401)),
    );
    setAccessToken(token, ACCESS_TTL_SEC, REFRESH_IN_SEC);
    const { api } = await import("./api");
    await expect(api.otpVerify("ada", "000000")).rejects.toThrow("Invalid or expired code");
    expect(getAccessToken()).toBe(token);
    expect(assign).not.toHaveBeenCalled();
  });
});
