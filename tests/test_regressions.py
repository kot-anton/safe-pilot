import json
from decimal import Decimal as D
from types import SimpleNamespace

from app.bot.handlers import aircraft_update, aircraft_wizard, flight_calculation, quick_calculate
from app.bot.handlers._common import recommendation_text
from app.bot.handlers.aircraft_wizard import _apply_station_type_change, got_station_edit_arm
from app.bot.handlers.flight_calculation import _history_summary
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.states.flight_wizard import FlightWizard
from app.bot.states.quick_calc_wizard import QuickCalcWizard
from app.database.models import StationTypeEnum
from app.domain.envelope import CGCheckResult, LimitStatus
from app.domain.models import AircraftProfile, StationProfile, StationType
from app.domain.models import (
    CalculationInput,
    CalculationResult,
    FuelStationInput,
    LoadItemInput,
    PhaseResult,
)
from app.domain.quick_recommendations import QuickRecommendation, QuickRecommendationKind
from app.services.flight_service import _snapshot


class _FakeState:
    def __init__(self, data: dict, current_state=None):
        self.data = data
        self.current_state = current_state

    async def get_data(self):
        return self.data

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current_state = state

    async def clear(self):
        self.data = {}
        self.current_state = None

    async def get_state(self):
        return self.current_state.state if hasattr(self.current_state, "state") else self.current_state


class _FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class _FakeCallback:
    def __init__(self, message: _FakeMessage):
        self.message = message
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


async def test_quick_fuel_prompt_identifies_configured_tanks_and_saved_total():
    state = _FakeState(
        {
            "fuel_tank_labels": ["Main", "Aux"],
            "full_fuel_gal": "53.0000",
        }
    )
    message = _FakeMessage()
    user = SimpleNamespace(language="en")

    await quick_calculate._ask_fuel(message, state, user)

    prompt, kwargs = message.answers[-1]
    assert prompt == "Total usable fuel on board at takeoff (Main, Aux), in US gal:"
    assert kwargs["reply_markup"].inline_keyboard[0][0].text == (
        "Full tanks (53 gal usable)"
    )
    assert all(
        "Use last" not in button.text
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    )


