from decimal import Decimal as D

from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput
from app.domain.recommendations import RecommendationKind, generate_recommendations
from tests.conftest import make_test_profile


def test_recommendation_reduces_fuel_for_overweight():
    profile = make_test_profile()
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("400")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("400")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("0")),
        ],
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("40")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("20")),
        ],
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS

    recs = generate_recommendations(profile, calc_input)
    fuel_recs = [r for r in recs if r.kind == RecommendationKind.REDUCE_FUEL]
    assert fuel_recs, "expected at least one fuel-reduction recommendation"

    # Verify the recommendation actually resolves the violation when applied.
    rec = fuel_recs[0]
    new_gal = D("40") - rec.delta_gal if rec.station_id == "main_fuel" else D("40")
    new_aux_gal = D("20") - rec.delta_gal if rec.station_id == "aux_fuel" else D("20")
    fixed_input = CalculationInput(
        loads=calc_input.loads,
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=new_gal),
            FuelStationInput(station_id="aux_fuel", starting_gal=new_aux_gal),
        ],
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS


def test_recommendation_reduces_baggage_for_overweight():
    profile = make_test_profile()
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("500")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("500")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("120")),
        ],
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("0")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ],
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS

    recs = generate_recommendations(profile, calc_input)
    baggage_recs = [r for r in recs if r.kind == RecommendationKind.REDUCE_BAGGAGE]
    assert baggage_recs
    assert baggage_recs[0].station_id == "baggage_1"

    rec = baggage_recs[0]
    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("500")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("500")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("120") - rec.delta_lb),
        ],
        fuel=calc_input.fuel,
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS


def test_recommendation_moves_load_between_stations():
    # Dedicated synthetic (demonstration-only) aircraft designed so that an aft baggage
    # station alone can push CG well past the aft limit, and moving that weight forward
    # to a second baggage station brings it back within the envelope.
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    aft_profile = AircraftProfile(
        tail_number="N99999",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("30000"),  # cg 30.0
        max_takeoff_weight_lb=D("2000"),
        max_ramp_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="baggage_aft", name="Aft Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("150.0"), maximum_weight_lb=D("300"),
            ),
            StationProfile(
                station_id="baggage_fwd", name="Forward Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("20.0"), maximum_weight_lb=D("300"),
            ),
            StationProfile(
                station_id="main_fuel", name="Main Fuel", station_type=StationType.FUEL,
                default_arm_in=D("40.0"), maximum_volume_gal=D("50"), fuel_density_lb_per_gal=D("6.0"),
            ),
        ],
        envelope=CGEnvelope(
            [
                EnvelopeRow(D("1200"), D("28.0"), D("45.0")),
                EnvelopeRow(D("1500"), D("30.0"), D("45.0")),
            ]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="baggage_aft", weight_lb=D("300")),
            LoadItemInput(station_id="baggage_fwd", weight_lb=D("0")),
        ],
        fuel=[FuelStationInput(station_id="main_fuel", starting_gal=D("10"))],
    )
    result = calculate(aft_profile, calc_input)
    assert result.ramp.cg_check.status == LimitStatus.OUT_OF_LIMITS  # too far aft

    recs = generate_recommendations(aft_profile, calc_input)
    move_recs = [r for r in recs if r.kind == RecommendationKind.MOVE_LOAD]
    assert move_recs
    assert move_recs[0].station_id == "baggage_aft"
    assert move_recs[0].target_station_id == "baggage_fwd"

    rec = move_recs[0]
    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="baggage_aft", weight_lb=D("300") - rec.delta_lb),
            LoadItemInput(station_id="baggage_fwd", weight_lb=rec.delta_lb),
        ],
        fuel=calc_input.fuel,
    )
    fixed_result = calculate(aft_profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS


def test_recommendation_never_reduces_fuel_below_pilot_minimum():
    profile = make_test_profile()
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("340")),
            LoadItemInput(station_id="rear_seats", weight_lb=D("340")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("0")),
        ],
        fuel=[
            FuelStationInput(station_id="main_fuel", starting_gal=D("40")),
            FuelStationInput(station_id="aux_fuel", starting_gal=D("0")),
        ],
    )
    # Pilot requires at least 39.9 gal in main tank (essentially no room to reduce fuel there).
    recs = generate_recommendations(
        profile, calc_input, min_fuel_gal={"main_fuel": D("39.9")}
    )
    fuel_recs = [r for r in recs if r.kind == "REDUCE_FUEL" and r.station_id == "main_fuel"]
    for rec in fuel_recs:
        remaining = D("40") - rec.delta_gal
        assert remaining >= D("39.9")
