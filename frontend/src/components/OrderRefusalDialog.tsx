import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";
import { explainOrderRefusal } from "../lib/orderRefusal";

type Props = {
  reason: string;
  onClose: () => void;
};

/** A submit was attempted and the server or broker refused it. The order is not filled. */
export function OrderRefusalDialog({ reason, onClose }: Props) {
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, onClose);

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="order-refusal-title"
      data-testid="order-refusal"
    >
      <div className="order-cert-card w-full max-w-lg">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-cert-stack">
            <h2 id="order-refusal-title" className="order-cert-title">
              Order not submitted
            </h2>
            <p className="order-cert-copy" data-testid="order-refusal-reason">
              {explainOrderRefusal(reason)}
            </p>
            <button type="button" className="order-cert-dismiss" data-testid="order-refusal-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
