"""remove temporary/rental aircraft flag

The "Temporary or Rental Aircraft" menu option was a duplicate entry point into the exact same
aircraft wizard, differing only by setting `is_temporary=True` on the created row. Nothing in the
app ever read that flag -- no listing/display difference, no filtering, no auto-archive (the
comment referencing a "future auto-archive pass" was never implemented). Removed entirely: the
menu option, the wizard handler, and the column.

Revision ID: 5a1c8e0f2b3d
Revises: 3f9a2c6b1d4e
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5a1c8e0f2b3d"
down_revision: Union[str, None] = "3f9a2c6b1d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("aircraft") as batch_op:
        batch_op.drop_column("is_temporary")


def downgrade() -> None:
    with op.batch_alter_table("aircraft") as batch_op:
        batch_op.add_column(
            sa.Column("is_temporary", sa.Boolean(), nullable=False, server_default=sa.false())
        )
