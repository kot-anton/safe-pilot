# Recommendation Engine Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Advanced/Full Calculation recommendation solver (`app/domain/recommendations.py`) with a fuel-safety priority bias, a new "reduce seat load" suggestion, rear-seat/baggage cross-group moves, and new fuel+load combination suggestions.

**Architecture:** All changes are confined to `app/domain/recommendations.py` (the solver), `app/config.py` (one new setting), and `tests/test_recommendations.py` (new/updated tests). No database, bot handler, or i18n changes — the bot already renders whatever `Recommendation.describe()` returns.

**Tech Stack:** Python, dataclasses, Decimal, pytest. Existing conventions: brute-force step search verified by re-running the real `calculate()` engine on every candidate (never approximated).

**Test runner:** this repo's virtualenv is at `.venv/bin/python`. Run tests as `.venv/bin/python -m pytest tests/test_recommendations.py -v` (plain `python`/`pytest` on PATH does not have the project's dependencies installed).

---

### Task 1: Configurable Front Seats floor

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Add the new setting**

In `app/config.py`, add one field to the `Settings` class, next to the other tolerance/default fields:

```python
    default_fuel_density_lb_per_gal: float = 6.0
    min_front_seat_weight_lb: float = 170.0
    log_level: str = "INFO"
```

- [ ] **Step 2: Verify the app still imports cleanly**

Run: `.venv/bin/python -c "from app.config import settings; print(settings.min_front_seat_weight_lb)"`
Expected: prints `170.0`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "Add configurable Front Seats minimum weight for seat-load recommendations"
```

---

### Task 2: Fuel-safety priority reorder

**Files:**
- Modify: `app/domain/recommendations.py:392-399`
- Test: `tests/test_recommendations.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_recommendations.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py::test_category_priority_puts_reduce_fuel_last -v`
Expected: FAIL — today's order is `MOVE_LOAD=0, REDUCE_BAGGAGE=1, REDUCE_FUEL=2, SHIFT_FUEL=3, ADD_BAGGAGE=4, ADD_FUEL=5`, so `REDUCE_FUEL`'s priority (2) is not greater than `ADD_FUEL`'s (5); the list `[0, 1, 4, 3, 5, 2]` is not sorted.

- [ ] **Step 3: Reorder `_CATEGORY_PRIORITY`**

In `app/domain/recommendations.py`, replace:

```python
_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.REDUCE_BAGGAGE: 1,
    RecommendationKind.REDUCE_FUEL: 2,
    RecommendationKind.SHIFT_FUEL: 3,
    RecommendationKind.ADD_BAGGAGE: 4,
    RecommendationKind.ADD_FUEL: 5,
}
```

with:

```python
_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.REDUCE_BAGGAGE: 1,
    RecommendationKind.ADD_BAGGAGE: 2,
    RecommendationKind.SHIFT_FUEL: 3,
    RecommendationKind.ADD_FUEL: 4,
    RecommendationKind.REDUCE_FUEL: 5,
}
```

- [ ] **Step 4: Run the full recommendations test file**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -v`
Expected: PASS (all tests, including the new one and `test_recommendations_preserve_category_priority_over_raw_delta`, which only compares `MOVE_LOAD` vs `REDUCE_FUEL` and is unaffected by the reorder).

- [ ] **Step 5: Commit**

```bash
git add app/domain/recommendations.py tests/test_recommendations.py
git commit -m "Rank Reduce Fuel last in recommendation priority (fuel-safety bias)"
```

---

### Task 3: New `REDUCE_SEAT_LOAD` category

**Files:**
- Modify: `app/domain/recommendations.py`
- Test: `tests/test_recommendations.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommendations.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -k reduce_seat_load -v`
Expected: FAIL — `RecommendationKind.REDUCE_SEAT_LOAD` does not exist yet (`AttributeError`).

- [ ] **Step 3: Add the `REDUCE_SEAT_LOAD` kind, its floor helper, and its search function**

In `app/domain/recommendations.py`, add `REDUCE_SEAT_LOAD` to the enum:

