import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";
import { signupValidationLines } from "../lib/signupValidation";

type Props = {
  detail: unknown;
  onClose: () => void;
};

/** Signup was refused by request validation. The account is not created. */
export function SignupValidationDialog({ detail, onClose }: Props) {
  const lines = signupValidationLines(detail);
  const shown = lines.length ? lines : ["Check each field and try again."];
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, onClose);

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-not-created-title"
      data-testid="account-not-created"
    >
      <div className="order-cert-card w-full max-w-lg">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-cert-stack">
            <h2 id="account-not-created-title" className="order-cert-title">
              Account not created
            </h2>
            <ul className="order-cert-lines" data-testid="account-not-created-reasons">
              {shown.map((line) => (
                <li key={line} data-testid="account-not-created-reason">
                  {line}
                </li>
              ))}
            </ul>
            <button type="button" className="order-cert-dismiss" data-testid="account-not-created-close" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
