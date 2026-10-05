/** Socket errors that mean the peer already hung up. They are not failed trades. */
const BENIGN_PROXY_CODES = new Set([
  "EPIPE",
  "ECONNRESET",
  "ECONNABORTED",
  "ECONNREFUSED",
  "ERR_STREAM_DESTROYED",
]);

export type ProxySocketError = { code?: string; message?: string };

export type SocketLike = {
  destroyed?: boolean;
  destroy?: () => void;
  on: (event: string, listener: (err: ProxySocketError) => void) => unknown;
};

type ProxyListener = (...args: readonly unknown[]) => void;

type UpgradeReq = {
  on: (event: "upgrade" | "error", listener: ProxyListener) => unknown;
};

export type QuietProxy = {
  on: (event: string, listener: ProxyListener) => unknown;
};

export function isBenignProxySocketError(err: ProxySocketError | null | undefined): boolean {
  if (!err) return false;
  if (err.code && BENIGN_PROXY_CODES.has(err.code)) return true;
  const message = err.message ?? "";
  return message.includes("EPIPE") || message.includes("ECONNRESET") || message.includes("ECONNREFUSED");
}

function destroyEnd(socket: SocketLike | null | undefined): void {
  if (!socket || socket.destroyed || typeof socket.destroy !== "function") return;
  try {
    socket.destroy();
  } catch {
    /* peer already closed */
  }
}

/** Hide EPIPE from Vite's logger and tear the socket down instead of writing again. */
export function swallowBenignSocketErrors(socket: SocketLike): void {
  const orig = socket.on.bind(socket);
  socket.on = ((event: string, listener: (err: ProxySocketError) => void) => {
    if (event !== "error") return orig(event, listener);
    return orig("error", (err: ProxySocketError) => {
      if (isBenignProxySocketError(err)) {
        destroyEnd(socket);
        return;
      }
      listener(err);
    });
  }) as SocketLike["on"];
}

/**
 * Vite logs `ws proxy socket error: write EPIPE` when the API process reloads
 * (or the browser closes) while the /ws pipe still has a frame to write.
 * Attach this from the proxy `configure` hook so both ends are destroyed and
 * Vite's own error listener never sees the benign close.
 */
export function attachQuietWsProxy(proxy: QuietProxy): void {
  const origOn = proxy.on.bind(proxy);

  origOn("proxyReqWs", ((proxyReq: UpgradeReq, _req: unknown, clientSocket: SocketLike) => {
    swallowBenignSocketErrors(clientSocket);
    let upstream: SocketLike | null = null;
    const kill = () => {
      destroyEnd(clientSocket);
      destroyEnd(upstream);
    };
    proxyReq.on("upgrade", ((_res: unknown, proxySocket: SocketLike) => {
      upstream = proxySocket;
      swallowBenignSocketErrors(proxySocket);
      proxySocket.on("close", kill);
      clientSocket.on("close", kill);
    }) as ProxyListener);
    proxyReq.on("error", ((err: ProxySocketError) => {
      if (isBenignProxySocketError(err)) kill();
    }) as ProxyListener);
  }) as ProxyListener);

  proxy.on = ((event: string, listener: ProxyListener) => {
    if (event === "error") {
      return origOn("error", ((err: ProxySocketError, _req: unknown, res: SocketLike) => {
        if (isBenignProxySocketError(err)) {
          destroyEnd(res);
          return;
        }
        listener(err, _req, res);
      }) as ProxyListener);
    }
    if (event === "proxyReqWs") {
      return origOn("proxyReqWs", ((proxyReq: UpgradeReq, req: unknown, socket: SocketLike, ...rest: unknown[]) => {
        swallowBenignSocketErrors(socket);
        listener(proxyReq, req, socket, ...rest);
      }) as ProxyListener);
    }
    return origOn(event, listener);
  }) as QuietProxy["on"];
}
