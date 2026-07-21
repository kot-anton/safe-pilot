"""fix PostgreSQL circular FKs and station enum

The initial migration intentionally used ``use_alter=True`` for the two circular foreign keys.
SQLite emitted those constraints inline, but PostgreSQL offline SQL omitted them and no later
migration added them. The ballast-removal migration also could not remove a value from an
existing PostgreSQL enum by altering the column to the same enum type.

This migration is a no-op on SQLite. On PostgreSQL it:

* recreates ``stationtypeenum`` without the obsolete BALLAST value (legacy BALLAST rows become
  CUSTOM rather than making the migration fail); and
* adds the two intended, named circular foreign-key constraints after all referenced tables
  exist.

Revision ID: 9c7e4f2a1b6d
Revises: 2aabeb6ce5a0
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "9c7e4f2a1b6d"
down_revision: Union[str, None] = "2aabeb6ce5a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_LABELS = (
    "FRONT_SEATS",
    "REAR_SEATS",
    "PASSENGER",
    "BAGGAGE",
    "FUEL",
    "CUSTOM",
)
_OLD_LABELS = (*_NEW_LABELS[:-1], "BALLAST", _NEW_LABELS[-1])


def _enum_labels(bind) -> list[str]:
    rows = bind.execute(
        sa.text(
            """
            SELECT e.enumlabel
            FROM pg_type AS t
            JOIN pg_enum AS e ON e.enumtypid = t.oid
            WHERE t.typname = 'stationtypeenum'
            ORDER BY e.enumsortorder
            """
        )
    )
    return [row[0] for row in rows]


def _recreate_station_enum(labels: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{label}'" for label in labels)
    op.execute("ALTER TYPE stationtypeenum RENAME TO stationtypeenum_old")
    op.execute(f"CREATE TYPE stationtypeenum AS ENUM ({quoted})")
    op.execute(
        "ALTER TABLE stations ALTER COLUMN station_type TYPE stationtypeenum "
        "USING station_type::text::stationtypeenum"
    )
    op.execute("DROP TYPE stationtypeenum_old")


def _foreign_key_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {
        fk["name"]
        for fk in inspector.get_foreign_keys(table_name)
        if fk.get("name") is not None
    }


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    bind = op.get_bind()
    offline = context.is_offline_mode()

    if offline:
        # Static SQL cannot inspect enum labels. The migration immediately before this one leaves
        # PostgreSQL's original enum in place, so emit the deterministic repair sequence.
        op.execute("UPDATE stations SET station_type = 'CUSTOM' WHERE station_type::text = 'BALLAST'")
        _recreate_station_enum(_NEW_LABELS)
        op.create_foreign_key(
            "fk_selected_aircraft",
            "users",
            "aircraft",
            ["selected_aircraft_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_active_revision",
            "aircraft",
            "aircraft_revisions",
            ["active_revision_id"],
            ["id"],
        )
        return

    labels = _enum_labels(bind)
    if "BALLAST" in labels:
        op.execute("UPDATE stations SET station_type = 'CUSTOM' WHERE station_type::text = 'BALLAST'")
        _recreate_station_enum(_NEW_LABELS)

    if "fk_selected_aircraft" not in _foreign_key_names(bind, "users"):
        op.create_foreign_key(
            "fk_selected_aircraft",
            "users",
            "aircraft",
            ["selected_aircraft_id"],
            ["id"],
        )
    if "fk_active_revision" not in _foreign_key_names(bind, "aircraft"):
        op.create_foreign_key(
            "fk_active_revision",
            "aircraft",
            "aircraft_revisions",
            ["active_revision_id"],
            ["id"],
        )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    # At down_revision these constraints were absent on PostgreSQL, so remove the repair.
    op.drop_constraint("fk_active_revision", "aircraft", type_="foreignkey")
    op.drop_constraint("fk_selected_aircraft", "users", type_="foreignkey")

    if context.is_offline_mode() or "BALLAST" not in _enum_labels(op.get_bind()):
        _recreate_station_enum(_OLD_LABELS)
