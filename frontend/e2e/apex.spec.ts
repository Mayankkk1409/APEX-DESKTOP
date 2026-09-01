import { expect, test, type Page } from "@playwright/test";
import { E2E_API_BASE as API } from "./helpers";

async function signup(request: { post: Function }, username: string, mode: "paper_funded" | "real_brokerage", balance?: number) {
  const body: Record<string, unknown> = {
    full_name: "E2E User",
    username,
    email: `${username}@example.com`,
    password: "ApexDesk!23",
    confirm_password: "ApexDesk!23",
    account_mode: mode,
  };
  if (mode === "paper_funded") body.starting_balance = balance ?? 25000;
  const res = await request.post(`${API}/auth/signup`, { data: body });
  return res;
}

/** Full document loads always play splash; wait it out before interacting. */
async function awaitSplash(page: Page) {
  await expect(page.getByTestId("splash")).toBeVisible();
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 20000 });
}

async function gotoAfterSplash(page: Page, path: string) {
  if (path === "/") {
    await page.goto("/");
    await awaitSplash(page);
    return;
  }
  // Deep links skip splash — same as portfolio.spec.ts and chart.spec.ts.
  await page.goto(path);
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 20000 });
}

test("splash then login route", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("splash")).toBeVisible();
  await expect(page.getByTestId("apex-logo")).toBeVisible();
  await expect(page.locator(".apex-assemble")).toBeVisible();
  await expect(page.locator(".apex-draw-mark")).toBeVisible();
  await expect(page.getByTestId("disclaimer")).toBeVisible({ timeout: 8000 });
  await expect(page.getByTestId("disclaimer")).toContainText("not personalized investment advice");
  await awaitSplash(page);
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("login-form")).toBeVisible();
});

test("reload and new document load replay splash", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("splash")).toBeVisible();
  await awaitSplash(page);
  await expect(page.getByTestId("login-form")).toBeVisible();

  await page.goto("/");
  await page.reload();
  await expect(page.getByTestId("splash")).toBeVisible();
  await awaitSplash(page);
  await expect(page.getByTestId("login-form")).toBeVisible();
});

test("paper shows starting balance; real unmounts the field", async ({ page }) => {
  await gotoAfterSplash(page, "/signup");
  await page.getByTestId("mode-paper").click();
  await expect(page.getByTestId("starting-balance")).toBeVisible();
  await page.getByTestId("mode-real").click();
  await expect(page.getByTestId("starting-balance")).toHaveCount(0);
});

test("signup never asks for a 2FA code", async ({ page }) => {
  await gotoAfterSplash(page, "/signup");
  await expect(page.getByTestId("signup-form")).toBeVisible();
  await expect(page.getByTestId("full-name")).toBeVisible();
  await expect(page.getByTestId("otp-boxes")).toHaveCount(0);
  await expect(page.getByTestId("get-code")).toHaveCount(0);
  await expect(page.getByText(/get new code/i)).toHaveCount(0);
  await expect(page.getByText(/one-time code/i)).toHaveCount(0);
});

test("fresh OTP codes each request", async ({ request }) => {
  const username = `otp${Date.now()}`;
  const created = await signup(request, username, "paper_funded");
  expect(created.ok()).toBeTruthy();
  await request.post(`${API}/auth/login`, { data: { username, password: "ApexDesk!23" } });
  const a = await request.post(`${API}/auth/otp/request`, { data: { username } });
  const b = await request.post(`${API}/auth/otp/request`, { data: { username } });
  const ca = (await a.json()).code;
  const cb = (await b.json()).code;
  expect(ca).toHaveLength(6);
  expect(cb).toHaveLength(6);
  expect(ca).not.toEqual(cb);
});

test("forgot-password recovery resets password and signs in", async ({ page, request }) => {
  const username = `recover${Date.now()}`;
  const created = await signup(request, username, "paper_funded");
  expect(created.ok()).toBeTruthy();

  await gotoAfterSplash(page, "/login");
  await page.getByTestId("forgot-password-link").click();
  await expect(page.getByTestId("recovery-notice")).toBeVisible();
  await expect(page.getByTestId("password")).toHaveCount(0);
  await expect(page.getByTestId("recovery-password")).toBeVisible();
  await page.getByTestId("username").fill(username);
  await page.getByTestId("recovery-password").fill("NewApexDesk!45");
  await page.getByTestId("recovery-confirm-password").fill("NewApexDesk!45");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("connect-modal")).toBeVisible();

  await gotoAfterSplash(page, "/login");
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("NewApexDesk!45");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
});

