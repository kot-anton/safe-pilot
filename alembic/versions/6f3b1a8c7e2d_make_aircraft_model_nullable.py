"""make aircraft.model nullable

The Add Aircraft wizard no longer asks for manufacturer/model -- nickname is the pilot-facing
label instead. The column is kept for legacy aircraft and any future re-add, but new rows must
be allowed to leave it unset.

Revision ID: 6f3b1a8c7e2d
Revises: 9c7e4f2a1b6d
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f3b1a8c7e2d"
down_revision: Union[str, None] = "9c7e4f2a1b6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("aircraft") as batch_op:
        batch_op.alter_column(
            "model",
            existing_type=sa.String(64),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("aircraft") as batch_op:
        batch_op.alter_column(
            "model",
            existing_type=sa.String(64),
            nullable=False,
        )
