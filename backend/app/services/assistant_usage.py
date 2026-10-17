"""Per-user assistant counts.

A question counts only after the model returns an answer. An entitlement denial
and a provider failure do not count. The day key is America/New_York.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantUsage
from app.services.assistant_plans import RESET_TIMEZONE

_NY = ZoneInfo(RESET_TIMEZONE)
_locks: dict[str, asyncio.Lock] = {}


def usage_day(now: datetime) -> str:
    return now.astimezone(_NY).date().isoformat()


def next_reset(now: datetime) -> datetime:
    local = now.astimezone(_NY)
    upcoming = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return upcoming


def _lock(user_id: str) -> asyncio.Lock:
    lock = _locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[user_id] = lock
    return lock


async def questions_used(session: AsyncSession, user_id: str, day: str) -> int:
    row = await session.scalar(
        select(AssistantUsage).where(
            AssistantUsage.user_id == user_id,
            AssistantUsage.usage_date == day,
        )
    )
    return 0 if row is None else int(row.question_count)


async def reserve_question(
    session: AsyncSession,
    user_id: str,
    day: str,
    limit: int | None,
) -> tuple[bool, int]:
    """Hold one allowance slot. ``limit`` None means the plan is unlimited."""
    async with _lock(user_id):
        row = await session.scalar(
            select(AssistantUsage).where(
                AssistantUsage.user_id == user_id,
                AssistantUsage.usage_date == day,
            )
        )
        if row is None:
            if limit is not None and limit <= 0:
                return False, 0
            row = AssistantUsage(user_id=user_id, usage_date=day, question_count=1)
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await _reserve_existing(session, user_id, day, limit)
            return True, 1
        if limit is not None and row.question_count >= limit:
            return False, int(row.question_count)
        row.question_count = int(row.question_count) + 1
        await session.commit()
        return True, int(row.question_count)


async def _reserve_existing(
    session: AsyncSession,
    user_id: str,
    day: str,
    limit: int | None,
) -> tuple[bool, int]:
    row = await session.scalar(
        select(AssistantUsage).where(
            AssistantUsage.user_id == user_id,
            AssistantUsage.usage_date == day,
        )
    )
    if row is None:
        return False, 0
    if limit is not None and row.question_count >= limit:
        return False, int(row.question_count)
    row.question_count = int(row.question_count) + 1
    await session.commit()
    return True, int(row.question_count)


async def release_question(session: AsyncSession, user_id: str, day: str) -> int:
    """Give a reserved slot back after the provider fails."""
    async with _lock(user_id):
        row = await session.scalar(
            select(AssistantUsage).where(
                AssistantUsage.user_id == user_id,
                AssistantUsage.usage_date == day,
            )
        )
        if row is None or row.question_count <= 0:
            return 0
        row.question_count = int(row.question_count) - 1
        await session.commit()
        return int(row.question_count)
