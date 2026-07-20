from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import FlightCalculation


class FlightRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_calculation(
        self,
        *,
        user_id: int,
        aircraft_id: int,
        aircraft_revision_id: int,
        engine_version: str,
        input_snapshot_json: str,
        result_snapshot_json: str,
    ) -> FlightCalculation:
        record = FlightCalculation(
            user_id=user_id,
            aircraft_id=aircraft_id,
            aircraft_revision_id=aircraft_revision_id,
            calculation_engine_version=engine_version,
            input_snapshot_json=input_snapshot_json,
            result_snapshot_json=result_snapshot_json,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_for_user(
        self, user_id: int, aircraft_id: int | None = None, limit: int = 10
    ) -> list[FlightCalculation]:
        stmt = select(FlightCalculation).where(FlightCalculation.user_id == user_id)
        if aircraft_id is not None:
            stmt = stmt.where(FlightCalculation.aircraft_id == aircraft_id)
        stmt = stmt.order_by(FlightCalculation.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(self, user_id: int, calculation_id: int) -> FlightCalculation | None:
        result = await self.session.execute(
            select(FlightCalculation).where(
                FlightCalculation.id == calculation_id, FlightCalculation.user_id == user_id
            )
        )
        return result.scalar_one_or_none()
