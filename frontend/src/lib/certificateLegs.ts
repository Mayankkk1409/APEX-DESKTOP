import { formatOptionExpiration, formatLegSide, parseOccSymbol } from "../lib/optionSymbolParse";
import type { OrderLegFill, PositionRow, StrategyLeg } from "../types";

export type CertificateLegDisplay = {
  id: string;
  side: string;
  qty: number;
  symbol: string;
  fill_price?: number | null;
  expiration?: string;
  strike?: number;
  optionSide?: "call" | "put";
  longShort?: "long" | "short";
  premium?: number | null;
  orderType?: string;
};

export function legFromOrderFill(leg: OrderLegFill): CertificateLegDisplay {
  const parsed = parseOccSymbol(leg.symbol);
  return {
    id: leg.id,
    side: leg.side,
    qty: leg.qty,
    symbol: leg.symbol,
    fill_price: leg.fill_price,
    expiration: parsed ? formatOptionExpiration(parsed.expiry) : undefined,
    strike: parsed?.strike,
    optionSide: parsed?.side,
    longShort: formatLegSide(leg.qty, leg.side),
    premium: leg.fill_price,
    orderType: leg.order_type ?? "limit",
  };
}

export function buildCertificateLegs(legs: OrderLegFill[]): CertificateLegDisplay[] {
  return legs.map(legFromOrderFill);
}

function formatStrategyLegExpiry(expiry: string | undefined): string | undefined {
  if (!expiry) return undefined;
  const formatted = formatOptionExpiration(expiry);
  return formatted === "—" ? expiry : formatted;
}

export function strategyLegToDisplay(leg: StrategyLeg, index: number): CertificateLegDisplay {
  if (leg.side === "stock") {
    const longShort = leg.action === "sell" ? "short" : "long";
    return {
      id: leg.symbol ?? `stock-leg-${index}`,
      side: leg.action,
      qty: leg.quantity ?? 100,
      symbol: leg.symbol ?? "STOCK",
      fill_price: leg.mid,
      expiration: undefined,
      strike: leg.strike ?? undefined,
      optionSide: undefined,
      longShort,
      premium: leg.mid,
    };
  }
  const parsed = leg.symbol ? parseOccSymbol(leg.symbol) : null;
  const expiry = leg.expiry ? formatStrategyLegExpiry(leg.expiry) : parsed ? formatOptionExpiration(parsed.expiry) : undefined;
  const longShort = leg.action === "sell" ? "short" : "long";
  return {
    id: leg.symbol ?? `strategy-leg-${index}`,
    side: leg.action,
    qty: 1,
    symbol: leg.symbol ?? `${leg.side ?? "opt"} ${leg.strike ?? ""}`.trim(),
    fill_price: leg.mid,
    expiration: expiry,
    strike: leg.strike ?? parsed?.strike,
    optionSide: (leg.side as "call" | "put" | undefined) ?? parsed?.side,
    longShort,
    premium: leg.mid,
    orderType: leg.order_type ?? "limit",
  };
}

export function buildCertificateLegsFromStrategy(legs: StrategyLeg[]): CertificateLegDisplay[] {
  return legs.map(strategyLegToDisplay);
}

export function positionToLeg(p: PositionRow): CertificateLegDisplay {
  const parsed = parseOccSymbol(p.symbol);
  const longShort = formatLegSide(p.qty);
  return {
    id: p.id,
    side: longShort === "short" ? "sell" : "buy",
    qty: Math.abs(p.qty),
    symbol: p.symbol,
    fill_price: p.avg_cost,
    expiration: parsed ? formatOptionExpiration(parsed.expiry) : undefined,
    strike: parsed?.strike,
    optionSide: parsed?.side,
    longShort,
    premium: p.avg_cost,
  };
}

export function formatLegDetail(leg: CertificateLegDisplay): string {
  const parts: string[] = [];
  if (leg.longShort) parts.push(leg.longShort.toUpperCase());
  if (leg.optionSide) parts.push(leg.optionSide.toUpperCase());
  if (leg.strike != null) parts.push(String(leg.strike));
  if (leg.expiration) parts.push(leg.expiration);
  return parts.join(" · ") || leg.symbol;
}
