import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { apiProxyOptions } from "./src/lib/devProxy";
import { attachQuietWsProxy, type QuietProxy } from "./src/lib/wsProxy";

const API = "http://127.0.0.1:8000";

const wsProxy = {
  target: "ws://127.0.0.1:8000",
  ws: true,
  configure(proxy: QuietProxy) {
    attachQuietWsProxy(proxy);
  },
};

/**
 * Browser calls stay on the Vite origin. The proxy forwards Cookie and rewrites
 * Set-Cookie so the httpOnly refresh cookie is stored for this host.
 * https://vite.dev/config/server-options.html#server-proxy
 */
const proxy = {
  "/api": apiProxyOptions(API),
  "/auth": apiProxyOptions(API),
  "/health": apiProxyOptions(API),
  "/market": apiProxyOptions(API),
  "/volatility": apiProxyOptions(API),
  "/scan": apiProxyOptions(API),
  "/watchlist": apiProxyOptions(API),
  "/sentiment": apiProxyOptions(API),
  "/ws": wsProxy,
};

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
  server: {
    // Always THIS project at http://localhost:5173 — never silently hop to 5174
    // (another folder like "PROJECT APEX" often steals 5173).
    // Bind IPv4 so http://127.0.0.1:5173 and http://localhost:5173 both hit THIS app
    // (macOS `localhost` alone often binds only [::1], leaving 127.0.0.1 free for other folders).
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy,
  },
});
