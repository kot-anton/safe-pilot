# Recommendation Engine Upgrade — Design

**Status:** implemented (see `docs/superpowers/plans/2026-08-04-recommendation-engine-upgrade.md`)
**Scope:** `app/domain/recommendations.py` (Advanced/Full Calculation recommendation solver) and its config/tests. No changes to Quick Calculation's aggregate recommender (`app/domain/quick_recommendations.py`).

## Problem

The existing Advanced-calculation recommendation engine already respects each fuel tank's
configured maximum usable capacity correctly (`maximum_volume_gal` bounds `ADD_FUEL`/`SHIFT_FUEL`;
current `starting_gal` bounds `REDUCE_FUEL`) — that part needed no change, confirmed by code
review before this design started.

Three real gaps were identified through discussion with a pilot user:

1. **No fuel-safety bias.** Today's category priority ranks `REDUCE_FUEL` ahead of most
   load-side options, when in fact removing fuel reduces a flight's safety margin and should be
   the last resort, tried only after every other adjustment has failed.
2. **No combination suggestions.** Every recommendation touches exactly one station/category.
   When no single change fixes an out-of-limits condition, the pilot gets nothing — even though a
   *combination* (e.g. a modest fuel reduction plus a modest baggage increase) might resolve it
   with a smaller, gentler change on each axis than either alone.
3. **Move Load is narrower than real aircraft operation.** It only searches within
   `{FRONT_SEATS, REAR_SEATS}` or within `{BAGGAGE}` — never between seats and baggage — and it
   never offers to simply *reduce* a seat's load (e.g. a passenger not flying), only baggage.

## Design

### 1. Priority order (fuel-safety bias)

`_CATEGORY_PRIORITY` changes from today's order to:

```
MOVE_LOAD=0, REDUCE_SEAT_LOAD=1, REDUCE_BAGGAGE=2, ADD_BAGGAGE=3,
SHIFT_FUEL=4, ADD_FUEL=5, REDUCE_FUEL=6
```

`REDUCE_FUEL` moves to last place: it is now the least-preferred single-category fix, tried
only when nothing else (including adding fuel, transferring between tanks, or any load-side
adjustment) resolves the problem. Load/passenger-affecting changes are tried before any fuel
change at all, reflecting that fuel margin is a safety consideration independent of what's
easiest to adjust.

### 2. New category: `REDUCE_SEAT_LOAD`

A new `RecommendationKind.REDUCE_SEAT_LOAD`, implemented as `_search_reduce_seat_load()` —
structurally identical to the existing `_search_reduce_baggage()` (same 1 lb step search, same
verification via `calculate()`), but targeting `FRONT_SEATS`/`REAR_SEATS` stations instead of
baggage, with an asymmetric floor:

- **Rear Seats:** floor = 0 lb. An empty rear seat is a normal, unremarkable flight condition.
- **Front Seats:** floor = `settings.min_front_seat_weight_lb`, a new configurable field in
  `app/config.py`'s `Settings` (env-driven, default **170 lb**), representing that at least a
  pilot must remain aboard. The search never proposes a target below this floor, mirroring how
  `_search_reduce_fuel` already respects a `min_fuel_gal` floor.

Phrasing mirrors baggage's neutral tone: `"Remove {X} lb ({Y} kg) from {station_name}."` — no
assertion of *who* that means, consistent with the existing Move Load design note.

### 3. `_MOVABLE_GROUPS` restructured

Today:
```python
_MOVABLE_GROUPS = (
    {StationType.FRONT_SEATS, StationType.REAR_SEATS},
    {StationType.BAGGAGE},
)
```
`_search_move_load` already only searches *within* a group — a single-member group like
`{BAGGAGE}` alone therefore never generates any candidates for baggage-to-baggage (there being
nothing else in that group), so this restructuring is additive, not a behavior removal.

New:
```python
_MOVABLE_GROUPS = (
    {StationType.FRONT_SEATS, StationType.REAR_SEATS},   # seat swap
    {StationType.REAR_SEATS, StationType.BAGGAGE},       # rear-seat cargo <-> baggage
)
```

Rear Seats participates in both groups, so it can trade weight with either Front Seats or
Baggage. Front Seats never pairs directly with Baggage — there is normally no loose cargo at a
front seat position to relocate, and simply moving a person's own bodyweight into the baggage
compartment isn't a real action, so that pairing is deliberately excluded. No change to the
existing search algorithm itself — only to which stations are grouped together.

### 4. Combination recommendations

