"""order fill quantity, venue, and broker id for idempotent fills

Revision ID: 007
Revises: 006
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("orders"):
        return
    cols = {c["name"] for c in inspect(bind).get_columns("orders")}
    if "filled_qty" not in cols:
        op.add_column("orders", sa.Column("filled_qty", sa.Float(), nullable=False, server_default="0"))
    if "venue" not in cols:
        op.add_column("orders", sa.Column("venue", sa.String(16), nullable=True))
    if "broker_order_id" not in cols:
        op.add_column("orders", sa.Column("broker_order_id", sa.String(64), nullable=True))
        op.create_index("ix_orders_broker_order_id", "orders", ["broker_order_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if not inspect(bind).has_table("orders"):
        return
    cols = {c["name"] for c in inspect(bind).get_columns("orders")}
    if "broker_order_id" in cols:
        op.drop_index("ix_orders_broker_order_id", table_name="orders")
        op.drop_column("orders", "broker_order_id")
    if "venue" in cols:
        op.drop_column("orders", "venue")
    if "filled_qty" in cols:
        op.drop_column("orders", "filled_qty")
