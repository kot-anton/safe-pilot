import json
from decimal import Decimal as D
from types import SimpleNamespace

from app.bot.handlers.aircraft_wizard import _apply_station_type_change, got_station_edit_arm
from app.bot.handlers import flight_calculation
from app.bot.handlers.flight_calculation import _history_summary, _parse_load_entry
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.states.flight_wizard import FlightWizard
from app.domain.models import AircraftProfile, StationProfile, StationType
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput
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

    await flight_calculation._begin_for_aircraft(
        message, state, user, aircraft_service=None, aircraft_id=1
    )

    assert state.current_state == FlightWizard.fuel_starting
    assert state.data["fuel_index"] == 0
    assert any("usable capacity 40 gal" in text for text, _ in message.answers)


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
    assert any("combined usable capacity (40 gal)" in text for text, _ in message.answers)


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
