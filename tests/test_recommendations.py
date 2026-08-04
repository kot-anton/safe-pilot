from decimal import Decimal as D

from app.domain.calculator import calculate
from app.domain.envelope import LimitStatus
from app.domain.models import CalculationInput, FuelStationInput, LoadItemInput
from app.domain.recommendations import Recommendation, RecommendationKind, generate_recommendations
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

    # max_results is raised here because the new fuel+load combination search (Task 5) can
    # surface gentler COMBINATION recommendations that legitimately outrank a standalone
    # REDUCE_FUEL within the default cutoff -- this test verifies the standalone recommendation
    # itself is still found and well-formed, not that it wins the default top-N ranking.
    recs = generate_recommendations(profile, calc_input, max_results=10)
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

    # The recommendation should state a concrete tank reading the pilot can act on (a fuel
    # gauge/tab level), not just an abstract delta.
    assert rec.resulting_gal is not None
    assert rec.tank_capacity_gal is not None
    assert "Target level" in rec.describe()


def test_add_fuel_recommendation_flags_full_tank_target():
    rec = Recommendation(
        kind=RecommendationKind.ADD_FUEL,
        station_id="main_fuel",
        station_name="Main Fuel",
        delta_lb=D("60"),
        delta_gal=D("10"),
        resulting_gal=D("40"),
        tank_capacity_gal=D("40"),
    )
    assert "full" in rec.describe().lower()
    assert "40 gal" in rec.describe()


def test_add_fuel_recommendation_states_target_level_when_not_full():
    rec = Recommendation(
        kind=RecommendationKind.ADD_FUEL,
        station_id="main_fuel",
        station_name="Main Fuel",
        delta_lb=D("60"),
        delta_gal=D("10"),
        resulting_gal=D("30"),
        tank_capacity_gal=D("40"),
    )
    assert "full" not in rec.describe().lower()
    assert "Target level: 30 gal" in rec.describe()


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
                default_arm_in=D("150.0"),
            ),
            StationProfile(
                station_id="baggage_fwd", name="Forward Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("20.0"),
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


def test_recommendation_suggests_moving_weight_between_front_and_rear_seats():
    """Front<->Rear seat moves are suggested generically ("Move X lb from Front Seats to Rear
    Seats") -- deliberately without naming who moves, since the app cannot know who is sitting
    where. This is an explicit product decision by the aircraft owner: some pilots always fly
    solo with a fixed, known loading, so the suggestion is theirs to accept or ignore."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N77777",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("50000"),  # cg 50.0
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front", name="Front Seats", station_type=StationType.FRONT_SEATS,
                default_arm_in=D("30"),
            ),
            StationProfile(
                station_id="rear", name="Rear Seats", station_type=StationType.REAR_SEATS,
                default_arm_in=D("70"),
            ),
            StationProfile(
                station_id="fuel", name="Fuel", station_type=StationType.FUEL,
                default_arm_in=D("50"), maximum_volume_gal=D("30"), fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=CGEnvelope([EnvelopeRow(D("1200"), D("45"), D("55")), EnvelopeRow(D("1600"), D("45"), D("55"))]),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("500")),
            LoadItemInput(station_id="rear", weight_lb=D("0")),
        ],
        fuel=[FuelStationInput(station_id="fuel", starting_gal=D("10"))],
    )
    result = calculate(profile, calc_input)
    assert result.ramp.cg_check.status == LimitStatus.OUT_OF_LIMITS  # forward of limit

    recs = generate_recommendations(profile, calc_input)
    move_recs = [r for r in recs if r.kind == RecommendationKind.MOVE_LOAD]
    front_to_rear = [
        r for r in move_recs if r.station_id == "front" and r.target_station_id == "rear"
    ]
    assert front_to_rear, "expected a Front Seats -> Rear Seats move suggestion"
    assert front_to_rear[0].describe() == "Move 55 lb (24.9 kg) from Front Seats to Rear Seats."


def test_recommendation_does_not_move_ambiguous_custom_load():
    """CUSTOM may mean installed equipment or another fixed item; only explicit BAGGAGE is
    treated as movable cargo by the automatic solver."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N-CUSTOM",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="custom_aft",
                name="Equipment Box",
                station_type=StationType.CUSTOM,
                default_arm_in=D("150"),
            ),
            StationProfile(
                station_id="baggage_forward",
                name="Forward Baggage",
                station_type=StationType.BAGGAGE,
                default_arm_in=D("20"),
            ),
        ],
        envelope=CGEnvelope(
            [
                EnvelopeRow(D("1000"), D("30"), D("55")),
                EnvelopeRow(D("1600"), D("30"), D("55")),
            ]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="custom_aft", weight_lb=D("250")),
            LoadItemInput(station_id="baggage_forward", weight_lb=D("0")),
        ],
        fuel=[],
    )

    recs = generate_recommendations(profile, calc_input)

    assert not any(
        rec.kind == RecommendationKind.MOVE_LOAD
        and rec.station_id == "custom_aft"
        for rec in recs
    )