```python
class RecommendationKind(str, Enum):
    REDUCE_FUEL = "REDUCE_FUEL"
    ADD_FUEL = "ADD_FUEL"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    ADD_BAGGAGE = "ADD_BAGGAGE"
    REDUCE_SEAT_LOAD = "REDUCE_SEAT_LOAD"
    MOVE_LOAD = "MOVE_LOAD"
    SHIFT_FUEL = "SHIFT_FUEL"
```

Add the `settings` import at the top of the file (with the other `app.domain` imports):

```python
from app.config import settings
```

Update `describe()`'s baggage-reduction branch to also cover seats (same neutral phrasing, no assertion of who):

```python
        if self.kind in (RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.REDUCE_SEAT_LOAD):
            kg = lb_to_kg(self.delta_lb)
            return (
                f"Remove {display(self.delta_lb)} lb ({display(kg)} kg) from "
                f"{self.station_name}."
            )
```

(replaces the existing `if self.kind == RecommendationKind.REDUCE_BAGGAGE:` line only — leave everything else in `describe()` unchanged)

Add the floor helper and search function, right after `_search_reduce_baggage`:

```python
_SEAT_STATION_TYPES = {StationType.FRONT_SEATS, StationType.REAR_SEATS}


def _seat_floor_lb(station: StationProfile) -> Decimal:
    """Front Seats always needs at least a pilot aboard; Rear Seats has no minimum."""
    if station.station_type == StationType.FRONT_SEATS:
        return Decimal(str(settings.min_front_seat_weight_lb))
    return Decimal("0")


def _search_reduce_seat_load(
    profile: AircraftProfile, calc_input: CalculationInput
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for station in profile.stations:
        if station.station_type not in _SEAT_STATION_TYPES:
            continue
        current = _current_load_weight(calc_input, station.station_id)
        floor = _seat_floor_lb(station)
        if current <= floor:
            continue
        steps = min(int((current - floor) / LOAD_STEP_LB), MAX_STEPS)
        for step in range(1, steps + 1):
            delta = LOAD_STEP_LB * step
            target = current - delta
            if target < floor:
                break
            candidate = _replace_load(calc_input, station.station_id, target)
            result = _try_calculate(profile, candidate)
            if result and _is_acceptable(result.overall_status):
                results.append(
                    Recommendation(
                        kind=RecommendationKind.REDUCE_SEAT_LOAD,
                        station_id=station.station_id,
                        station_name=station.name,
                        delta_lb=delta,
                    )
                )
                break
    return results
```

`StationProfile` needs to be imported for the type hint — check the existing import line near the top of the file:

```python
from app.domain.models import AircraftProfile, CalculationInput, LoadItemInput, StationProfile, StationType
```

