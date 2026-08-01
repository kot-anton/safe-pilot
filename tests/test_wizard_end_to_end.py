"""Drives the real Add Aircraft wizard handlers, in order, against a real database -- the
closest thing to an actual pilot session that a test can exercise without a live Telegram
connection. Complements the per-handler unit tests in test_regressions.py / test_bot_ui.py by
proving the *sequence* still holds together end to end after the 2026-07-31 simplification
(manufacturer/model/fuel-density/known-useful-load/total-usable-fuel questions removed, no
Quick/Advanced mode picker, nickname always asked, ramp/takeoff validated immediately)."""
from decimal import Decimal as D

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers import aircraft_wizard
from app.bot.states.aircraft_wizard import AircraftWizard
from app.database.models import Base, StationTypeEnum
from app.repositories.aircraft_repository import AircraftRepository
from app.services.aircraft_service import AircraftService
from tests.test_regressions import _FakeCallback, _FakeMessage, _FakeState


class _ClearableFakeState(_FakeState):
    """The real FSMContext supports `.clear()`; the shared test double doesn't need it for
    per-handler unit tests, but a full wizard walkthrough starts with the same `state.clear()`
    every real session does."""

    async def clear(self):
        self.data = {}
        self.current_state = None


@pytest.fixture
async def session_factory(tmp_path):
    db_path = tmp_path / "wizard_e2e.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


