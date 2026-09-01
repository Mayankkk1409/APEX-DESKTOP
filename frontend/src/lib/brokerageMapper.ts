import type { BrokeragePosition } from "./brokerageApi";
import { extractBrokerageDayPl } from "./positionDayPl";
import type { PositionRow } from "../types";

export function mapBrokeragePositions(positions: BrokeragePosition[]): PositionRow[] {
  return positions.map((p, i) => ({
    id: `brokerage-${p.symbol}-${i}`,
    symbol: p.symbol,
    qty: p.quantity,
    avg_cost: p.average_cost,
    current: p.current_price,
    unrealized_pl: p.unrealized_pnl,
    market_value: p.market_value,
    day_pl: extractBrokerageDayPl(p),
    asset_class: "us_equity",
  }));
}
