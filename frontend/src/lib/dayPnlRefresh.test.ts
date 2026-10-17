import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { DAY_PNL_REFRESH_MS } from "./deskRefresh";
import { explainOrderRefusal, isPendingOrder, pendingReason, pendingStatusLabel, plainQueueReason } from "./orderRefusal";

const here = dirname(fileURLToPath(import.meta.url));

describe("daily P&L refresh", () => {
  it("polls about every 15 seconds and pauses while the tab is hidden", () => {
    expect(DAY_PNL_REFRESH_MS).toBe(15_000);
    const brokerage = readFileSync(resolve(here, "../hooks/useBrokerage.ts"), "utf8");
    const portfolio = readFileSync(resolve(here, "../pages/Portfolio.tsx"), "utf8");
    const dashboard = readFileSync(resolve(here, "../pages/Dashboard.tsx"), "utf8");
    for (const source of [brokerage, portfolio, dashboard]) {
      expect(source).toContain("DAY_PNL_REFRESH_MS");
      expect(source).toContain("refetchIntervalInBackground: false");
    }
    expect(portfolio).toContain("Holdings Daily P&L");
    expect(portfolio).not.toContain("Open holdings · Partial data");
    expect(portfolio).not.toContain("How this is calculated");
    expect(portfolio).not.toContain("about every 15 seconds");
    expect(dashboard).toContain("Holdings Daily P&L");
    expect(dashboard).not.toContain("Open holdings · Partial data");
    expect(dashboard).not.toContain("about every 15 seconds");
  });
});

describe("pending order status", () => {
  it("keeps an unfilled broker order pending and states the broker message once", () => {
    const sentence =
      "The broker accepted your limit order, but it has not filled yet. It will fill only if the market reaches your limit. It is not waiting in the APEX queue.";
    const shown = explainOrderRefusal(sentence);
    expect(shown).toBe("Your order is waiting to fill at the broker. You can follow its status in Pending orders.");
    expect(shown.match(/waiting to fill at the broker/g)).toHaveLength(1);
    expect(isPendingOrder({ status: "accepted" })).toBe(true);
    expect(isPendingOrder({ status: "queued" })).toBe(true);
    expect(isPendingOrder({ status: "filled" })).toBe(false);
    expect(pendingStatusLabel({ status: "accepted" })).toBe("Pending at broker");
    expect(pendingStatusLabel({ status: "accepted", order_type: "limit" })).toBe("Limit order");
    expect(pendingStatusLabel({ status: "queued" })).toBe("Queued in APEX");
    expect(pendingReason({ status: "accepted", order_type: "market" })).toBe(
      "Order submitted to Alpaca — awaiting execution.",
    );
    expect(pendingReason({ status: "accepted", order_type: "limit", side: "buy", limit_price: 395.69 })).toBe(
      "Limit buy at $395.69. Submitted to Alpaca. It fills only if the market reaches that price.",
    );
    expect(pendingStatusLabel({ status: "queued", queue_reason: "Queued — market closed." })).toBe(
      "Queued — market closed",
    );
  });
});

describe("queue list copy", () => {
  it("explains a limit wait and a wide spread without calling either one a broker fill", () => {
    expect(plainQueueReason("Waiting for the authorized limit price.")).toContain("has not been sent to the broker");
    expect(plainQueueReason("Bid/ask spread is 15.4% of mid, wider than the 10% cap.")).toContain("was not sent");
    expect(plainQueueReason("Waiting for the authorized limit price.")).not.toContain("broker received");
  });
});
