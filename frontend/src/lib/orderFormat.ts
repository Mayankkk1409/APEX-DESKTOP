import type { AccountMode, OrderConfirmationDetails, OrderPlacementResult, User } from "../types";

/** Display order type and asset class as `market · us_option`. */
export function formatOrderType(orderType: string, assetClass: string): string {
  const type = orderType.trim().toLowerCase() || "market";
  const asset = assetClass.trim().toLowerCase() || "us_option";
  return `${type} · ${asset}`;
}

/** Paper or brokerage account label for order confirmation. */
export function formatOrderAccountLabel(user: User | null | undefined): string {
  if (!user) return "Paper · APEX";
  const shortId = user.id.length > 8 ? user.id.slice(0, 8) : user.id;
  if (user.account_mode === "paper_funded") {
    return `Paper · @${user.username} · ${shortId}`;
  }
  return `Brokerage · @${user.username} · ${shortId}`;
}

export function accountModeLabel(mode: AccountMode | null | undefined): string {
  if (mode === "paper_funded") return "Paper Funded";
  if (mode === "real_brokerage") return "Real Brokerage";
  return "APEX Account";
}

/** Map POST /api/orders response into certificate modal fields. */
export function buildOrderConfirmationDetails(
  result: OrderPlacementResult,
  ctx: {
    strategyName: string;
    ticker: string;
    user: User | null | undefined;
    accountMode: AccountMode | null | undefined;
    orderAssetClass?: string;
  },
): OrderConfirmationDetails {
  const legs = result.legs_filled ?? [];
  const orderIds = legs.length ? legs.map((leg) => leg.id) : [result.id];
  const assetClass = result.asset_class ?? ctx.orderAssetClass ?? "us_option";
  return {
    orderIds,
    legs,
    strategyName: ctx.strategyName,
    accountLabel: formatOrderAccountLabel(ctx.user),
    accountMode: ctx.accountMode ?? ctx.user?.account_mode ?? null,
    ticker: ctx.ticker,
    orderType: "market",
    assetClass,
    status: result.status,
  };
}
