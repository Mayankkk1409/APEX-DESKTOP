"""Sign-in verification follows the NYSE regular open, not a rolling 24 hours.

A fresh login on a weekend or full-day holiday still requires a code.
An existing session stays valid until the next regular open and does not send mail.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.market_session import NY, getLastMarketOpen, is_trading_day

VERIFICATION_EXPIRED = "Sign-in verification expired"


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def verification_current(verified_at: datetime, now: datetime) -> bool:
    """True when this verification is still inside the open that bounds ``now``."""
    return _aware(verified_at) >= getLastMarketOpen(now)


def fresh_login_requires_code(now: datetime) -> bool:
    """Weekend and full-day holiday logins always email a code."""
    return not is_trading_day(now.astimezone(NY).date())


def login_skips_otp(verified_at: datetime, now: datetime) -> bool:
    if fresh_login_requires_code(now):
        return False
    return verification_current(verified_at, now)


def access_verification_current(payload: dict, now: datetime) -> bool:
    """A signed access token cannot outlive the verification it was issued with."""
    raw = payload.get("vfy")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return False
    verified_at = datetime.fromtimestamp(int(raw), tz=timezone.utc)
    return verification_current(verified_at, now)
