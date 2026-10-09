import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { OrderSubmitProgress } from "../components/OrderSubmitProgress";
import { RiskReviewLegs } from "../components/RiskReviewLegs";
import { RiskReviewOrderActions, THESIS_ACCEPTANCE_TEXT } from "../components/RiskReviewOrderActions";
import { optionReviewRows, optionsLegBlockReason, type OptionReviewRow } from "../lib/orderTicket";
import { orderPlacement, thesisCheckboxState, type OrderPlacement } from "../lib/riskReview";
import { DEFAULT_USER_SETTINGS } from "../lib/userSettings";

const here = dirname(fileURLToPath(import.meta.url));

function renderOrderActions(placement: OrderPlacement, thesisAccepted = false): string {
  return renderToStaticMarkup(
    <RiskReviewOrderActions
      placement={placement}
      thesisAccepted={thesisAccepted}
      onThesisChange={() => undefined}
      onPlace={() => undefined}
    />,
  );
}

const executableScan = {
  serverAutoSubmit: true,
  definedRisk: true,
  hasLegs: true,
  executable: true,
  validationPassed: true,
  placeable: true,
};

function ticketTypeLabel(rows: OptionReviewRow[]): string {
  return rows.map((row) => row.orderTypeLabel).join(" · ");
}

function notExecutableLine(failed: string[]): string {
  return failed.length ? "NOT EXECUTABLE" : "";
}

function buildOrderReview(input: {
  metricLegs?: Parameters<typeof optionReviewRows>[0]["metricLegs"];
  ticketLegs?: Parameters<typeof optionReviewRows>[0]["ticketLegs"];
  validationErrors?: Array<{ check?: string; expected?: string; actual?: string }>;
  failedChecks?: string[];
  blockReason?: string | null;
  contractsPerLeg: number;
  multiplier?: number;
  equityRequired?: boolean;
}): { rows: OptionReviewRow[]; emptyReason: string; failedChecks: string[]; typeLabel: string } {
  const optionRows = optionReviewRows({
    ticketLegs: input.ticketLegs,
    metricLegs: input.metricLegs,
    equityRequired: input.equityRequired,
    contractsPerLeg: input.contractsPerLeg,
    multiplier: input.multiplier,
  });
  const stockRows: OptionReviewRow[] = [];
  for (const leg of input.metricLegs ?? []) {
    if (leg.side !== "stock" || !leg.symbol) continue;
    const qty = leg.quantity ?? 0;
    const price = leg.mid ?? null;
    const impact = price == null ? null : price * qty;
    stockRows.push({
      symbol: leg.symbol,
      side: (leg.action || "buy").toLowerCase(),
      sideLabel: (leg.action || "buy").toUpperCase(),
      contracts: qty,
      orderType: "limit",
      orderTypeLabel: "shares",
      price,
      quoteAsOf: null,
      premiumLabel: price == null ? null : `est. price $${price.toFixed(2)}`,
      impactLabel: impact == null ? null : `account impact debit $${impact.toFixed(2)}`,
    });
  }
  const rows = [...stockRows, ...optionRows];
  return {
    rows,
    emptyReason: rows.length ? "" : "The scan returned no legs.",
    failedChecks:
      rows.length > 0
        ? (input.failedChecks ?? []).filter((line) => !line.includes("actual 0"))
        : (input.failedChecks ?? []),
    typeLabel: ticketTypeLabel(rows) || "limit",
  };
}