async def test_quick_back_returns_to_the_previous_step_and_pops_history():
    state = _FakeState(
        {
            "has_front": True,
            "has_rear": True,
            "has_baggage": True,
            "last_front_lb": None,
            "front_lb": "180",
            "_nav_history": [QuickCalcWizard.front.state],
        },
        current_state=QuickCalcWizard.rear,
    )
    message = _FakeMessage()
    callback = _FakeCallback(message)
    user = SimpleNamespace(language="en")

    await quick_calculate.quick_back(callback, state, user)

    assert state.current_state == QuickCalcWizard.front.state
    assert state.data["_nav_history"] == []
    prompt, kwargs = message.answers[-1]
    assert prompt == "Front seats combined weight in lb:"
    callbacks = [
        button.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "quick:zero" not in callbacks  # front seat: no "None" shortcut
    assert "quick:back" not in callbacks  # nothing left behind the first step


async def test_quick_back_at_first_step_tells_pilot_there_is_nowhere_to_go():
    state = _FakeState({"_nav_history": []}, current_state=QuickCalcWizard.front)
    message = _FakeMessage()
    callback = _FakeCallback(message)
    user = SimpleNamespace(language="en")

    await quick_calculate.quick_back(callback, state, user)

    assert message.answers[-1][0] == "You are already at the first step."


async def test_empty_cg_and_moment_are_derived_from_the_entered_aircraft_record():
    user = SimpleNamespace(language="en")

    cg_state = _FakeState(
        {"basic_empty_weight_lb": "1960.8"}
    )
    await aircraft_wizard.got_empty_cg(
        _FakeMessage("79.1300"), cg_state, user
    )
    assert D(cg_state.data["basic_empty_moment_lb_in"]) == D("155158.104")

    moment_state = _FakeState(
        {"basic_empty_weight_lb": "1960.8"}
    )
    await aircraft_wizard.got_empty_moment(
        _FakeMessage("155158.104"), moment_state, user
    )
    assert D(moment_state.data["basic_empty_cg_in"]) == D("79.13")


async def test_empty_cg_accepts_negative_value_like_the_moment_path_does():
    """Regression: got_empty_cg used to disallow negative values while got_empty_moment (which
    can derive an equally negative CG) did not, so a negative CG -- physically valid depending
    on datum placement, same as a station ARM -- was only reachable indirectly via moment."""
    user = SimpleNamespace(language="en")
    cg_state = _FakeState({"basic_empty_weight_lb": "1000"})

    await aircraft_wizard.got_empty_cg(_FakeMessage("-5.0"), cg_state, user)

    assert D(cg_state.data["basic_empty_cg_in"]) == D("-5.0")
    assert D(cg_state.data["basic_empty_moment_lb_in"]) == D("-5000.0")


async def test_finishing_stations_shows_readonly_fuel_total_and_goes_to_envelope():
    """Regression: the wizard used to re-ask the pilot to type back the fuel total they'd
    already configured tank-by-tank. It's now a read-only recap, sent as its own message right
    as the station loop ends -- not folded into the CG-envelope prompt, since tank capacity has
    nothing to do with the CG envelope that follows it."""
    user = SimpleNamespace(language="en")
    route_state = _FakeState(
        {
            "stations": [
                {
                    "name": "Main Fuel Tanks",
                    "station_type": "FUEL",
                    "maximum_volume_gal": "40",
                },
                {
                    "name": "Aux Fuel Tanks",
                    "station_type": "FUEL",
                    "maximum_volume_gal": "13.0000",
                },
            ],
            "envelope_rows": [],
            "_nav_history": [],
        },
        AircraftWizard.station_add_prompt,
    )
    route_callback = _FakeCallback(_FakeMessage())

    await aircraft_wizard.stations_done(route_callback, route_state, user)

    assert route_state.current_state == AircraftWizard.envelope_rows
    recap, envelope_prompt = (text for text, _ in route_callback.message.answers)
    assert recap == "Configured tanks: 53 gal usable"
    assert "Enter one CG-envelope row per message" in envelope_prompt
    assert "Tanks" not in envelope_prompt


def _envelope_rows_fixture():
    return [
        {"weight_lb": "2265", "forward_cg_limit_in": "76.5", "aft_cg_limit_in": "85.7"},
        {"weight_lb": "2525", "forward_cg_limit_in": "79.9", "aft_cg_limit_in": "85.7"},
        {"weight_lb": "2775", "forward_cg_limit_in": "83.2", "aft_cg_limit_in": "85.1"},
    ]


async def test_edit_row_prompt_lists_every_row_with_its_own_callback():
    state = _FakeState(
        {"envelope_rows": _envelope_rows_fixture()}, AircraftWizard.envelope_rows
    )
    callback = _FakeCallback(_FakeMessage())
    user = SimpleNamespace(language="en")

    await aircraft_wizard.edit_row_prompt(callback, state, user)

    keyboard = callback.message.answers[-1][1]["reply_markup"]
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert callbacks == [
        "wizard:edit_row_at:0",
        "wizard:edit_row_at:1",
        "wizard:edit_row_at:2",
        "wizard:edit_row_cancel",
    ]
    # Middle row specifically -- proving the picker (not a fixed "first"/"last" row) is what
    # lets the pilot fix exactly the one they mean.
    middle_button = keyboard.inline_keyboard[1][0]
    assert "2525" in middle_button.text


async def test_edit_row_at_prefills_the_currently_typed_values():
    state = _FakeState(
        {"envelope_rows": _envelope_rows_fixture(), "_nav_history": []},
        AircraftWizard.envelope_rows,
    )
    callback = _FakeCallback(_FakeMessage())
    callback.data = "wizard:edit_row_at:1"
    user = SimpleNamespace(language="en")

    await aircraft_wizard.edit_row_at(callback, state, user)

    assert state.current_state == AircraftWizard.envelope_edit_row
    assert state.data["editing_envelope_row_index"] == 1
    prompt = callback.message.answers[-1][0]
    assert "2525, 79.9, 85.7" in prompt


async def test_got_envelope_row_edit_replaces_only_the_targeted_row():
    """The edit must replace the row in place, not append a fourth row or disturb the other
    two -- and must return the wizard to the row list, not leave it stuck mid-edit."""
    state = _FakeState(
        {"envelope_rows": _envelope_rows_fixture(), "editing_envelope_row_index": 1},
        AircraftWizard.envelope_edit_row,
    )
    message = _FakeMessage("2530, 80.0, 85.7")
    user = SimpleNamespace(language="en")

    await aircraft_wizard.got_envelope_row_edit(message, state, user)

    assert state.current_state == AircraftWizard.envelope_rows
    assert state.data["editing_envelope_row_index"] is None
    rows = state.data["envelope_rows"]
    assert len(rows) == 3
    assert rows[0]["weight_lb"] == "2265"
    assert rows[1] == {
        "weight_lb": "2530",
        "forward_cg_limit_in": "80",
        "aft_cg_limit_in": "85.7",
    }
    assert rows[2]["weight_lb"] == "2775"
    assert any("Row updated" in text for text, _ in message.answers)


async def test_edit_row_cancel_returns_to_row_list_without_changing_data():
    state = _FakeState(
        {
            "envelope_rows": _envelope_rows_fixture(),
            "editing_envelope_row_index": 1,
        },
        AircraftWizard.envelope_edit_row,
    )
    callback = _FakeCallback(_FakeMessage())
    user = SimpleNamespace(language="en")

    await aircraft_wizard.edit_row_cancel(callback, state, user)

    assert state.current_state == AircraftWizard.envelope_rows
    assert state.data["editing_envelope_row_index"] is None
    assert state.data["envelope_rows"] == _envelope_rows_fixture()


async def test_takeoff_weight_rejected_immediately_when_below_ramp_weight():
    """Regression: ramp weight is asked before takeoff weight, but the ramp>=takeoff domain
    rule used to only be checked at the very end, at Review -- after every remaining
    Advanced-Setup question had already been answered. It must now be caught the moment
    takeoff weight is entered, while the pilot is still on that screen."""
    user = SimpleNamespace(language="en")
    state = _FakeState(
        {"max_ramp_weight_lb": "2200", "_nav_history": [AircraftWizard.max_ramp_weight]},
        AircraftWizard.max_takeoff_weight,
    )
    message = _FakeMessage("2300")

    await aircraft_wizard.got_max_takeoff_weight(message, state, user)

    assert state.current_state == AircraftWizard.max_takeoff_weight
    assert any("cannot be below max takeoff weight" in text for text, _ in message.answers)
    assert any("Max takeoff weight, lb:" in text for text, _ in message.answers)


async def test_takeoff_weight_accepted_when_at_or_above_ramp_weight():
    user = SimpleNamespace(language="en")
    state = _FakeState(
        {"max_ramp_weight_lb": "2200", "_nav_history": [AircraftWizard.max_ramp_weight]},
        AircraftWizard.max_takeoff_weight,
    )
    message = _FakeMessage("2200")

    await aircraft_wizard.got_max_takeoff_weight(message, state, user)

    assert state.current_state == AircraftWizard.max_landing_weight
    assert not any("cannot be below max takeoff weight" in text for text, _ in message.answers)


async def test_advanced_pilot_surfaces_never_expose_database_decimal_scale():
    user = SimpleNamespace(language="en")
    review_state = _FakeState(
        {
            "loads": {
                "front": "320.0000",
                "rear": "130.0000",
                "baggage": "20.0000",
            },
            "non_fuel_station_names": {
                "front": "Front Seats",
                "rear": "Rear Seats",
                "baggage": "Baggage Area",
            },
            "fuel": {
                "main": {
                    "starting_gal": "40.0000",
                    "enroute_burn_gal": "30.0000",
                },
                "aux": {
                    "starting_gal": "13.0000",
                    "enroute_burn_gal": "13.0000",
                },
            },
            "fuel_station_names": {
                "main": "Main Fuel Tanks",
                "aux": "Aux Fuel Tanks",
            },
        }
    )
    review = "\n".join(
        flight_calculation._flight_review_lines(review_state.data, "en")
    )
    assert ".0000" not in review
    assert "Front Seats: 320 lb" in review
    assert "Main Fuel Tanks: start 40 gal, enroute burn 30 gal" in review
    assert "Aux Fuel Tanks: start 13 gal, enroute burn 13 gal" in review

    prompt_state = _FakeState(
        {
            "non_fuel_station_ids": ["pilot"],
            "non_fuel_station_names": {"pilot": "Pilot Seat"},
            "non_fuel_station_types": {"pilot": "CUSTOM"},
            "last_load_values": {},
        }
    )
    prompt_message = _FakeMessage()

    await flight_calculation._render_load_prompt(
        prompt_message, prompt_state, user, 0, show_back=False
    )

    prompt = prompt_message.answers[-1][0]
    assert ".0000" not in prompt
    assert "Weight at Pilot Seat, in lb:" in prompt

    quick_state = _FakeState(
        {
            "tail_number": "N100AA",
            "has_front": True,
            "has_rear": True,
            "has_baggage": True,
            "front_lb": "320.0000",
            "rear_lb": "130.0000",
            "baggage_lb": "20.0000",
            "total_fuel_gal": "53.0000",
        }
    )
    quick_review_lines = quick_calculate._quick_review_lines(
        quick_state.data,
        tail_number=quick_state.data["tail_number"],
        front=D(quick_state.data["front_lb"]),
        rear=D(quick_state.data["rear_lb"]),
        baggage=D(quick_state.data["baggage_lb"]),
        total_fuel=D(quick_state.data["total_fuel_gal"]),
        lang="en",
    )

    quick_review = "\n".join(quick_review_lines)
    assert ".0000" not in quick_review
    assert "Front seats: 320 lb" in quick_review
    assert "Usable fuel: 53 gal" in quick_review


async def test_edit_station_arm_returns_to_station_hub_state():
    """Regression: editing an ARM used to render the station hub while the FSM remained in
    station_edit_arm, so Done adding stations had no matching callback handler."""
    state = _FakeState(
        {
            "editing_station_index": 0,
            "stations": [
                {
                    "name": "Front Seats",
                    "station_type": "FRONT_SEATS",
                    "default_arm_in": "86",
                    "maximum_volume_gal": None,
                    "fuel_density_lb_per_gal": None,
                }
            ],
        },
        AircraftWizard.station_edit_arm,
    )
    message = _FakeMessage("87.5")
    user = SimpleNamespace(language="en")

    await got_station_edit_arm(message, state, user)

    assert state.data["stations"][0]["default_arm_in"] == "87.5"
    assert state.data["editing_station_index"] is None
    assert state.current_state == AircraftWizard.station_add_prompt
    assert any("Station updated" in text for text, _ in message.answers)


def test_flight_snapshot_remains_structured_json():
    calc_input = CalculationInput(
        loads=[LoadItemInput(station_id="front", weight_lb=D("340"))],
        fuel=[FuelStationInput(station_id="fuel", starting_gal=D("20"))],
    )

    decoded = json.loads(_snapshot(calc_input))

    assert isinstance(decoded, dict)
    assert decoded["loads"][0]["station_id"] == "front"
    assert decoded["loads"][0]["weight_lb"] == "340"
    assert decoded["fuel"][0]["starting_gal"] == "20"


def test_history_summary_handles_legacy_opaque_snapshot():
    calc = SimpleNamespace(result_snapshot_json=json.dumps("CalculationResult(...)"))
    assert _history_summary(calc) == "legacy result — details unavailable"

    scaled = SimpleNamespace(
        result_snapshot_json=json.dumps(
            {"total_weight_lb": "2739.0000", "overall_status": "WITHIN"}
        )
    )
    assert _history_summary(scaled) == "2739 lb -- Within Limits"


def test_legacy_custom_station_can_be_converted_to_fuel_without_stale_pound_fields():
    station = {
        "name": "Fuel Aux Tanks",
        "station_type": "CUSTOM",
        "default_arm_in": "94",
        "maximum_volume_gal": None,
        "fuel_density_lb_per_gal": None,
    }

    _apply_station_type_change(station, "FUEL")

    assert station["station_type"] == "FUEL"
    assert station["maximum_volume_gal"] is None
    # Fuel density is no longer a wizard question -- converting to FUEL attaches the
    # configured default automatically instead of leaving it unset.
    assert station["fuel_density_lb_per_gal"] == "6.0"


def test_station_type_change_away_from_fuel_rejected_when_name_still_looks_like_fuel():
    """Changing a station's type away from Fuel Tank must not silently leave a fuel-sounding
    name attached to a non-fuel station -- that's the exact CUSTOM+"Fuel Aux Tanks" failure
    mode this guard exists for, just triggered from the other direction."""
    station = {
        "name": "Aux Fuel Tanks",
        "station_type": "FUEL",
        "default_arm_in": "94",
        "maximum_volume_gal": "20",
        "fuel_density_lb_per_gal": "6.0",
    }

    changed = _apply_station_type_change(station, "CUSTOM")

    assert changed is False
    assert station["station_type"] == "FUEL"
    assert station["maximum_volume_gal"] == "20"


def test_station_type_change_away_from_fuel_allowed_for_non_fuel_name():
    station = {
        "name": "Wing Locker",
        "station_type": "FUEL",
        "default_arm_in": "94",
        "maximum_volume_gal": "20",
        "fuel_density_lb_per_gal": "6.0",
    }

    changed = _apply_station_type_change(station, "CUSTOM")

    assert changed is True
    assert station["station_type"] == "CUSTOM"
    assert station["maximum_volume_gal"] is None
    assert station["fuel_density_lb_per_gal"] is None


async def test_advanced_flow_with_only_fuel_stations_starts_at_first_tank(monkeypatch):
    """Regression: this branch called the next-fuel helper without its required index."""
    profile = AircraftProfile(
        tail_number="N100AA",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("1600"),
        stations=[
            StationProfile(
                station_id="fuel",
                name="Main Fuel",
                station_type=StationType.FUEL,
                default_arm_in=D("48"),
                maximum_volume_gal=D("40"),
                fuel_density_lb_per_gal=D("6"),
            )
        ],
        envelope=None,
    )
    aircraft = SimpleNamespace(id=1, nickname=None)

    async def fake_load(*_args):
        return aircraft, profile

    monkeypatch.setattr(flight_calculation, "_load_profile_and_aircraft", fake_load)
    state = _FakeState({})
    message = _FakeMessage()
    user = SimpleNamespace(id=7, language="en")

    class FakeFlightService:
        async def list_history(self, *_args, **_kwargs):
            return []

    await flight_calculation._begin_for_aircraft(
        message,
        state,
        user,
        aircraft_service=None,
        flight_service=FakeFlightService(),
        aircraft_id=1,
    )

    assert state.current_state == FlightWizard.fuel_starting
    assert state.data["fuel_index"] == 0
    assert any("Saved usable capacity: 40 gal" in text for text, _ in message.answers)


async def test_advanced_from_quick_reuses_loads_and_skips_to_fuel(monkeypatch):
    """Regression: Quick -> Advanced used to re-ask front/rear/baggage from scratch."""
    profile = AircraftProfile(
        tail_number="N100AA",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile("front", "Front Seats", StationType.FRONT_SEATS, D("37")),
            StationProfile("rear", "Rear Seats", StationType.REAR_SEATS, D("73")),
            StationProfile("baggage", "Baggage", StationType.BAGGAGE, D("95")),
            StationProfile(
                "fuel",
                "Main Fuel",
                StationType.FUEL,
                D("48"),
                maximum_volume_gal=D("40"),
                fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=None,
    )
    aircraft = SimpleNamespace(id=1, nickname=None)

    async def fake_load(*_args):
        return aircraft, profile

    monkeypatch.setattr(flight_calculation, "_load_profile_and_aircraft", fake_load)

    class FakeFlightService:
        async def list_history(self, *_args, **_kwargs):
            return []

    state = _FakeState(
        {
            "aircraft_id": 1,
            "front_lb": "180",
            "rear_lb": "0",
            "baggage_lb": "30",
            "total_fuel_gal": "20",
        }
    )
    message = _FakeMessage()
    callback = _FakeCallback(message)
    user = SimpleNamespace(id=7, language="en")

    await flight_calculation.advanced_from_quick(
        callback, state, user, aircraft_service=None, flight_service=FakeFlightService()
    )

    assert state.current_state == FlightWizard.fuel_starting
    assert state.data["loads"] == {"front": "180", "rear": "0", "baggage": "30"}
    assert not any(
        any(word in text for word in ("Front seat", "Rear seat", "Baggage"))
        for text, _ in message.answers
    )


async def test_advanced_flow_uses_canonical_station_order(monkeypatch):
    profile = AircraftProfile(
        tail_number="N100AA",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile("rear", "Rear Seats", StationType.REAR_SEATS, D("73")),
            StationProfile(
                "main",
                "Main Tank",
                StationType.FUEL,
                D("48"),
                maximum_volume_gal=D("20"),
                fuel_density_lb_per_gal=D("6"),
            ),
            StationProfile("bag", "Baggage", StationType.BAGGAGE, D("95")),
            StationProfile("front", "Front Seats", StationType.FRONT_SEATS, D("37")),
            StationProfile(
                "aux",
                "Aux Tank",
                StationType.FUEL,
                D("60"),
                maximum_volume_gal=D("10"),
                fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=None,
    )
    aircraft = SimpleNamespace(id=1, nickname=None)

    async def fake_load(*_args):
        return aircraft, profile

    class FakeFlightService:
        async def list_history(self, *_args, **_kwargs):
            return []

    monkeypatch.setattr(flight_calculation, "_load_profile_and_aircraft", fake_load)
    state = _FakeState({})
    message = _FakeMessage()
    user = SimpleNamespace(id=7, language="en")

    await flight_calculation._begin_for_aircraft(
        message,
        state,
        user,
        aircraft_service=None,
        flight_service=FakeFlightService(),
        aircraft_id=1,
    )

    assert state.data["non_fuel_station_ids"] == ["front", "rear", "bag"]
    assert state.data["fuel_station_ids"] == ["main", "aux"]
    assert state.current_state == FlightWizard.load_at_station
    assert message.answers[-1][0] == "Front seats combined weight in lb:"

    await flight_calculation._render_load_prompt(message, state, user, 1)
    assert message.answers[-1][0] == "Rear seats combined weight in lb:"
    
    await flight_calculation._render_load_prompt(message, state, user, 2)
    assert message.answers[-1][0] == "Baggage weight in lb:"


async def test_advanced_flow_rejects_fuel_above_tank_capacity_immediately():
    state = _FakeState(
        {
            "fuel_station_ids": ["fuel"],
            "fuel_station_capacities": {"fuel": "40"},
            "fuel_index": 0,
            "fuel": {},
        },
        FlightWizard.fuel_starting,
    )
    message = _FakeMessage("41")
    user = SimpleNamespace(language="en")

    await flight_calculation.got_fuel_starting(message, state, user)

    assert state.data["fuel"] == {}
    assert any("this tank's usable capacity (40 gal)" in text for text, _ in message.answers)


async def test_advanced_flow_rejects_burn_above_starting_fuel_immediately():
    state = _FakeState(
        {
            "fuel_station_ids": ["fuel"],
            "fuel_index": 0,
            "fuel": {"fuel": {"starting_gal": "20", "taxi_burn_gal": "0"}},
        },
        FlightWizard.fuel_enroute,
    )
    message = _FakeMessage("21")
    user = SimpleNamespace(language="en")

    await flight_calculation.got_fuel_enroute(
        message, state, user, aircraft_service=None, flight_service=None
    )

    assert "enroute_burn_gal" not in state.data["fuel"]["fuel"]
    assert any("cannot exceed starting fuel (20 gal)" in text for text, _ in message.answers)


async def test_fuel_enroute_prompt_has_no_skip_button():
    """The enroute-burn prompt always requires a typed answer -- there is no skip shortcut,
    since skipping a tank silently disabled landing evaluation for every tank, which was
    confusing to pilots trying to verify their full takeoff/landing setup."""
    user = SimpleNamespace(language="en")

    state = _FakeState(
        {
            "fuel_station_ids": ["main", "aux"],
            "fuel_station_names": {"main": "Main", "aux": "Aux"},
            "fuel": {"main": {"starting_gal": "20"}, "aux": {"starting_gal": "10"}},
        }
    )
    message = _FakeMessage()
    await flight_calculation._render_fuel_prompt(message, state, user, 0, "enroute")

    text, kwargs = message.answers[-1]
    assert "landing will not be evaluated" not in text
    callbacks = [
        button.callback_data
        for row in kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "wizard:skip" not in callbacks


async def test_last_advanced_input_skips_quick_and_malformed_history():
    history = [
        SimpleNamespace(
            calculation_engine_version="wb-engine-quick",
            input_snapshot_json=json.dumps({"front_lb": "340"}),
        ),
        SimpleNamespace(
            calculation_engine_version="wb-engine",
            input_snapshot_json="not json",
        ),
        SimpleNamespace(
            calculation_engine_version="wb-engine",
            input_snapshot_json=json.dumps(
                {
                    "loads": [
                        {"station_id": "front", "weight_lb": "340"},
                        {"station_id": "cargo", "weight_lb": "25"},
                    ],
                    "fuel": [
                        {"station_id": "left", "starting_gal": "20"},
                    ],
                }
            ),
        ),
    ]

    class FakeFlightService:
        async def list_history(self, *_args, **_kwargs):
            return history

    values = await flight_calculation._last_advanced_input(
        7, 1, FakeFlightService()
    )

    assert values == {
        "loads": {"front": "340", "cargo": "25"},
    }


async def test_advanced_use_last_load_stores_value_and_advances():
    state = _FakeState(
        {
            "non_fuel_station_ids": ["front", "rear"],
            "non_fuel_station_names": {"front": "Front Seats", "rear": "Rear Seats"},
            "non_fuel_station_default_arms": {"front": "37", "rear": "73"},
            "last_load_values": {"front": "180"},
            "loads": {},
            "load_index": 0,
            "_nav_history": [],
        },
        FlightWizard.load_at_station,
    )
    callback = _FakeCallback(_FakeMessage())
    user = SimpleNamespace(language="en")

    await flight_calculation.use_last_load(
        callback, state, user, aircraft_service=None, flight_service=None
    )

    assert state.data["loads"]["front"] == "180"
    assert state.data["load_index"] == 1
    assert state.current_state == FlightWizard.load_at_station
    assert callback.answers


async def test_advanced_full_tank_stores_capacity_and_advances_to_burn():
    state = _FakeState(
        {
            "fuel_station_ids": ["left"],
            "fuel_station_names": {"left": "Left Tank"},
            "fuel_station_capacities": {"left": "20"},
            "fuel_index": 0,
            "fuel": {},
            "_nav_history": [],
        },
        FlightWizard.fuel_starting,
    )
    callback = _FakeCallback(_FakeMessage())
    user = SimpleNamespace(language="en")

    await flight_calculation.use_full_fuel(callback, state, user)

    assert state.data["fuel"]["left"]["starting_gal"] == "20"
    assert state.current_state == FlightWizard.fuel_enroute
    assert callback.answers


async def test_advanced_calculation_finalizes_without_a_separate_confirm_step(monkeypatch):
    """Advanced used to stop at a "review your inputs, tap Calculate" screen. It should
    calculate immediately once the last question is answered -- same as Quick calc -- and
    still offer Change Load afterward instead of clearing state and losing that option."""
    profile = AircraftProfile(
        tail_number="N100AA",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile("front", "Front Seats", StationType.FRONT_SEATS, D("37")),
            StationProfile(
                "fuel",
                "Fuel Tank",
                StationType.FUEL,
                D("48"),
                maximum_volume_gal=D("20"),
                fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=None,
    )
    aircraft = SimpleNamespace(id=1, active_revision_id=1)

    async def fake_load(*_args):
        return aircraft, profile

    monkeypatch.setattr(flight_calculation, "_load_profile_and_aircraft", fake_load)

    takeoff = PhaseResult(
        phase="TAKEOFF",
        total_weight_lb=D("1500"),
        weight_limit_lb=D("2000"),
        cg_in=D("40"),
        cg_check=None,
        station_results=[],
        weight_status=LimitStatus.WITHIN,
        overall_status=LimitStatus.WITHIN,
    )
    result = CalculationResult(
        ramp=takeoff,
        takeoff=takeoff,
        landing=None,
        landing_evaluated=False,
        overall_status=LimitStatus.WITHIN,
    )
    persisted = {}

    class FakeFlightService:
        def run_calculation(self, _profile, _calc_input):
            return result

        async def persist_calculation(self, **kwargs):
            persisted.update(kwargs)

        def recommend(self, *_args, **_kwargs):
            return []

    state = _FakeState(
        {
            "aircraft_id": 1,
            "non_fuel_station_ids": ["front"],
            "non_fuel_station_names": {"front": "Front Seats"},
            "fuel_station_ids": ["fuel"],
            "fuel_station_names": {"fuel": "Fuel Tank"},
            "loads": {"front": "180"},
            "fuel": {
                "fuel": {
                    "starting_gal": "20",
                    "taxi_burn_gal": "0",
                    "enroute_burn_gal": "0",
                    "landing_fuel_provided": False,
                }
            },
            "fuel_index": 0,
        },
        FlightWizard.fuel_enroute,
    )
    message = _FakeMessage()
    user = SimpleNamespace(id=7, language="en")

    await flight_calculation._finalize_flight_calculation(
        message, state, user, aircraft_service=None, flight_service=FakeFlightService()
    )

    assert state.current_state == FlightWizard.review
    assert persisted["aircraft_id"] == 1
    texts = [text for text, _ in message.answers]
    assert any("Front Seats: 180 lb" in text for text in texts)
    assert any("WITHIN LIMITS" in text for text in texts)

    final_markup = message.answers[-1][1]["reply_markup"]
    final_callbacks = [
        button.callback_data for row in final_markup.inline_keyboard for button in row
    ]
    assert "wizard:edit" in final_callbacks
    assert "quick:main_menu" in final_callbacks


def test_advanced_result_uses_plain_language_cg_failure_and_phase_statuses():
    takeoff = PhaseResult(
        phase="TAKEOFF",
        total_weight_lb=D("2738.8"),
        weight_limit_lb=D("2775"),
        cg_in=D("81.2"),
        cg_check=CGCheckResult(
            status=LimitStatus.OUT_OF_LIMITS,
            forward_limit_in=D("82.7"),
            aft_limit_in=D("85.2"),
            forward_margin_in=D("-1.5"),
            aft_margin_in=D("4.0"),
        ),
        station_results=[],
        weight_status=LimitStatus.WITHIN,
        overall_status=LimitStatus.OUT_OF_LIMITS,
    )
    landing = PhaseResult(
        phase="LANDING",
        total_weight_lb=D("2480.8"),
        weight_limit_lb=D("2775"),
        cg_in=D("81.3"),
        cg_check=CGCheckResult(
            status=LimitStatus.WITHIN,
            forward_limit_in=D("79.3"),
            aft_limit_in=D("85.7"),
            forward_margin_in=D("1.94"),
            aft_margin_in=D("4.4"),
        ),
        station_results=[],
        weight_status=LimitStatus.WITHIN,
        overall_status=LimitStatus.WITHIN,
    )
    result = CalculationResult(
        ramp=takeoff,
        takeoff=takeoff,
        landing=landing,
        landing_evaluated=True,
        overall_status=LimitStatus.OUT_OF_LIMITS,
    )

    takeoff_text = flight_calculation._phase_text(takeoff, "en")
    landing_text = flight_calculation._phase_text(landing, "en")
    overall_text = flight_calculation._overall_result_text(result, "en")

    assert "TAKEOFF — ❌ NOT WITHIN LIMITS" in takeoff_text
    assert "Maximum takeoff weight: 2775 lb" in takeoff_text
    assert "CG is 1.5 in forward of the permitted limit" in takeoff_text
    assert "Forward margin" not in takeoff_text
    assert "LANDING — ✅ WITHIN LIMITS" in landing_text
    assert "CG is within the saved range" in landing_text
    assert "TAKEOFF CG is 1.5 in forward" in overall_text
    assert "Adjust the loading and calculate again" in overall_text


async def test_station_edit_list_is_canonical_but_keeps_original_callback_indexes():
    state = _FakeState(
        {
            "stations": [
                {"name": "Rear Seats", "station_type": "REAR_SEATS"},
                {"name": "Main Tank", "station_type": "FUEL"},
                {"name": "Front Seats", "station_type": "FRONT_SEATS"},
                {"name": "Baggage", "station_type": "BAGGAGE"},
            ]
        },
        AircraftWizard.station_add_prompt,
    )
    message = _FakeMessage()
    user = SimpleNamespace(language="en")

    await aircraft_wizard.render_edit_station_prompt(message, state, user)

    keyboard = message.answers[-1][1]["reply_markup"]
    station_buttons = [row[0] for row in keyboard.inline_keyboard[:-1]]
    assert [button.text for button in station_buttons] == [
        "✏️ Front Seats",
        "✏️ Rear Seats",
        "✏️ Baggage",
        "✏️ Main Tank",
    ]
    assert [button.callback_data for button in station_buttons] == [
        "wizard:edit_at:2",
        "wizard:edit_at:0",
        "wizard:edit_at:3",
        "wizard:edit_at:1",
    ]


def test_recommendation_text_handles_quick_recommendations_without_note():
    """Regression: QuickRecommendation has no `note` field (Quick never sets one), but
    recommendation_text() is shared with Advanced's Recommendation, which still has one for
    SHIFT_FUEL. Accessing `.note` unconditionally crashed the moment a Quick Calculation
    produced any recommendation at all."""
    recs = [
        QuickRecommendation(
            kind=QuickRecommendationKind.REDUCE_FUEL,
            delta_gal=D("0.1"),
            delta_lb=D("0.6"),
            target_total_fuel_gal=D("39.9"),
        )
    ]
    text = recommendation_text(recs, "en")
    assert "Reduce total usable fuel" in text


async def test_update_mode_offers_keep_current_for_tail_number_and_nickname():
    """The Edit Aircraft flow revisits tail number and nickname too -- a pilot who re-registered
    under a new N-number, or wants a different nickname, can retype them instead of recreating
    the whole profile. Keep Current is offered for both since the aircraft already has values."""
    user = SimpleNamespace(language="en")
    state = _FakeState({"update_mode": True, "tail_number": "N123AB", "nickname": "Old Bird"})

    tail_message = _FakeMessage()
    await aircraft_wizard.render_tail_number(tail_message, state, user)
    tail_text, tail_kwargs = tail_message.answers[-1]
    assert "Current: N123AB" in tail_text
    tail_callbacks = [
        button.callback_data
        for row in tail_kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "wizard:keep" in tail_callbacks

    nickname_message = _FakeMessage()
    await aircraft_wizard.render_nickname(nickname_message, state, user)
    nick_text, nick_kwargs = nickname_message.answers[-1]
    assert "Current: Old Bird" in nick_text
    nick_callbacks = [
        button.callback_data
        for row in nick_kwargs["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "wizard:keep" in nick_callbacks
    assert "wizard:skip" not in nick_callbacks

    keep_cb = _FakeCallback(_FakeMessage())
    await aircraft_wizard.keep_tail_number(keep_cb, state, user)
    assert state.current_state == AircraftWizard.nickname
    assert state.data["tail_number"] == "N123AB"


async def test_update_aircraft_chosen_starts_at_tail_number():
    """Regression: the Edit Aircraft entry point used to jump straight to empty weight,
    skipping tail number and nickname entirely -- making them impossible to change without
    recreating the aircraft."""

    class _FakeStation:
        def __init__(self):
            self.name = "Front Seats"
            self.station_type = StationTypeEnum.FRONT_SEATS
            self.display_order = 0
            self.active = True
            self.default_arm_in = D("0")
            self.maximum_volume_gal = None
            self.fuel_density_lb_per_gal = None

    aircraft = SimpleNamespace(
        id=1,
        tail_number="N123AB",
        model="172",
        nickname="Old Bird",
        manufacturer=None,
        active_revision_id=9,
    )
    revision = SimpleNamespace(
        stations=[_FakeStation()],
        envelope_rows=[],
        basic_empty_weight_lb=D("1500"),
        basic_empty_cg_in=D("39"),
        basic_empty_moment_lb_in=D("58500"),
        max_ramp_weight_lb=None,
        max_takeoff_weight_lb=D("2550"),
        max_landing_weight_lb=None,
        known_useful_load_lb=None,
        source_document_name=None,
        source_document_date=None,
    )

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return aircraft

        async def get_revision_for_user(self, user_id, revision_id):
            return revision

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState({})
    callback = _FakeCallback(_FakeMessage())
    callback.data = "update:1"

    await aircraft_update.update_aircraft_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert state.current_state == AircraftWizard.tail_number
    assert state.data["tail_number"] == "N123AB"
    assert state.data["nickname"] == "Old Bird"


async def test_download_data_prompt_lists_aircraft():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def list_aircraft(self, user_id):
            return [SimpleNamespace(id=1, tail_number="N123AB", nickname=None)]

    message = _FakeMessage()
    state = _FakeState({})
    user = SimpleNamespace(id=1, language="en")

    await menu.download_data_prompt(
        message, state, user, aircraft_service=FakeAircraftService()
    )

    assert state.data == {}
    prompt, kwargs = message.answers[-1]
    assert prompt == "Select an aircraft:"
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "download:1"


async def test_download_data_prompt_handles_no_aircraft():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def list_aircraft(self, user_id):
            return []

    message = _FakeMessage()
    state = _FakeState({})
    user = SimpleNamespace(id=1, language="en")

    await menu.download_data_prompt(
        message, state, user, aircraft_service=FakeAircraftService()
    )

    assert message.answers[-1][0] == "You have no aircraft yet. Use \"Add Aircraft\" to create one."


async def test_download_data_chosen_replies_with_summary_and_no_state_change():
    from app.bot.handlers import menu

    class _FakeStation:
        def __init__(self):
            self.name = "Front Seats"
            self.station_type = StationTypeEnum.FRONT_SEATS
            self.display_order = 0
            self.active = True
            self.default_arm_in = D("89")
            self.maximum_volume_gal = None
            self.fuel_density_lb_per_gal = None

    aircraft = SimpleNamespace(
        id=1,
        tail_number="N123AB",
        model="172",
        nickname="Old Bird",
        manufacturer=None,
        active_revision_id=9,
    )
    revision = SimpleNamespace(
        stations=[_FakeStation()],
        envelope_rows=[],
        basic_empty_weight_lb=D("1500"),
        basic_empty_cg_in=D("39"),
        basic_empty_moment_lb_in=D("58500"),
        max_ramp_weight_lb=None,
        max_takeoff_weight_lb=D("2550"),
        max_landing_weight_lb=None,
        known_useful_load_lb=None,
        source_document_name=None,
        source_document_date=None,
    )

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return aircraft

        async def get_revision_for_user(self, user_id, revision_id):
            return revision

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState(
        {"some_stale_key": "some_stale_value"}, current_state="some_stale_state"
    )
    callback = _FakeCallback(_FakeMessage())
    callback.data = "download:1"

    await menu.download_data_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert state.data == {"some_stale_key": "some_stale_value"}
    assert state.current_state == "some_stale_state"
    reply_text, _ = callback.message.answers[-1]
    assert "N123AB — 172" in reply_text
    assert "Front Seats" in reply_text
    assert callback.answers == [((), {})]


async def test_download_data_chosen_alerts_when_aircraft_not_found():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return None

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState({})
    callback = _FakeCallback(_FakeMessage())
    callback.data = "download:1"

    await menu.download_data_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert callback.answers == [
        (("Aircraft not found. It may have been archived.",), {"show_alert": True})
    ]
    assert callback.message.answers == []


async def test_download_data_chosen_alerts_when_aircraft_has_no_active_revision():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return SimpleNamespace(id=1, tail_number="N123AB", active_revision_id=None)

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState({})
    callback = _FakeCallback(_FakeMessage())
    callback.data = "download:1"

    await menu.download_data_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert callback.answers == [
        (("Aircraft not found. It may have been archived.",), {"show_alert": True})
    ]
    assert callback.message.answers == []


async def test_build_revision_summary_data_shapes_stations_and_envelope():
    class _FakeStation:
        def __init__(
            self,
            name="Front Seats",
            station_type=StationTypeEnum.FRONT_SEATS,
            display_order=0,
            active=True,
            default_arm_in=D("89"),
            maximum_volume_gal=None,
            fuel_density_lb_per_gal=None,
        ):
            self.name = name
            self.station_type = station_type
            self.display_order = display_order
            self.active = active
            self.default_arm_in = default_arm_in
            self.maximum_volume_gal = maximum_volume_gal
            self.fuel_density_lb_per_gal = fuel_density_lb_per_gal

    aircraft = SimpleNamespace(
        tail_number="N123AB",
        model="172",
        nickname="Old Bird",
        manufacturer=None,
    )

    # Create stations in non-canonical order to verify sorting by station_type_order then display_order.
    # Expected canonical order: FRONT_SEATS (0), REAR_SEATS (1), BAGGAGE (3), FUEL (5)
    stations_unordered = [
        # FUEL station (type_order=5, display_order=1) -- inserted first
        _FakeStation(
            name="Aux Tank",
            station_type=StationTypeEnum.FUEL,
            display_order=1,
            active=True,
            default_arm_in=D("95"),
            maximum_volume_gal=D("15"),
            fuel_density_lb_per_gal=D("6.0"),
        ),
        # BAGGAGE station (type_order=3, display_order=0)
        _FakeStation(
            name="Baggage Area",
            station_type=StationTypeEnum.BAGGAGE,
            display_order=0,
            active=True,
            default_arm_in=D("110"),
            maximum_volume_gal=None,
            fuel_density_lb_per_gal=None,
        ),
        # FRONT_SEATS (type_order=0, display_order=0) -- inserted last
        _FakeStation(
            name="Front Seats",
            station_type=StationTypeEnum.FRONT_SEATS,
            display_order=0,
            active=True,
            default_arm_in=D("89"),
            maximum_volume_gal=None,
            fuel_density_lb_per_gal=None,
        ),
        # REAR_SEATS (type_order=1, display_order=1) -- should sort between front and baggage
        _FakeStation(
            name="Rear Seats",
            station_type=StationTypeEnum.REAR_SEATS,
            display_order=1,
            active=True,
            default_arm_in=D("105"),
            maximum_volume_gal=None,
            fuel_density_lb_per_gal=None,
        ),
        # FUEL station (type_order=5, display_order=0) with None optional fields
        _FakeStation(
            name="Main Tank",
            station_type=StationTypeEnum.FUEL,
            display_order=0,
            active=True,
            default_arm_in=D("75"),
            maximum_volume_gal=D("40"),
            fuel_density_lb_per_gal=D("6.0"),
        ),
        # Inactive FUEL station -- should be excluded
        _FakeStation(
            name="Empty Tank",
            station_type=StationTypeEnum.FUEL,
            display_order=2,
            active=False,
            default_arm_in=D("90"),
            maximum_volume_gal=D("10"),
            fuel_density_lb_per_gal=D("6.0"),
        ),
    ]

    # Create envelope rows in non-sorted order
    class _FakeEnvelopeRow:
        def __init__(self, weight_lb, forward_cg_limit_in, aft_cg_limit_in):
            self.weight_lb = weight_lb
            self.forward_cg_limit_in = forward_cg_limit_in
            self.aft_cg_limit_in = aft_cg_limit_in

    envelope_rows_unordered = [
        _FakeEnvelopeRow(D("2525"), D("79.9"), D("85.7")),
        _FakeEnvelopeRow(D("2265"), D("76.5"), D("85.7")),
        _FakeEnvelopeRow(D("2775"), D("83.2"), D("85.1")),
    ]

    revision = SimpleNamespace(
        stations=stations_unordered,
        envelope_rows=envelope_rows_unordered,
        basic_empty_weight_lb=D("1500"),
        basic_empty_cg_in=D("39"),
        basic_empty_moment_lb_in=D("58500"),
        max_ramp_weight_lb=None,
        max_takeoff_weight_lb=D("2550"),
        max_landing_weight_lb=None,
    )

    data = aircraft_update.build_revision_summary_data(aircraft, revision)

    # Verify aircraft-level data
    assert data["tail_number"] == "N123AB"
    assert data["nickname"] == "Old Bird"
    assert data["basic_empty_weight_lb"] == "1500"
    assert data["basic_empty_cg_in"] == "39"
    assert data["max_ramp_weight_lb"] is None
    assert data["max_takeoff_weight_lb"] == "2550"

    # Verify stations are sorted by station_type_order then display_order, and inactive is excluded.
    # Expected order: FRONT_SEATS(0,0), REAR_SEATS(1,1), BAGGAGE(3,0), FUEL(5,0), FUEL(5,1)
    # The inactive station (FUEL, display_order=2) should not appear.
    assert len(data["stations"]) == 5
    station_names_in_order = [s["name"] for s in data["stations"]]
    assert station_names_in_order == [
        "Front Seats",
        "Rear Seats",
        "Baggage Area",
        "Main Tank",
        "Aux Tank",
    ]

    # Verify optional fields for fuel stations are passed through compact_decimal correctly
    main_tank = data["stations"][3]
    assert main_tank["name"] == "Main Tank"
    assert main_tank["maximum_volume_gal"] == "40"
    assert main_tank["fuel_density_lb_per_gal"] == "6"

    aux_tank = data["stations"][4]
    assert aux_tank["name"] == "Aux Tank"
    assert aux_tank["maximum_volume_gal"] == "15"
    assert aux_tank["fuel_density_lb_per_gal"] == "6"

    # Verify non-fuel stations have None for optional fields
    baggage = data["stations"][2]
    assert baggage["name"] == "Baggage Area"
    assert baggage["maximum_volume_gal"] is None
    assert baggage["fuel_density_lb_per_gal"] is None

    # Verify envelope rows are sorted by weight_lb ascending
    assert len(data["envelope_rows"]) == 3
    envelope_weights = [D(r["weight_lb"]) for r in data["envelope_rows"]]
    assert envelope_weights == [D("2265"), D("2525"), D("2775")]

    # Verify CG limit values are compact_decimal'd
    assert data["envelope_rows"][0] == {
        "weight_lb": "2265",
        "forward_cg_limit_in": "76.5",
        "aft_cg_limit_in": "85.7",
    }
    assert data["envelope_rows"][1] == {
        "weight_lb": "2525",
        "forward_cg_limit_in": "79.9",
        "aft_cg_limit_in": "85.7",
    }
    assert data["envelope_rows"][2] == {
        "weight_lb": "2775",
        "forward_cg_limit_in": "83.2",
        "aft_cg_limit_in": "85.1",
    }
