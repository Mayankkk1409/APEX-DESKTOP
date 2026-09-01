"""rename account_balances brokerage_account_id to account_id

Revision ID: 004
Revises: 003
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("account_balances"):
        return
    cols = _column_names("account_balances")
    if "brokerage_account_id" in cols and "account_id" not in cols:
        with op.batch_alter_table("account_balances") as batch_op:
            batch_op.alter_column(
                "brokerage_account_id",
                new_column_name="account_id",
            )
    elif "account_id" not in cols:
        op.add_column(
            "account_balances",
            sa.Column("account_id", sa.String(36), nullable=False, server_default=""),
        )
        op.alter_column("account_balances", "account_id", server_default=None)


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table("account_balances"):
        return
    cols = _column_names("account_balances")
    if "account_id" in cols and "brokerage_account_id" not in cols:
        with op.batch_alter_table("account_balances") as batch_op:
            batch_op.alter_column(
                "account_id",
                new_column_name="brokerage_account_id",
            )
