import { describe, expect, it } from "vitest";
import { apiProxyOptions, forwardProxyCookie } from "./devProxy";

describe("dev proxy cookies", () => {
  it("stores the refresh cookie on the Vite host and forwards Cookie", () => {
    const options = apiProxyOptions("http://127.0.0.1:8000");
    expect(options.changeOrigin).toBe(true);
    expect(options.cookieDomainRewrite).toBe("");

    const headers: Record<string, string> = {};
    const proxyReq = {
      setHeader(name: string, value: string) {
        headers[name] = value;
      },
    };
    forwardProxyCookie(proxyReq, { headers: { cookie: "apex_refresh=not-a-real-token" } });
    expect(headers.cookie).toBe("apex_refresh=not-a-real-token");

    let wired: ((proxyReq: typeof proxyReq, req: { headers?: { cookie?: string } }) => void) | null = null;
    options.configure({
      on(_event, listener) {
        wired = listener;
      },
    });
    expect(wired).toBeTypeOf("function");
    headers.cookie = "";
    wired!(proxyReq, { headers: { cookie: "apex_refresh=from-browser" } });
    expect(headers.cookie).toBe("apex_refresh=from-browser");
  });
});