**Data model** — one new `RecommendationKind.COMBINATION`, and one new optional field on the
existing frozen `Recommendation` dataclass:
```python
legs: tuple["Recommendation", ...] | None = None
```
A combination recommendation leaves its own top-level fields (`station_id`, `delta_lb`, etc.)
as `None` and carries its two component legs in `legs` instead. `describe()` for `COMBINATION`
joins each leg's own `describe()` output with `" AND "`, e.g.:

> "Add fuel to Main Tank: +8.0 US gal (+48.0 lb). Target level: 32.0 gal. AND Add 5 lb (2.3 kg)
> to Baggage."

**Legal pairs** — cross-group only, one leg from each side:

- Fuel-side: `REDUCE_FUEL`, `ADD_FUEL` (gated by existing `allow_add_fuel`), `SHIFT_FUEL` (gated
  by existing `allow_fuel_transfer`).
- Load-side: `MOVE_LOAD`, `REDUCE_SEAT_LOAD`, `REDUCE_BAGGAGE`, `ADD_BAGGAGE`.

Same-group pairs (fuel+fuel, load+load) are never combined — `SHIFT_FUEL` and `MOVE_LOAD`
already cover same-group adjustments on their own.

**Search algorithm** — new `_search_combinations()`, called after all single-category searches
have already produced their results, and reusing that output rather than re-running brute force
from scratch:

- Only considers a (fuel-side leg, load-side leg) pair when **both** already have an
  independently-found "alone" fix (from the existing single-category searches). That tells us
  each axis *can* resolve the problem alone, and gives each leg an upper-bound delta to search
  under — a combo is only interesting if it can do *less* on each axis than either alone would.
- Starts each leg at half its alone-delta (rounded down to that category's step granularity,
  minimum one step) and checks the combined candidate via one `calculate()` call.
- If not yet acceptable, grows the smaller-magnitude leg one step at a time (alternating
  between legs) up to each leg's own alone-ceiling, stopping at the first acceptable
  combination.
- Bounded by a new `MAX_COMBO_ATTEMPTS = 200` constant (mirrors the existing `MAX_STEPS` pattern)
  — pure numeric-stability bound, hardcodable per this repo's existing convention.
- If no combo strictly smaller-on-both-axes than the two alones is found for a given pair,
  nothing is emitted for it — the existing alone suggestions already cover that case.

**Priority** — a `COMBINATION` recommendation's priority tier is its **fuel-side leg's** tier
from `_CATEGORY_PRIORITY` (so an Add-Fuel combo ranks in tier 5, a Reduce-Fuel combo in tier 6,
same fuel-safety bias as single-category results). Tiebreak within a tier: total combined
magnitude (smaller wins), same rule already used for single-category results.

### 5. Result cap

`generate_recommendations()`'s `max_results` default changes from 3 to 4, so all four existing
single-category slots stay intact and one extra slot is available for a combination suggestion
when one is found and ranks well enough to make the cut. No signature change beyond the default;
existing callers passing an explicit `max_results` are unaffected.

### 6. UI

No changes needed to `app/bot/texts/i18n.py` or `app/bot/handlers/flight_calculation.py` — both
already render whatever `Recommendation.describe()` returns as one line per suggestion in the
results screen's existing "here are your options" list.

### 7. Testing

New tests, mirroring the structure of existing recommendation tests:

- `REDUCE_SEAT_LOAD`: floor behavior (Front Seats never proposed below
  `min_front_seat_weight_lb`; Rear Seats reducible to 0), phrasing.
- `_MOVABLE_GROUPS`: Rear Seats ↔ Baggage now produces `MOVE_LOAD` candidates; Front Seats ↔
  Baggage never does.
- Combination search: a synthetic profile with a main + aux fuel tank and a baggage station
  where no single-category fix exists but a fuel+baggage combo does; verify the combo is found,
  correctly bounded by both legs' alone-ceilings, and never pairs same-group legs.
- Priority ordering: `REDUCE_FUEL` (and Reduce-Fuel combos) always sort last; `ADD_FUEL`
  (and Add-Fuel combos) sort ahead of `REDUCE_FUEL`.
- `max_results=4` (new default) surfaces a combination suggestion in the fourth slot when one is
  found and ranks within the top 4.

## Out of scope

- Quick Calculation's aggregate recommender (`quick_recommendations.py`) — unchanged; it has no
  per-tank/per-station concept to attach seat/combo logic to.
- Any change to per-tank fuel capacity enforcement — already correct, verified, no work needed.
- N-way (3+) combinations — only two-leg, cross-group combinations are in scope for this pass.
