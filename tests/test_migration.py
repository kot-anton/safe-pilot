"""Verifies the fuel-systems migration is additive: existing rows created under the prior
schema remain fully readable after upgrading to head, with the new column safely defaulted."""
import pathlib

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_existing_data_survives_fuel_system_migration(tmp_path):
    db_path = tmp_path / "migration_test.db"
    sync_url = f"sqlite:///{db_path}"
    async_url = f"sqlite+aiosqlite:///{db_path}"

    cfg = _alembic_config(async_url)

    # 1. Upgrade only to the revision immediately before the fuel-systems migration.
    command.upgrade(cfg, "7d1117d0308d")

    # 2. Insert data using the pre-migration schema, simulating a real existing user/aircraft.
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, telegram_user_id, language) VALUES (1, 42, 'en')"))
        conn.execute(
            text(
                "INSERT INTO aircraft (id, user_id, tail_number, model, allow_added_ballast_recommendations) "
                "VALUES (1, 1, 'N123AB', '172', 0)"
            )
        )
    engine.dispose()

    # 3. Upgrade to head (applies the fuel-systems migration).
    command.upgrade(cfg, "head")

    # 4. The pre-existing row must still be readable, and the new column must have a safe default.
    engine = create_engine(sync_url)
    with engine.begin() as conn:
        row = conn.execute(text("SELECT tail_number, is_temporary FROM aircraft WHERE id = 1")).fetchone()
    engine.dispose()

    assert row is not None
    assert row[0] == "N123AB"
    assert row[1] in (0, False)  # defaulted to false, not null, not dropped


def test_postgresql_offline_migration_repairs_circular_foreign_keys_and_enum():
    """The generated PostgreSQL migration SQL must include integrity constraints that the
    original ``use_alter`` create-table statements omitted, and truly remove BALLAST from the
    enum instead of altering the column to the same unchanged type."""
    import io

    output = io.StringIO()
    cfg = _alembic_config("postgresql+asyncpg://user:pass@localhost/safe_pilot")
    cfg.output_buffer = output

    command.upgrade(cfg, "head", sql=True)
    sql = output.getvalue()

    assert "CONSTRAINT fk_selected_aircraft" in sql
    assert "CONSTRAINT fk_active_revision" in sql
    assert "ALTER TYPE stationtypeenum RENAME TO stationtypeenum_old" in sql
    assert "CREATE TYPE stationtypeenum AS ENUM ('FRONT_SEATS', 'REAR_SEATS', 'PASSENGER', 'BAGGAGE', 'FUEL', 'CUSTOM')" in sql
