from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models.trading import Order, Position, Scan, WatchlistItem
from app.models.user import RefreshToken, User
from app.models.user_settings import PaperBalanceAudit, UserTradingSettings
from app.schemas.settings import (
    DeleteAccountRequest,
    PaperBalanceAuditOut,
    PaperBalancePatch,
    TradingSettingsOut,
    TradingSettingsPatch,
)
from app.security import verify_password

router = APIRouter(prefix="/api/settings", tags=["settings"])


async def _get_or_create_settings(user: User, db: AsyncSession) -> UserTradingSettings:
    row = await db.scalar(select(UserTradingSettings).where(UserTradingSettings.user_id == user.id))
    if row:
        return row
    row = UserTradingSettings(user_id=user.id)
    db.add(row)
    await db.flush()
    return row


@router.get("/trading", response_model=TradingSettingsOut)
async def get_trading_settings(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)) -> UserTradingSettings:
    return await _get_or_create_settings(user, db)


@router.patch("/trading", response_model=TradingSettingsOut)
async def patch_trading_settings(
    body: TradingSettingsPatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> UserTradingSettings:
    settings = await _get_or_create_settings(user, db)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await db.commit()
    await db.refresh(settings)
    return settings


@router.patch("/paper-balance")
async def patch_paper_balance(
    body: PaperBalancePatch,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if user.account_mode != "paper_funded":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paper balance can only be adjusted on paper-funded accounts")
    prev = user.cash_balance
    user.cash_balance = round(body.balance, 2)
    user.buying_power = user.cash_balance
    if user.starting_balance is None:
        user.starting_balance = user.cash_balance
    user.portfolio_value = user.cash_balance
    audit = PaperBalanceAudit(
        user_id=user.id,
        previous_balance=prev,
        new_balance=user.cash_balance,
        reason=body.reason,
    )
    db.add(audit)
    await db.commit()
    return {
        "ok": True,
        "previous_balance": prev,
        "new_balance": user.cash_balance,
        "reason": body.reason,
    }


@router.get("/paper-balance/audit", response_model=list[PaperBalanceAuditOut])
async def list_paper_balance_audit(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = (
        await db.scalars(
            select(PaperBalanceAudit)
            .where(PaperBalanceAudit.user_id == user.id)
            .order_by(PaperBalanceAudit.created_at.desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "id": r.id,
            "previous_balance": r.previous_balance,
            "new_balance": r.new_balance,
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]


@router.post("/account/delete")
async def delete_account(
    body: DeleteAccountRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid password")
    uid = user.id
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == uid))
    await db.execute(delete(WatchlistItem).where(WatchlistItem.user_id == uid))
    await db.execute(delete(Position).where(Position.user_id == uid))
    await db.execute(delete(Order).where(Order.user_id == uid))
    await db.execute(delete(Scan).where(Scan.user_id == uid))
    await db.execute(delete(PaperBalanceAudit).where(PaperBalanceAudit.user_id == uid))
    await db.execute(delete(UserTradingSettings).where(UserTradingSettings.user_id == uid))
    await db.delete(user)
    await db.commit()
    return {"ok": True, "deleted": True}
