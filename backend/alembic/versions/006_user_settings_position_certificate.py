"""user trading settings and paper balance audit tables

Revision ID: 006
Revises: 005
Create Date: 2026-08-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("user_trading_settings"):
        op.create_table(
            "user_trading_settings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("auto_execution_threshold", sa.Float(), nullable=False, server_default="85"),
            sa.Column("risk_profile", sa.String(32), nullable=False, server_default="moderate"),
            sa.Column("max_risk_per_trade_pct", sa.Float(), nullable=False, server_default="3"),
            sa.Column("max_positions", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("theme_preference", sa.String(16), nullable=False, server_default="dark"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_user_trading_settings_user_id", "user_trading_settings", ["user_id"], unique=True)

    if not inspect(bind).has_table("paper_balance_audits"):
        op.create_table(
            "paper_balance_audits",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("previous_balance", sa.Float(), nullable=False),
            sa.Column("new_balance", sa.Float(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_paper_balance_audits_user_id", "paper_balance_audits", ["user_id"])

    if inspect(bind).has_table("positions"):
        cols = {c["name"] for c in inspect(bind).get_columns("positions")}
        if "strategy_name" not in cols:
            op.add_column("positions", sa.Column("strategy_name", sa.String(120), nullable=True))
        if "certificate" not in cols:
            op.add_column("positions", sa.Column("certificate", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if inspect(bind).has_table("positions"):
        cols = {c["name"] for c in inspect(bind).get_columns("positions")}
        if "certificate" in cols:
            op.drop_column("positions", "certificate")
        if "strategy_name" in cols:
            op.drop_column("positions", "strategy_name")
    if inspect(bind).has_table("paper_balance_audits"):
        op.drop_table("paper_balance_audits")
    if inspect(bind).has_table("user_trading_settings"):
        op.drop_table("user_trading_settings")
