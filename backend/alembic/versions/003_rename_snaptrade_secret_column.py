"""rename snaptrade secret column

Revision ID: 003
Revises: 002
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(table: str) -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("brokerage_connections"):
        return
    cols = _column_names("brokerage_connections")
    if "snaptrade_user_secret_enc" in cols and "snaptrade_user_secret_encrypted" not in cols:
        with op.batch_alter_table("brokerage_connections") as batch_op:
            batch_op.alter_column(
                "snaptrade_user_secret_enc",
                new_column_name="snaptrade_user_secret_encrypted",
            )
    elif "snaptrade_user_secret_encrypted" not in cols:
        op.add_column(
            "brokerage_connections",
            sa.Column("snaptrade_user_secret_encrypted", sa.Text(), nullable=False, server_default=""),
        )
        op.alter_column("brokerage_connections", "snaptrade_user_secret_encrypted", server_default=None)


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table("brokerage_connections"):
        return
    cols = _column_names("brokerage_connections")
    if "snaptrade_user_secret_encrypted" in cols and "snaptrade_user_secret_enc" not in cols:
        with op.batch_alter_table("brokerage_connections") as batch_op:
            batch_op.alter_column(
                "snaptrade_user_secret_encrypted",
                new_column_name="snaptrade_user_secret_enc",
            )
