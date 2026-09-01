from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BrokerageConnection(Base):
    __tablename__ = "brokerage_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="snaptrade")
    snaptrade_user_id: Mapped[str] = mapped_column(String(128), index=True)
    snaptrade_user_secret_encrypted: Mapped[str] = mapped_column(Text)
    connection_status: Mapped[str] = mapped_column(String(32), default="pending")
    authorization_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    accounts: Mapped[list["BrokerageAccount"]] = relationship(back_populates="connection")


class BrokerageAccount(Base):
    __tablename__ = "brokerage_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id: Mapped[str] = mapped_column(ForeignKey("brokerage_connections.id"), index=True)
    account_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    account_name: Mapped[str] = mapped_column(String(255), default="")
    account_type: Mapped[str] = mapped_column(String(64), default="")
    broker_name: Mapped[str] = mapped_column(String(128), default="")
    account_number_masked: Mapped[str] = mapped_column(String(32), default="")
    sync_status: Mapped[str] = mapped_column(String(32), default="pending")

    connection: Mapped[BrokerageConnection] = relationship(back_populates="accounts")
    balances: Mapped[list["AccountBalance"]] = relationship(back_populates="account")


class AccountBalance(Base):
    __tablename__ = "account_balances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("brokerage_accounts.id"), index=True)
    cash_balance: Mapped[float] = mapped_column(Float, default=0.0)
    buying_power: Mapped[float] = mapped_column(Float, default=0.0)
    total_equity: Mapped[float] = mapped_column(Float, default=0.0)
    day_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    as_of_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account: Mapped[BrokerageAccount] = relationship(back_populates="balances")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(64), default="ok")
