export type MarketSocketMessage = {
  type?: string;
  seq?: number;
  balance?: number;
  buying_power?: number;
  portfolio_value?: number;
  quotes?: unknown;
};

export type MarketSocket = {
  readyState: number;
  onopen: (() => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onerror: (() => void) | null;
  onclose: ((ev: { code: number }) => void) | null;
  send: (data: string) => void;
  close: (code?: number) => void;
};

const OPEN = 1;
const CLOSING = 2;
const CLOSED = 3;

/** Auth rejection. A proxy drop or API reload must still reconnect. */
const TERMINAL_CLOSE = new Set([4401, 1008]);

export function marketSocketUrl(base: string, token: string): string {
  const trimmed = base.replace(/\/$/, "");
  return `${trimmed}/ws/market?token=${encodeURIComponent(token)}`;
}

export function nextReconnectDelay(attempt: number): number {
  const step = Math.min(Math.max(attempt, 0), 4);
  return Math.min(800 * 2 ** step, 8000);
}

export function shouldReconnect(code: number, stopped: boolean): boolean {
  if (stopped) return false;
  return !TERMINAL_CLOSE.has(code);
}

export function connectMarketSocket(opts: {
  url: string;
  getSymbols?: () => string[];
  onMessage: (msg: MarketSocketMessage) => void;
  WebSocketImpl?: new (url: string) => MarketSocket;
  schedule?: (fn: () => void, ms: number) => number;
  cancel?: (id: number) => void;
}): { close: () => void; send: (data: string) => boolean } {
  const WSImpl = opts.WebSocketImpl ?? (globalThis.WebSocket as unknown as new (url: string) => MarketSocket);
  const schedule = opts.schedule ?? ((fn, ms) => setTimeout(fn, ms) as unknown as number);
  const cancel = opts.cancel ?? ((id) => clearTimeout(id));

  let stopped = false;
  let attempt = 0;
  let timer: number | null = null;
  let socket: MarketSocket | null = null;

  const clearTimer = () => {
    if (timer == null) return;
    cancel(timer);
    timer = null;
  };

  const send = (data: string) => {
    if (!socket || socket.readyState !== OPEN) return false;
    try {
      socket.send(data);
      return true;
    } catch {
      return false;
    }
  };

  const connect = () => {
    if (stopped) return;
    clearTimer();
    const ws = new WSImpl(opts.url);
    socket = ws;

    ws.onopen = () => {
      if (stopped || socket !== ws) return;
      attempt = 0;
      const symbols = (opts.getSymbols?.() ?? []).filter(Boolean);
      if (symbols.length) send(JSON.stringify({ type: "subscribe", symbols }));
    };

    ws.onmessage = (ev) => {
      if (stopped || socket !== ws) return;
      let msg: MarketSocketMessage;
      try {
        msg = JSON.parse(String(ev.data)) as MarketSocketMessage;
      } catch {
        return;
      }
      if (!msg || typeof msg !== "object") return;
      opts.onMessage(msg);
    };

    ws.onerror = () => {
      // The Vite proxy reports EPIPE here when the API socket is already gone.
      // Closing lets onclose reconnect. This is not an order rejection.
      if (ws.readyState === CLOSING || ws.readyState === CLOSED) return;
      ws.close();
    };

    ws.onclose = (ev) => {
      if (socket === ws) socket = null;
      if (!shouldReconnect(ev?.code ?? 1006, stopped)) return;
      if (timer != null) return;
      const delay = nextReconnectDelay(attempt);
      attempt = Math.min(attempt + 1, 4);
      timer = schedule(() => {
        timer = null;
        connect();
      }, delay);
    };
  };

  connect();

  return {
    send,
    close: () => {
      stopped = true;
      clearTimer();
      if (socket && socket.readyState !== CLOSED) socket.close();
      socket = null;
    },
  };
}
