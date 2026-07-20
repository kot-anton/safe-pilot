"""Synthetic demonstration-only aircraft data for tests. NOT suitable for flight."""
from decimal import Decimal as D

import pytest

from app.domain.envelope import CGEnvelope, EnvelopeRow
from app.domain.models import AircraftProfile, StationProfile, StationType


def make_test_profile(**overrides) -> AircraftProfile:
    stations = overrides.pop(
        "stations",
        [
            StationProfile(
                station_id="front_seats",
                name="Front Seats",
                station_type=StationType.FRONT_SEATS,
                default_arm_in=D("37.0"),
            ),
            StationProfile(
                station_id="rear_seats",
                name="Rear Seats",
                station_type=StationType.REAR_SEATS,
                default_arm_in=D("73.0"),
            ),
            StationProfile(
                station_id="baggage_1",
                name="Baggage Area 1",
                station_type=StationType.BAGGAGE,
                default_arm_in=D("95.0"),
                maximum_weight_lb=D("120"),
            ),
            StationProfile(
                station_id="main_fuel",
                name="Main Fuel",
                station_type=StationType.FUEL,
                default_arm_in=D("48.0"),
                maximum_volume_gal=D("40"),
                fuel_density_lb_per_gal=D("6.0"),
            ),
            StationProfile(
                station_id="aux_fuel",
                name="Auxiliary Fuel",
                station_type=StationType.FUEL,
                default_arm_in=D("20.0"),
                maximum_volume_gal=D("20"),
                fuel_density_lb_per_gal=D("6.0"),
            ),
        ],
    )
    envelope = overrides.pop(
        "envelope",
        CGEnvelope(
            [
                EnvelopeRow(D("2200"), D("35.0"), D("47.3")),
                EnvelopeRow(D("2400"), D("37.0"), D("47.3")),
                EnvelopeRow(D("2550"), D("41.0"), D("47.3")),
            ]
        ),
    )
    defaults = dict(
        tail_number="N12345",
        revision_number=1,
        basic_empty_weight_lb=D("1500"),
        basic_empty_moment_lb_in=D("58500"),  # cg 39.0
        max_takeoff_weight_lb=D("2550"),
        max_ramp_weight_lb=D("2560"),
        max_landing_weight_lb=D("2440"),
        max_zero_fuel_weight_lb=None,
        stations=stations,
        envelope=envelope,
    )
    defaults.update(overrides)
    return AircraftProfile(**defaults)


@pytest.fixture
def profile() -> AircraftProfile:
    return make_test_profile()
