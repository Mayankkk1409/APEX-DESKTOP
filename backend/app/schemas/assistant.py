from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AskIn(BaseModel):
    """The signed-in user's words only. Plan and screen context are not accepted."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class AskOut(BaseModel):
    kind: Literal["answer", "upgrade", "limit", "boundary", "error"]
    text: str
    plan_id: str
    plan_name: str
    daily_questions: int | None
    used: int
    unlimited: bool
    resets_at: str
    reset_note: str
    plans: list[dict[str, Any]] | None = None
    separate_from_every_plan: str | None = None
    checkout_available: bool = False


class EntitlementOut(BaseModel):
    plan_id: str
    plan_name: str
    daily_questions: int | None
    used: int
    unlimited: bool
    resets_at: str
    reset_note: str
    provider_configured: bool
    checkout_available: bool = False
    separate_from_every_plan: str
