"""make account_balances.day_pnl nullable

Revision ID: 005
Revises: 004
Create Date: 2026-08-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not inspect(op.get_bind()).has_table("account_balances"):
        return
    with op.batch_alter_table("account_balances") as batch_op:
        batch_op.alter_column("day_pnl", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    if not inspect(op.get_bind()).has_table("account_balances"):
        return
    with op.batch_alter_table("account_balances") as batch_op:
        batch_op.alter_column("day_pnl", existing_type=sa.Float(), nullable=False)
