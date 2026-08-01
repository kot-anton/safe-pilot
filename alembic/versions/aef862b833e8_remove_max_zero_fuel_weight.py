"""remove max zero-fuel weight (MZFW)

MZFW only constrains aircraft where wing fuel provides bending relief (twins, turboprops,
transport-category); it does not apply to the light GA singles this app targets, and no
calculation ever surfaced a meaningful result from it when unset. Dropping the field and
question entirely rather than continuing to carry an always-optional, rarely-applicable
column.

Revision ID: aef862b833e8
Revises: 6f3b1a8c7e2d
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "aef862b833e8"
down_revision: Union[str, None] = "6f3b1a8c7e2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("aircraft_revisions") as batch_op:
        batch_op.drop_column("max_zero_fuel_weight_lb")


def downgrade() -> None:
    with op.batch_alter_table("aircraft_revisions") as batch_op:
        batch_op.add_column(
            sa.Column("max_zero_fuel_weight_lb", sa.Numeric(precision=14, scale=4), nullable=True)
        )
