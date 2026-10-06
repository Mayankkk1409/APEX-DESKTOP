import { motion } from "framer-motion";
import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";
import {
  expiryLoginNotes,
  formatDirectionLabel,
  formatRightLabel,
  isDeskManaged,
  type ExpiryLoginRow,
} from "../lib/expiryLoginNotice";
import { ApexLogo } from "./ApexLogo";

type Props = {
  items: ExpiryLoginRow[];
  isPaper: boolean;
  onDismiss: () => void;
};

export function ExpiryLoginCertificate({ items, isPaper, onDismiss }: Props) {
  const trapRef = useFocusTrap(items.length > 0);
  useEscapeKey(items.length > 0, onDismiss);

  if (items.length === 0) return null;

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      data-testid="expiry-login-certificate"
      role="dialog"
      aria-labelledby="expiry-login-title"
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
              <p className="order-cert-paper-banner" data-testid="expiry-login-paper-banner">
                PAPER TRADE
              </p>
            ) : null}

            <div className="order-cert-header">
              <ApexLogo size={52} className="order-cert-logo" />
              <p className="order-cert-eyebrow">APEX Terminal</p>
              <h2 id="expiry-login-title" className="order-cert-title">
                Expiring positions
              </h2>
              <p className="order-cert-status">Next 7 days</p>
            </div>

            <div className="mb-3 space-y-1" data-testid="expiry-login-copy">
              {expiryLoginNotes(items, isPaper).map((note) => (
                <p key={note} className="sf-panel-note">
                  {note}
                </p>
              ))}
            </div>

            <div className="order-cert-legs" data-testid="expiry-login-list">
              <p className="order-cert-legs-label">Open trades</p>
              <ul>
                {items.map((item) => (
                  <li key={item.key} data-testid={`expiry-login-row-${item.key}`}>
                    <dl className="order-cert-grid">
                      <div className="order-cert-row">
                        <dt>Symbol</dt>
                        <dd data-testid={`expiry-login-symbol-${item.key}`}>{item.symbol}</dd>
                      </div>
                      {item.strategy ? (
                        <div className="order-cert-row">
                          <dt>Strategy</dt>
                          <dd data-testid={`expiry-login-strategy-${item.key}`}>{item.strategy}</dd>
                        </div>
                      ) : null}
                      <div className="order-cert-row">
                        <dt>Expiry</dt>
                        <dd className="order-cert-leg-expiry" data-testid={`expiry-login-expiry-${item.key}`}>
                          {item.expiryLabel}
                        </dd>
                      </div>
                      <div className="order-cert-row">
                        <dt>Strike</dt>
                        <dd data-testid={`expiry-login-strike-${item.key}`}>{item.strikeLabel}</dd>
                      </div>
                      <div className="order-cert-row">
                        <dt>Call/Put</dt>
                        <dd data-testid={`expiry-login-right-${item.key}`}>{formatRightLabel(item.right)}</dd>
                      </div>
                      <div className="order-cert-row">
                        <dt>Long/Short</dt>
                        <dd data-testid={`expiry-login-direction-${item.key}`}>
                          {formatDirectionLabel(item.direction)}
                        </dd>
                      </div>
                      <div className="order-cert-row">
                        <dt>Settles</dt>
                        <dd data-testid={`expiry-login-settles-${item.key}`}>
                          {isDeskManaged(item, isPaper) ? "APEX auto-close" : "Your broker"}
                        </dd>
                      </div>
                    </dl>
                  </li>
                ))}
              </ul>
            </div>

            <button type="button" className="order-cert-dismiss" data-testid="expiry-login-dismiss" onClick={onDismiss}>
              Dismiss
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
