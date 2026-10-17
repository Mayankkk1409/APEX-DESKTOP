from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.deps import current_user
from app.models.user import User
from app.schemas.assistant import AskIn, AskOut, EntitlementOut
from app.services.assistant_gate import classify_question, decide_access
from app.services.assistant_model import AssistantProviderError, complete_basic_answer
from app.services.assistant_plans import (
    BOUNDARY_TEXT,
    PLAN_BY_ID,
    RESET_NOTE,
    SEPARATE_FROM_EVERY_PLAN,
    UPGRADE_TEXT,
    plan_catalog,
    resolve_plan_id,
)
from app.services.assistant_usage import next_reset, questions_used, release_question, reserve_question, usage_day

router = APIRouter(prefix="/assistant", tags=["assistant"])

_PROVIDER_FAILED = "APEX AI is temporarily unavailable. Please try again."


def _plan(user: User) -> dict:
    return PLAN_BY_ID[resolve_plan_id(user)]


def _limit_text(plan: dict, resets_at: datetime) -> str:
    allowance = plan["assistant"]
    when = resets_at.strftime("%b %d, %Y %I:%M %p ET").replace(" 0", " ")
    return (
        f"Today's APEX AI questions for the {plan['name']} plan are used ({allowance}). "
        f"The next reset is {when}. "
        "A higher allowance is listed with the plans below. Viewing these prices does not change your plan."
    )


@router.get("/plans")
async def plans(_user: User = Depends(current_user)) -> dict:
    return {
        "plans": plan_catalog(),
        "separate_from_every_plan": SEPARATE_FROM_EVERY_PLAN,
        "checkout_available": False,
    }


@router.get("/entitlement", response_model=EntitlementOut)
async def entitlement(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> EntitlementOut:
    plan = _plan(user)
    now = datetime.now(timezone.utc)
    used = await questions_used(db, user.id, usage_day(now))
    return EntitlementOut(
        plan_id=plan["id"],
        plan_name=plan["name"],
        daily_questions=plan["daily_questions"],
        used=used,
        unlimited=plan["daily_questions"] is None,
        resets_at=next_reset(now).isoformat(),
        reset_note=RESET_NOTE,
        provider_configured=settings.apex_ai_configured,
        checkout_available=False,
        separate_from_every_plan=SEPARATE_FROM_EVERY_PLAN,
    )


@router.post("/ask", response_model=AskOut)
async def ask(
    body: AskIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AskOut:
    message = " ".join(body.message.split())
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a question.")
    plan = _plan(user)
    now = datetime.now(timezone.utc)
    day = usage_day(now)
    resets = next_reset(now)
    kind = classify_question(message)
    decision = decide_access(plan["id"], kind)

    def pack(result: str, text: str, used: int, include_plans: bool) -> AskOut:
        return AskOut(
            kind=result,  # type: ignore[arg-type]
            text=text,
            plan_id=plan["id"],
            plan_name=plan["name"],
            daily_questions=plan["daily_questions"],
            used=used,
            unlimited=plan["daily_questions"] is None,
            resets_at=resets.isoformat(),
            reset_note=RESET_NOTE,
            plans=plan_catalog() if include_plans else None,
            separate_from_every_plan=SEPARATE_FROM_EVERY_PLAN if include_plans else None,
            checkout_available=False,
        )

    if decision == "upgrade":
        return pack("upgrade", UPGRADE_TEXT, await questions_used(db, user.id, day), True)
    if decision == "boundary":
        return pack("boundary", BOUNDARY_TEXT, await questions_used(db, user.id, day), False)

    reserved, used = await reserve_question(db, user.id, day, plan["daily_questions"])
    if not reserved:
        return pack("limit", _limit_text(plan, resets), used, True)
    try:
        answer = await complete_basic_answer(settings, message)
    except AssistantProviderError:
        used = await release_question(db, user.id, day)
        return pack("error", _PROVIDER_FAILED, used, False)
    return pack("answer", answer, used, False)