def test_recommendation_shifts_fuel_between_tanks_to_fix_forward_cg():
    """A forward-CG problem can sometimes be fixed by moving fuel from a forward tank to an
    aft tank, leaving total fuel (and total weight) unchanged. This is opt-in because many
    aircraft do not permit a pilot-controlled tank-to-tank transfer."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N88888",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("50000"),  # cg 50.0
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front", name="Front Seats", station_type=StationType.FRONT_SEATS,
                default_arm_in=D("30"),
            ),
            StationProfile(
                station_id="main", name="Main Fuel", station_type=StationType.FUEL,
                default_arm_in=D("20"), maximum_volume_gal=D("20"), fuel_density_lb_per_gal=D("6"),
            ),
            StationProfile(
                station_id="aux", name="Aux Fuel", station_type=StationType.FUEL,
                default_arm_in=D("80"), maximum_volume_gal=D("30"), fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=CGEnvelope([EnvelopeRow(D("1200"), D("45"), D("55")), EnvelopeRow(D("2000"), D("45"), D("55"))]),
    )
    calc_input = CalculationInput(
        loads=[LoadItemInput(station_id="front", weight_lb=D("500"))],
        fuel=[
            FuelStationInput(station_id="main", starting_gal=D("20")),
            FuelStationInput(station_id="aux", starting_gal=D("0")),
        ],
    )
    result = calculate(profile, calc_input)
    assert result.ramp.cg_check.status == LimitStatus.OUT_OF_LIMITS  # forward of limit

    recs = generate_recommendations(
        profile, calc_input, allow_fuel_transfer=True
    )
    shift_recs = [r for r in recs if r.kind == RecommendationKind.SHIFT_FUEL]
    assert shift_recs, "expected at least one fuel-shift recommendation"
    rec = shift_recs[0]
    assert rec.station_id == "main"
    assert rec.target_station_id == "aux"

    fixed_input = CalculationInput(
        loads=calc_input.loads,
        fuel=[
            FuelStationInput(station_id="main", starting_gal=D("20") - rec.delta_gal),
            FuelStationInput(station_id="aux", starting_gal=rec.delta_gal),
        ],
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS
    # Total fuel on board -- and therefore total weight -- must be unchanged by a shift.
    assert fixed_result.ramp.total_weight_lb == result.ramp.total_weight_lb


def test_recommendations_preserve_category_priority_over_raw_delta():
    """A tiny fuel-only fix must not outrank a load-move recommendation just because its
    delta is numerically smaller -- category order comes first."""
    from app.domain.recommendations import Recommendation, RecommendationKind, _CATEGORY_PRIORITY

    move = Recommendation(kind=RecommendationKind.MOVE_LOAD, station_id="a", station_name="A", delta_lb=D("50"))
    fuel = Recommendation(kind=RecommendationKind.REDUCE_FUEL, station_id="b", station_name="B", delta_lb=D("1"))
    candidates = [fuel, move]
    candidates.sort(key=lambda r: (_CATEGORY_PRIORITY[r.kind], r.delta_lb))
    assert candidates[0] is move


def test_category_priority_puts_reduce_fuel_last():
    """Removing fuel reduces a flight's safety margin, so it must be the least-preferred
    single-category fix -- ranked below every other adjustment, including adding fuel."""
    from app.domain.recommendations import _CATEGORY_PRIORITY, RecommendationKind

    order = [
        RecommendationKind.MOVE_LOAD,
        RecommendationKind.REDUCE_BAGGAGE,
        RecommendationKind.ADD_BAGGAGE,
        RecommendationKind.SHIFT_FUEL,
        RecommendationKind.ADD_FUEL,
        RecommendationKind.REDUCE_FUEL,
    ]
    priorities = [_CATEGORY_PRIORITY[kind] for kind in order]
    assert priorities == sorted(priorities), (
        f"expected strictly increasing priority in this order, got {priorities}"
    )


def test_reduce_seat_load_fixes_overweight_with_default_front_floor():
    """Default floor (170 lb) doesn't block the fix in this scenario: the minimal working
    reduction lands well above it (front seat drops from 400 lb to 290 lb)."""
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
    front_recs = [
        r for r in recs
        if r.kind == RecommendationKind.REDUCE_SEAT_LOAD and r.station_id == "front_seats"
    ]
    assert front_recs, "expected a Front Seats reduce-load recommendation"
    rec = front_recs[0]
    assert rec.delta_lb == D("110")

    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front_seats", weight_lb=D("400") - rec.delta_lb),
            LoadItemInput(station_id="rear_seats", weight_lb=D("400")),
            LoadItemInput(station_id="baggage_1", weight_lb=D("0")),
        ],
        fuel=calc_input.fuel,
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS
    assert "Remove" in rec.describe()


def test_reduce_seat_load_never_proposes_below_front_floor(monkeypatch):
    """If the configured floor exceeds what a fix would require, no Front Seats suggestion is
    made at all -- the search must never suggest a target below the floor. Other categories
    (e.g. Reduce Fuel) still cover the pilot in that case."""
    from app.config import settings

    monkeypatch.setattr(settings, "min_front_seat_weight_lb", 350.0)
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
    recs = generate_recommendations(profile, calc_input)
    front_recs = [
        r for r in recs
        if r.kind == RecommendationKind.REDUCE_SEAT_LOAD and r.station_id == "front_seats"
    ]
    assert not front_recs, "fixing this overweight condition requires going below the floor"
    assert recs, "the pilot must still see other recommendations (e.g. Reduce Fuel)"


def test_reduce_seat_load_allows_rear_seat_below_front_floor():
    """Rear Seats has no minimum -- it can be recommended down to a level that would be
    disallowed for Front Seats, proving the floor is asymmetric and per-station-type."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N-SEAT",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("50000"),  # cg 50.0
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front", name="Front Seats", station_type=StationType.FRONT_SEATS,
                default_arm_in=D("30"),
            ),
            StationProfile(
                station_id="rear", name="Rear Seats", station_type=StationType.REAR_SEATS,
                default_arm_in=D("150"),
            ),
        ],
        envelope=CGEnvelope(
            [EnvelopeRow(D("1200"), D("40"), D("55")), EnvelopeRow(D("1600"), D("40"), D("55"))]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("170")),
            LoadItemInput(station_id="rear", weight_lb=D("300")),
        ],
        fuel=[],
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS  # too far aft

    recs = generate_recommendations(profile, calc_input)
    rear_recs = [
        r for r in recs if r.kind == RecommendationKind.REDUCE_SEAT_LOAD and r.station_id == "rear"
    ]
    assert rear_recs, "expected a Rear Seats reduce-load recommendation"
    rec = rear_recs[0]
    assert rec.delta_lb == D("203")
    remaining = D("300") - rec.delta_lb
    assert remaining == D("97")  # below the 170 lb Front Seats floor -- proves no floor on Rear

    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("170")),
            LoadItemInput(station_id="rear", weight_lb=remaining),
        ],
        fuel=[],
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS


