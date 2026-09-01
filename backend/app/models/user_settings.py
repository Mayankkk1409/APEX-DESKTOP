"""User trading settings and balance audit models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserTradingSettings(Base):
    __tablename__ = "user_trading_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    auto_execution_threshold: Mapped[float] = mapped_column(Float, default=85.0)
    risk_profile: Mapped[str] = mapped_column(String(32), default="moderate")
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=3.0)
    max_positions: Mapped[int] = mapped_column(Integer, default=10)
    theme_preference: Mapped[str] = mapped_column(String(16), default="dark")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="trading_settings")


class PaperBalanceAudit(Base):
    __tablename__ = "paper_balance_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    previous_balance: Mapped[float] = mapped_column(Float)
    new_balance: Mapped[float] = mapped_column(Float)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="balance_audits")
