import json
from decimal import Decimal as D
from types import SimpleNamespace

from app.bot.handlers import aircraft_wizard, flight_calculation, quick_calculate
from app.bot.handlers.aircraft_wizard import _apply_station_type_change, got_station_edit_arm
from app.bot.handlers.flight_calculation import _history_summary, _parse_load_entry
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.states.flight_wizard import FlightWizard
from app.domain.envelope import CGCheckResult, LimitStatus
from app.domain.models import AircraftProfile, StationProfile, StationType
from app.domain.models import (
    CalculationInput,
    CalculationResult,
    FuelStationInput,
    LoadItemInput,
    PhaseResult,
)
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
            "last_total_fuel_gal": "40.0000",
        }
    )
    message = _FakeMessage()
    user = SimpleNamespace(language="en")

    await quick_calculate._ask_fuel(message, state, user)

    prompt, kwargs = message.answers[-1]
    assert prompt == "Total usable fuel on board at takeoff (Main, Aux), in US gal:"
    assert kwargs["reply_markup"].inline_keyboard[0][0].text == (
        "Full tanks — 53 gal (saved capacity)"
    )


async def test_empty_cg_and_moment_are_derived_from_the_entered_aircraft_record():
    user = SimpleNamespace(language="en")

    cg_state = _FakeState(
        {"basic_empty_weight_lb": "1960.8", "setup_mode": "quick"}
    )
    await aircraft_wizard.got_empty_cg(
        _FakeMessage("79.1300"), cg_state, user
    )
    assert D(cg_state.data["basic_empty_moment_lb_in"]) == D("155158.104")

    moment_state = _FakeState(
        {"basic_empty_weight_lb": "1960.8", "setup_mode": "quick"}
    )
    await aircraft_wizard.got_empty_moment(
        _FakeMessage("155158.104"), moment_state, user
    )
    assert D(moment_state.data["basic_empty_cg_in"]) == D("79.13")


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
                    "is_adjustable_arm": False,
                    "minimum_arm_in": None,
                    "maximum_arm_in": None,
                    "maximum_weight_lb": None,
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


def test_legacy_custom_station_can_be_converted_to_fuel_without_stale_pound_fields():
    station = {
        "name": "Fuel Aux Tanks",
        "station_type": "CUSTOM",
        "default_arm_in": "94",
        "is_adjustable_arm": True,
        "minimum_arm_in": "90",
        "maximum_arm_in": "98",
        "maximum_weight_lb": "78",
        "maximum_volume_gal": None,
        "fuel_density_lb_per_gal": None,
    }

    _apply_station_type_change(station, "FUEL")

    assert station["station_type"] == "FUEL"
    assert station["maximum_weight_lb"] is None
    assert station["maximum_volume_gal"] is None
    assert station["fuel_density_lb_per_gal"] is None
    assert station["is_adjustable_arm"] is False


def test_adjustable_load_requires_and_parses_actual_arm():
    weight, arm = _parse_load_entry(
        "25 / 90.5", adjustable=True, default_arm=D("88")
    )
    assert weight == D("25")
    assert arm == D("90.5")

    zero_weight, zero_arm = _parse_load_entry(
        "0", adjustable=True, default_arm=D("88")
    )
    assert zero_weight == 0
    assert zero_arm == D("88")


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
    aircraft = SimpleNamespace(id=1)

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
    aircraft = SimpleNamespace(id=1)

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
    assert message.answers[-1][0] == "Combined weight on the front seats, in lb:"

    await flight_calculation._render_load_prompt(message, state, user, 1)
    assert message.answers[-1][0] == "Combined weight on the rear seats, in lb:"

    await flight_calculation._render_load_prompt(message, state, user, 2)
    assert message.answers[-1][0] == "Total baggage weight, in lb:"


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

    await flight_calculation.got_fuel_enroute(message, state, user)

    assert "enroute_burn_gal" not in state.data["fuel"]["fuel"]
    assert any("cannot exceed starting fuel (20 gal)" in text for text, _ in message.answers)


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
                        {"station_id": "front", "weight_lb": "340", "arm_in": None},
                        {"station_id": "cargo", "weight_lb": "25", "arm_in": "90"},
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
        "load_arms": {"cargo": "90"},
        "fuel_starting": {"left": "20"},
    }


async def test_advanced_use_last_load_stores_value_and_advances():
    state = _FakeState(
        {
            "non_fuel_station_ids": ["front", "rear"],
            "non_fuel_station_names": {"front": "Front Seats", "rear": "Rear Seats"},
            "non_fuel_station_adjustable": {"front": False, "rear": False},
            "non_fuel_station_default_arms": {"front": "37", "rear": "73"},
            "non_fuel_station_min_arms": {"front": None, "rear": None},
            "non_fuel_station_max_arms": {"front": None, "rear": None},
            "last_load_values": {"front": "180"},
            "last_load_arms": {},
            "loads": {},
            "load_arms": {},
            "load_index": 0,
            "_nav_history": [],
        },
        FlightWizard.load_at_station,
    )
    callback = _FakeCallback(_FakeMessage())
    user = SimpleNamespace(language="en")

    await flight_calculation.use_last_load(callback, state, user)

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
        zero_fuel_weight_lb=D("2420.8"),
        zero_fuel_limit_lb=None,
        zero_fuel_status=LimitStatus.WITHIN,
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


async def test_update_skips_unset_maximum_zero_fuel_weight_question():
    state = _FakeState(
        {
            "update_mode": True,
            "max_zero_fuel_weight_lb": None,
            "known_useful_load_lb": None,
            "_nav_history": [],
        },
        AircraftWizard.max_landing_weight,
    )
    message = _FakeMessage()
    user = SimpleNamespace(language="en")

    await aircraft_wizard._advance_past_max_landing(message, state, user)

    assert state.current_state == AircraftWizard.known_useful_load
    assert any("Known Useful Load" in text for text, _ in message.answers)
    assert all("Zero Fuel Weight" not in text for text, _ in message.answers)


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
