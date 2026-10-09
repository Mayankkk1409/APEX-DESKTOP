"""Write signup and sign-in HTML previews to temp files. Does not send mail.

Both letters are one table. The header image is cid:apex-logo and is attached
inline when the message is sent.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.signup_email import login_code_html, signup_confirmation_html, write_email_preview


def main() -> None:
    signup = signup_confirmation_html(
        full_name="Ada Lovelace",
        username="ada.lovelace",
        email="ada@example.com",
        password="sample-only-xyz",
        account_mode="paper_funded",
        starting_balance=25000,
    )
    login = login_code_html(full_name="Ada Lovelace", code="000000")
    print(write_email_preview(signup, name="apex-signup"))
    print(write_email_preview(login, name="apex-login"))


if __name__ == "__main__":
    main()
