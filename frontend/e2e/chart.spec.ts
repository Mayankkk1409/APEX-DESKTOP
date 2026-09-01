import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE as API } from "./helpers";

async function login(page: Page, request: { post: Function }, tag: string) {
  const username = `${tag}${Date.now()}`;
  await request.post(`${API}/auth/signup`, {
    data: {
      full_name: "Chart E2E",
      username,
      email: `${username}@example.com`,
      password: "ApexDesk!23",
      confirm_password: "ApexDesk!23",
      account_mode: "paper_funded",
      starting_balance: 50000,
    },
  });
  await page.goto("/login");
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 20000 });
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 20000 });
  const modal = page.getByTestId("connect-modal");
  await expect(async () => {
    if (await modal.count()) await page.getByTestId("connect-later").click();
    await expect(modal).toHaveCount(0, { timeout: 1000 });
  }).toPass({ timeout: 20000 });
  return username;
}

async function chartReady(page: Page) {
  await expect(page.getByTestId("chart")).toBeVisible();
  await expect(page.getByTestId("chart")).toHaveAttribute("data-chart-engine", "tradingview");
  await expect(page.getByTestId("tv-embed")).toBeVisible({ timeout: 20000 });
  await expect(page.getByTestId("chart")).not.toHaveAttribute("data-bar-count", "0", { timeout: 25000 });
  await page.waitForTimeout(500);
}

async function setTicker(page: Page, symbol: string) {
  await page.getByTestId("ticker-search").fill(symbol);
  await page.getByTestId("ticker-search").press("Enter");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", new RegExp(`${symbol}|SPXUSD`), {
    timeout: 15000,
  });
  await chartReady(page);
}

test("dashboard mounts TradingView Advanced Chart embed", async ({ page, request }) => {
  await login(page, request, "tv");
  await chartReady(page);
  const chart = page.getByTestId("chart");
  await expect(chart).toHaveAttribute("data-chart-engine", "tradingview");
  await expect(chart).toHaveAttribute("data-tv-symbol", /FOREXCOM:SPXUSD|AMEX:SPY/);
  await expect(page.getByTestId("tv-embed")).toBeVisible();
  await expect(page.getByTestId("chart-overlay")).toBeVisible();
  // TV logo is covered; chrome (sidebars / timeframes) stays inside the embed.
  await expect(page.locator(".tv-logo-cover")).toHaveCount(1);
});

for (const [symbol, mapped] of [
  ["AAPL", "NASDAQ:AAPL"],
  ["SPY", "AMEX:SPY"],
  ["SPX", "FOREXCOM:SPXUSD"],
] as const) {
  test(`ticker ${symbol} remounts TV embed to ${mapped}`, async ({ page, request }) => {
    await login(page, request, `map${symbol.toLowerCase()}`);
    await chartReady(page);
    await setTicker(page, symbol);
    await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", mapped);
    await expect(page.getByTestId("tv-embed")).toBeVisible();
  });
}

test("dashboard chart timeframe toolbar remounts the embed", async ({ page, request }) => {
  await login(page, request, "tf");
  await setTicker(page, "AAPL");
  const before = await page.getByTestId("chart").getAttribute("data-bar-count");
  await page.getByTestId("chart-timeframe").getByRole("button", { name: "5 Minutes", exact: true }).click();
  await chartReady(page);
  await expect(page.getByTestId("tv-embed")).toBeVisible();
  // Bars may differ by interval; remount must still publish a non-empty series.
  await expect(page.getByTestId("chart")).not.toHaveAttribute("data-bar-count", "0");
  expect(before).toBeTruthy();
});

test("exactly one watchlist toggle is mounted on the dashboard", async ({ page, request }) => {
  await login(page, request, "wl");
  await chartReady(page);
  const toggles = page.getByRole("button", { name: /^(Add to|Remove from) watchlist$/ });
  await expect(toggles).toHaveCount(1);
  await expect(page.getByTestId("watchlist-toggle")).toHaveCount(1);
  await expect(page.getByTestId("watchlist-toggle-ticker")).toHaveCount(0);
  await expect(page.getByTestId("watchlist-toggle-expiry")).toHaveCount(0);

  await page.getByTestId("watchlist-toggle").click();
  await expect(page.getByRole("button", { name: /^(Add to|Remove from) watchlist$/ })).toHaveCount(1);
});

test("price-pane overlay never covers TV chrome hit targets", async ({ page, request }) => {
  await login(page, request, "overlay");
  await chartReady(page);
  const overlay = page.getByTestId("chart-overlay");
  await expect(overlay).toBeVisible();
  await expect(overlay).toHaveCSS("pointer-events", "none");
  // Overlay is EMA-only; SuperTrend / Traditional pivots are not drawn.
  const pivotCount = await page.locator("[data-testid^='pivot-']").count();
  expect(pivotCount).toBe(0);
  await expect(page.getByTestId("overlay-st-bull")).toHaveCount(0);
  await expect(page.getByTestId("st-box")).toHaveCount(0);
});

test("scan analyses the captured bars window for the selected symbol", async ({ page, request }) => {
  await login(page, request, "scan");
  await chartReady(page);
  await setTicker(page, "AAPL");

  const visible = Number(await page.getByTestId("chart").getAttribute("data-visible-bars"));
  expect(visible).toBeGreaterThan(8);

  await page.getByTestId("scan-btn").click();
  await page.waitForURL("**/scan", { timeout: 15000 });
  await expect(page.getByTestId("deep-scan")).toBeVisible({ timeout: 15000 });

  await expect(page.getByTestId("captured-window")).toContainText(`${visible} bars`);
  await expect(page.getByTestId("chart-snapshot")).toBeVisible();
  await expect(page.getByTestId("chart-snapshot").getByTestId("chart")).toHaveAttribute("data-chart-engine", "snapshot");
  await expect(page.getByTestId("chart-snapshot").getByTestId("chart")).toHaveAttribute("data-frozen", "true");
  await expect(page.getByTestId("chart-snapshot").getByTestId("tv-iframe")).toHaveCount(0);
  await expect(page.getByTestId("chart-snapshot").getByTestId("tv-embed")).toHaveCount(0);

  const firstCard = page.getByTestId("ta-card");
  await expect(firstCard).toContainText(/Captured|window|bars|EMA|MACD|RSI/i);

  const before = await firstCard.innerText();
  await page.keyboard.press("ArrowRight");
  await expect(firstCard).not.toHaveText(before);
});

test("rapid ticker switching lands on the last symbol", async ({ page, request }) => {
  await login(page, request, "rapid");
  await chartReady(page);
  for (const s of ["AAPL", "MSFT", "NVDA"]) {
    await page.getByTestId("ticker-search").fill(s);
    await page.getByTestId("ticker-search").press("Enter");
  }
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", "NASDAQ:NVDA", { timeout: 15000 });
  await chartReady(page);
  await expect(page.getByTestId("tv-embed")).toBeVisible();
});
