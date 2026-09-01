"""brokerage tables

Revision ID: 002
Revises: 001
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brokerage_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("snaptrade_user_id", sa.String(128), nullable=False),
        sa.Column("snaptrade_user_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("connection_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_brokerage_connections_user_id", "brokerage_connections", ["user_id"])
    op.create_index("ix_brokerage_connections_snaptrade_user_id", "brokerage_connections", ["snaptrade_user_id"])

    op.create_table(
        "brokerage_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("brokerage_connections.id"), nullable=False),
        sa.Column("account_id", sa.String(128), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(64), nullable=False),
        sa.Column("broker_name", sa.String(128), nullable=False),
        sa.Column("account_number_masked", sa.String(32), nullable=False),
        sa.Column("sync_status", sa.String(32), nullable=False),
    )
    op.create_index("ix_brokerage_accounts_connection_id", "brokerage_accounts", ["connection_id"])
    op.create_index("ix_brokerage_accounts_account_id", "brokerage_accounts", ["account_id"], unique=True)

    op.create_table(
        "account_balances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("brokerage_accounts.id"), nullable=False),
        sa.Column("cash_balance", sa.Float(), nullable=False),
        sa.Column("buying_power", sa.Float(), nullable=False),
        sa.Column("total_equity", sa.Float(), nullable=False),
        sa.Column("day_pnl", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("as_of_timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_account_balances_account_id", "account_balances", ["account_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("result", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("account_balances")
    op.drop_table("brokerage_accounts")
    op.drop_table("brokerage_connections")