test("OTP autofill works for a brand-new paper user and a brand-new real user", async ({ page, request }) => {
  for (const mode of ["paper_funded", "real_brokerage"] as const) {
    const username = `${mode === "paper_funded" ? "pap" : "real"}${Date.now()}`;
    const created = await signup(request, username, mode);
    expect(created.ok()).toBeTruthy();
    await gotoAfterSplash(page, "/login");
    await page.getByTestId("username").fill(username);
    await page.getByTestId("password").fill("ApexDesk!23");
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
    await gotoAfterSplash(page, "/login");
  }
});

test("watchlist and positions collapse", async ({ page, request }) => {
  const username = `dash${Date.now()}`;
  await signup(request, username, "paper_funded");
  await request.post(`${API}/auth/login`, { data: { username, password: "ApexDesk!23" } });
  await gotoAfterSplash(page, "/login");
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("connect-modal")).toBeVisible();
  await page.getByTestId("connect-later").click();
  await expect(page.getByTestId("watch-list")).toBeVisible();
  await page.getByTestId("watch-toggle").click();
  await expect(page.getByTestId("watch-list")).toHaveCount(0);
  await page.getByTestId("watch-toggle").click();
  await expect(page.getByTestId("watch-list")).toBeVisible();
  await expect(page.getByTestId("positions")).toBeVisible();
  await page.getByTestId("pos-toggle").click();
  await expect(page.getByTestId("positions")).toHaveCount(0);

  await gotoAfterSplash(page, "/login");
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("connect-modal")).toBeVisible();
});

test("chart snapshot captured into scan and keyboard slider", async ({ page, request }) => {
  const username = `scan${Date.now()}`;
  await signup(request, username, "paper_funded", 50000);
  await request.post(`${API}/auth/login`, { data: { username, password: "ApexDesk!23" } });
  await gotoAfterSplash(page, "/login");
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("connect-modal")).toBeVisible();
  await page.getByTestId("connect-later").click();
  await expect(page.getByTestId("connect-modal")).toHaveCount(0);
  await page.getByTestId("scan-btn").click();
  await page.waitForURL("**/scan", { timeout: 10000 });
  await expect(page.getByTestId("splash")).toHaveCount(0);
  await expect(page.getByTestId("scan-intro")).toBeVisible();
  await expect(page.getByTestId("scan-ticker")).toHaveText(/^[A-Z0-9.]+$/);
  await expect(page.getByTestId("scan-intro")).not.toContainText("Deep Scan");
  await expect(page.getByTestId("deep-scan")).toBeVisible({ timeout: 8000 });
  await expect(page.getByTestId("chart-snapshot")).toBeVisible();
  await expect(page.getByTestId("ta-carousel")).toBeVisible();
  const cardCount = Number(await page.getByTestId("ta-carousel").getAttribute("data-card-count"));
  expect(cardCount).toBeGreaterThanOrEqual(9);
  await expect(page.locator('[data-testid^="ta-mark-"][data-kind="candle"]')).toHaveCount(0);
  const firstCard = await page.getByTestId("ta-card").innerText();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("ta-card")).not.toHaveText(firstCard);
  await page.getByTestId("next-layer").click();
  await expect(page.getByTestId("layer-name")).toContainText(/options chain greeks/i);
  await expect(page.getByTestId("layer-name")).toHaveText(/2 \/ 8/);
  await page.keyboard.press("End");
  await expect(page.getByTestId("layer-name")).toContainText("risk review");
  await expect(page.getByTestId("layer-name")).toHaveText(/8 \/ 8/);
});

test("expiry picker lists the full live Alpaca calendar for equities", async ({ page, request }) => {
  await loginToDash(page, request, `exp${Date.now()}`);

  for (const ticker of ["AAPL", "MSFT"]) {
    await page.getByTestId("ticker-search").fill(ticker);
    await page.getByTestId("ticker-search").press("Enter");
    await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", new RegExp(ticker), { timeout: 15000 });

    const expirySelect = page.getByTestId("expiry");
    await expect(expirySelect.locator("option").first()).toBeAttached({ timeout: 20000 });
    await expect
      .poll(async () => Number(await expirySelect.getAttribute("data-expiry-count")), { timeout: 20000 })
      .toBeGreaterThanOrEqual(15);

    const options = await expirySelect.locator("option").evaluateAll((els) =>
      els.map((e) => (e as HTMLOptionElement).value).filter(Boolean),
    );
    expect(options.length).toBeGreaterThanOrEqual(15);
    // Nearest (first) is selected by default; list is chronological and not nearest-5 truncated.
    await expect(expirySelect).toHaveValue(options[0]);
    const sorted = [...options].sort();
    expect(options).toEqual(sorted);
    expect(options[options.length - 1] > options[0]).toBe(true);
  }
});

