import { apiErrorSentence, isSettledOrderSentence } from "./apiError";

/** Turn a refusal into the measured fact plus one sentence a trader can use. */

const ALREADY_EXPLAINED =
  /not reliable|cannot cover the order|not the strategy on the card|not the shape on the card|too old to trust the price|did not take the order|enough to hold the order|not split into market orders|no short leg was submitted|paper order filled/i;

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
    return "The price you would pay is not reliable.";
  }
  if (text.includes("buying power")) {
    return "The account cannot cover the order.";
  }
  if (text.includes("leg count") || text.includes("leg_count")) {
    return "This is not the strategy on the card.";
  }
  if (text.includes("breakeven")) {
    return "The payoff is not the shape on the card.";
  }
  if (text.includes("quote not current") || text.includes("quoted ")) {
    return "The quote is too old to trust the price.";
  }
  if (text.includes("order status") || text.includes("not filled")) {
    return "The broker did not take the order.";
  }
  return "This check is enough to hold the order.";
}

export function explainOrderRefusal(reason: string): string {
  const text = reason.trim();
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
