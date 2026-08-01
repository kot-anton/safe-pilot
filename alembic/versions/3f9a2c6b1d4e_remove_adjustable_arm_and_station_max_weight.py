"""remove adjustable ARM and station max weight

Adjustable ARM (is_adjustable_arm/minimum_arm_in/maximum_arm_in) and the per-station published
maximum weight (maximum_weight_lb) are removed entirely, per explicit product decision: a
station's ARM is now always just its default_arm_in, and stations are never weight-capped
individually. The wizard questions, calculator branches, and recommendation logic that read
these fields are removed alongside the columns.

Revision ID: 3f9a2c6b1d4e
Revises: aef862b833e8
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3f9a2c6b1d4e"
down_revision: Union[str, None] = "aef862b833e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stations") as batch_op:
        batch_op.drop_column("is_adjustable_arm")
        batch_op.drop_column("minimum_arm_in")
        batch_op.drop_column("maximum_arm_in")
        batch_op.drop_column("maximum_weight_lb")


def downgrade() -> None:
    with op.batch_alter_table("stations") as batch_op:
        batch_op.add_column(
            sa.Column("is_adjustable_arm", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("minimum_arm_in", sa.Numeric(precision=14, scale=4), nullable=True)
        )
        batch_op.add_column(
            sa.Column("maximum_arm_in", sa.Numeric(precision=14, scale=4), nullable=True)
        )
        batch_op.add_column(
            sa.Column("maximum_weight_lb", sa.Numeric(precision=14, scale=4), nullable=True)
        )
