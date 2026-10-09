import { motion } from "framer-motion";
import { useMemo } from "react";
import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";
import { accountModeLabel, formatOrderType } from "../lib/orderFormat";
import { formatBreakevens, breakevenIvAssumptionNote } from "../lib/strategyFormat";
import { normalizeStrategyName } from "../lib/strategyDisplay";
import { formatCompositeScore } from "../lib/scoreFormat";
import { parseOccSymbol } from "../lib/optionSymbolParse";
import {
  buildCertificateLegs,
  buildCertificateLegsFromStrategy,
  positionToLeg,
} from "../lib/certificateLegs";
import type { CertificateLegDisplay } from "../lib/certificateLegs";
import { CertificateLegList } from "./CertificateLegList";
import { ApexLogo } from "./ApexLogo";
import {
  EXPIRY_AUTO_CLOSE_NOTICE,
  formatDaysLeft,
  sortExpiryItems,
  type ExpiryNoticeItem,
} from "../lib/expiryNotice";
import { formatOptionExpiration } from "../lib/optionSymbolParse";
import type { BreakevenValue, OrderConfirmationDetails, PositionRow, StrategyLeg } from "../types";

export type PositionCertificateDetails = {
  position: PositionRow;
  strategyName?: string;
  entryScore?: number | null;
  accountLabel: string;
  isPaper: boolean;
  greeks?: { delta?: number | null; gamma?: number | null; theta?: number | null; vega?: number | null };
  relatedLegs?: PositionRow[];
  strategyLegs?: StrategyLeg[];
  breakevens?: BreakevenValue[];
  breakevenIvAssumption?: boolean;
  breakevenAssumptionNote?: string;
};

type OrderProps = {
  variant?: "order";
  details: OrderConfirmationDetails;
  onDismiss: () => void;
};

type PositionProps = {
  variant: "position";
  details: PositionCertificateDetails;
  onDismiss: () => void;
  onClosePosition?: (positionId: string) => void;
  closing?: boolean;
};

export type ExpiryNoticeDetails = {
  items: ExpiryNoticeItem[];
  isPaper: boolean;
};

type ExpiryProps = {
  variant: "expiry";
  details: ExpiryNoticeDetails;
  onDismiss: () => void;
  onClosePosition?: (positionId: string) => void;
  closingId?: string | null;
};

type Props = OrderProps | PositionProps | ExpiryProps;

function positionTicker(symbol: string): string {
  const parsed = parseOccSymbol(symbol);
  return parsed?.root ?? symbol.slice(0, 6);
}

