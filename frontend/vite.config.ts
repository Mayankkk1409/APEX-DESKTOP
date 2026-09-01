import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API = "http://127.0.0.1:8000";

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
    proxy: {
      "/api": API,
      "/auth": API,
      "/health": API,
      "/market": API,
      "/volatility": API,
      "/scan": API,
      "/watchlist": API,
      "/sentiment": API,
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/api": API,
      "/auth": API,
      "/health": API,
      "/market": API,
      "/volatility": API,
      "/scan": API,
      "/watchlist": API,
      "/sentiment": API,
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