def test_move_load_allows_rear_seats_to_baggage():
    """Rear Seats and Baggage can now trade weight directly (e.g. a loose item relocated from
    the rear seat area to the baggage compartment) -- previously these were disjoint groups."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N-RB",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="rear", name="Rear Seats", station_type=StationType.REAR_SEATS,
                default_arm_in=D("80"),
            ),
            StationProfile(
                station_id="bag", name="Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("20"),
            ),
        ],
        envelope=CGEnvelope(
            [EnvelopeRow(D("1200"), D("35"), D("45")), EnvelopeRow(D("1600"), D("35"), D("45"))]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="rear", weight_lb=D("300")),
            LoadItemInput(station_id="bag", weight_lb=D("0")),
        ],
        fuel=[],
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS  # too far aft

    recs = generate_recommendations(profile, calc_input)
    move_recs = [
        r for r in recs
        if r.kind == RecommendationKind.MOVE_LOAD
        and r.station_id == "rear" and r.target_station_id == "bag"
    ]
    assert move_recs, "expected a Rear Seats -> Baggage move suggestion"
    rec = move_recs[0]
    assert rec.delta_lb == D("92")

    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="rear", weight_lb=D("300") - rec.delta_lb),
            LoadItemInput(station_id="bag", weight_lb=rec.delta_lb),
        ],
        fuel=[],
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS


def test_move_load_still_excludes_front_seats_from_baggage():
    """Front Seats never trades weight with Baggage -- there's normally no loose cargo at a
    front seat position, and a person's own bodyweight isn't something to 'move' to cargo."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N-FB",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("40000"),
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front", name="Front Seats", station_type=StationType.FRONT_SEATS,
                default_arm_in=D("80"),
            ),
            StationProfile(
                station_id="bag", name="Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("20"),
            ),
        ],
        envelope=CGEnvelope(
            [EnvelopeRow(D("1200"), D("35"), D("45")), EnvelopeRow(D("1600"), D("35"), D("45"))]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("300")),
            LoadItemInput(station_id="bag", weight_lb=D("0")),
        ],
        fuel=[],
    )
    recs = generate_recommendations(profile, calc_input)
    assert not any(
        r.kind == RecommendationKind.MOVE_LOAD
        and {r.station_id, r.target_station_id} == {"front", "bag"}
        for r in recs
    )


