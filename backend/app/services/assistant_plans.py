"""Proposed research plans. One list feeds both the monthly and annual views.

There is no checkout. Trading Access and the 14-day trial are not sold here.
"""

from __future__ import annotations

from typing import Any

# No documented assistant reset existed. The terminal already uses America/New_York
# for the session and the expiry clock, so a used question expires at the next
# midnight in that timezone.
RESET_TIMEZONE = "America/New_York"
RESET_NOTE = (
    "Usage resets at midnight New York time. "
    "No other daily reset policy is documented."
)

SEPARATE_FROM_EVERY_PLAN = (
    "Trading Access is proposed at $9.99 once, including for Elite. It is not sold here.\n\n"
    "Read-only portfolio import is proposed as free on all plans. "
    "Holdings analysis is a different entitlement and is proposed for paid plans.\n\n"
    "A research subscription does not override broker options or margin approvals, "
    "account restrictions, or supported order types. No broker list is published.\n\n"
    "A 14-day Pro trial appears in the pricing workbook. Card requirements, renewal, "
    "cancellation, refunds, and taxes are unresolved, so the trial is not offered here."
)

UPGRADE_TEXT = (
    "This question needs deeper research or analysis of your current screen. "
    "Please upgrade your plan to access the appropriate research features."
)

BOUNDARY_TEXT = (
    "This question needs screen analysis or deeper research. "
    "That boundary is not configured for your plan, so APEX AI will not answer it."
)


def _plan(
    plan_id: str,
    name: str,
    description: str,
    monthly: str,
    annual: str,
    equivalent: str,
    twelve: str,
    memos: str,
    horizon: str,
    indicators: str,
    assistant: str,
    alerts: str,
    daily_questions: int | None,
    subtitle: str | None = None,
) -> dict[str, Any]:
    return {
        "id": plan_id,
        "name": name,
        "subtitle": subtitle,
        "description": description,
        "monthly_price": monthly,
        "annual_checkout": annual,
        "equivalent_monthly": equivalent,
        "twelve_monthly_total": twelve,
        "memos": memos,
        "horizon": horizon,
        "indicators": indicators,
        "assistant": assistant,
        "alerts": alerts,
        "daily_questions": daily_questions,
    }


PLANS: tuple[dict[str, Any], ...] = (
    _plan(
        "free",
        "Free",
        "Limited introductory research",
        "$0",
        "$0",
        "$0.00",
        "$0.00",
        "Three full memos, then three snapshots monthly, then score-only",
        "Short",
        "Six",
        "5 questions a day",
        "3. Measurement period not confirmed",
        5,
    ),
    _plan(
        "equity",
        "Equity",
        "Stock research",
        "$14.99",
        "$149.99",
        "$12.50",
        "$179.88",
        "Unlimited for entitled markets",
        "Short and long",
        "Ten",
        "50 questions a day",
        "25. Measurement period not confirmed",
        50,
    ),
    _plan(
        "options",
        "Options",
        "Options research. Fundamentals kept brief",
        "$21.99",
        "$219.99",
        "$18.33",
        "$263.88",
        "Unlimited for entitled markets",
        "Short and long",
        "Ten",
        "50 questions a day",
        "25. Measurement period not confirmed",
        50,
    ),
    _plan(
        "pro",
        "Pro Bundle",
        "Equity and options together",
        "$34.99",
        "$349.99",
        "$29.17",
        "$419.88",
        "Unlimited for entitled markets",
        "Short and long",
        "Ten",
        "100 questions a day",
        "50. Measurement period not confirmed",
        100,
        subtitle="For stocks and options",
    ),
    _plan(
        "elite",
        "Apex Elite",
        "Deeper research. Advice and automation are separate",
        "$99.99",
        "$999.99",
        "$83.33",
        "$1,199.88",
        "Unlimited for entitled markets",
        "Short and long",
        "Ten",
        "Unlimited questions a day",
        "200. Measurement period not confirmed",
        None,
    ),
)

PLAN_BY_ID = {plan["id"]: plan for plan in PLANS}


def plan_catalog() -> list[dict[str, Any]]:
    return [dict(plan) for plan in PLANS]


def resolve_plan_id(_user: object) -> str:
    """No subscription table exists. Every account stays Free.

    A client-supplied plan name is never read. Paid access is not assigned here.
    """
    return "free"