export function OrderConfirmationCertificate(props: Props) {
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, props.onDismiss);

  const isExpiry = props.variant === "expiry";
  const isPosition = props.variant === "position";
  const positionDetails = isPosition ? props.details : null;
  const orderDetails = !isPosition && !isExpiry ? props.details : null;
  const expiryItems = isExpiry ? sortExpiryItems(props.details.items) : [];

  const strategyName = normalizeStrategyName(
    isPosition ? positionDetails?.strategyName : orderDetails?.strategyName,
  );
  const isPaper = isExpiry
    ? Boolean(props.details.isPaper)
    : isPosition
      ? Boolean(positionDetails?.isPaper)
      : orderDetails?.accountMode === "paper_funded";

  const legs = useMemo((): CertificateLegDisplay[] => {
    if (isPosition && positionDetails) {
      if (positionDetails.strategyLegs?.length) {
        return buildCertificateLegsFromStrategy(positionDetails.strategyLegs);
      }
      const rows = positionDetails.relatedLegs?.length
        ? positionDetails.relatedLegs
        : [positionDetails.position];
      return rows.map(positionToLeg);
    }
    if (orderDetails) {
      return buildCertificateLegs(orderDetails.legs);
    }
    return [];
  }, [isPosition, orderDetails, positionDetails]);

  const breakevenNote =
    isPosition && positionDetails
      ? breakevenIvAssumptionNote(positionDetails.breakevens, {
          breakeven_iv_assumption: positionDetails.breakevenIvAssumption,
          breakeven_assumption_note: positionDetails.breakevenAssumptionNote,
        })
      : null;

  const orderTypeDisplay = orderDetails
    ? formatOrderType(orderDetails.orderType, orderDetails.assetClass)
    : null;
  const pnl = positionDetails?.position.unrealized_pl;

  if (isExpiry && expiryItems.length === 0) return null;

  const testId = isExpiry
    ? "expiry-notice-modal"
    : isPosition
      ? "position-certificate-modal"
      : "order-confirmation-modal";
  const titleId = isExpiry ? "expiry-notice-title" : isPosition ? "position-cert-title" : "order-cert-title";
  const title = isExpiry ? "Expiration notice" : isPosition ? "Position Certificate" : "Order Confirmation";

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      data-testid={testId}
      role="dialog"
      aria-labelledby={titleId}
      aria-modal="true"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 12 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.22, 0.82, 0.2, 1] }}
        className="order-cert-card w-full max-w-lg"
      >
        <div className="order-cert-frame">
          <div className="order-cert-inner">
            {isPaper ? (
              <p
                className="order-cert-paper-banner"
                data-testid={
                  isExpiry ? "expiry-notice-paper-banner" : isPosition ? "position-cert-paper-banner" : "order-cert-paper-banner"
                }
              >
                PAPER TRADE
              </p>
            ) : null}

            <div className="order-cert-header">
              <ApexLogo size={52} className="order-cert-logo" />
              <p className="order-cert-eyebrow">APEX Terminal</p>
              <h2 id={titleId} className="order-cert-title">
                {title}
              </h2>
              {isExpiry ? (
                <p className="order-cert-status">Next 7 days</p>
              ) : isPosition ? (
                <p className="order-cert-status">Open · read-only</p>
              ) : orderDetails?.status ? (
                <p className="order-cert-status" data-testid="order-cert-status">
                  {orderDetails.status}
                </p>
              ) : null}
            </div>

            {isExpiry ? (
              <>
                <p className="sf-panel-note" data-testid="expiry-notice-copy">
                  {EXPIRY_AUTO_CLOSE_NOTICE}
                </p>
                <div className="order-cert-legs" data-testid="expiry-notice-list">
                  <p className="order-cert-legs-label">Open trades</p>
                  <ul>
                    {expiryItems.map((item) => (
                      <li key={`${item.position_id ?? "ext"}-${item.symbol}`} data-testid={`expiry-row-${item.symbol}`}>
                        <dl className="order-cert-grid">
                          <div className="order-cert-row">
                            <dt>Symbol</dt>
                            <dd data-testid={`expiry-symbol-${item.symbol}`}>{item.symbol}</dd>
                          </div>
                          <div className="order-cert-row">
                            <dt>Strategy</dt>
                            <dd data-testid={`expiry-strategy-${item.symbol}`}>{normalizeStrategyName(item.strategy)}</dd>
                          </div>
                          <div className="order-cert-row">
                            <dt>Expiry</dt>
                            <dd className="order-cert-leg-expiry" data-testid={`expiry-date-${item.symbol}`}>
                              {formatOptionExpiration(item.expiry)}
                            </dd>
                          </div>
                          <div className="order-cert-row">
                            <dt>Days left</dt>
                            <dd data-testid={`expiry-days-${item.symbol}`}>{formatDaysLeft(item.days_left)}</dd>
                          </div>
                        </dl>
                        {item.can_close && item.position_id && props.variant === "expiry" && props.onClosePosition ? (
                          <button
                            type="button"
                            className="order-cert-dismiss order-cert-dismiss-secondary"
                            data-testid={`expiry-close-${item.position_id}`}
                            disabled={props.closingId === item.position_id}
                            onClick={() => props.onClosePosition?.(item.position_id as string)}
                          >
                            Close
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
                <button
                  type="button"
                  className="order-cert-dismiss"
                  data-testid="expiry-notice-dismiss"
                  onClick={props.onDismiss}
                >
                  Dismiss
                </button>
              </>
            ) : (
              <>
            <dl className="order-cert-grid">
              {isPosition && positionDetails ? (
                <>
                  <div className="order-cert-row">
                    <dt>Ticker</dt>
                    <dd data-testid="position-cert-ticker">{positionTicker(positionDetails.position.symbol)}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Strategy</dt>
                    <dd data-testid="position-cert-strategy">{strategyName}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Entry score</dt>
                    <dd data-testid="position-cert-entry-score">
                      {formatCompositeScore(positionDetails.entryScore)}
                    </dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Current P&amp;L</dt>
                    <dd
                      className={pnl != null && pnl >= 0 ? "num-up" : "num-down"}
                      data-testid="position-cert-pnl"
                    >
                      {pnl == null ? "—" : `${pnl >= 0 ? "+" : ""}${pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}`}
                    </dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Account</dt>
                    <dd data-testid="position-cert-account">{positionDetails.accountLabel}</dd>
                  </div>
                  {positionDetails.greeks ? (
                    <div className="order-cert-row">
                      <dt>Greeks (Δ Γ Θ V)</dt>
                      <dd className="text-xs" data-testid="position-cert-greeks">
                        {[
                          positionDetails.greeks.delta,
                          positionDetails.greeks.gamma,
                          positionDetails.greeks.theta,
                          positionDetails.greeks.vega,
                        ]
                          .map((g) => (g == null ? "—" : g.toFixed(3)))
                          .join(" · ")}
                      </dd>
                    </div>
                  ) : null}
                  {positionDetails.breakevens?.length ? (
                    <div className="order-cert-row">
                      <dt>Breakeven(s)</dt>
                      <dd data-testid="position-cert-breakevens">
                        {formatBreakevens(positionDetails.breakevens)}
                      </dd>
                    </div>
                  ) : null}
                </>
              ) : orderDetails ? (
                <>
                  <div className="order-cert-row">
                    <dt>Ticker</dt>
                    <dd data-testid="order-cert-ticker">{orderDetails.ticker}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Strategy</dt>
                    <dd data-testid="order-cert-strategy">{strategyName}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Order type</dt>
                    <dd data-testid="order-cert-order-type">{orderTypeDisplay}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Account</dt>
                    <dd data-testid="order-cert-account">{orderDetails.accountLabel}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Account mode</dt>
                    <dd data-testid="order-cert-account-mode">{accountModeLabel(orderDetails.accountMode)}</dd>
                  </div>
                  <div className="order-cert-row">
                    <dt>Order ID{orderDetails.orderIds.length === 1 ? "" : "s"}</dt>
                    <dd className="order-cert-ids" data-testid="order-cert-order-ids">
                      {orderDetails.orderIds.join(", ")}
                    </dd>
                  </div>
                </>
              ) : null}
            </dl>

            <CertificateLegList
              legs={legs}
              label={isPosition ? "Open legs" : "Purchased"}
              testId={isPosition ? "position-cert-legs" : "order-cert-legs"}
            />

            {breakevenNote ? (
              <p className="sf-panel-note mt-2" data-testid="position-cert-breakeven-iv-note">
                {breakevenNote}
              </p>
            ) : null}

            {isPosition && props.variant === "position" && props.onClosePosition ? (
              <div className="flex gap-2">
                <button
                  type="button"
                  className="order-cert-dismiss order-cert-dismiss-secondary flex-1"
                  data-testid="position-cert-close-btn"
                  disabled={props.closing}
                  onClick={() => props.onClosePosition!(positionDetails!.position.id)}
                >
                  Close position
                </button>
                <button
                  type="button"
                  className="order-cert-dismiss flex-1"
                  data-testid="position-cert-dismiss"
                  onClick={props.onDismiss}
                >
                  Dismiss
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="order-cert-dismiss"
                data-testid={isPosition ? "position-cert-dismiss" : "order-cert-dismiss"}
                onClick={props.onDismiss}
              >
                {isPosition ? "Dismiss" : "Continue to dashboard"}
              </button>
            )}
              </>
            )}
          </div>
        </div>
      </motion.div>
    </div>
  );
}
