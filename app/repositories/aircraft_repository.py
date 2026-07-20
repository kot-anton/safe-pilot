"""All queries here are strictly scoped by the owning User -- an aircraft or revision that
does not belong to the requesting Telegram user is treated as not found, never as a 403."""
from __future__ import annotations

import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Aircraft, AircraftRevision, CGEnvelopeRow, Station, User


class AircraftRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_or_create_user(self, telegram_user_id: int, language: str = "en") -> User:
        result = await self.session.execute(select(User).where(User.telegram_user_id == telegram_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_user_id=telegram_user_id, language=language)
            self.session.add(user)
            await self.session.flush()
        return user

    async def list_aircraft(self, user_id: int, include_archived: bool = False) -> list[Aircraft]:
        stmt = select(Aircraft).where(Aircraft.user_id == user_id).options(
            selectinload(Aircraft.active_revision)
        )
        if not include_archived:
            stmt = stmt.where(Aircraft.archived_at.is_(None))
        result = await self.session.execute(stmt.order_by(Aircraft.created_at))
        return list(result.scalars().all())

    async def get_aircraft(self, user_id: int, aircraft_id: int) -> Aircraft | None:
        result = await self.session.execute(
            select(Aircraft)
            .where(Aircraft.id == aircraft_id, Aircraft.user_id == user_id)
            .options(selectinload(Aircraft.active_revision))
        )
        return result.scalar_one_or_none()

    async def get_revision(self, user_id: int, revision_id: int) -> AircraftRevision | None:
        stmt = (
            select(AircraftRevision)
            .join(Aircraft, Aircraft.id == AircraftRevision.aircraft_id)
            .where(AircraftRevision.id == revision_id, Aircraft.user_id == user_id)
            .options(
                selectinload(AircraftRevision.stations),
                selectinload(AircraftRevision.envelope_rows),
                selectinload(AircraftRevision.aircraft),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_aircraft(
        self,
        user_id: int,
        tail_number: str,
        model: str,
        nickname: str | None,
        manufacturer: str | None,
        is_temporary: bool = False,
    ) -> Aircraft:
        aircraft = Aircraft(
            user_id=user_id,
            tail_number=tail_number,
            model=model,
            nickname=nickname,
            manufacturer=manufacturer,
            is_temporary=is_temporary,
        )
        self.session.add(aircraft)
        await self.session.flush()
        return aircraft

    async def next_revision_number(self, aircraft_id: int) -> int:
        result = await self.session.execute(
            select(AircraftRevision.revision_number)
            .where(AircraftRevision.aircraft_id == aircraft_id)
            .order_by(AircraftRevision.revision_number.desc())
        )
        last = result.scalars().first()
        return (last or 0) + 1

    async def add_revision(
        self,
        aircraft: Aircraft,
        *,
        basic_empty_weight_lb: Decimal,
        basic_empty_moment_lb_in: Decimal,
        basic_empty_cg_in: Decimal,
        max_ramp_weight_lb: Decimal | None,
        max_takeoff_weight_lb: Decimal,
        max_landing_weight_lb: Decimal | None,
        max_zero_fuel_weight_lb: Decimal | None,
        known_useful_load_lb: Decimal | None,
        source_document_name: str | None,
        source_document_date: datetime.date | None,
        notes: str | None,
        stations: list[dict],
        envelope_rows: list[dict],
    ) -> AircraftRevision:
        revision_number = await self.next_revision_number(aircraft.id)
        revision = AircraftRevision(
            aircraft_id=aircraft.id,
            revision_number=revision_number,
            basic_empty_weight_lb=basic_empty_weight_lb,
            basic_empty_moment_lb_in=basic_empty_moment_lb_in,
            basic_empty_cg_in=basic_empty_cg_in,
            max_ramp_weight_lb=max_ramp_weight_lb,
            max_takeoff_weight_lb=max_takeoff_weight_lb,
            max_landing_weight_lb=max_landing_weight_lb,
            max_zero_fuel_weight_lb=max_zero_fuel_weight_lb,
            known_useful_load_lb=known_useful_load_lb,
            source_document_name=source_document_name,
            source_document_date=source_document_date,
            notes=notes,
        )
        self.session.add(revision)
        await self.session.flush()

        for order, s in enumerate(stations):
            self.session.add(Station(aircraft_revision_id=revision.id, display_order=order, **s))

        for row in envelope_rows:
            self.session.add(CGEnvelopeRow(aircraft_revision_id=revision.id, **row))

        await self.session.flush()

        aircraft.active_revision_id = revision.id
        await self.session.flush()
        return revision

    async def archive_aircraft(self, aircraft: Aircraft) -> None:
        aircraft.archived_at = datetime.datetime.now(datetime.timezone.utc)
        await self.session.flush()

    async def set_selected_aircraft(self, user: User, aircraft_id: int | None) -> None:
        user.selected_aircraft_id = aircraft_id
        await self.session.flush()

    async def set_selected_aircraft_id(self, user_id: int, aircraft_id: int | None) -> None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()
        user.selected_aircraft_id = aircraft_id
        await self.session.flush()
