"""remove ballast station type and recommendation flag

Ballast was never surfaced as a usable feature (the recommendation flag defaulted to False
and nothing in the bot ever set it True), so this drops it outright rather than deprecating
it: the allow_added_ballast_recommendations column, and BALLAST as a valid stations.station_type
value.

Revision ID: 2aabeb6ce5a0
Revises: beb0592006cc
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2aabeb6ce5a0'
down_revision: Union[str, None] = 'beb0592006cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_STATION_TYPE = sa.Enum(
    'FRONT_SEATS', 'REAR_SEATS', 'PASSENGER', 'BAGGAGE', 'FUEL', 'BALLAST', 'CUSTOM',
    name='stationtypeenum',
)
_NEW_STATION_TYPE = sa.Enum(
    'FRONT_SEATS', 'REAR_SEATS', 'PASSENGER', 'BAGGAGE', 'FUEL', 'CUSTOM',
    name='stationtypeenum',
)


def upgrade() -> None:
    with op.batch_alter_table('aircraft') as batch_op:
        batch_op.drop_column('allow_added_ballast_recommendations')

    with op.batch_alter_table('stations') as batch_op:
        batch_op.alter_column(
            'station_type',
            existing_type=_OLD_STATION_TYPE,
            type_=_NEW_STATION_TYPE,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('stations') as batch_op:
        batch_op.alter_column(
            'station_type',
            existing_type=_NEW_STATION_TYPE,
            type_=_OLD_STATION_TYPE,
            existing_nullable=False,
        )

    with op.batch_alter_table('aircraft') as batch_op:
        batch_op.add_column(
            sa.Column('allow_added_ballast_recommendations', sa.Boolean(), nullable=False, server_default=sa.false())
        )
