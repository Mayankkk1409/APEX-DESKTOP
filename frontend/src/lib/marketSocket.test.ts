import { describe, expect, it } from "vitest";
import { connectMarketSocket, marketSocketUrl, nextReconnectDelay, shouldReconnect, type MarketSocket } from "./marketSocket";

class FakeSocket implements MarketSocket {
  static sockets: FakeSocket[] = [];
  url: string;
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((ev: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeSocket.sockets.push(this);
  }

  send(data: string) {
    if (this.readyState !== 1) throw new Error("not open");
    this.sent.push(data);
  }

  close(code = 1000) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.({ code });
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  /** Proxy EPIPE arrives as an error, then the browser closes the socket. */
  proxyDrop() {
    this.onerror?.();
  }
}

function harness(getSymbols?: () => string[]) {
  FakeSocket.sockets = [];
  const messages: { type?: string }[] = [];
  const pending: Array<(() => void) | null> = [];
  const delays: number[] = [];
  const conn = connectMarketSocket({
    url: marketSocketUrl("ws://127.0.0.1:5173", "tok en"),
    getSymbols,
    onMessage: (msg) => messages.push(msg),
    WebSocketImpl: FakeSocket,
    schedule: (fn, ms) => {
      delays.push(ms);
      pending.push(fn);
      return pending.length;
    },
    cancel: (id) => {
      pending[id - 1] = null;
    },
  });
  return { conn, messages, pending, delays };
}

describe("market socket", () => {
  it("builds the dashboard url through the Vite host", () => {
    expect(marketSocketUrl("ws://127.0.0.1:5173/", "a b")).toBe(
      "ws://127.0.0.1:5173/ws/market?token=a%20b",
    );
  });

  it("backs off and still reconnects after an abnormal close", () => {
    expect(nextReconnectDelay(0)).toBe(800);
    expect(nextReconnectDelay(3)).toBe(6400);
    expect(nextReconnectDelay(8)).toBe(8000);
    expect(shouldReconnect(1006, false)).toBe(true);
    expect(shouldReconnect(1000, false)).toBe(true);
    expect(shouldReconnect(4401, false)).toBe(false);
    expect(shouldReconnect(1006, true)).toBe(false);
  });

  it("treats a proxy drop as a reconnect, not a failed trade", () => {
    const { messages, pending, delays } = harness(() => ["SPX"]);
    const first = FakeSocket.sockets[0];
    first.proxyDrop();
    expect(messages).toEqual([]);
    expect(delays).toEqual([800]);
    expect(FakeSocket.sockets).toHaveLength(1);

    pending[0]?.();
    const second = FakeSocket.sockets[1];
    second.open();
    expect(JSON.parse(second.sent[0])).toEqual({ type: "subscribe", symbols: ["SPX"] });
    second.onmessage?.({ data: JSON.stringify({ type: "fill", balance: 10, buying_power: 9, portfolio_value: 11 }) });
    expect(messages).toEqual([{ type: "fill", balance: 10, buying_power: 9, portfolio_value: 11 }]);
  });

  it("ignores a torn frame and does not open a second socket for auth failure", () => {
    const { messages, pending } = harness(() => ["AAPL"]);
    const first = FakeSocket.sockets[0];
    first.open();
    first.onmessage?.({ data: "{not-json" });
    expect(messages).toEqual([]);
    first.close(4401);
    expect(pending.filter(Boolean)).toHaveLength(0);
    expect(FakeSocket.sockets).toHaveLength(1);
  });

  it("reconnects a 4401 when the in-memory token was refreshed", () => {
    let token = "expired";
    FakeSocket.sockets = [];
    const pending: Array<(() => void) | null> = [];
    const conn = connectMarketSocket({
      url: marketSocketUrl("ws://127.0.0.1:5173", token),
      getToken: () => token,
      urlForToken: (next) => marketSocketUrl("ws://127.0.0.1:5173", next),
      onMessage: () => undefined,
      WebSocketImpl: FakeSocket,
      schedule: (fn) => {
        pending.push(fn);
        return pending.length;
      },
      cancel: (id) => {
        pending[id - 1] = null;
      },
    });
    const first = FakeSocket.sockets[0];
    first.open();
    token = "refreshed";
    first.close(4401);
    expect(pending.filter(Boolean)).toHaveLength(1);
    pending[0]?.();
    const second = FakeSocket.sockets[1];
    expect(second.url).toContain("token=refreshed");
    expect(second.url).not.toContain("expired");
    conn.close();
  });

  it("does not reopen a 4401 when the token is unchanged", () => {
    const { pending } = harness();
    FakeSocket.sockets[0].close(4401);
    expect(pending.filter(Boolean)).toHaveLength(0);
  });

  it("does not reconnect after stop", () => {
    const { conn, pending, delays } = harness(() => ["SPX"]);
    FakeSocket.sockets[0].close(1006);
    expect(delays).toEqual([800]);
    conn.close();
    pending[0]?.();
    expect(FakeSocket.sockets).toHaveLength(1);
  });

  it("resubscribes with the latest symbols after the API drops", () => {
    let symbols = ["SPX"];
    const { conn, pending } = harness(() => symbols);
    const first = FakeSocket.sockets[0];
    first.open();
    expect(JSON.parse(first.sent[0]).symbols).toEqual(["SPX"]);
    expect(conn.send(JSON.stringify({ type: "subscribe", symbols: ["QQQ"] }))).toBe(true);
    symbols = ["NVDA"];
    first.close(1006);
    pending[0]?.();
    const second = FakeSocket.sockets[1];
    second.open();
    expect(JSON.parse(second.sent[0]).symbols).toEqual(["NVDA"]);
  });
});
