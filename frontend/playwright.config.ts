import { defineConfig } from "@playwright/test";

const API_PORT = process.env.E2E_API_PORT ?? "8000";
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const VITE_PORT = process.env.E2E_VITE_PORT ?? "5174";
const VITE_BASE = `http://127.0.0.1:${VITE_PORT}`;

// E2E specs read VITE_API_BASE_URL at module load — mirror the webServer API target.
process.env.VITE_API_BASE_URL = API_BASE;
process.env.VITE_WS_BASE_URL = `ws://127.0.0.1:${API_PORT}`;
process.env.VITE_SPLASH_DURATION_MS = process.env.VITE_SPLASH_DURATION_MS ?? "3000";

const apiEnv = {
  APP_ENV: "development",
  APP_SECRET_KEY: "e2e-secret-key-32bytes-minimum-len",
  APP_CORS_ORIGINS: `${VITE_BASE},http://localhost:${VITE_PORT}`,
  DATABASE_URL: "sqlite+aiosqlite:///./e2e_playwright.db",
  REDIS_URL: "redis://localhost:6379/15",
  AUTOFILL_2FA: "true",
  ALPACA_API_KEY_ID: "",
  ALPACA_API_SECRET_KEY: "",
  ALLOW_OPTIONS_SIMULATOR: "true",
};

const viteEnv = {
  VITE_API_BASE_URL: API_BASE,
  VITE_WS_BASE_URL: `ws://127.0.0.1:${API_PORT}`,
  VITE_SPLASH_DURATION_MS: "3000",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  use: {
    baseURL: VITE_BASE,
    headless: true,
  },
  webServer: [
    {
      command: `rm -f e2e_playwright.db && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: "../backend",
      url: `${API_BASE}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: apiEnv,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${VITE_PORT}`,
      url: VITE_BASE,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: viteEnv,
    },
  ],
});
