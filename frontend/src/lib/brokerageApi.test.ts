import { afterEach, describe, expect, it, vi } from "vitest";
import { getAccessToken, setAccessToken } from "../api";
import { brokerageApi } from "./brokerageApi";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("brokerage fetch", () => {
  afterEach(() => {
    setAccessToken(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("retries once after the silent refresh on 401", async () => {
    setAccessToken("expired-access");
    const writes: string[] = [];
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: (key: string, value: string) => {
        writes.push(`${key}=${value}`);
      },
      removeItem: () => undefined,
    });
    const headers: string[] = [];
    let accountCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo, init?: RequestInit) => {
        const url = String(input);
        headers.push(new Headers(init?.headers).get("Authorization") ?? "");
        if (url.includes("/auth/refresh")) {
          return jsonResponse({ access_token: "refreshed-access", expires_in: 900, refresh_in: 840 });
        }
        accountCalls += 1;
        if (accountCalls === 1) return jsonResponse({ detail: "Invalid access token" }, 401);
        return jsonResponse({ connection_status: "connected", accounts: [] });
      }),
    );

    const body = await brokerageApi.accounts();
    expect(accountCalls).toBe(2);
    expect(body.connection_status).toBe("connected");
    expect(getAccessToken()).toBe("refreshed-access");
    expect(headers).toContain("Bearer refreshed-access");
    expect(writes.join(" ")).not.toContain("refreshed-access");
    expect(writes.join(" ")).not.toContain("expired-access");
  });
});