(add `StationProfile` to that existing import if it isn't already there).

- [ ] **Step 4: Wire the new search into `generate_recommendations` and reprioritize**

In `generate_recommendations`, add the call right after `_search_move_load`:

```python
    candidates: list[Recommendation] = []
    candidates += _search_move_load(profile, calc_input)
    candidates += _search_reduce_seat_load(profile, calc_input)
    candidates += _search_reduce_baggage(profile, calc_input)
    candidates += _search_add_baggage(profile, calc_input)
    candidates += _search_reduce_fuel(profile, calc_input, min_fuel_gal)
```

Update `_CATEGORY_PRIORITY` to insert the new tier and shift the rest down by one:

```python
_CATEGORY_PRIORITY = {
    RecommendationKind.MOVE_LOAD: 0,
    RecommendationKind.REDUCE_SEAT_LOAD: 1,
    RecommendationKind.REDUCE_BAGGAGE: 2,
    RecommendationKind.ADD_BAGGAGE: 3,
    RecommendationKind.SHIFT_FUEL: 4,
    RecommendationKind.ADD_FUEL: 5,
    RecommendationKind.REDUCE_FUEL: 6,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -v`
Expected: PASS (all tests, including `test_category_priority_puts_reduce_fuel_last` from Task 2, which is unaffected by inserting a new tier since it only checks relative order among the original six).

- [ ] **Step 6: Commit**

```bash
git add app/domain/recommendations.py tests/test_recommendations.py
git commit -m "Add Reduce Seat Load recommendation with a Front Seats floor"
```

---

### Task 4: Rear Seats <-> Baggage cross-group moves

**Files:**
- Modify: `app/domain/recommendations.py:158-161`
- Test: `tests/test_recommendations.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommendations.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -k "rear_seats_to_baggage" -v`
Expected: FAIL — `_MOVABLE_GROUPS` today has `{BAGGAGE}` as its own disjoint group, so no Rear Seats <-> Baggage candidate is ever generated; `move_recs` is empty.

- [ ] **Step 3: Restructure `_MOVABLE_GROUPS`**

Replace:

```python
_MOVABLE_GROUPS = (
    {StationType.FRONT_SEATS, StationType.REAR_SEATS},
    {StationType.BAGGAGE},
)
```

with:

```python
_MOVABLE_GROUPS = (
    {StationType.FRONT_SEATS, StationType.REAR_SEATS},   # seat swap
    {StationType.REAR_SEATS, StationType.BAGGAGE},       # rear-seat cargo <-> baggage
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -v`
Expected: PASS (all tests — including `test_recommendation_does_not_move_ambiguous_custom_load`, which only checks `CUSTOM` stations and is unaffected).

- [ ] **Step 5: Commit**

```bash
git add app/domain/recommendations.py tests/test_recommendations.py
git commit -m "Allow Rear Seats <-> Baggage moves; keep Front Seats excluded from Baggage"
```

---

### Task 5: Fuel + load combination recommendations

**Files:**
- Modify: `app/domain/recommendations.py`
- Test: `tests/test_recommendations.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommendations.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -k "combination or max_results_is_four" -v`
Expected: FAIL — `RecommendationKind.COMBINATION` and `_combination_priority` don't exist yet; `max_results` default is still `3`.

- [ ] **Step 3: Add the `COMBINATION` kind and `legs` field**

Add to the enum:

```python
class RecommendationKind(str, Enum):
    REDUCE_FUEL = "REDUCE_FUEL"
    ADD_FUEL = "ADD_FUEL"
    REDUCE_BAGGAGE = "REDUCE_BAGGAGE"
    ADD_BAGGAGE = "ADD_BAGGAGE"
    REDUCE_SEAT_LOAD = "REDUCE_SEAT_LOAD"
    MOVE_LOAD = "MOVE_LOAD"
    SHIFT_FUEL = "SHIFT_FUEL"
    COMBINATION = "COMBINATION"
```

Add the `legs` field to `Recommendation`:

```python
@dataclass(frozen=True)
class Recommendation:
    kind: RecommendationKind
    station_id: str
    station_name: str
    delta_lb: Decimal | None = None
    delta_gal: Decimal | None = None
    target_station_id: str | None = None
    target_station_name: str | None = None
    note: str | None = None
    resulting_gal: Decimal | None = None
    tank_capacity_gal: Decimal | None = None
    legs: tuple["Recommendation", ...] | None = None
```

Add a `describe()` branch for it, right before the final `return "Adjustment."`:

```python
        if self.kind == RecommendationKind.COMBINATION:
            return " AND ".join(leg.describe() for leg in self.legs)
```

- [ ] **Step 4: Add the leg-application helper**

Add near `_replace_load`/`_replace_fuel`:

```python
def _apply_combination_leg(
    calc_input: CalculationInput, leg: Recommendation, amount: Decimal
) -> CalculationInput:
    """Apply `amount` (a fraction of `leg`'s full delta) of a single-category leg on top of
    calc_input. Fuel-side and load-side legs never touch the same station, so applying one
    leg's partial amount, then the other's, on the same base input is always safe."""
    if leg.kind == RecommendationKind.REDUCE_FUEL:
        current = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        return _replace_fuel(calc_input, leg.station_id, current - amount)
    if leg.kind == RecommendationKind.ADD_FUEL:
        current = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        return _replace_fuel(calc_input, leg.station_id, current + amount)
    if leg.kind == RecommendationKind.SHIFT_FUEL:
        source = next(f.starting_gal for f in calc_input.fuel if f.station_id == leg.station_id)
        dest = next(
            f.starting_gal for f in calc_input.fuel if f.station_id == leg.target_station_id
        )
        candidate = _replace_fuel(calc_input, leg.station_id, source - amount)
        return _replace_fuel(candidate, leg.target_station_id, dest + amount)
    if leg.kind in (RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.REDUCE_SEAT_LOAD):
        current = _current_load_weight(calc_input, leg.station_id)
        return _replace_load(calc_input, leg.station_id, current - amount)
    if leg.kind == RecommendationKind.ADD_BAGGAGE:
        current = _current_load_weight(calc_input, leg.station_id)
        return _replace_load(calc_input, leg.station_id, current + amount)
    if leg.kind == RecommendationKind.MOVE_LOAD:
        source_w = _current_load_weight(calc_input, leg.station_id)
        dest_w = _current_load_weight(calc_input, leg.target_station_id)
        candidate = _replace_load(calc_input, leg.station_id, source_w - amount)
        return _replace_load(candidate, leg.target_station_id, dest_w + amount)
    raise ValueError(f"Cannot apply combination leg of kind {leg.kind}")


def _leg_magnitude(leg: Recommendation) -> Decimal:
    return leg.delta_gal if leg.delta_gal is not None else leg.delta_lb


def _leg_step(leg: Recommendation) -> Decimal:
    return FUEL_STEP_GAL if leg.delta_gal is not None else LOAD_STEP_LB


def _half_step_amount(alone: Decimal, step: Decimal) -> Decimal:
    steps_count = max(1, int((alone / 2) / step))
    return step * steps_count


def _leg_with_amount(profile: AircraftProfile, leg: Recommendation, amount: Decimal) -> Recommendation:
    if leg.delta_gal is not None:
        station = profile.station(leg.station_id)
        return dataclasses.replace(
            leg, delta_gal=amount, delta_lb=amount * station.fuel_density_lb_per_gal,
            resulting_gal=None,
        )
    return dataclasses.replace(leg, delta_lb=amount)
```

- [ ] **Step 5: Add `_search_combinations`**

```python
MAX_COMBO_ATTEMPTS = 200

_COMBINATION_FUEL_KINDS = (
    RecommendationKind.REDUCE_FUEL, RecommendationKind.ADD_FUEL, RecommendationKind.SHIFT_FUEL,
)
_COMBINATION_LOAD_KINDS = (
    RecommendationKind.MOVE_LOAD, RecommendationKind.REDUCE_SEAT_LOAD,
    RecommendationKind.REDUCE_BAGGAGE, RecommendationKind.ADD_BAGGAGE,
)


def _search_combinations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    fuel_side: list[Recommendation],
    load_side: list[Recommendation],
) -> list[Recommendation]:
    results: list[Recommendation] = []
    for fuel_leg in fuel_side:
        if fuel_leg.kind not in _COMBINATION_FUEL_KINDS:
            continue
        fuel_alone = _leg_magnitude(fuel_leg)
        fuel_step = _leg_step(fuel_leg)
        for load_leg in load_side:
            if load_leg.kind not in _COMBINATION_LOAD_KINDS:
                continue
            load_alone = _leg_magnitude(load_leg)
            load_step = _leg_step(load_leg)

            fuel_amount = _half_step_amount(fuel_alone, fuel_step)
            load_amount = _half_step_amount(load_alone, load_step)
            grow_fuel_next = fuel_amount <= load_amount
            found_amounts = None
            for _ in range(MAX_COMBO_ATTEMPTS):
                if fuel_amount > fuel_alone or load_amount > load_alone:
                    break
                candidate = _apply_combination_leg(calc_input, fuel_leg, fuel_amount)
                candidate = _apply_combination_leg(candidate, load_leg, load_amount)
                result = _try_calculate(profile, candidate)
                if result and _is_acceptable(result.overall_status):
                    found_amounts = (fuel_amount, load_amount)
                    break
                if grow_fuel_next:
                    fuel_amount += fuel_step
                else:
                    load_amount += load_step
                grow_fuel_next = not grow_fuel_next

            if found_amounts is None:
                continue
            fuel_amount, load_amount = found_amounts
            if fuel_amount >= fuel_alone and load_amount >= load_alone:
                continue  # no gentler than doing either alone -- not worth offering
            results.append(
                Recommendation(
                    kind=RecommendationKind.COMBINATION,
                    station_id=fuel_leg.station_id,
                    station_name=fuel_leg.station_name,
                    legs=(
                        _leg_with_amount(profile, fuel_leg, fuel_amount),
                        _leg_with_amount(profile, load_leg, load_amount),
                    ),
                )
            )
    return results
```

- [ ] **Step 6: Wire combinations into `generate_recommendations`, add `_combination_priority`, raise `max_results` default**

Replace the body of `generate_recommendations` with:

```python
def generate_recommendations(
    profile: AircraftProfile,
    calc_input: CalculationInput,
    min_fuel_gal: dict[str, Decimal] | None = None,
    max_results: int = 4,
    *,
    allow_fuel_transfer: bool = False,
    allow_add_fuel: bool = False,
) -> list[Recommendation]:
    """Return verified load adjustments in practical priority order.

    The standard UI does not ask for a minimum-fuel value. Consequently, every fuel-reduction
    recommendation includes an explicit reminder that trip/reserve requirements remain the
    pilot's responsibility. Callers that already know a hard floor may still pass it here.
    """
    min_fuel_gal = min_fuel_gal or {}

    move_load_results = _search_move_load(profile, calc_input)
    reduce_seat_results = _search_reduce_seat_load(profile, calc_input)
    reduce_baggage_results = _search_reduce_baggage(profile, calc_input)
    add_baggage_results = _search_add_baggage(profile, calc_input)
    reduce_fuel_results = _search_reduce_fuel(profile, calc_input, min_fuel_gal)
    shift_fuel_results = (
        _search_shift_fuel(profile, calc_input, min_fuel_gal) if allow_fuel_transfer else []
    )
    add_fuel_results = _search_add_fuel(profile, calc_input) if allow_add_fuel else []

    candidates: list[Recommendation] = []
    candidates += move_load_results
    candidates += reduce_seat_results
    candidates += reduce_baggage_results
    candidates += add_baggage_results
    candidates += reduce_fuel_results
    candidates += shift_fuel_results
    candidates += add_fuel_results

    load_side_results = (
        move_load_results + reduce_seat_results + reduce_baggage_results + add_baggage_results
    )
    fuel_side_results = reduce_fuel_results + shift_fuel_results + add_fuel_results
    candidates += _search_combinations(profile, calc_input, fuel_side_results, load_side_results)

    candidates.sort(key=lambda recommendation: (_combination_priority(recommendation), _tiebreak(recommendation)))
    return candidates[:max_results]
```

Add `_combination_priority` and `_tiebreak` as module-level functions (replacing the old inline `tiebreak` closure), right above `generate_recommendations`:

```python
def _combination_priority(recommendation: Recommendation) -> int:
    if recommendation.kind == RecommendationKind.COMBINATION and recommendation.legs:
        fuel_leg = recommendation.legs[0]
        return _CATEGORY_PRIORITY.get(fuel_leg.kind, 99)
    return _CATEGORY_PRIORITY.get(recommendation.kind, 99)


def _tiebreak(recommendation: Recommendation) -> Decimal:
    if recommendation.kind == RecommendationKind.COMBINATION and recommendation.legs:
        return sum((leg.delta_lb for leg in recommendation.legs), Decimal("0"))
    if recommendation.delta_lb is not None:
        return recommendation.delta_lb
    if recommendation.delta_gal is not None:
        return recommendation.delta_gal
    return Decimal("0")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recommendations.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 8: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests, including `tests/test_regressions.py`, `tests/test_quick_recommendations.py`, and the end-to-end wizard test — none of which touch `app/domain/recommendations.py`'s internals directly except through the already-tested `generate_recommendations` public signature, whose only change is a default value).

- [ ] **Step 9: Commit**

```bash
git add app/domain/recommendations.py tests/test_recommendations.py
git commit -m "Add fuel+load combination recommendations"
```

---

### Task 6: Update the spec's "out of scope" note (documentation only)

**Files:**
- Modify: `docs/superpowers/specs/2026-08-04-recommendation-engine-upgrade-design.md`

- [ ] **Step 1: Mark the spec implemented**

Add a one-line status update at the very top of the spec file, changing:

```markdown
**Status:** approved, ready for implementation planning
```

to:

```markdown
**Status:** implemented (see `docs/superpowers/plans/2026-08-04-recommendation-engine-upgrade.md`)
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-08-04-recommendation-engine-upgrade-design.md
git commit -m "Mark recommendation engine upgrade spec as implemented"
```
