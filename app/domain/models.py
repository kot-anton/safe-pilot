"""Pure domain data model for weight & balance. No aiogram or SQLAlchemy imports allowed here."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.envelope import CGCheckResult, CGEnvelope, LimitStatus
from app.domain.exceptions import InvalidStationError


class StationType(str, Enum):
    FRONT_SEATS = "FRONT_SEATS"
    REAR_SEATS = "REAR_SEATS"
    PASSENGER = "PASSENGER"
    BAGGAGE = "BAGGAGE"
    FUEL = "FUEL"
    CUSTOM = "CUSTOM"


FUEL_STATION_TYPES = {StationType.FUEL}
BAGGAGE_STATION_TYPES = {StationType.BAGGAGE}


@dataclass(frozen=True)
class StationProfile:
    station_id: str
    name: str
    station_type: StationType
    default_arm_in: Decimal
    is_adjustable_arm: bool = False
    minimum_arm_in: Decimal | None = None
    maximum_arm_in: Decimal | None = None
    maximum_weight_lb: Decimal | None = None
    maximum_volume_gal: Decimal | None = None
    fuel_density_lb_per_gal: Decimal | None = None

    def __post_init__(self):
        if self.station_type in FUEL_STATION_TYPES:
            if self.maximum_volume_gal is None or self.maximum_volume_gal <= 0:
                raise InvalidStationError(f"Fuel station '{self.name}' requires a positive maximum volume")
            if self.fuel_density_lb_per_gal is None or self.fuel_density_lb_per_gal <= 0:
                raise InvalidStationError(f"Fuel station '{self.name}' requires an explicit fuel density")
        if self.is_adjustable_arm:
            if self.minimum_arm_in is None or self.maximum_arm_in is None:
                raise InvalidStationError(f"Adjustable station '{self.name}' requires min/max arm")
            if self.minimum_arm_in > self.maximum_arm_in:
                raise InvalidStationError(f"Station '{self.name}' min arm exceeds max arm")


@dataclass(frozen=True)
class AircraftProfile:
    """Everything the calculator needs, derived from one confirmed AircraftRevision."""

    tail_number: str
    revision_number: int
    basic_empty_weight_lb: Decimal
    basic_empty_moment_lb_in: Decimal
    max_takeoff_weight_lb: Decimal
    stations: list[StationProfile]
    envelope: CGEnvelope | None
    max_ramp_weight_lb: Decimal | None = None
    max_landing_weight_lb: Decimal | None = None
    max_zero_fuel_weight_lb: Decimal | None = None

    @property
    def basic_empty_cg_in(self) -> Decimal:
        return self.basic_empty_moment_lb_in / self.basic_empty_weight_lb

    def station(self, station_id: str) -> StationProfile:
        for s in self.stations:
            if s.station_id == station_id:
                return s
        raise InvalidStationError(f"Unknown station id '{station_id}'")

    @property
    def fuel_stations(self) -> list[StationProfile]:
        return [s for s in self.stations if s.station_type in FUEL_STATION_TYPES]

    @property
    def baggage_stations(self) -> list[StationProfile]:
        return [s for s in self.stations if s.station_type in BAGGAGE_STATION_TYPES]


@dataclass(frozen=True)
class LoadItemInput:
    """Non-fuel load at a station (passengers, baggage)."""

    station_id: str
    weight_lb: Decimal
    arm_in: Decimal | None = None  # required only for adjustable-arm stations


@dataclass(frozen=True)
class FuelStationInput:
    station_id: str
    starting_gal: Decimal
    taxi_burn_gal: Decimal = Decimal("0")
    enroute_burn_gal: Decimal = Decimal("0")
    landing_fuel_provided: bool = False


@dataclass(frozen=True)
class CalculationInput:
    loads: list[LoadItemInput]
    fuel: list[FuelStationInput]

    @property
    def landing_evaluated(self) -> bool:
        return any(f.landing_fuel_provided for f in self.fuel) or any(
            f.enroute_burn_gal > 0 for f in self.fuel
        )


@dataclass(frozen=True)
class StationLoadResult:
    station_id: str
    name: str
    weight_lb: Decimal
    arm_in: Decimal
    moment_lb_in: Decimal
    over_station_limit: bool
    over_capacity: bool = False  # fuel volume or similar


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    total_weight_lb: Decimal
    weight_limit_lb: Decimal | None
    cg_in: Decimal
    cg_check: CGCheckResult | None  # None when the aircraft has no CG envelope configured
    station_results: list[StationLoadResult]
    weight_status: LimitStatus
    overall_status: LimitStatus

    @property
    def weight_margin_lb(self) -> Decimal | None:
        if self.weight_limit_lb is None:
            return None
        return self.weight_limit_lb - self.total_weight_lb


@dataclass(frozen=True)
class CalculationResult:
    ramp: PhaseResult
    takeoff: PhaseResult
    landing: PhaseResult | None
    landing_evaluated: bool
    overall_status: LimitStatus
