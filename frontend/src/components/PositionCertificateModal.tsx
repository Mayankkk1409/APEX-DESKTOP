import type { PositionRow } from "../types";
import {
  OrderConfirmationCertificate,
  type PositionCertificateDetails,
} from "./OrderConfirmationCertificate";

export type { PositionCertificateDetails };

type Props = {
  details: PositionCertificateDetails;
  onDismiss: () => void;
  onClosePosition?: (positionId: string) => void;
  closing?: boolean;
};

export function PositionCertificateModal({ details, onDismiss, onClosePosition, closing }: Props) {
  return (
    <OrderConfirmationCertificate
      variant="position"
      details={details}
      onDismiss={onDismiss}
      onClosePosition={onClosePosition}
      closing={closing}
    />
  );
}

export { positionToLeg } from "../lib/certificateLegs";
