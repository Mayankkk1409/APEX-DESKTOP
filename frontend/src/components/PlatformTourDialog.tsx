import { useEscapeKey, useFocusTrap } from "../hooks/useFocusTrap";

/** Served from frontend/public. Symlink or copy the tour file here for local runs. */
export const PLATFORM_TOUR_SRC = "/brand/apex-platform-tour.mp4";

type Props = {
  onDismiss: () => void;
};

/**
 * First sign-in after a new account verifies its code. The dialog is required;
 * watching the full video is not — Skip or Close ends it.
 */
export function PlatformTourDialog({ onDismiss }: Props) {
  const trapRef = useFocusTrap(true);
  useEscapeKey(true, onDismiss);

  return (
    <div
      ref={trapRef}
      className="order-cert-backdrop fixed inset-0 z-[90] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="platform-tour-title"
      data-testid="platform-tour-dialog"
    >
      <div className="order-cert-card w-full max-w-3xl">
        <div className="order-cert-frame">
          <div className="order-cert-inner order-cert-stack">
            <h2 id="platform-tour-title" className="order-cert-title">
              Platform tour
            </h2>
            <p className="order-cert-copy">
              Watch how APEX works before you open the desk. You can skip or close anytime. This
              walkthrough appears once after you create an account and enter your sign-in code.
            </p>
            <video
              className="mt-2 w-full rounded-md border border-line bg-black"
              controls
              playsInline
              preload="metadata"
              data-testid="platform-tour-video"
              src={PLATFORM_TOUR_SRC}
            >
              Your browser does not play this tour video.
            </video>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                className="order-cert-dismiss"
                data-testid="platform-tour-skip"
                onClick={onDismiss}
              >
                Skip
              </button>
              <button
                type="button"
                className="rounded-md border border-line px-4 py-2 text-sm"
                data-testid="platform-tour-close"
                onClick={onDismiss}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