def test_combination_recommendation_found_when_no_single_fix_is_gentler():
    """A forward-CG problem where both Add Baggage alone (250 lb) and Add Fuel alone (41.7 gal)
    can fix it independently -- but a combination using less of each is also possible and must
    be offered as an extra option."""
    from app.domain.envelope import CGEnvelope, EnvelopeRow
    from app.domain.models import AircraftProfile, StationProfile, StationType

    profile = AircraftProfile(
        tail_number="N-COMBO",
        revision_number=1,
        basic_empty_weight_lb=D("1000"),
        basic_empty_moment_lb_in=D("30000"),  # cg 30.0
        max_takeoff_weight_lb=D("2000"),
        stations=[
            StationProfile(
                station_id="front", name="Front Seats", station_type=StationType.FRONT_SEATS,
                default_arm_in=D("10"),
            ),
            StationProfile(
                station_id="bag", name="Baggage", station_type=StationType.BAGGAGE,
                default_arm_in=D("100"),
            ),
            StationProfile(
                station_id="fuel", name="Main Fuel", station_type=StationType.FUEL,
                default_arm_in=D("100"), maximum_volume_gal=D("60"), fuel_density_lb_per_gal=D("6"),
            ),
        ],
        envelope=CGEnvelope(
            [EnvelopeRow(D("1200"), D("35"), D("50")), EnvelopeRow(D("1800"), D("35"), D("50"))]
        ),
    )
    calc_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("450")),
            LoadItemInput(station_id="bag", weight_lb=D("0")),
        ],
        fuel=[FuelStationInput(station_id="fuel", starting_gal=D("0"))],
    )
    result = calculate(profile, calc_input)
    assert result.overall_status == LimitStatus.OUT_OF_LIMITS  # too far forward

    recs = generate_recommendations(profile, calc_input, allow_add_fuel=True, max_results=10)
    combos = [r for r in recs if r.kind == RecommendationKind.COMBINATION]
    assert combos, "expected at least one combination recommendation"

    combo = combos[0]
    assert combo.legs is not None and len(combo.legs) == 2
    fuel_leg, load_leg = combo.legs
    assert fuel_leg.kind == RecommendationKind.ADD_FUEL
    assert load_leg.kind == RecommendationKind.ADD_BAGGAGE
    # Must be gentler than at least one of the two "alone" fixes (250 lb baggage / 41.7 gal fuel).
    assert load_leg.delta_lb < D("250") or fuel_leg.delta_gal < D("41.7")

    fixed_input = CalculationInput(
        loads=[
            LoadItemInput(station_id="front", weight_lb=D("450")),
            LoadItemInput(station_id="bag", weight_lb=load_leg.delta_lb),
        ],
        fuel=[FuelStationInput(station_id="fuel", starting_gal=fuel_leg.delta_gal)],
    )
    fixed_result = calculate(profile, fixed_input)
    assert fixed_result.overall_status != LimitStatus.OUT_OF_LIMITS
    assert " AND " in combo.describe()


def test_combination_priority_matches_its_fuel_side_leg():
    """A combination's priority tier must come from its fuel-side leg -- an Add-Fuel combo
    outranks a Reduce-Fuel combo, same fuel-safety bias as standalone recommendations."""
    from app.domain.recommendations import _CATEGORY_PRIORITY

    add_fuel_leg = Recommendation(
        kind=RecommendationKind.ADD_FUEL, station_id="f", station_name="F",
        delta_lb=D("30"), delta_gal=D("5"),
    )
    reduce_fuel_leg = Recommendation(
        kind=RecommendationKind.REDUCE_FUEL, station_id="f", station_name="F",
        delta_lb=D("30"), delta_gal=D("5"),
    )
    baggage_leg = Recommendation(
        kind=RecommendationKind.ADD_BAGGAGE, station_id="b", station_name="B", delta_lb=D("10"),
    )
    add_fuel_combo = Recommendation(
        kind=RecommendationKind.COMBINATION, station_id="f", station_name="F",
        legs=(add_fuel_leg, baggage_leg),
    )
    reduce_fuel_combo = Recommendation(
        kind=RecommendationKind.COMBINATION, station_id="f", station_name="F",
        legs=(reduce_fuel_leg, baggage_leg),
    )
    candidates = [reduce_fuel_combo, add_fuel_combo]
    from app.domain.recommendations import _combination_priority

    candidates.sort(key=_combination_priority)
    assert candidates[0] is add_fuel_combo


def test_generate_recommendations_default_max_results_is_four():
    import inspect

    from app.domain.recommendations import generate_recommendations

    signature = inspect.signature(generate_recommendations)
    assert signature.parameters["max_results"].default == 4
