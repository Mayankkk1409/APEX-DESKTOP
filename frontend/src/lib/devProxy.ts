type HeaderWriter = { setHeader: (name: string, value: string) => void };
type Incoming = { headers?: { cookie?: string | string[] | undefined } };
type ProxyWithEvents = {
  on: (event: "proxyReq", listener: (proxyReq: HeaderWriter, req: Incoming) => void) => void;
};

/** Copy the browser Cookie header onto the proxied API request. */
export function forwardProxyCookie(proxyReq: HeaderWriter, req: Incoming): void {
  const cookie = req.headers?.cookie;
  const value = Array.isArray(cookie) ? cookie.join("; ") : cookie;
  if (value) proxyReq.setHeader("cookie", value);
}

/**
 * Same-origin dev proxy so the httpOnly refresh cookie is stored for the Vite host.
 * cookieDomainRewrite "" removes Domain (http-proxy: empty string clears it).
 */
export function apiProxyOptions(target: string) {
  return {
    target,
    changeOrigin: true,
    cookieDomainRewrite: "" as const,
    configure(proxy: ProxyWithEvents) {
      proxy.on("proxyReq", (proxyReq, req) => {
        forwardProxyCookie(proxyReq, req);
      });
    },
  };
}