/**
 * The combined options chain + Greeks screen is the product's main selling point, so it is
 * asserted end to end: the expiry the dashboard picked must be the expiry the screen loads,
 * the chain table must render, and the carousel must be navigable by click and by keyboard.
 */
test("combined options chain and Greeks screen", async ({ page, request }) => {
  await loginToDash(page, request, `chain${Date.now()}`);

  // SPX is the default dashboard symbol but has no listed chain on this vendor — switch to
  // an equity so the combined screen can render a live (or honestly degraded) ladder.
  await page.getByTestId("ticker-search").fill("AAPL");
  await page.getByTestId("ticker-search").press("Enter");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", /AAPL/, { timeout: 15000 });

  // The expiry picker drives the scan session. Take the second listed expiry so the
  // assertion is not accidentally satisfied by a default.
  const expirySelect = page.getByTestId("expiry");
  await expect(expirySelect.locator("option").first()).toBeAttached({ timeout: 15000 });
  const options = await expirySelect.locator("option").evaluateAll((els) => els.map((e) => (e as HTMLOptionElement).value));
  expect(options.length).toBeGreaterThan(1);
  const chosenExpiry = options[1];
  await expirySelect.selectOption(chosenExpiry);
  await expect(expirySelect).toHaveValue(chosenExpiry);

  await page.getByTestId("scan-btn").click();
  await page.waitForURL("**/scan", { timeout: 10000 });
  await expect(page.getByTestId("deep-scan")).toBeVisible({ timeout: 12000 });
  await expect(page.getByTestId("snapshot-header")).toContainText(chosenExpiry);

  // technical → combined options + Greeks
  await expect(page.getByTestId("layer-name")).toHaveText(/1 \/ 8/);
  await page.getByTestId("next-layer").click();
  await expect(page.getByTestId("layer-name")).toContainText(/options chain greeks/i);
  await expect(page.getByTestId("options-chain-greeks-layer")).toBeVisible();

  const stage = page.getByTestId("chain-stage");
  await expect(stage).toBeVisible({ timeout: 15000 });

  // The screen must analyse the SAME expiry the dashboard selected.
  await expect(stage).toHaveAttribute("data-expiry", chosenExpiry, { timeout: 15000 });
  await expect(page.getByTestId("chain-head")).toContainText(chosenExpiry);

  // Provenance is quiet chrome: badge only when degraded (not live). Live chains show no feed badge.
  const badge = page.getByTestId("chain-source-badge");
  const badgeCount = await badge.count();
  if (badgeCount > 0) {
    await expect(badge).toBeVisible();
    await expect(badge).not.toContainText(/Live\s*·/i);
    await expect(page.getByTestId("chain-degraded-warning")).toContainText(
      /not live|not entitled|Configure Alpaca|no listed chain|no Alpaca credentials/i,
    );
    await expect(badge).not.toContainText(/vendor \/ .* model|MODEL-COMPUTED/i);
  } else {
    await expect(page.getByTestId("chain-degraded-warning")).toHaveCount(0);
    await expect(page.getByTestId("chain-caveats")).toHaveCount(0);
  }

  // Clean professional chain — quotes + Greeks, no REJECT/MODEL/compliance chrome on the grid.
  const table = page.getByTestId("chain-table");
  await expect(table).toBeVisible();
  await expect(table.locator("thead")).toContainText("Calls");
  await expect(table.locator("thead")).toContainText("Puts");
  await expect(table.locator("thead")).toContainText("Strike");
  await expect(table.locator("thead")).toContainText("Bid");
  await expect(table.locator("thead")).toContainText("Δ");
  const rowCount = Number(await table.getAttribute("data-rows"));
  expect(rowCount).toBeGreaterThanOrEqual(5);
  await expect(page.locator('.chain-row[data-recommended="true"]')).toHaveCount(1);
  await expect(page.getByTestId("chain-head")).not.toContainText(/DTE · spot|ATM /);
  await expect(page.locator(".chain-verdict-tag")).toHaveCount(0);
  await expect(page.getByTestId("chain-controls")).toHaveCount(0);
  await expect(page.getByTestId("chain-spread-cap")).toHaveCount(0);
  await expect(page.getByTestId("chain-vega-override")).toHaveCount(0);
  await expect(page.getByTestId("chain-trampoline")).toHaveCount(0);
  if (badgeCount === 0) {
    await expect(page.getByTestId("chain-caveats")).toHaveCount(0);
  }
  await expect(page.getByTestId("chain-tally")).toHaveCount(0);
  await expect(page.getByTestId("chain-legend")).toHaveCount(0);
  // Banner soup must not paint the chain chrome. Verbose §5 wording may still appear in analysis cards.
  const head = page.getByTestId("chain-head");
  await expect(head).not.toContainText(/LIVE VENDOR QUOTES|MODEL-COMPUTED GREEKS|Compact columns|Gamma Trampoline|Live\s*·\s*indicative/i);

  // The carousel carries every documented analysis card (gates live here, not on every row).
  const carousel = page.getByTestId("chain-carousel");
  await expect(carousel).toBeVisible();
  expect(Number(await carousel.getAttribute("data-card-count"))).toBeGreaterThanOrEqual(14);

  for (const cardId of [
    "chain-provenance",
    "chain-spread",
    "chain-liquidity",
    "chain-volume",
    "greeks-delta",
    "greeks-theta",
    "greeks-delta-theta",
    "greeks-vega",
    "greeks-gamma",
    "chain-iv",
    "chain-positioning",
    "chain-vs-technical",
  ]) {
    await expect(page.getByTestId("chain-card")).toHaveAttribute("data-card-id", cardId);
    await page.getByTestId("chain-next").click();
  }
  while (/^candidates-/.test((await page.getByTestId("chain-card").getAttribute("data-card-id")) ?? "")) {
    await page.getByTestId("chain-next").click();
  }
  await expect(page.getByTestId("chain-card")).toHaveAttribute("data-card-id", "chain-gates");
  await page.getByTestId("chain-next").click();

  // Arrow keys drive the card carousel and must not change the scan layer.
  await page.keyboard.press("Home");
  await expect(page.getByTestId("layer-name")).toHaveText(/1 \/ 8/);
  await page.getByTestId("next-layer").click();
  await expect(page.getByTestId("chain-card")).toHaveAttribute("data-card-id", "chain-provenance");
  const firstBody = await page.getByTestId("chain-card").innerText();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("chain-card")).not.toHaveAttribute("data-card-id", "chain-provenance");
  await expect(page.getByTestId("chain-card")).not.toHaveText(firstBody);
  await expect(page.getByTestId("layer-name")).toContainText(/options chain greeks/i);
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByTestId("chain-card")).toHaveAttribute("data-card-id", "chain-provenance");
  await expect(page.getByTestId("layer-name")).toContainText(/options chain greeks/i);
});

