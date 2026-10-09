import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";

type Props = {
  title: string;
  message: string;
  testId: string;
  onClose: () => void;
};

/** Centered certificate notice for signup email outcomes. */
export function SignupNoticeDialog({ title, message, testId, onClose }: Props) {
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, onClose);
  const titleId = `${testId}-title`;

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
          <div className="order-cert-inner order-cert-stack">
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
        </div>
      </div>
    </div>
  );
}