async def test_full_add_aircraft_wizard_walkthrough_creates_a_correct_aircraft(session_factory):
    async with session_factory() as session:
        aircraft_service = AircraftService(AircraftRepository(session))
        user = await aircraft_service.get_or_create_user(telegram_user_id=42)
        state = _ClearableFakeState({})
        message = _FakeMessage()

        # 1. Add Aircraft -- no mode picker, straight to tail number.
        await aircraft_wizard.start_wizard(message, state, user)
        assert state.current_state == AircraftWizard.tail_number

        # 2. Tail number -> nickname is always asked next (not gated behind a setup mode).
        await aircraft_wizard.got_tail_number(_FakeMessage("N999XE"), state, user)
        assert state.current_state == AircraftWizard.nickname

        # 3. Nickname skipped -> straight to empty weight (no manufacturer/model questions).
        skip_nick_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.skip_nickname(skip_nick_cb, state, user)
        assert state.current_state == AircraftWizard.empty_weight
        assert state.data["nickname"] is None

        # 4. Empty weight.
        await aircraft_wizard.got_empty_weight(_FakeMessage("1500"), state, user)
        assert state.current_state == AircraftWizard.cg_or_moment_choice

        # 5. Pilot knows the empty CG (also exercises the negative-CG-allowed fix, using a
        # realistic positive value here since a light GA aircraft's CG is never negative --
        # the negative-input path itself is covered directly in test_regressions.py).
        know_cg_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.choose_know_cg(know_cg_cb, state, user)
        assert state.current_state == AircraftWizard.empty_cg
        await aircraft_wizard.got_empty_cg(_FakeMessage("39.0"), state, user)
        assert state.current_state == AircraftWizard.max_ramp_weight

        # 6. Ramp weight set below what will become takeoff weight, on purpose, then corrected
        # -- proving the immediate cross-check (not deferred to Review) actually fires.
        await aircraft_wizard.got_max_ramp_weight(_FakeMessage("2500"), state, user)
        assert state.current_state == AircraftWizard.max_takeoff_weight

        bad_takeoff_message = _FakeMessage("2600")
        await aircraft_wizard.got_max_takeoff_weight(bad_takeoff_message, state, user)
        assert state.current_state == AircraftWizard.max_takeoff_weight
        assert any(
            "cannot be below max takeoff weight" in text for text, _ in bad_takeoff_message.answers
        )

        await aircraft_wizard.got_max_takeoff_weight(_FakeMessage("2500"), state, user)
        assert state.current_state == AircraftWizard.max_landing_weight

        # 7. Landing weight and MZFW both skipped.
        skip_landing_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.skip_max_landing_weight(skip_landing_cb, state, user)
        assert state.current_state == AircraftWizard.max_zfw
        skip_zfw_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.skip_max_zfw(skip_zfw_cb, state, user)
        # No Known Useful Load question -- straight to the station loop.
        assert state.current_state == AircraftWizard.station_add_prompt
        assert "known_useful_load_lb" not in state.data or state.data["known_useful_load_lb"] is None

        # 8. Add a Front Seats station.
        add_station_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.add_station(add_station_cb, state, user)
        assert state.current_state == AircraftWizard.station_type
        front_type_cb = _FakeCallback(_FakeMessage())
        front_type_cb.data = f"stype:{StationTypeEnum.FRONT_SEATS.value}"
        await aircraft_wizard.got_station_type(front_type_cb, state, user)
        assert state.current_state == AircraftWizard.station_name
        use_default_name_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.use_default_station_name(use_default_name_cb, state, user)
        assert state.current_state == AircraftWizard.station_arm
        await aircraft_wizard.got_station_arm(_FakeMessage("37.0"), state, user)
        assert state.current_state == AircraftWizard.station_add_prompt
        assert len(state.data["stations"]) == 1

        # 9. Add a Fuel Tank station -- no fuel-density question, default density applied.
        add_station_cb_2 = _FakeCallback(_FakeMessage())
        await aircraft_wizard.add_station(add_station_cb_2, state, user)
        fuel_type_cb = _FakeCallback(_FakeMessage())
        fuel_type_cb.data = f"stype:{StationTypeEnum.FUEL.value}"
        await aircraft_wizard.got_station_type(fuel_type_cb, state, user)
        use_default_name_cb_2 = _FakeCallback(_FakeMessage())
        await aircraft_wizard.use_default_station_name(use_default_name_cb_2, state, user)
        await aircraft_wizard.got_station_arm(_FakeMessage("48.0"), state, user)
        assert state.current_state == AircraftWizard.station_fuel_max_volume
        await aircraft_wizard.got_fuel_max_volume(_FakeMessage("40"), state, user)
        # Straight back to the station hub -- no fuel-density question in between.
        assert state.current_state == AircraftWizard.station_add_prompt
        assert len(state.data["stations"]) == 2
        fuel_station = state.data["stations"][1]
        assert fuel_station["station_type"] == StationTypeEnum.FUEL.value
        assert fuel_station["fuel_density_lb_per_gal"] == "6.0"

        # 10. Done adding stations -- goes straight to the CG envelope with a read-only fuel
        # recap folded into the prompt (no separate "total usable fuel" question).
        done_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.stations_done(done_cb, state, user)
        assert state.current_state == AircraftWizard.envelope_rows
        assert "Tanks total: 40 gal" in done_cb.message.answers[-1][0]

        # 11. Skip the CG envelope.
        skip_envelope_cb = _FakeCallback(_FakeMessage())
        skip_envelope_cb.data = "wizard:skip_envelope"
        await aircraft_wizard.skip_envelope(skip_envelope_cb, state, user)
        assert state.current_state == AircraftWizard.review

        # 12. Confirm -- persists to the real database with no model/manufacturer/known-useful-
        # load, and the fuel station carrying the configured default density.
        confirm_cb = _FakeCallback(_FakeMessage())
        await aircraft_wizard.review_confirm(confirm_cb, state, user, aircraft_service)

        aircraft_list = await aircraft_service.list_aircraft(user.id)
        assert len(aircraft_list) == 1
        aircraft = aircraft_list[0]
        assert aircraft.tail_number == "N999XE"
        assert aircraft.nickname is None
        assert aircraft.model is None
        assert aircraft.manufacturer is None

        revision = await aircraft_service.get_revision_for_user(user.id, aircraft.active_revision_id)
        assert revision.known_useful_load_lb is None
        assert revision.max_takeoff_weight_lb == D("2500")
        assert revision.max_ramp_weight_lb == D("2500")
        fuel_stations = [s for s in revision.stations if s.station_type == StationTypeEnum.FUEL]
        assert len(fuel_stations) == 1
        assert fuel_stations[0].fuel_density_lb_per_gal == D("6.0")