test("index underlying reports no listed chain instead of inventing one", async ({ page, request }) => {
  await loginToDash(page, request, `spx${Date.now()}`);
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", /SPX/);
  await page.getByTestId("scan-btn").click();
  await page.waitForURL("**/scan", { timeout: 10000 });
  await expect(page.getByTestId("deep-scan")).toBeVisible({ timeout: 12000 });
  await page.getByTestId("next-layer").click();
  await expect(page.getByTestId("chain-stage")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("chain-source-badge")).not.toContainText("Live vendor chain");
  await expect(page.getByTestId("chain-source-badge")).toContainText(/no listed chain|unsupported|Configure Alpaca/i);
  await expect(page.getByTestId("chain-caveats")).toBeVisible();
  await expect(page.getByTestId("chain-caveats")).toContainText(/cash-settled index|SPY|no .* chain/i);
  // Honest degradation: no invented ladder pretending SPX options exist on this vendor.
  await expect(page.getByTestId("chain-table")).toHaveCount(0);
  await expect(page.getByTestId("chain-empty")).toBeVisible();
  await expect(page.getByTestId("chain-card")).toHaveAttribute("data-card-id", "chain-unavailable");
});

async function loginToDash(page: Page, request: { post: Function }, username: string) {
  await signup(request, username, "paper_funded");
  await gotoAfterSplash(page, "/login");
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("dashboard")).toBeVisible({ timeout: 15000 });
  await expect(page.getByTestId("connect-modal")).toBeVisible();
  await page.getByTestId("connect-later").click();
}

test("ticker switch AAPL then SPX is not stuck on SPY", async ({ page, request }) => {
  await loginToDash(page, request, `tick${Date.now()}`);
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", "FOREXCOM:SPXUSD");
  await expect(page.getByTestId("watch-list")).toBeVisible();
  await page.getByTestId("ticker-search").fill("AAPL");
  await page.getByTestId("ticker-search").press("Enter");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", "NASDAQ:AAPL");
  await expect(page.getByTestId("chart")).not.toHaveAttribute("data-tv-symbol", "AMEX:SPY");
  await page.getByTestId("ticker-search").fill("SPX");
  await page.getByTestId("ticker-search").press("Enter");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tv-symbol", "FOREXCOM:SPXUSD");
  await expect(page.getByTestId("chart")).not.toHaveAttribute("data-tv-symbol", /SPY/);
});

