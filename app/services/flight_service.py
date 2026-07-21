from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

from app.database.models import Aircraft, AircraftRevision
from app.domain.calculator import ENGINE_VERSION, calculate
from app.domain.models import AircraftProfile, CalculationInput, CalculationResult
from app.domain.quick_recommendations import QuickRecommendation, generate_quick_recommendations
from app.domain.recommendations import Recommendation, generate_recommendations
from app.repositories.flight_repository import FlightRepository
from app.services.aircraft_service import build_domain_profile


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        if dataclasses.is_dataclass(o) and not isinstance(o, type):
            return dataclasses.asdict(o)
        return super().default(o)


def _snapshot(obj) -> str:
    # Do not pass a second ``default=`` callback here: json.JSONEncoder would replace the
    # custom encoder's ``default`` method, turning dataclasses into opaque strings and breaking
    # history/replay. _DecimalEncoder keeps snapshots as structured JSON.
    return json.dumps(obj, cls=_DecimalEncoder)


class FlightService:
    def __init__(self, repo: FlightRepository):
        self.repo = repo

    def build_profile(self, revision: AircraftRevision, aircraft: Aircraft) -> AircraftProfile:
        return build_domain_profile(revision, aircraft)

    def run_calculation(self, profile: AircraftProfile, calc_input: CalculationInput) -> CalculationResult:
        return calculate(profile, calc_input)

    def recommend(
        self,
        profile: AircraftProfile,
        calc_input: CalculationInput,
        min_fuel_gal: dict[str, Decimal] | None = None,
    ) -> list[Recommendation]:
        return generate_recommendations(profile, calc_input, min_fuel_gal=min_fuel_gal)

    def recommend_quick(
        self,
        profile: AircraftProfile,
        *,
        front_lb: Decimal,
        rear_lb: Decimal,
        baggage_lb: Decimal,
        total_fuel_gal: Decimal,
    ) -> list[QuickRecommendation]:
        return generate_quick_recommendations(
            profile,
            front_lb=front_lb,
            rear_lb=rear_lb,
            baggage_lb=baggage_lb,
            total_fuel_gal=total_fuel_gal,
        )

    async def persist_calculation(
        self,
        *,
        user_id: int,
        aircraft_id: int,
        aircraft_revision_id: int,
        calc_input: CalculationInput,
        result: CalculationResult,
    ):
        return await self.repo.save_calculation(
            user_id=user_id,
            aircraft_id=aircraft_id,
            aircraft_revision_id=aircraft_revision_id,
            engine_version=ENGINE_VERSION,
            input_snapshot_json=_snapshot(calc_input),
            result_snapshot_json=_snapshot(result),
        )

    async def persist_quick_calculation(
        self,
        *,
        user_id: int,
        aircraft_id: int,
        aircraft_revision_id: int,
        quick_input: dict,
        result,
    ):
        """Same storage as the full calculator (FlightCalculation is engine-agnostic), used
        by the quick 4-question flow. `quick_input` is a plain dict of front/rear/baggage/fuel
        values, kept engine-independent for history and replay."""
        return await self.repo.save_calculation(
            user_id=user_id,
            aircraft_id=aircraft_id,
            aircraft_revision_id=aircraft_revision_id,
            engine_version=f"{ENGINE_VERSION}-quick",
            input_snapshot_json=_snapshot(quick_input),
            result_snapshot_json=_snapshot(result),
        )

    async def list_history(self, user_id: int, aircraft_id: int | None = None, limit: int = 10):
        return await self.repo.list_for_user(user_id, aircraft_id, limit)
