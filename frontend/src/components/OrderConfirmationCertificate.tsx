import { motion } from "framer-motion";
import { ApexLogo } from "./ApexLogo";
import { accountModeLabel, formatOrderType } from "../lib/orderFormat";
import type { OrderConfirmationDetails } from "../types";

type Props = {
  details: OrderConfirmationDetails;
  onDismiss: () => void;
};

export function OrderConfirmationCertificate({ details, onDismiss }: Props) {
  const orderTypeDisplay = formatOrderType(details.orderType, details.assetClass);

  return (
    <div
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center bg-black/75 p-4"
      data-testid="order-confirmation-modal"
      role="dialog"
      aria-labelledby="order-cert-title"
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
            <div className="order-cert-header">
              <ApexLogo size={52} className="order-cert-logo" />
              <p className="order-cert-eyebrow">APEX Terminal</p>
              <h2 id="order-cert-title" className="order-cert-title">
                Order Confirmation
              </h2>
              {details.status ? (
                <p className="order-cert-status" data-testid="order-cert-status">
                  {details.status}
                </p>
              ) : null}
            </div>

            <dl className="order-cert-grid">
              <div className="order-cert-row">
                <dt>Ticker</dt>
                <dd data-testid="order-cert-ticker">{details.ticker}</dd>
              </div>
              <div className="order-cert-row">
                <dt>Strategy</dt>
                <dd data-testid="order-cert-strategy">{details.strategyName}</dd>
              </div>
              <div className="order-cert-row">
                <dt>Order type</dt>
                <dd data-testid="order-cert-order-type">{orderTypeDisplay}</dd>
              </div>
              <div className="order-cert-row">
                <dt>Account</dt>
                <dd data-testid="order-cert-account">{details.accountLabel}</dd>
              </div>
              <div className="order-cert-row">
                <dt>Account mode</dt>
                <dd data-testid="order-cert-account-mode">{accountModeLabel(details.accountMode)}</dd>
              </div>
              <div className="order-cert-row">
                <dt>Order ID{details.orderIds.length === 1 ? "" : "s"}</dt>
                <dd className="order-cert-ids" data-testid="order-cert-order-ids">
                  {details.orderIds.join(", ")}
                </dd>
              </div>
            </dl>

            <div className="order-cert-legs">
              <p className="order-cert-legs-label">Purchased</p>
              <ul data-testid="order-cert-legs">
                {details.legs.map((leg) => (
                  <li key={leg.id} className="order-cert-leg">
                    <span className="order-cert-leg-side">{leg.side.toUpperCase()}</span>
                    <span>
                      {leg.qty} × {leg.symbol}
                    </span>
                    {leg.fill_price != null ? (
                      <span className="order-cert-leg-fill">@ {leg.fill_price.toFixed(2)}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>

            <button
              type="button"
              className="order-cert-dismiss"
              data-testid="order-cert-dismiss"
              onClick={onDismiss}
            >
              Continue to dashboard
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
