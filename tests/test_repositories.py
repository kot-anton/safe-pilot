import dataclasses
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.models import Base
from app.repositories.aircraft_repository import AircraftRepository
from app.repositories.flight_repository import FlightRepository
from app.services.aircraft_service import AircraftRevisionDraft, EnvelopeRowDraft, StationDraft
from app.services.aircraft_service import AircraftService
from app.domain.models import StationType


def _draft() -> AircraftRevisionDraft:
    return AircraftRevisionDraft(
        basic_empty_weight_lb=D("1500"),
        basic_empty_moment_lb_in=D("58500"),
        basic_empty_cg_in=D("39.0"),
        max_takeoff_weight_lb=D("2550"),
        max_ramp_weight_lb=D("2560"),
        stations=[
            StationDraft(
                name="Front Seats",
                station_type=StationType.FRONT_SEATS,
                default_arm_in=D("37.0"),
            ),
            StationDraft(
                name="Main Fuel",
                station_type=StationType.FUEL,
                default_arm_in=D("48.0"),
                maximum_volume_gal=D("40"),
                fuel_density_lb_per_gal=D("6.0"),
            ),
        ],
        envelope_rows=[
            EnvelopeRowDraft(D("2200"), D("35.0"), D("47.3")),
            EnvelopeRowDraft(D("2550"), D("41.0"), D("47.3")),
        ],
    )


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory, str(db_path)
    await engine.dispose()


async def test_default_language_is_honored_for_new_users(session_factory):
    """DbSessionMiddleware passes settings.default_language into get_or_create_user -- this
    verifies that language argument is actually stored, not silently dropped to 'en'."""
    factory, _ = session_factory
    async with factory() as session:
        service = AircraftService(AircraftRepository(session))

        ru_user = await service.get_or_create_user(telegram_user_id=999, language="ru")
        await session.commit()
        assert ru_user.language == "ru"

        # a returning user's language must not be reset by a later call with a different default
        same_user_again = await service.get_or_create_user(telegram_user_id=999, language="en")
        assert same_user_again.language == "ru"


async def test_new_aircraft_becomes_active_automatically(session_factory):
    factory, _ = session_factory
    async with factory() as session:
        service = AircraftService(AircraftRepository(session))
        user = await service.get_or_create_user(telegram_user_id=666)
        assert user.selected_aircraft_id is None

        aircraft = await service.create_aircraft(user.id, "N666FF", "172", None, None, _draft())
        await session.commit()

        assert user.selected_aircraft_id == aircraft.id

        # a second aircraft becomes the new active one -- no manual "Select Aircraft" needed
        aircraft2 = await service.create_aircraft(user.id, "N667GG", "182", None, None, _draft())
        await session.commit()
        assert user.selected_aircraft_id == aircraft2.id


async def test_multi_user_data_isolation(session_factory):
    factory, _ = session_factory
    async with factory() as session:
        repo = AircraftRepository(session)
        service = AircraftService(repo)

        user_a = await service.get_or_create_user(telegram_user_id=111)
        user_b = await service.get_or_create_user(telegram_user_id=222)

        aircraft_a = await service.create_aircraft(user_a.id, "N111AA", "172", None, "Cessna", _draft())
        await service.create_aircraft(user_b.id, "N222BB", "172", None, "Cessna", _draft())
        await session.commit()

        # user B must not see or be able to fetch user A's aircraft
        b_list = await service.list_aircraft(user_b.id)
        assert all(a.tail_number != "N111AA" for a in b_list)

        fetched = await service.get_aircraft(user_b.id, aircraft_a.id)
        assert fetched is None

        fetched_by_owner = await service.get_aircraft(user_a.id, aircraft_a.id)
        assert fetched_by_owner is not None


async def test_aircraft_revision_history(session_factory):
    factory, _ = session_factory
    async with factory() as session:
        repo = AircraftRepository(session)
        service = AircraftService(repo)

        user = await service.get_or_create_user(telegram_user_id=333)
        aircraft = await service.create_aircraft(user.id, "N333CC", "172", None, None, _draft())
        await session.commit()

        first_revision_id = aircraft.active_revision_id

        updated_draft = dataclasses.replace(_draft(), notes="updated empty weight after annual")
        new_revision = await service.update_aircraft(aircraft, updated_draft)
        await session.commit()

        assert new_revision.revision_number == 2
        assert aircraft.active_revision_id == new_revision.id
        assert aircraft.active_revision_id != first_revision_id

        old_revision = await repo.get_revision(user.id, first_revision_id)
        assert old_revision is not None
        assert old_revision.revision_number == 1  # historical revision remains untouched


async def test_flight_calculation_stays_linked_to_its_revision(session_factory):
    factory, _ = session_factory
    async with factory() as session:
        aircraft_repo = AircraftRepository(session)
        flight_repo = FlightRepository(session)
        service = AircraftService(aircraft_repo)

        user = await service.get_or_create_user(telegram_user_id=444)
        aircraft = await service.create_aircraft(user.id, "N444DD", "172", None, None, _draft())
        await session.commit()
        revision_id = aircraft.active_revision_id

        await flight_repo.save_calculation(
            user_id=user.id,
            aircraft_id=aircraft.id,
            aircraft_revision_id=revision_id,
            engine_version="1.0.0",
            input_snapshot_json="{}",
            result_snapshot_json="{}",
        )
        await session.commit()

        # create a new revision; old flight calculation must still point at revision 1
        await service.update_aircraft(aircraft, _draft())
        await session.commit()

        history = await flight_repo.list_for_user(user.id)
        assert len(history) == 1
        assert history[0].aircraft_revision_id == revision_id


async def test_persistence_after_application_restart(tmp_path):
    db_path = tmp_path / "restart_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # "First run": create engine, tables, and data, then dispose the engine entirely.
    engine1 = create_async_engine(db_url)
    async with engine1.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory1 = async_sessionmaker(engine1, expire_on_commit=False, class_=AsyncSession)
    async with factory1() as session:
        service = AircraftService(AircraftRepository(session))
        user = await service.get_or_create_user(telegram_user_id=555)
        await service.create_aircraft(user.id, "N555EE", "182", "Skylane", "Cessna", _draft())
        await session.commit()
    await engine1.dispose()

    # "Restart": brand new engine/session pointed at the same file.
    engine2 = create_async_engine(db_url)
    factory2 = async_sessionmaker(engine2, expire_on_commit=False, class_=AsyncSession)
    async with factory2() as session:
        service = AircraftService(AircraftRepository(session))
        user = await service.get_or_create_user(telegram_user_id=555)
        aircraft_list = await service.list_aircraft(user.id)
        assert len(aircraft_list) == 1
        assert aircraft_list[0].tail_number == "N555EE"
        assert aircraft_list[0].nickname == "Skylane"
    await engine2.dispose()
