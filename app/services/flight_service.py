from __future__ import annotations

import dataclasses
import json
from decimal import Decimal

from app.database.models import Aircraft, AircraftRevision
from app.domain.calculator import ENGINE_VERSION, calculate
from app.domain.models import AircraftProfile, CalculationInput, CalculationResult
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
    return json.dumps(obj, cls=_DecimalEncoder, default=lambda o: str(o))


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
        min_fuel_gal: dict[str, Decimal] | None,
        allow_added_ballast_recommendations: bool,
    ) -> list[Recommendation]:
        return generate_recommendations(
            profile,
            calc_input,
            min_fuel_gal=min_fuel_gal,
            allow_added_ballast_recommendations=allow_added_ballast_recommendations,
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

    async def list_history(self, user_id: int, aircraft_id: int | None = None, limit: int = 10):
        return await self.repo.list_for_user(user_id, aircraft_id, limit)
