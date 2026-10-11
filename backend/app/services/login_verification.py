"""A fresh login on a recognized device skips the code for 24 hours after OTP.

The window starts at successful verification and is not extended by later
password logins. Session refresh still follows the NYSE open separately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.market_session import getLastMarketOpen

VERIFICATION_EXPIRED = "Sign-in verification expired"
OTP_TRUST_WINDOW = timedelta(hours=24)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def verification_current(verified_at: datetime, now: datetime) -> bool:
    """True when this verification is still inside the open that bounds ``now``."""
    return _aware(verified_at) >= getLastMarketOpen(now)


def login_skips_otp(verified_at: datetime, now: datetime) -> bool:
    """True only inside the 24 hours that began at this device's last successful OTP."""
    verified = _aware(verified_at)
    clock = _aware(now)
    if clock < verified:
        return False
    return clock < verified + OTP_TRUST_WINDOW


def access_verification_current(payload: dict, now: datetime) -> bool:
    """A signed access token cannot outlive the verification it was issued with."""
    raw = payload.get("vfy")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False
    verified_at = datetime.fromtimestamp(int(raw), tz=timezone.utc)
    return verification_current(verified_at, now)
