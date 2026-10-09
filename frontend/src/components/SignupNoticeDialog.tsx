import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";

type Props = {
  title: string;
  message: string;
  testId: string;
  onClose: () => void;
  /** Sign-in failures stay a flat centered panel. Signup keeps the certificate. */
  plain?: boolean;
};

/** Centered notice. Signup uses the certificate frame. Sign-in uses a flat panel. */
export function SignupNoticeDialog({ title, message, testId, onClose, plain = false }: Props) {
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, onClose);
  const titleId = `${testId}-title`;
  const body = (
    <div className="order-cert-stack">
      <h2 id={titleId} className="order-cert-title">
        {title}
      </h2>
      <p className="order-cert-copy" data-testid={`${testId}-message`}>
        {message}
      </p>
      <button type="button" className="order-cert-dismiss" data-testid={`${testId}-close`} onClick={onClose}>
        Close
      </button>
    </div>
  );

  if (plain) {
    return (
      <div
        ref={trapRef}
        className="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
      >
        <div className="w-full max-w-md rounded-xl border border-line bg-panel p-8">{body}</div>
      </div>
    );
  }

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      data-testid={testId}
    >
      <div className="order-cert-card w-full max-w-lg">
        <div className="order-cert-frame">
          <div className="order-cert-inner">{body}</div>
        </div>
      </div>
    </div>
  );
}
