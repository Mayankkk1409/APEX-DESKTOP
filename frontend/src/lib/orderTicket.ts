/** Order-review rows. The ticket is preferred; strategy metrics fill a missing ticket. */

const SHORT_STOCK = "cannot confirm easy-to-borrow / margin";
const APEX_STRATEGY = "APEX Strategy";

export type TicketOptionLeg = {
  symbol: string;
  side: string;
  qty?: number;
  strike?: number;
  option_side?: string;
  expiry?: string;
  order_type?: string;
  price?: number | null;
  limit_basis?: string | null;
};

export type MetricOptionLeg = {
  action?: string;
  side?: string;
  strike?: number;
  expiry?: string;
  mid?: number | null;
  symbol?: string;
  quantity?: number;
  order_type?: string;
  limit_basis?: string | null;
  short_unconfirmed?: boolean;
};

export type OptionReviewRow = {
  symbol: string;
  side: string;
  sideLabel: string;
  contracts: number;
  optionSide?: string;
  strike?: number;
  expiry?: string;
  orderType: string;
  orderTypeLabel: string;
  price: number | null;
  premiumLabel: string | null;
  impactLabel: string | null;
};

type Draft = {
  symbol: string;
  side: string;
  qty?: number;
  optionSide?: string;
  strike?: number;
  expiry?: string;
  orderType?: string;
  limitBasis?: string | null;
  price?: number | null;
};

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

function orderTypeLabel(orderType: string, limitBasis?: string | null): string {
  if (orderType === "limit" && limitBasis === "mid") return "limit at mid";
  return orderType || "market";
}

function toRow(draft: Draft, multiplier: number, contractsPerLeg: number): OptionReviewRow {
  const contracts = draft.qty && draft.qty > 0 ? draft.qty : contractsPerLeg;
  const orderType = (draft.orderType || "market").toLowerCase();
  const price = draft.price == null || Number.isNaN(Number(draft.price)) ? null : Number(draft.price);
  const impact = price == null ? null : price * contracts * multiplier;
  const side = draft.side.toLowerCase();
  return {
    symbol: draft.symbol,
    side,
    sideLabel: side.toUpperCase(),
    contracts,
    optionSide: draft.optionSide,
    strike: draft.strike,
    expiry: draft.expiry,
    orderType,
    orderTypeLabel: orderTypeLabel(orderType, draft.limitBasis),
    price,
    premiumLabel: price == null ? null : `est. premium ${money(price)}`,
    impactLabel:
      impact == null ? null : `account impact ${side === "sell" ? "credit" : "debit"} ${money(impact)}`,
  };
}

function metricOptions(legs: MetricOptionLeg[] | null | undefined): Draft[] {
  const rows: Draft[] = [];
  for (const leg of legs ?? []) {
    if (leg.short_unconfirmed || leg.side === "stock") continue;
    const action = (leg.action || "").toLowerCase();
    if (!leg.symbol || (action !== "buy" && action !== "sell")) continue;
    if (leg.side !== "call" && leg.side !== "put") continue;
    rows.push({
      symbol: leg.symbol,
      side: action,
      qty: leg.quantity,
      optionSide: leg.side,
      strike: leg.strike,
      expiry: leg.expiry,
      orderType: leg.order_type,
      limitBasis: leg.limit_basis,
      price: leg.mid,
    });
  }
  return rows;
}

/**
 * Ticket rows when the scan stored them. Otherwise the strategy's option contracts,
 * except an unconfirmed short, a missing required stock leg, or a partial APEX Strategy.
 */
export function optionReviewRows(input: {
  ticketLegs?: TicketOptionLeg[] | null;
  metricLegs?: MetricOptionLeg[] | null;
  strategyName?: string;
  equityRequired?: boolean;
  equityLegs?: unknown[] | null;
  equityCovered?: boolean;
  validationError?: string | null;
  multiplier?: number | null;
  contractsPerLeg: number;
}): OptionReviewRow[] {
  const multiplier = input.multiplier && input.multiplier > 0 ? input.multiplier : 100;
  const ticket = (input.ticketLegs ?? []).filter(
    (leg) => leg.symbol && (leg.side === "buy" || leg.side === "sell"),
  );
  if (ticket.length) {
    return ticket.map((leg) =>
      toRow(
        {
          symbol: leg.symbol,
          side: leg.side,
          qty: leg.qty,
          optionSide: leg.option_side,
          strike: leg.strike,
          expiry: leg.expiry,
          orderType: leg.order_type,
          limitBasis: leg.limit_basis,
          price: leg.price,
        },
        multiplier,
        input.contractsPerLeg,
      ),
    );
  }
  const reason = input.validationError || "";
  if (reason.includes(SHORT_STOCK)) return [];
  if ((input.metricLegs ?? []).some((leg) => leg.short_unconfirmed)) return [];
  if (input.equityRequired && !(input.equityLegs?.length) && !input.equityCovered) return [];
  const options = metricOptions(input.metricLegs);
  if (input.strategyName === APEX_STRATEGY && options.length !== 4) return [];
  return options.map((leg) => toRow(leg, multiplier, input.contractsPerLeg));
}

export function optionsLegBlockReason(input: {
  blockReason?: string | null;
  equityNote?: string | null;
  validationError?: string | null;
  validationErrors?: Array<{ check?: string; expected?: string; actual?: string }> | null;
  riskNotes?: string[] | null;
}): string {
  const block = input.blockReason?.trim();
  if (block) return block;
  const handler = input.validationError?.trim();
  if (handler) return handler;
  const first = (input.validationErrors ?? []).find((error) => error?.check);
  if (first?.check) {
    return `Pre-trade check ${first.check}: expected ${first.expected ?? "—"}; actual ${first.actual ?? "—"}.`;
  }
  const note = (input.riskNotes ?? []).find((line) => line.trim());
  if (note) return note;
  const equity = input.equityNote?.trim();
  if (equity) return equity;
  return "No options legs are available for this scan.";
}
