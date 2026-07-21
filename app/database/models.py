from __future__ import annotations

import datetime
import enum
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


NUM = Numeric(14, 4)


class StationTypeEnum(str, enum.Enum):
    FRONT_SEATS = "FRONT_SEATS"
    REAR_SEATS = "REAR_SEATS"
    PASSENGER = "PASSENGER"
    BAGGAGE = "BAGGAGE"
    FUEL = "FUEL"
    CUSTOM = "CUSTOM"


class FuelInputModeEnum(str, enum.Enum):
    SINGLE_ARM = "SINGLE_ARM"
    UNKNOWN_SPLIT_RANGE = "UNKNOWN_SPLIT_RANGE"
    FIXED_ALLOCATION = "FIXED_ALLOCATION"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    selected_aircraft_id: Mapped[int | None] = mapped_column(
        ForeignKey("aircraft.id", use_alter=True, name="fk_selected_aircraft"), nullable=True
    )
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aircraft: Mapped[list["Aircraft"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="Aircraft.user_id"
    )


class Aircraft(Base):
    __tablename__ = "aircraft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tail_number: Mapped[str] = mapped_column(String(16), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    active_revision_id: Mapped[int | None] = mapped_column(
        ForeignKey("aircraft_revisions.id", use_alter=True, name="fk_active_revision"), nullable=True
    )
    is_temporary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="aircraft", foreign_keys=[user_id])
    revisions: Mapped[list["AircraftRevision"]] = relationship(
        back_populates="aircraft",
        cascade="all, delete-orphan",
        foreign_keys="AircraftRevision.aircraft_id",
    )
    active_revision: Mapped["AircraftRevision | None"] = relationship(
        foreign_keys=[active_revision_id], post_update=True
    )


class AircraftRevision(Base):
    __tablename__ = "aircraft_revisions"
    __table_args__ = (UniqueConstraint("aircraft_id", "revision_number", name="uq_aircraft_revision_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)

    basic_empty_weight_lb: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    basic_empty_moment_lb_in: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    basic_empty_cg_in: Mapped[Decimal] = mapped_column(NUM, nullable=False)

    max_ramp_weight_lb: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    max_takeoff_weight_lb: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    max_landing_weight_lb: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    max_zero_fuel_weight_lb: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    known_useful_load_lb: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)

    source_document_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_document_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    user_confirmation_timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aircraft: Mapped["Aircraft"] = relationship(back_populates="revisions", foreign_keys=[aircraft_id])
    stations: Mapped[list["Station"]] = relationship(
        back_populates="aircraft_revision",
        cascade="all, delete-orphan",
        order_by="Station.display_order",
    )
    envelope_rows: Mapped[list["CGEnvelopeRow"]] = relationship(
        back_populates="aircraft_revision", cascade="all, delete-orphan", order_by="CGEnvelopeRow.weight_lb"
    )
    fuel_systems: Mapped[list["FuelSystem"]] = relationship(
        back_populates="aircraft_revision", cascade="all, delete-orphan", order_by="FuelSystem.display_order"
    )


class FuelSystem(Base):
    """Groups one or more fuel-tank stations that share one 'total usable fuel' input.

    Additive to the existing Station model -- a FuelSystem doesn't replace Station rows, it
    just says how a group of FUEL-type stations should be treated when the pilot enters one
    total gallons number instead of per-tank amounts (see app.domain.fuel_allocation).
    """

    __tablename__ = "fuel_systems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_revision_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="Fuel")
    input_mode: Mapped[FuelInputModeEnum] = mapped_column(SAEnum(FuelInputModeEnum), nullable=False)
    usable_capacity_gal: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    total_physical_capacity_gal: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    fuel_density_lb_per_gal: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    aircraft_revision: Mapped["AircraftRevision"] = relationship(back_populates="fuel_systems")
    tanks: Mapped[list["FuelSystemTank"]] = relationship(
        back_populates="fuel_system", cascade="all, delete-orphan", order_by="FuelSystemTank.allocation_order"
    )


class FuelSystemTank(Base):
    __tablename__ = "fuel_system_tanks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fuel_system_id: Mapped[int] = mapped_column(
        ForeignKey("fuel_systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    station_id: Mapped[int] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    usable_capacity_gal: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    # Only meaningful for FIXED_ALLOCATION -- a confirmed, explicit fill order/quantity.
    allocation_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fixed_full_quantity_gal: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)

    fuel_system: Mapped["FuelSystem"] = relationship(back_populates="tanks")
    station: Mapped["Station"] = relationship()


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_revision_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    station_type: Mapped[StationTypeEnum] = mapped_column(SAEnum(StationTypeEnum), nullable=False)
    default_arm_in: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    is_adjustable_arm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    minimum_arm_in: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    maximum_arm_in: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    maximum_weight_lb: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    maximum_volume_gal: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    fuel_density_lb_per_gal: Mapped[Decimal | None] = mapped_column(NUM, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    aircraft_revision: Mapped["AircraftRevision"] = relationship(back_populates="stations")


class CGEnvelopeRow(Base):
    __tablename__ = "cg_envelope_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    aircraft_revision_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight_lb: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    forward_cg_limit_in: Mapped[Decimal] = mapped_column(NUM, nullable=False)
    aft_cg_limit_in: Mapped[Decimal] = mapped_column(NUM, nullable=False)

    aircraft_revision: Mapped["AircraftRevision"] = relationship(back_populates="envelope_rows")


class FlightCalculation(Base):
    __tablename__ = "flight_calculations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    aircraft_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft.id", ondelete="CASCADE"), nullable=False, index=True
    )
    aircraft_revision_id: Mapped[int] = mapped_column(
        ForeignKey("aircraft_revisions.id", ondelete="CASCADE"), nullable=False
    )
    calculation_engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
