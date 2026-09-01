import { buildCertificateLegs, formatLegDetail, type CertificateLegDisplay } from "../lib/certificateLegs";

type Props = {
  legs: CertificateLegDisplay[];
  label?: string;
  testId?: string;
};

export function CertificateLegList({ legs, label = "Legs", testId = "order-cert-legs" }: Props) {
  return (
    <div className="order-cert-legs">
      <p className="order-cert-legs-label">{label}</p>
      <ul data-testid={testId}>
        {legs.map((leg) => (
          <li key={leg.id} className="order-cert-leg" data-testid="cert-leg-row">
            <span className="order-cert-leg-side">{leg.side.toUpperCase()}</span>
            <span>
              {leg.qty} × {leg.symbol}
            </span>
            <span className="text-faint">{formatLegDetail(leg)}</span>
            {leg.premium != null ? (
              <span className="order-cert-leg-fill" data-testid="cert-leg-premium">
                @ {leg.premium.toFixed(2)}
              </span>
            ) : null}
            {leg.expiration ? (
              <span className="order-cert-leg-expiry" data-testid="cert-leg-expiration">
                Exp {leg.expiration}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export { buildCertificateLegs, formatLegDetail };
