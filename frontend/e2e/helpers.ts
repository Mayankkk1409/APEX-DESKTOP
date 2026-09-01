/** Shared API base for Playwright specs — set in playwright.config.ts before specs load. */
export const E2E_API_BASE = process.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
