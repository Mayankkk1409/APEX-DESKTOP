from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AssistantUsage(Base):
    """Questions that received a model answer, for one New York calendar day."""

    __tablename__ = "assistant_usage"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    usage_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
