"""Pure domain data model for Weight & Balance calculations.

This module intentionally has no aiogram or SQLAlchemy imports. Persisted records are converted
into these immutable objects by ``app.services.aircraft_service`` before any calculation runs.
"""
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


def _require_finite(value: Decimal | None, label: str) -> None:
    if value is not None and not value.is_finite():
        raise InvalidStationError(f"{label} must be finite")


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

    def __post_init__(self) -> None:
        if not self.station_id.strip():
            raise InvalidStationError("Station id is required")
        if not self.name.strip():
            raise InvalidStationError("Station name is required")

        _require_finite(self.default_arm_in, f"ARM for station '{self.name}'")
        _require_finite(self.minimum_arm_in, f"Minimum ARM for station '{self.name}'")
        _require_finite(self.maximum_arm_in, f"Maximum ARM for station '{self.name}'")
        _require_finite(self.maximum_weight_lb, f"Maximum weight for station '{self.name}'")
        _require_finite(self.maximum_volume_gal, f"Maximum volume for station '{self.name}'")
        _require_finite(self.fuel_density_lb_per_gal, f"Fuel density for station '{self.name}'")

        if self.maximum_weight_lb is not None and self.maximum_weight_lb <= 0:
            raise InvalidStationError(f"Station '{self.name}' maximum weight must be positive")

        if self.station_type in FUEL_STATION_TYPES:
            if self.maximum_volume_gal is None or self.maximum_volume_gal <= 0:
                raise InvalidStationError(f"Fuel station '{self.name}' requires a positive maximum volume")
            if self.fuel_density_lb_per_gal is None or self.fuel_density_lb_per_gal <= 0:
                raise InvalidStationError(f"Fuel station '{self.name}' requires an explicit positive fuel density")

        if self.is_adjustable_arm:
            if self.minimum_arm_in is None or self.maximum_arm_in is None:
                raise InvalidStationError(f"Adjustable station '{self.name}' requires min/max ARM")
            if self.minimum_arm_in > self.maximum_arm_in:
                raise InvalidStationError(f"Station '{self.name}' minimum ARM exceeds maximum ARM")
            if not self.minimum_arm_in <= self.default_arm_in <= self.maximum_arm_in:
                raise InvalidStationError(
                    f"Default ARM for station '{self.name}' must be inside its adjustable range"
                )


@dataclass(frozen=True)
class AircraftProfile:
    """Everything the calculator needs from one confirmed aircraft revision."""

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

    def __post_init__(self) -> None:
        if not self.tail_number.strip():
            raise InvalidStationError("Aircraft identifier is required")
        if self.revision_number <= 0:
            raise InvalidStationError("Aircraft revision number must be positive")

        numeric_values = {
            "Basic Empty Weight": self.basic_empty_weight_lb,
            "Basic Empty Moment": self.basic_empty_moment_lb_in,
            "Maximum Takeoff Weight": self.max_takeoff_weight_lb,
            "Maximum Ramp Weight": self.max_ramp_weight_lb,
            "Maximum Landing Weight": self.max_landing_weight_lb,
            "Maximum Zero Fuel Weight": self.max_zero_fuel_weight_lb,
        }
        for label, value in numeric_values.items():
            if value is not None and not value.is_finite():
                raise InvalidStationError(f"{label} must be finite")

        if self.basic_empty_weight_lb <= 0:
            raise InvalidStationError("Basic Empty Weight must be greater than zero")
        if self.max_takeoff_weight_lb <= 0:
            raise InvalidStationError("Maximum Takeoff Weight must be greater than zero")
        if self.max_takeoff_weight_lb < self.basic_empty_weight_lb:
            raise InvalidStationError("Maximum Takeoff Weight cannot be below Basic Empty Weight")
        for label, value in (
            ("Maximum Ramp Weight", self.max_ramp_weight_lb),
            ("Maximum Landing Weight", self.max_landing_weight_lb),
            ("Maximum Zero Fuel Weight", self.max_zero_fuel_weight_lb),
        ):
            if value is not None and value <= 0:
                raise InvalidStationError(f"{label} must be positive")
            if value is not None and value < self.basic_empty_weight_lb:
                raise InvalidStationError(f"{label} cannot be below Basic Empty Weight")
        if (
            self.max_ramp_weight_lb is not None
            and self.max_ramp_weight_lb < self.max_takeoff_weight_lb
        ):
            raise InvalidStationError(
                "Maximum Ramp Weight cannot be below Maximum Takeoff Weight"
            )

        ids = [station.station_id for station in self.stations]
        if len(ids) != len(set(ids)):
            raise InvalidStationError("Aircraft profile contains duplicate station ids")

    @property
    def basic_empty_cg_in(self) -> Decimal:
        return self.basic_empty_moment_lb_in / self.basic_empty_weight_lb

    def station(self, station_id: str) -> StationProfile:
        for station in self.stations:
            if station.station_id == station_id:
                return station
        raise InvalidStationError(f"Unknown station id '{station_id}'")

    @property
    def fuel_stations(self) -> list[StationProfile]:
        return [station for station in self.stations if station.station_type in FUEL_STATION_TYPES]

    @property
    def baggage_stations(self) -> list[StationProfile]:
        return [station for station in self.stations if station.station_type in BAGGAGE_STATION_TYPES]


@dataclass(frozen=True)
class LoadItemInput:
    """Non-fuel load at a station (occupants, baggage, or custom load)."""

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
        """Whether a complete landing fuel condition was supplied.

        With more than one tank, a burn entered for only one tank is not enough to calculate a
        truthful landing CG. Every configured fuel input must therefore have either an explicit
        landing/burn answer (including an intentional zero) or a positive burn value. This keeps
        a skipped tank from being silently treated as zero burn while another tank enables the
        landing calculation.
        """
        if not self.fuel:
            return False
        return all(
            fuel.landing_fuel_provided or fuel.enroute_burn_gal > 0
            for fuel in self.fuel
        )


@dataclass(frozen=True)
class StationLoadResult:
    station_id: str
    name: str
    weight_lb: Decimal
    arm_in: Decimal
    moment_lb_in: Decimal
    over_station_limit: bool
    over_capacity: bool = False


@dataclass(frozen=True)
class PhaseResult:
    phase: str
    total_weight_lb: Decimal
    weight_limit_lb: Decimal | None
    cg_in: Decimal
    cg_check: CGCheckResult | None
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
    zero_fuel_weight_lb: Decimal
    zero_fuel_limit_lb: Decimal | None
    zero_fuel_status: LimitStatus
    overall_status: LimitStatus
