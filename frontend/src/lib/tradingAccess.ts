import type { PortfolioViewMode } from "../types";

/**
 * Trading stays available on the paper book.
 * It is refused only while the desk is showing a connected real brokerage.
 * Choosing real brokerage at signup, or leaving that connection unused, does not block paper orders.
 */
export function realBrokerageSource(input: {
  viewMode: PortfolioViewMode | null | undefined;
  brokerageConnected: boolean;
}): boolean {
  return input.viewMode === "brokerage" && input.brokerageConnected;
}
