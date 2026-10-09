import { describe, expect, it } from "vitest";
import {
  accountModeLabel,
  buildOrderConfirmationDetails,
  formatOrderAccountLabel,
  formatOrderType,
} from "./orderFormat";
import type { User } from "../types";

const paperUser: User = {
  id: "usr-paper-001",
  full_name: "Test User",
  username: "trader1",
  email: "t@example.com",
  account_mode: "paper_funded",
  brokerage_connected: false,
  connect_later_banner: false,
  first_login_completed: true,
  cash_balance: 25000,
  buying_power: 25000,
  portfolio_value: 25000,
  starting_balance: 25000,
};

describe("formatOrderType", () => {
  it("shows the order type without the raw asset class", () => {
    expect(formatOrderType("limit", "us_option")).toBe("limit");
    expect(formatOrderType("Limit", "US_OPTION")).toBe("limit");
    expect(formatOrderType("market", "us_option")).not.toContain("us_option");
  });

  it("defaults missing values to limit", () => {
    expect(formatOrderType("", "")).toBe("limit");
  });
});

describe("formatOrderAccountLabel", () => {
  it("formats paper funded account", () => {
    expect(formatOrderAccountLabel(paperUser)).toBe("Paper · @trader1 · usr-pape");
  });

  it("formats brokerage account", () => {
    expect(
      formatOrderAccountLabel({ ...paperUser, account_mode: "real_brokerage", id: "abc" }),
    ).toBe("Brokerage · @trader1 · abc");
  });

  it("handles missing user", () => {
    expect(formatOrderAccountLabel(null)).toBe("Paper · APEX");
  });
});

describe("accountModeLabel", () => {
  it("maps account modes", () => {
    expect(accountModeLabel("paper_funded")).toBe("Paper Funded");
    expect(accountModeLabel("real_brokerage")).toBe("Real Brokerage");
    expect(accountModeLabel(null)).toBe("APEX Account");
  });
});

describe("buildOrderConfirmationDetails", () => {
  it("maps place order response into certificate fields", () => {
    const details = buildOrderConfirmationDetails(
      {
        id: "root-id",
        status: "filled",
        fill_price: 4.2,
        asset_class: "us_option",
        legs_filled: [
          {
            id: "leg-a",
            symbol: "SPX260116C00550000",
            side: "buy",
            qty: 2,
            fill_price: 4.2,
            asset_class: "us_option",
          },
        ],
      },
      {
        strategyName: "Bull Call Spread",
        ticker: "SPX",
        user: paperUser,
        accountMode: "paper_funded",
      },
    );
    expect(details.orderIds).toEqual(["leg-a"]);
    expect(details.strategyName).toBe("Bull Call Spread");
    expect(details.ticker).toBe("SPX");
    expect(formatOrderType(details.orderType, details.assetClass)).toBe("limit");
    expect(formatOrderType(details.orderType, details.assetClass)).not.toContain("us_option");
    expect(details.accountLabel).toBe(formatOrderAccountLabel(paperUser));
  });
});
