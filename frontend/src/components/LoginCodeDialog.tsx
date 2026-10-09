import { SignupNoticeDialog } from "./SignupNoticeDialog";
import { OTP_CODE_INVALID } from "../lib/apiError";
import { NO_SIGNIN_EMAIL, SIGNIN_CODE_NOT_SENT, type LoginCodeNotice } from "../lib/loginCode";

type Props = {
  kind: LoginCodeNotice;
  message?: string;
  onClose: () => void;
};

/** Centered notice when a sign-in code cannot be emailed. */
export function LoginCodeDialog({ kind, message, onClose }: Props) {
  if (kind === "otp-invalid") {
    return (
      <SignupNoticeDialog
        title="Code not accepted"
        message={OTP_CODE_INVALID}
        testId="login-code-invalid"
        onClose={onClose}
      />
    );
  }
  if (kind === "no-email") {
    return (
      <SignupNoticeDialog
        title="No email on file"
        message={message || NO_SIGNIN_EMAIL}
        testId="login-no-email"
        onClose={onClose}
      />
    );
  }
  return (
    <SignupNoticeDialog
      title="Code not sent"
      message={message || SIGNIN_CODE_NOT_SENT}
      testId="login-code-not-sent"
      onClose={onClose}
    />
  );
}
