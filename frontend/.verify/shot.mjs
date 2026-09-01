import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const API = "http://127.0.0.1:8000";
const APP = process.env.APP_URL ?? "http://127.0.0.1:5175";
const OUT = `${path.resolve(process.cwd(), ".verify/out")}/`;
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ headless: true, channel: "chrome" });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.on("console", (m) => {
  if (m.type() === "error") console.log("CONSOLE ERROR:", m.text().slice(0, 300));
});
page.on("pageerror", (e) => console.log("PAGE ERROR:", String(e).slice(0, 400)));

const username = `viz${Date.now()}`;
await page.request.post(`${API}/auth/signup`, {
  data: {
    full_name: "Viz Check",
    username,
    email: `${username}@example.com`,
    password: "ApexDesk!23",
    confirm_password: "ApexDesk!23",
    account_mode: "paper_funded",
    starting_balance: 50000,
  },
});
await page.request.post(`${API}/auth/login`, { data: { username, password: "ApexDesk!23" } });

await page.goto(`${APP}/login`);
await page.getByTestId("splash").waitFor({ state: "hidden", timeout: 20000 }).catch(() => {});
await page.getByTestId("username").fill(username);
await page.getByTestId("password").fill("ApexDesk!23");
await page.getByTestId("login-submit").click();
await page.getByTestId("get-code").click();
await page.getByTestId("otp-boxes").locator("input").nth(5).waitFor({ state: "visible", timeout: 15000 });
await page.waitForTimeout(900);
await page.getByTestId("login-submit").click();
await page.getByTestId("dashboard").waitFor({ state: "visible", timeout: 20000 });
if (await page.getByTestId("connect-modal").count()) await page.getByTestId("connect-later").click();

async function report(tag) {
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}${tag}-page.png` });
  await page.getByTestId("chart").screenshot({ path: `${OUT}${tag}-chart.png` });
  const legend = await page.evaluate(() => {
    const rows = [...document.querySelectorAll("[data-testid^='study-']")];
    return rows.map((r) => ({ id: r.getAttribute("data-testid"), value: r.getAttribute("data-value") }));
  });
  const meta = await page.evaluate(() => {
    const c = document.querySelector("[data-testid='chart']");
    return {
      bars: c?.getAttribute("data-bar-count"),
      visible: c?.getAttribute("data-visible-bars"),
      symbol: c?.getAttribute("data-tv-symbol"),
      canvases: [...document.querySelectorAll("[data-testid='chart-canvas'] canvas")].map((x) => `${x.width}x${x.height}`),
      panes: [...document.querySelectorAll("[data-testid^='legend-']")].map((x) => x.getAttribute("data-testid")),
    };
  });
  const watchButtons = await page.getByRole("button", { name: /watchlist/i }).count();
  console.log(`\n=== ${tag} ===`);
  console.log("meta", JSON.stringify(meta));
  console.log("watchlist buttons:", watchButtons);
  console.log("legend:", JSON.stringify(legend, null, 1));
}

await report("spx-1D");

await page.getByTestId("ticker-search").fill("AAPL");
await page.getByTestId("ticker-search").press("Enter");
await page.waitForTimeout(1500);
await report("aapl-1D");

await page.getByTestId("tf-1H").click();
await page.waitForTimeout(2000);
await report("aapl-1H");

await page.getByTestId("tf-1D").click();
await page.waitForTimeout(1800);

const box = await page.getByTestId("chart-canvas").boundingBox();
if (box) {
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.35);
  await page.mouse.wheel(0, -600);
  await page.waitForTimeout(700);
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.4);
  await page.waitForTimeout(500);
}
await report("aapl-zoomed-crosshair");

await page.getByTestId("scan-btn").click();
await page.waitForTimeout(3500);
await page.screenshot({ path: `${OUT}scan-page.png`, fullPage: true });
const window = await page
  .getByTestId("snapshot-header")
  .innerText()
  .catch(() => "(no snapshot-header)");
console.log("\n=== scan ===");
console.log("captured window:", window.replace(/\s+/g, " "));

await browser.close();
