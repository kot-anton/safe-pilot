"""Synthetic recommendation tests. Values are demonstration-only, not flight data."""
from decimal import Decimal as D

from app.domain.envelope import CGEnvelope, EnvelopeRow, LimitStatus
from app.domain.models import AircraftProfile, StationProfile, StationType
from app.domain.quick_calculation import run_quick_calculation
from app.domain.quick_recommendations import (
    QuickRecommendationKind,
    generate_quick_recommendations,
)


def _envelope(forward: str = "40", aft: str = "60") -> CGEnvelope:
    return CGEnvelope(
        [
            EnvelopeRow(D("1000"), D(forward), D(aft)),
            EnvelopeRow(D("2000"), D(forward), D(aft)),
        ]
    )


def test_quick_recommendation_adds_secured_baggage_for_forward_cg():
    profile = AircraftProfile(
        tail_number="N-ADD",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front",
                name="Front Seats",
                station_type=StationType.FRONT_SEATS,
                default_arm_in=D("20"),
            ),
            StationProfile(
                station_id="bag",
                name="Aft Baggage",
                station_type=StationType.BAGGAGE,
                default_arm_in=D("100"),
                maximum_weight_lb=D("300"),
            ),
        ],
        envelope=_envelope(),
    )

    initial = run_quick_calculation(
        profile, D("500"), D("0"), D("0"), D("0")
    )
    assert initial.overall_status == LimitStatus.OUT_OF_LIMITS

    recommendations = generate_quick_recommendations(
        profile,
        front_lb=D("500"),
        rear_lb=D("0"),
        baggage_lb=D("0"),
        total_fuel_gal=D("0"),
    )

    add = next(
        rec for rec in recommendations if rec.kind == QuickRecommendationKind.ADD_BAGGAGE
    )
    assert add.delta_lb == D("167")
    assert "secured" in add.describe().lower()
    assert add.note is not None

    fixed = run_quick_calculation(
        profile, D("500"), D("0"), add.target_baggage_lb, D("0")
    )
    assert fixed.overall_status != LimitStatus.OUT_OF_LIMITS


def test_quick_recommendation_removes_baggage_over_station_limit():
    profile = AircraftProfile(
        tail_number="N-REMOVE",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="bag",
                name="Baggage",
                station_type=StationType.BAGGAGE,
                default_arm_in=D("100"),
                maximum_weight_lb=D("200"),
            )
        ],
        envelope=_envelope(forward="35", aft="50"),
    )

    initial = run_quick_calculation(
        profile, D("0"), D("0"), D("300"), D("0")
    )
    assert initial.station_status == LimitStatus.OUT_OF_LIMITS

    recommendations = generate_quick_recommendations(
        profile,
        front_lb=D("0"),
        rear_lb=D("0"),
        baggage_lb=D("300"),
        total_fuel_gal=D("0"),
    )
    removal = next(
        rec
        for rec in recommendations
        if rec.kind == QuickRecommendationKind.REDUCE_BAGGAGE
    )
    assert removal.delta_lb == D("100")
    assert removal.target_baggage_lb == D("200")

    fixed = run_quick_calculation(
        profile, D("0"), D("0"), removal.target_baggage_lb, D("0")
    )
    assert fixed.overall_status != LimitStatus.OUT_OF_LIMITS


def test_quick_recommendation_reduces_fuel_and_never_reseats_passengers():
    profile = AircraftProfile(
        tail_number="N-FUEL",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("50000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front",
                name="Front Seats",
                station_type=StationType.FRONT_SEATS,
                default_arm_in=D("30"),
            ),
            StationProfile(
                station_id="fuel",
                name="Main Fuel",
                station_type=StationType.FUEL,
                default_arm_in=D("20"),
                maximum_volume_gal=D("20"),
                fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=_envelope(forward="45", aft="60"),
    )

    recommendations = generate_quick_recommendations(
        profile,
        front_lb=D("300"),
        rear_lb=D("0"),
        baggage_lb=D("0"),
        total_fuel_gal=D("20"),
    )

    assert {rec.kind for rec in recommendations} <= {
        QuickRecommendationKind.ADD_BAGGAGE,
        QuickRecommendationKind.REDUCE_BAGGAGE,
        QuickRecommendationKind.REDUCE_FUEL,
    }
    fuel = next(
        rec for rec in recommendations if rec.kind == QuickRecommendationKind.REDUCE_FUEL
    )
    assert fuel.target_total_fuel_gal is not None
    assert fuel.note is not None
    fixed = run_quick_calculation(
        profile, D("300"), D("0"), D("0"), fuel.target_total_fuel_gal
    )
    assert fixed.overall_status != LimitStatus.OUT_OF_LIMITS


def test_quick_add_baggage_is_disabled_when_compartment_limit_unknown():
    profile = AircraftProfile(
        tail_number="N-NOMAX",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front",
                name="Front Seats",
                station_type=StationType.FRONT_SEATS,
                default_arm_in=D("20"),
            ),
            StationProfile(
                station_id="bag",
                name="Baggage",
                station_type=StationType.BAGGAGE,
                default_arm_in=D("100"),
                maximum_weight_lb=None,
            ),
        ],
        envelope=_envelope(),
    )

    recommendations = generate_quick_recommendations(
        profile,
        front_lb=D("500"),
        rear_lb=D("0"),
        baggage_lb=D("0"),
        total_fuel_gal=D("0"),
    )
    assert not any(
        rec.kind == QuickRecommendationKind.ADD_BAGGAGE
        for rec in recommendations
    )
