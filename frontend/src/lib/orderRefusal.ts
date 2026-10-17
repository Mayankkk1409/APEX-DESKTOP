import { apiErrorSentence, isSettledOrderSentence } from "./apiError";

/** Turn a refusal into the measured fact plus one sentence a trader can use. */

const ALREADY_EXPLAINED =
  /not reliable|cannot cover the order|not the strategy on the card|not the shape on the card|too old to trust the price|did not take the order|not split into market orders|no short leg was submitted|paper order filled|no order was sent|this order was not sent|review the reason|already at the limit/i;

function strategyLabel(id: string): string {
  const words = id.split("_").filter(Boolean);
  if (!words.length) return "Strategy";
  return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function refusalRecord(raw: string): Record<string, string> | null {
  const direct = parseRecord(raw);
  if (direct) return direct;
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  return parseRecord(raw.slice(start, end + 1));
}

function parseRecord(raw: string): Record<string, string> | null {
  const text = raw.trim();
  if (!text.startsWith("{") || !text.endsWith("}")) return null;
  try {
    const parsed = JSON.parse(text) as unknown;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const out: Record<string, string> = {};
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        if (value != null && typeof value !== "object") out[key] = String(value);
      }
      return Object.keys(out).length ? out : null;
    }
  } catch {
    /* Python repr uses single quotes. */
  }
  const out: Record<string, string> = {};
  const pairs = text.matchAll(/['"]([A-Za-z0-9_]+)['"]\s*:\s*['"]([^'"]*)['"]/g);
  for (const match of pairs) out[match[1]] = match[2];
  return Object.keys(out).length ? out : null;
}

function factFromRecord(record: Record<string, string>): string {
  const check = (record.check || "validation").replaceAll("_", " ");
  const name = strategyLabel(record.strategy_id || "strategy");
  const ticker = record.ticker ? ` on ${record.ticker}` : "";
  const expected = record.expected ?? "—";
  const actual = record.actual ?? "—";
  return `${name}${ticker} failed the ${check} check: expected ${expected}, got ${actual}.`;
}

const BARE_CODES: Record<string, string> = {
  leg_count: "Failed the leg count check.",
  breakeven_shape: "Failed the breakeven shape check.",
  spread: "The bid/ask spread is wider than the cap.",
};

function refusalFact(raw: string): string {
  const text = raw.trim();
  const record = parseRecord(text);
  if (record) return factFromRecord(record);
  if (text.startsWith("{")) return "Strategy validation failed.";
  return BARE_CODES[text] ?? text;
}

function refusalWhy(fact: string): string {
  const text = fact.toLowerCase();
  if (text.includes("bid/ask spread") || text.includes("% of mid") || text.includes("wider than the")) {
    return "The price you would pay is not reliable. No order was sent. Review the quotes, then try again if you still want this trade.";
  }
  if (text.includes("buying power")) {
    return "The account cannot cover the order. No order was sent. Reduce the size or free up buying power, then review the trade again.";
  }
  if (text.includes("no current price") || text.includes("usable price") || text.includes("couldn't get a price")) {
    return "We couldn't place this trade because one option leg doesn't have a usable price. No order was sent. Refresh the option chain and review the prices before trying again.";
  }
  if (text.includes("leg count") || text.includes("leg_count")) {
    return "This is not the strategy on the card. No order was sent. Go back to the strategy and rebuild the legs.";
  }
  if (text.includes("breakeven")) {
    return "The payoff is not the shape on the card. No order was sent. Review the strategy before trying again.";
  }
  if (text.includes("quote not current") || text.includes("quoted ") || text.includes("couldn't confirm when")) {
    return "Refresh the quote and try again. No order was sent.";
  }
  if (text.includes("read-only")) {
    return "You're in read-only mode. No order was sent. Switch back to the paper account to place a paper trade.";
  }
  if (text.includes("stale or suspect") || text.includes("enough to hold the order")) {
    return "We couldn't confirm an up-to-date price. No order was sent. Refresh the quote or review the order before trying again.";
  }
  if (text.includes("below your minimum") || text.includes("not recommended")) {
    return "This trade is below your minimum score. No order was sent. Review the warning and confirm Proceed at my own risk if you still want to continue.";
  }
  if (
    text.includes("has not confirmed a fill") ||
    text.includes("broker received this order") ||
    text.includes("broker accepted") ||
    text.includes("waiting to fill at the broker")
  ) {
    return "Your order is waiting to fill at the broker. You can follow its status in Pending orders.";
  }
  if (text.includes("order status") || text.includes("not filled")) {
    return "The broker did not take the order. Check the order status before you send it again.";
  }
  return "This order was not sent. Review the reason, then try again if you still want the trade.";
}

/** Queue-list copy. The stored audit reason stays; this is only what the row shows. */
export function plainQueueReason(reason: string | null | undefined): string {
  const text = (reason || "").trim();
  if (!text) return "";
  if (/waiting for the authorized limit price/i.test(text)) {
    return "Your limit has not been reached. This order is waiting in APEX and has not been sent to the broker. It will be sent only if the market reaches the price you confirmed. Cancel it if you do not want that.";
  }
  if (/still waiting in APEX/i.test(text) && /wider/i.test(text)) {
    return text;
  }
  if (/bid\/ask spread|wider than the \d/i.test(text)) {
    return "This order was not sent. The bid/ask is wider than the 10% limit, so the price is not reliable. Remove it from this list, or place the trade again and confirm the warning.";
  }
  if (/waiting for a quote/i.test(text)) {
    return "A current price is not available for one leg. This order is waiting in APEX and has not been sent.";
  }
  if (/market closed|waiting for the trading session/i.test(text)) {
    return "Queued — market closed. APEX will submit this order when the applicable market opens, if it remains valid.";
  }
  if (/awaiting execution|broker has this order|broker received|has not confirmed a fill/i.test(text)) {
    return "Order submitted to Alpaca — awaiting execution.";
  }
  if (/stale or suspect|enough to hold the order/i.test(text)) {
    return "We couldn't confirm an up-to-date price. No order was sent. Refresh the quote or review the order before trying again.";
  }
  return text;
}

const BROKER_PENDING = new Set(["accepted", "pending", "new", "pending_new", "partial", "partially_filled"]);

export function isPendingOrder(row: { status?: string | null; queue_reason?: string | null }): boolean {
  const status = (row.status || "").toLowerCase();
  if (status === "queued" || status === "submitting" || status === "unknown") return true;
  if (status === "rejected" && Boolean(row.queue_reason)) return true;
  return BROKER_PENDING.has(status);
}

function limitAtBroker(row: { status?: string | null; queue_reason?: string | null; order_type?: string | null }): boolean {
  const status = (row.status || "").toLowerCase();
  const reason = row.queue_reason || "";
  if ((row.order_type || "").toLowerCase() !== "limit") return false;
  if (status === "partial" || status === "partially_filled") return false;
  if (/market closed|waiting for the trading session|when the market opens|has not been sent/i.test(reason)) return false;
  const brokerHeld = /awaiting execution|broker has this order|broker received|has not confirmed a fill/i.test(reason);
  return brokerHeld || BROKER_PENDING.has(status);
}

function limitOrderSentence(row: { side?: string | null; limit_price?: number | null }): string {
  const side = (row.side || "").toLowerCase() === "sell" ? "sell" : (row.side || "").toLowerCase() === "buy" ? "buy" : "";
  const price = typeof row.limit_price === "number" && Number.isFinite(row.limit_price) && row.limit_price > 0
    ? `$${row.limit_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    : "";
  const kind = side ? `Limit ${side}` : "Limit order";
  if (price) {
    return `${kind} at ${price}. Submitted to Alpaca. It fills only if the market reaches that price.`;
  }
  return `${kind} submitted to Alpaca. It fills only if the market reaches your limit.`;
}

export function pendingStatusLabel(row: { status?: string | null; queue_reason?: string | null; order_type?: string | null }): string {
  const status = (row.status || "").toLowerCase();
  const reason = row.queue_reason || "";
  const brokerHeld = /awaiting execution|broker has this order|broker received|has not confirmed a fill/i.test(reason);
  if (/market closed|waiting for the trading session|when the market opens/i.test(reason)) return "Queued — market closed";
  if (/stock order is at the broker/i.test(reason)) return "Pending at broker";
  if (status === "partial" || status === "partially_filled") return "Partially filled";
  if (limitAtBroker(row)) return "Limit order";
  if (brokerHeld || BROKER_PENDING.has(status)) return "Pending at broker";
  if (status === "rejected") return "Not submitted";
  if (status === "unknown") return "Checking submission status";
  if (status === "submitting") return "Submitting";
  return "Queued in APEX";
}

export function pendingReason(row: {
  status?: string | null;
  queue_reason?: string | null;
  order_type?: string | null;
  side?: string | null;
  limit_price?: number | null;
}): string {
  if (limitAtBroker(row)) return limitOrderSentence(row);
  if (row.queue_reason) return plainQueueReason(row.queue_reason);
  const status = (row.status || "").toLowerCase();
  if (status === "partial" || status === "partially_filled") {
    return "Partially filled. The rest is still pending at the broker.";
  }
  if (status === "unknown") {
    return "Checking submission status. This order will not be sent again until that result is reconciled.";
  }
  if (BROKER_PENDING.has(status)) {
    return "Order submitted to Alpaca — awaiting execution.";
  }
  return "";
}

export function orderHistoryStatus(status: string | null | undefined): string {
  const key = (status || "").toLowerCase();
  if (key === "accepted" || key === "pending" || key === "new" || key === "pending_new") return "Broker accepted";
  if (key === "partially_filled" || key === "partial") return "Partially filled";
  if (key === "filled") return "Filled";
  if (key === "canceled" || key === "cancelled") return "Canceled";
  if (key === "rejected" || key === "blocked") return "Not submitted";
  if (key === "expired") return "Expired";
  if (key === "unknown") return "Outcome unknown";
  if (key === "queued") return "Waiting in APEX";
  if (key === "submitting") return "Submitting";
  if (key === "archived") return "Removed";
  return status || "—";
}

export function explainOrderRefusal(reason: string): string {
  const text = reason.trim();
  if (/already at the limit/i.test(text)) {
    const cap = text.match(/limit of (\d+)/i)?.[1];
    const limit = cap ? `the limit of ${cap}` : "your position limit";
    return `Open positions are already at ${limit}. This order was not sent. Existing holdings were not closed.`;
  }
  if (/stale or suspect|enough to hold the order/i.test(text)) {
    return "We couldn't confirm an up-to-date price. No order was sent. Refresh the quote or review the order before trying again.";
  }
  if (/below your minimum|not recommended/i.test(text) && !/no order was sent/i.test(text)) {
    return "This trade is below your minimum score. No order was sent. Review the warning and confirm Proceed at my own risk if you still want to continue.";
  }
  if (/awaiting execution/i.test(text)) {
    return "Order submitted to Alpaca — awaiting execution.";
  }
  if (/market closed/i.test(text)) {
    return "Queued — market closed. APEX will submit this order when the applicable market opens, if it remains valid.";
  }
  if (/has not confirmed a fill|broker received this order|broker accepted|waiting to fill at the broker|has not filled yet/i.test(text)) {
    return "Your order is waiting to fill at the broker. You can follow its status in Pending orders.";
  }
  if (/^the order was not submitted\.?$/i.test(text)) {
    return "APEX stopped this order before sending it. The check that stopped it did not come back with a reason.";
  }
  if (isSettledOrderSentence(text)) return text;
  const record = refusalRecord(text);
  if (record && (record.check || record.expected || record.actual)) {
    return withWhy(factFromRecord(record));
  }
  const mapped = apiErrorSentence(text, "order");
  if (mapped) return mapped;
  return withWhy(refusalFact(text));
}

function withWhy(fact: string): string {
  if (!fact) return "APEX did not submit this order. The check that blocked it was not explained.";
  if (ALREADY_EXPLAINED.test(fact)) return /[.!?]$/.test(fact) ? fact : `${fact}.`;
  const base = /[.!?]$/.test(fact) ? fact : `${fact}.`;
  return `${base} ${refusalWhy(fact)}`;
}
