import { EventEmitter } from "node:events";
import { describe, expect, it } from "vitest";
import { attachQuietWsProxy, isBenignProxySocketError, type QuietProxy, type SocketLike } from "./wsProxy";

function fakeSocket() {
  const ee = new EventEmitter();
  return Object.assign(ee, {
    destroyed: false,
    destroy() {
      this.destroyed = true;
    },
  });
}

describe("ws proxy", () => {
  it("names the socket errors Vite was printing", () => {
    expect(isBenignProxySocketError({ code: "EPIPE" })).toBe(true);
    expect(isBenignProxySocketError({ message: "write ECONNRESET" })).toBe(true);
    expect(isBenignProxySocketError({ code: "EACCES" })).toBe(false);
  });

  it("destroys both ends on EPIPE and does not call Vite's logger", () => {
    const proxy = new EventEmitter() as EventEmitter & QuietProxy;
    attachQuietWsProxy(proxy);
    const logged: unknown[] = [];
    const client = fakeSocket();
    const upstream = fakeSocket();
    const proxyReq = new EventEmitter();

    proxy.on("error", ((err: { code?: string }) => {
      logged.push(err);
    }) as (...args: never[]) => void);
    proxy.on("proxyReqWs", ((_proxyReq: unknown, _req: unknown, socket: SocketLike) => {
      socket.on("error", (err) => logged.push(["vite-socket", err]));
    }) as (...args: never[]) => void);

    proxy.emit("proxyReqWs", proxyReq, {}, client);
    proxyReq.emit("upgrade", {}, upstream);
    client.emit("error", { code: "EPIPE" });
    expect(logged).toEqual([]);
    expect(client.destroyed).toBe(true);

    client.emit("close");
    expect(upstream.destroyed).toBe(true);

    const refused = fakeSocket();
    proxy.emit("error", { code: "ECONNREFUSED" }, {}, refused);
    expect(logged).toEqual([]);
    expect(refused.destroyed).toBe(true);

    proxy.emit("error", { code: "EACCES" }, {}, fakeSocket());
    expect(logged).toEqual([{ code: "EACCES" }]);
  });
});