describe("DeepScan risk review order panel", () => {
  it("shows formatted order type and the inline thesis checkbox", () => {
    const placement = orderPlacement({ ...executableScan, composite: 66, threshold: 40 });
    const html = renderToStaticMarkup(
      <div data-testid="risk-review">
        <RiskReviewOrderActions
          placement={placement}
          thesisAccepted={false}
          onThesisChange={() => undefined}
          onPlace={() => undefined}
        />
        <div className="grid grid-cols-2 gap-3 text-sm">
          <p>Type</p>
          <p className="font-mono text-champagne/90" data-testid="order-type">
            market · us_option
          </p>
        </div>
      </div>,
    );
    expect(html).toContain('data-testid="order-type"');
    expect(html).toContain("market · us_option");
    expect(html).toContain('class="flex cursor-pointer items-center gap-2 text-sm leading-snug"');
    expect(html).toContain('class="shrink-0"');
    expect(html).toContain(THESIS_ACCEPTANCE_TEXT);
  });

  it("submits on one checkbox above the saved minimum with no Acknowledge button", () => {
    expect(DEFAULT_USER_SETTINGS.autoExecEnabled).toBe(false);
    const placement = orderPlacement({
      ...executableScan,
      toggleOn: DEFAULT_USER_SETTINGS.autoExecEnabled,
      composite: 52.8,
      threshold: 40,
    });
    const html = renderOrderActions(placement);
    expect(placement.autoSubmitOnAck).toBe(true);
    expect(thesisCheckboxState(placement)).toEqual({
      disabled: false,
      submitsOnAccept: true,
      reason: null,
    });
    expect(html).toContain('data-testid="thesis"');
    expect(html).not.toContain("disabled");
    expect(html).toContain('data-testid="auto-exec-hint"');
    expect(html).toContain("Accepting the thesis submits these legs.");
    expect(html).not.toContain('data-testid="submit-order"');
    expect(html).not.toContain('data-testid="acknowledge-order"');
    expect(html).not.toContain("Acknowledge");
    expect(html).not.toContain("NO TRADE");
  });

  it("shows Place Trade below the saved minimum and keeps the checkbox as consent", () => {
    const placement = orderPlacement({
      ...executableScan,
      toggleOn: DEFAULT_USER_SETTINGS.autoExecEnabled,
      serverAutoSubmit: false,
      composite: 39,
      threshold: 40,
    });
    const html = renderOrderActions(placement);
    expect(placement.placeTradeEnabled).toBe(true);
    expect(thesisCheckboxState(placement)).toEqual({
      disabled: false,
      submitsOnAccept: false,
      reason: null,
    });
    expect(html).toContain('data-testid="submit-order"');
    expect(html).toContain("Place Trade");
    expect(html).toContain('data-testid="thesis"');
    expect(html).toContain('data-testid="manual-confirmation-note"');
    expect(html).toContain("Manual confirmation required (score 39.0 vs. your auto-execute minimum 40.0).");
    expect(html).not.toContain('data-testid="auto-exec-hint"');
    expect(html).not.toContain("Acknowledge");
    expect(html).not.toContain("NO TRADE");
  });

  it("keeps the checkbox clickable and opens Acknowledge when the order would be rejected", () => {
    const stale = "Composite 62.9. Your minimum 50.0. Not auto-executable: quote 17 min old.";
    const placement = orderPlacement({
      ...executableScan,
      composite: 62.9,
      threshold: 50,
      executable: false,
      validationPassed: false,
      placeable: false,
      blockReason: stale,
    });
    const html = renderOrderActions(placement, true);
    expect(thesisCheckboxState(placement)).toEqual({
      disabled: false,
      submitsOnAccept: false,
      reason: null,
    });
    expect(placement.overrideRequired).toBe(true);
    expect(html).not.toContain('data-testid="order-blocked-reason"');
    expect(html).toContain('data-testid="thesis"');
    expect(html).not.toContain('disabled=""');
    expect(html).toContain('data-testid="acknowledge-order"');
    expect(html).toContain("Acknowledge");
    expect(html).toContain('data-testid="submit-order"');
    expect(html).toContain("Place Trade");
  });

  it("keeps the checkbox clickable until a wide spread is confirmed", () => {
    const reason = "Bid/ask spread is 12% of mid. Confirm to continue.";
    const unconfirmed = orderPlacement({
      ...executableScan,
      composite: 80,
      threshold: 40,
      spreadConfirmationRequired: true,
      spreadConfirmed: false,
      blockReason: reason,
    });
    expect(thesisCheckboxState(unconfirmed)).toEqual({
      disabled: false,
      submitsOnAccept: false,
      reason: null,
    });
    expect(unconfirmed.overrideRequired).toBe(true);
    expect(renderOrderActions(unconfirmed, true)).toContain("Acknowledge");
    const confirmed = orderPlacement({
      ...executableScan,
      composite: 80,
      threshold: 40,
      spreadConfirmationRequired: true,
      spreadConfirmed: true,
    });
    const state = thesisCheckboxState(confirmed);
    expect(state.disabled).toBe(false);
    expect(state.submitsOnAccept).toBe(true);
    expect(confirmed.overrideRequired).toBe(false);
  });

  it("does not lock the checkbox when the server sent no sentence", () => {
    const placement = orderPlacement({ ...executableScan, composite: 80, threshold: 40, placeable: false });
    expect(thesisCheckboxState(placement)).toEqual({
      disabled: false,
      submitsOnAccept: false,
      reason: null,
    });
    expect(placement.overrideRequired).toBe(true);
    expect(renderOrderActions(placement, true)).toContain("Acknowledge");
    expect(renderOrderActions(placement)).not.toContain("This order cannot be submitted right now.");
  });

  it("wires the checkbox to the order mutation and the override disclaimer", () => {
    const page = readFileSync(resolve(here, "DeepScan.tsx"), "utf8");
    expect(page).toContain("thesisState.submitsOnAccept");
    expect(page).toContain("order.mutate({ thesisAccepted: true })");
    expect(page).toContain("userOverride: true");
    expect(page).toContain("thesis_accepted: input.thesisAccepted");
    expect(page).toContain("APEX could not verify this trade");
    expect(page).toContain("Proceed at my own risk");
    expect(page).toContain("const userOverride = input.userOverride === true");
    expect(page).toContain("user_override: userOverride");
    expect(page).toContain("OrderRefusalDialog");
    expect(page).toContain("setOrderRefusal(sentence)");
    expect(page).toContain("explainOrderRefusal((e as Error).message)");
    expect(page).not.toContain("setOrderRefusal((e as Error).message)");
    expect(page).toContain("OrderSubmitProgress");
    expect(page).toContain("order.isPending || progressComplete");
    expect(page).toContain("orderConfirmation && !order.isPending && !progressComplete");
    expect(page).toContain('toLowerCase() !== "filled"');
    expect(page).toContain("refreshDeskQueries(qc)");
    expect(page).toContain('nav("/app")');
    expect(page).toContain("if (orderRefusal !== null) return");
    expect(page).not.toContain("onError: (e) => setMsg");
    expect(page).not.toContain("Strategy layer is not tradeable");
    const actions = readFileSync(resolve(here, "../components/RiskReviewOrderActions.tsx"), "utf8");
    expect(actions).toContain("acknowledge-order");
    expect(actions).toContain("Acknowledge");
    const progress = readFileSync(resolve(here, "../components/OrderSubmitProgress.tsx"), "utf8");
    expect(progress).toContain('data-testid="order-progress"');
    expect(progress).toContain("Submitting");
    expect(progress).toContain("Filled");
    expect(progress).toContain("Not submitted");
    expect(progress).not.toContain("order-progress-pct");
    expect(progress).not.toContain("aria-valuenow");
    expect(progress).not.toContain("requestAnimationFrame");
    const pending = renderToStaticMarkup(
      <OrderSubmitProgress phase="submitting" facts={{ ticker: "AAPL", strategy: "Bull Call Spread" }} />,
    );
    expect(pending).toContain('data-testid="order-progress"');
    expect(pending).toContain('data-phase="submitting"');
    expect(pending).toContain("Submitting");
    expect(pending).toContain("AAPL");
    expect(pending).toContain("Bull Call Spread");
    expect(pending).not.toContain("%");
    expect(pending).not.toContain("order-progress-ring");
    const filled = renderToStaticMarkup(
      <OrderSubmitProgress phase="filled" facts={{ ticker: "AAPL", strategy: "Bull Call Spread" }} />,
    );
    expect(filled).toContain('data-phase="filled"');
    expect(filled).toContain("Filled");
    expect(filled).toContain("AAPL");
    const refused = renderToStaticMarkup(
      <OrderSubmitProgress
        phase="not-submitted"
        facts={{ detail: "The connection failed, so the order was not submitted." }}
      />,
    );
    expect(refused).toContain('data-phase="not-submitted"');
    expect(refused).toContain("Not submitted");
    expect(refused).toContain("The connection failed, so the order was not submitted.");
    expect(refused).not.toContain("%");
  });

  it("renders each option leg from the scan ticket and not the empty sentence", () => {
    const rows = optionReviewRows({
      ticketLegs: [
        {
          symbol: "MSFT261016C00515000",
          side: "buy",
          qty: 1,
          strike: 515,
          option_side: "call",
          expiry: "2026-10-16",
          order_type: "limit",
          limit_basis: "mid",
          price: 11.07,
        },
      ],
      contractsPerLeg: 1,
      multiplier: 100,
    });
    const html = renderToStaticMarkup(<RiskReviewLegs rows={rows} />);
    expect(html).toContain("MSFT261016C00515000");
    expect(html).toContain("BUY");
    expect(html).toContain(">1<");
    expect(html).toContain("limit at mid");
    expect(html).toContain("est. premium $11.07");
    expect(html).toContain("account impact debit $1107.00");
    expect(html).not.toContain("No options legs are available for this scan.");
  });

  it("uses strategy metrics when the risk-review ticket was left empty", () => {
    const rows = optionReviewRows({
      ticketLegs: [],
      metricLegs: [
        {
          action: "buy",
          side: "call",
          strike: 515,
          expiry: "2026-10-16",
          mid: 11.07,
          symbol: "MSFT261016C00515000",
          quantity: 1,
          order_type: "market",
        },
      ],
      strategyName: "Long Call",
      contractsPerLeg: 1,
      multiplier: 100,
    });
    const html = renderToStaticMarkup(<RiskReviewLegs rows={rows} />);
    expect(rows).toHaveLength(1);
    expect(html).toContain("MSFT261016C00515000");
    expect(html).toContain("BUY");
    expect(html).toContain("market");
    expect(html).toContain("est. premium $11.07");
    expect(html).toContain("account impact debit $1107.00");
    expect(html).not.toContain("No options legs are available for this scan.");
  });

  it("shows the gate that failed when the scan has no buildable contracts", () => {
    const rows = optionReviewRows({
      ticketLegs: [],
      metricLegs: [],
      strategyName: "APEX Strategy",
      contractsPerLeg: 1,
    });
    const reason = optionsLegBlockReason({
      validationError: "APEX Strategy requires all four legs. Missing: back-week put.",
    });
    const html = renderToStaticMarkup(
      <p data-testid="risk-blocked">{rows.length ? "legs" : reason}</p>,
    );
    expect(rows).toHaveLength(0);
    expect(html).toContain("APEX Strategy requires all four legs. Missing: back-week put.");
    expect(html).not.toContain("No options legs are available for this scan.");
  });

  it("labels the AAPL mid limit as limit at mid, not a market order", () => {
    const rows = optionReviewRows({
      ticketLegs: [
        {
          symbol: "AAPL261023C00330000",
          side: "buy",
          qty: 1,
          strike: 330,
          option_side: "call",
          expiry: "2026-10-23",
          order_type: "limit",
          limit_basis: "mid",
          price: 9.16,
        },
      ],
      contractsPerLeg: 1,
      multiplier: 100,
    });
    expect(ticketTypeLabel(rows)).toBe("limit at mid");
    expect(ticketTypeLabel(rows)).not.toBe("market · us_option");
    const html = renderToStaticMarkup(<RiskReviewLegs rows={rows} />);
    expect(html).toContain("AAPL261023C00330000");
    expect(html).toContain("limit at mid");
    expect(html).toContain("est. premium $9.16");
    expect(html).toContain("account impact debit $916.00");
  });

  function twoLegReview(source: "metrics" | "ticket") {
    const call = {
      symbol: "MSFT261016C00515000",
      strike: 515,
      expiry: "2026-10-16",
      price: 11.07,
    };
    const put = {
      symbol: "MSFT261016P00500000",
      strike: 500,
      expiry: "2026-10-16",
      price: 8.4,
    };
    const validationErrors = [{ check: "leg_count", expected: "2", actual: "0" }];
    const failedChecks = ["Pre-trade check leg_count: expected 2; actual 0."];
    const review = buildOrderReview({
      metricLegs:
        source === "metrics"
          ? [
              { action: "buy", side: "call", strike: call.strike, expiry: call.expiry, mid: call.price, symbol: call.symbol, quantity: 1 },
              { action: "sell", side: "put", strike: put.strike, expiry: put.expiry, mid: put.price, symbol: put.symbol, quantity: 1, order_type: "market" },
            ]
          : [],
      ticketLegs:
        source === "ticket"
          ? [
              { symbol: call.symbol, side: "buy", qty: 1, strike: call.strike, option_side: "call", expiry: call.expiry, price: call.price },
              { symbol: put.symbol, side: "sell", qty: 1, strike: put.strike, option_side: "put", expiry: put.expiry, price: put.price, order_type: "market" },
            ]
          : [],
      validationErrors,
      failedChecks,
      blockReason: failedChecks[0],
      contractsPerLeg: 1,
      multiplier: 100,
    });
    const placement = orderPlacement({
      ...executableScan,
      composite: 80,
      threshold: 40,
      hasLegs: review.rows.length > 0,
    });
    const html = renderToStaticMarkup(
      review.rows.length === 0 ? (
        <p data-testid="risk-blocked">{review.emptyReason}</p>
      ) : (
        <div data-testid="risk-review">
          <RiskReviewLegs rows={review.rows} />
          {review.failedChecks.length > 0 ? (
            <p data-testid="execution-banner">{notExecutableLine(review.failedChecks)}</p>
          ) : null}
          <p data-testid="order-type">{review.typeLabel}</p>
          <RiskReviewOrderActions
            placement={placement}
            thesisAccepted={false}
            onThesisChange={() => undefined}
            onPlace={() => undefined}
          />
        </div>
      ),
    );
    return { review, placement, html };
  }

  it("does not render expected 2; actual 0 when metrics.legs already has two legs", () => {
    const { review, placement, html } = twoLegReview("metrics");
    expect(review.rows).toHaveLength(2);
    expect(html).not.toContain("expected 2; actual 0");
    expect(html).toContain("MSFT261016C00515000");
    expect(html).toContain("MSFT261016P00500000");
    expect(html).toContain("BUY");
    expect(html).toContain("SELL");
    expect(html).toContain("contract");
    expect(html).toContain("limit at mid");
    expect(html).not.toContain("market · us_option");
    expect(html).toContain("est. premium $11.07");
    expect(html).toContain("account impact debit $1107.00");
    expect(html).toContain("est. premium $8.40");
    expect(html).toContain("account impact credit $840.00");
    expect(html).toContain('data-testid="thesis"');
    expect(placement.autoSubmitOnAck).toBe(true);
    expect(html).toContain("Accepting the thesis submits these legs.");
    expect(html).not.toContain("Acknowledge");
  });

  it("does not render expected 2; actual 0 when strategy_legs already has two legs", () => {
    const { review, html } = twoLegReview("ticket");
    expect(review.rows).toHaveLength(2);
    expect(html).not.toContain("expected 2; actual 0");
    expect(html).toContain("MSFT261016C00515000");
    expect(html).toContain("MSFT261016P00500000");
    expect(html).toContain("limit at mid");
    expect(html).not.toContain("market · us_option");
    expect(html).toContain("Accepting the thesis submits these legs.");
    expect(html).not.toContain("Acknowledge");
  });

  it("renders a stock leg as shares at the mid and keeps Place Trade when no check failed", () => {
    const review = buildOrderReview({
      metricLegs: [
        { action: "buy", side: "stock", symbol: "MSFT", quantity: 100, mid: 420.5, order_type: "market" },
        {
          action: "sell",
          side: "call",
          strike: 430,
          expiry: "2026-10-16",
          mid: 4.2,
          symbol: "MSFT261016C00430000",
          quantity: 1,
        },
      ],
      ticketLegs: [],
      validationErrors: [{ check: "leg_count", expected: "2", actual: "0" }],
      failedChecks: ["Pre-trade check leg_count: expected 2; actual 0."],
      blockReason: "Pre-trade check leg_count: expected 2; actual 0.",
      contractsPerLeg: 1,
      multiplier: 100,
    });
    const placement = orderPlacement({
      ...executableScan,
      serverAutoSubmit: false,
      composite: 30,
      threshold: 40,
      hasLegs: review.rows.length > 0,
    });
    const html = renderToStaticMarkup(
      <div>
        <RiskReviewLegs rows={review.rows} />
        <p data-testid="order-type">{review.typeLabel}</p>
        <RiskReviewOrderActions
          placement={placement}
          thesisAccepted={false}
          onThesisChange={() => undefined}
          onPlace={() => undefined}
        />
      </div>,
    );
    expect(html).not.toContain("expected 2; actual 0");
    expect(html).toContain("MSFT");
    expect(html).toContain("100");
    expect(html).toContain("shares");
    expect(html).toContain("est. price $420.50");
    expect(html).toContain("account impact debit $42050.00");
    expect(html).toContain("MSFT261016C00430000");
    expect(html).toContain("limit at mid");
    expect(html).not.toContain("market · us_option");
    expect(placement.placeTradeEnabled).toBe(true);
    expect(html).toContain("Place Trade");
    expect(html).toContain('data-testid="submit-order"');
    expect(html).toContain("Place Trade");
  });

  it("says the scan returned no legs when both leg arrays are empty", () => {
    const review = buildOrderReview({
      metricLegs: [],
      ticketLegs: [],
      validationErrors: [{ check: "leg_count", expected: "2", actual: "0" }],
      failedChecks: ["Pre-trade check leg_count: expected 2; actual 0."],
      blockReason: "Pre-trade check leg_count: expected 2; actual 0.",
      equityRequired: true,
      contractsPerLeg: 1,
    });
    const html = renderToStaticMarkup(<p data-testid="risk-blocked">{review.rows.length ? "legs" : review.emptyReason}</p>);
    expect(review.rows).toHaveLength(0);
    expect(html).toContain("The scan returned no legs.");
    expect(html).not.toContain("expected 2; actual 0");
    expect(html).not.toContain("MSFT");
    expect(html).not.toContain("limit at mid");
  });
});
