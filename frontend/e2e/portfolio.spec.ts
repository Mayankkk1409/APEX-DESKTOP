import { expect, test } from "@playwright/test";
import { E2E_API_BASE as API } from "./helpers";

test("portfolio client nav renders sections", async ({ page, request }) => {
  const username = `port${Date.now()}`;
  await request.post(`${API}/auth/signup`, {
    data: {
      full_name: "Portfolio E2E",
      username,
      email: `${username}@example.com`,
      password: "ApexDesk!23",
      confirm_password: "ApexDesk!23",
      account_mode: "paper_funded",
      starting_balance: 50000,
    },
  });
  await request.post(`${API}/auth/login`, { data: { username, password: "ApexDesk!23" } });
  await request.post(`${API}/auth/otp/request`, { data: { username } });

  await page.goto("/login");
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 20000 });
  await page.getByTestId("username").fill(username);
  await page.getByTestId("password").fill("ApexDesk!23");
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/app/, { timeout: 20000 });
  await page.getByTestId("connect-modal").getByRole("button", { name: /later/i }).click();

  await page.getByTestId("portfolio-btn").click();
  await expect(page.getByTestId("portfolio-page")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId("pnl-chart")).toBeVisible();
  await expect(page.getByTestId("portfolio-positions-section")).toBeVisible();
  await expect(page.getByTestId("portfolio-orders-section")).toBeVisible();
  await expect(page.getByTestId("portfolio-overall-section")).toBeVisible();
});

test("portfolio direct load serves SPA not API JSON", async ({ page }) => {
  await page.goto("/portfolio");
  await expect(page.getByTestId("splash")).toHaveCount(0, { timeout: 20000 });
  await expect(page.locator("body")).not.toContainText("Missing access token");
  await expect(page.getByTestId("login-form")).toBeVisible();
});
