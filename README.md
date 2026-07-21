# Weight & Balance Telegram Bot

A Telegram bot for a personal Weight & Balance calculator: one pilot, a few friends, an
occasional rental. The normal calculation is four questions -- front seats, rear seats,
baggage, total fuel -- and takes under a minute, backed by the same deterministic Decimal
calculation engine used for the full ramp/takeoff/landing "Advanced" flow.

**This is not an aviation safety authority.** It does not search the FAA registry, does not
read POH/AFM documents, does not use AI or OCR, and does not invent missing aircraft values.
Every number that goes into a calculation is typed in by a pilot. See
[Aviation limitations and disclaimer](#aviation-limitations-and-disclaimer).

## Contents

- [Simplified workflow](#simplified-workflow)
- [Total fuel input: exact vs. range](#total-fuel-input-exact-vs-range)
- [Architecture](#architecture)
- [Local installation](#local-installation)
- [Docker installation](#docker-installation)
- [BotFather token setup](#botfather-token-setup)
- [Database migrations](#database-migrations)
- [Starting the bot](#starting-the-bot)
- [Running tests](#running-tests)
- [PostgreSQL configuration](#postgresql-configuration)
- [Backup procedure](#backup-procedure)
- [Calculation engine explained](#calculation-engine-explained)
- [Sample conversation](#sample-conversation)
- [Known MVP simplifications](#known-mvp-simplifications)
- [Aviation limitations and disclaimer](#aviation-limitations-and-disclaimer)

## Simplified workflow

**Main menu**: ✈️ Calculate / 🛩 Aircraft / ⚙️ More. `/start` shows a compact card for your
active aircraft (tail number, model, [Calculate] [Change Aircraft]) when one is selected.

**✈️ Calculate** runs the standard 4-question flow: Front seats, Rear seats, Baggage (each
skipped entirely if the aircraft has no such station), then total usable fuel (with
`Full -- N gal` sized from that aircraft's actual configured tank capacity, `Use last`, `0`,
or `Exact tank split` to switch to the full per-tank Advanced flow). A compact confirmation
screen follows, then one result message with weight, CG (or CG range), status, and -- when
out of limits -- a verified correction. "Advanced / Landing" on the result re-opens the full
per-tank flow (taxi burn, enroute burn, minimum fuel, ramp/takeoff/landing separately) for
when you need it.

**🛩 Aircraft** submenu: Select Aircraft, Add Aircraft, Edit Aircraft, Temporary/Rental
Aircraft, Archive Aircraft, My Aircraft. A newly created aircraft becomes active
automatically -- no separate "Select Aircraft" step required.

**Add Aircraft** offers **Quick Setup** (recommended default: tail number, model, empty
weight/CG, max takeoff weight, seats/baggage ARMs, fuel configuration, CG envelope -- nothing
else) or **Advanced Setup** (adds manufacturer, nickname, ramp/landing/ZFW weights, known
useful load). Both produce a full `AircraftRevision`; nothing about the underlying data model
changes based on which path you took.

## Total fuel input: exact vs. range

A pilot filling in "total fuel on board" usually doesn't know the exact gallons in each
physical tank. `app/domain/fuel_allocation.py` handles this honestly:

- **One tank, or multiple tanks sharing the same ARM** (`SINGLE_ARM`): the split doesn't
  matter -- the resulting moment is exact regardless of which tank holds the fuel.
- **Different ARMs, unknown split** (`UNKNOWN_SPLIT_RANGE`): the mathematically possible
  minimum moment (fill the lowest-ARM tank first) and maximum moment (fill the highest-ARM
  tank first) are both computed, giving a genuine CG *range* -- never a single invented
  number. At full usable capacity every tank is full, so the split is forced and the range
  collapses to one exact value automatically.
- **A confirmed, explicit fill rule for that aircraft** (`FIXED_ALLOCATION`): follows only
  that stored rule, never a guessed "main tanks first" default. (The math and DB schema for
  this mode exist -- see `FuelSystem`/`FuelSystemTank` in `app/database/models.py` -- but
  there's currently no guided setup UI for confirming a fixed-allocation rule; see [Known MVP
  simplifications](#known-mvp-simplifications).)

The result is classified as:

- ✅ **WITHIN LIMITS FOR ALL POSSIBLE FUEL SPLITS**
- ❌ **OUT OF LIMITS FOR ALL POSSIBLE FUEL SPLITS**
- ⚠️ **EXACT TANK SPLIT REQUIRED** -- some feasible distributions are within limits and some
  aren't; use "Exact tank split" / Advanced to get a definitive answer.

## Architecture

```
app/
  bot/            Telegram presentation layer (aiogram 3): handlers, keyboards, FSM states,
                  middlewares, centralized i18n strings. Contains no calculation logic.
  domain/         Pure Python calculation engine. No aiogram or SQLAlchemy imports.
    units.py             Decimal unit conversions (lb / kg / gal)
    envelope.py          Weight-dependent CG envelope with linear interpolation
    models.py            Dataclasses: AircraftProfile, StationProfile, CalculationInput/Result
    calculator.py        Ramp / takeoff / landing calculation (the "Advanced" flow)
    fuel_allocation.py   Total-fuel -> exact moment or min/max range across tanks
    quick_calculation.py Front/rear/baggage/total-fuel calculation (the standard flow)
    recommendations.py   Deterministic load-adjustment solver
    exceptions.py
  services/       Bridges Telegram/DB data into the domain layer (aircraft_service,
                  flight_service). Converts DB rows <-> domain dataclasses.
  repositories/   SQLAlchemy async queries, strictly scoped by the owning Telegram user.
  database/       SQLAlchemy 2 async models + session factory.
  config.py       pydantic-settings configuration (reads .env)
  main.py         aiogram Dispatcher wiring, long polling entrypoint

alembic/          Database migrations (initial schema in alembic/versions/)
tests/            pytest / pytest-asyncio unit + integration tests
```

The domain package (`app/domain`) has zero dependencies on aiogram or SQLAlchemy and can be
unit tested in isolation -- see `tests/test_calculator.py`, `tests/test_envelope.py`,
`tests/test_recommendations.py`.

## Local installation

Requires Python 3.12+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env and set BOT_TOKEN=<your token from BotFather>

alembic upgrade head
python -m app.main
```

## Docker installation

```bash
cp .env.example .env
# edit .env and set BOT_TOKEN=<your token from BotFather>

docker compose up --build
```

This builds the image, runs `alembic upgrade head` automatically on container start (see the
Dockerfile `CMD`), and starts the bot with long polling. SQLite data is persisted in the
`safe_pilot_data` named Docker volume, mounted at `/app/data`.

## BotFather token setup

1. Open a chat with [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. BotFather returns an HTTP API token, e.g. `123456789:AAExampleTokenDoNotReuse`.
4. Put that token in your `.env` file as `BOT_TOKEN=...`. Never commit this file or paste the
   token anywhere public -- anyone with the token has full control of the bot. If a token is
   ever exposed, immediately revoke/regenerate it via `/revoke` (or `/token`) in BotFather.

## Database migrations

Migrations are managed with Alembic and target the same async engine used by the app.

```bash
# apply all migrations (also run automatically by the Docker image on startup)
alembic upgrade head

# after changing app/database/models.py, generate a new migration:
alembic revision --autogenerate -m "describe the change"

# roll back one revision
alembic downgrade -1
```

## Starting the bot

```bash
python -m app.main
```

The bot uses long polling (no public HTTPS endpoint required). Stop it with Ctrl+C.

## Running tests

```bash
pytest
```

61 tests cover: moment/CG calculation, CG envelope interpolation (including exact-boundary
"ON LIMIT" behavior and forward/aft violations), overweight and station/tank-capacity
violations, ramp -> takeoff -> landing fuel subtraction across multiple tanks with different
arms, useful-load consistency warnings, empty CG <-> empty moment conversion, the
recommendation solver (fuel reduction, baggage reduction, passenger/load moves, category
priority preserved over raw delta, the rule that fuel is never suggested below the pilot's
stated minimum), the quick-calculation flow (front/rear/baggage/total-fuel, missing-station
rejection, over-capacity rejection), total-fuel allocation math (exact single-ARM result,
full-tank forced-exact split, partial-fuel min/max moment, mixed-density rejection,
fixed-allocation following only its configured rule, CG-range classification against an
envelope in all four cases -- within/forward/aft/exact-split-required), multi-user data
isolation, aircraft revision history, DEFAULT_LANGUAGE honored for new users, new aircraft
becoming active automatically, persistence across a simulated application restart, and that
the fuel-systems migration preserves pre-existing data.

## PostgreSQL configuration

SQLite (via `aiosqlite`) is the default for local development. For production with multiple
concurrent users, switch to PostgreSQL:

1. In `.env`, set:
   ```
   DATABASE_URL=postgresql+asyncpg://safe_pilot:safe_pilot@db:5432/safe_pilot
   ```
2. In `docker-compose.yml`, uncomment the `db` service, the `safe_pilot_pg_data` volume, and
   the `depends_on` block under the `bot` service.
3. Run `docker compose up --build`. The bot container runs `alembic upgrade head` against
   PostgreSQL automatically on startup; the schema is identical (Alembic doesn't distinguish
   between the two beyond standard SQL types).

## Backup procedure

**SQLite (default):** the database lives in the `safe_pilot_data` Docker volume as a single
file. Back it up with:
```bash
docker run --rm -v safe_pilot_data:/data -v "$(pwd)":/backup alpine \
  tar czf /backup/safe_pilot_backup_$(date +%Y%m%d).tar.gz -C /data .
```
Restore by extracting the tarball back into the volume the same way, in reverse.

**PostgreSQL:** use `pg_dump`/`pg_restore` against the `db` service:
```bash
docker compose exec db pg_dump -U safe_pilot safe_pilot > backup_$(date +%Y%m%d).sql
```
Schedule either of these (e.g. via cron) for regular backups; aircraft revisions and flight
calculation history are the data that matters most to preserve.

## Calculation engine explained

All math lives in `app/domain` and is deterministic: identical input always produces
identical output, computed with `Decimal` (never binary `float`) and rounded only at display
time.

1. **Per-item moment**: `moment = weight × arm` for every load and fuel item, using each
   station's configured ARM (or the pilot-entered ARM for adjustable-arm stations).
2. **Totals**: `total_weight = basic_empty_weight + Σ(item weights)`,
   `total_moment = basic_empty_moment + Σ(item moments)`, `CG = total_moment / total_weight`.
3. **Three phases**:
   - **Ramp** = empty aircraft + all entered load + starting fuel in every tank. Passenger and
     baggage weight is the same across all three phases -- people and bags don't lose weight
     in flight, only fuel burns.
   - **Takeoff** = Ramp. Taxi fuel burn isn't asked for (the domain layer still supports it --
     `FuelStationInput.taxi_burn_gal`, defaulted to 0 -- but for private GA aircraft it's
     negligible for W&B purposes, so the bot doesn't add friction asking for it).
   - **Landing** = Takeoff minus pilot-entered enroute fuel burn, per tank. If no enroute burn
     or landing fuel is entered for any tank, landing is **not evaluated** -- the bot never
     invents a landing fuel state.
4. **CG envelope**: a list of `(weight, forward_limit, aft_limit)` rows. Between rows, both
   limits are linearly interpolated by weight. Outside the lowest/highest published weight,
   the result is `OUT_OF_LIMITS`. A CG exactly equal to a limit (within a tiny floating-point
   epsilon, not an operational safety margin) is reported as `ON_LIMIT`, not `WITHIN`. If an
   aircraft's POH only lists a single, weight-independent CG range, enter it as two rows (the
   aircraft's min and max weight, same forward/aft numbers both times) -- mathematically
   identical to a constant range. An aircraft can also have **no envelope at all** (explicitly
   skipped during setup, e.g. when that data genuinely isn't at hand yet): calculations for it
   then check weight limits only, and every result clearly states `CG: NOT EVALUATED` rather
   than silently assuming CG is fine.
5. **Checks per phase**: total weight vs. the applicable maximum (ramp/takeoff/landing/ZFW),
   CG vs. the interpolated envelope, each station's own weight limit, and each fuel tank's
   volume capacity.
6. **Recommendation solver** (`app/domain/recommendations.py`): when a phase is `ON_LIMIT` or
   `OUT_OF_LIMITS`, the solver searches for adjustments -- moving load between non-passenger
   stations, reducing baggage, reducing fuel (never below the pilot's stated minimum, never
   changing which tank burns first), or adding fuel. Every candidate is applied to a copy of
   the input and re-run through the full ramp/takeoff/landing calculation before being offered
   -- nothing is suggested that the engine hasn't itself verified lands inside all configured
   limits. Up to three options are returned, smallest change first.

The engine never guesses: if a value wasn't entered (e.g. no enroute fuel burn), the
corresponding check is simply not run, and the bot says so explicitly ("Landing condition not
evaluated") rather than assuming a number.

## Sample conversation

### Standard calculation (Quick flow)

```
You:  ✈️ Calculate
Bot:  N4508D (rev. 3)
Bot:  Front seats -- total weight in lb   [Use last: 440 lb] [Cancel]
You:  440
Bot:  Rear seats -- total weight in lb    [Use last: 0 lb] [Cancel]
You:  0
Bot:  Baggage -- total weight in lb       [Use last: 10 lb] [Cancel]
You:  10
Bot:  Usable fuel on board -- total US gallons
      [Full -- 53 gal] [Use last: 53 gal] [Exact tank split] [Cancel]
You:  (taps "Full -- 53 gal")
Bot:  N4508D

      Front: 440 lb
      Rear: 0 lb
      Baggage: 10 lb
      Fuel: 53 gal
      [Calculate] [Edit] [Cancel]
You:  (taps "Calculate")
Bot:  ✅ WITHIN LIMITS

      N4508D

      WEIGHT
      2,728.8 lb / 2,775.0 lb
      46.2 lb below maximum

      CG
      80.77 in
      Allowed: 78.20-84.90 in

      Based on the saved aircraft profile. Verify against current aircraft records.
      [Change Load] [Advanced / Landing]
```

### Unknown fuel split (`EXACT TANK SPLIT REQUIRED`)

When an aircraft's fuel tanks have different ARMs and the entered total doesn't force an
exact split (i.e. it's not zero and not full capacity), the result reports a range instead of
inventing one number:

```
Bot:  ⚠️ EXACT TANK SPLIT REQUIRED

      N4508D

      WEIGHT
      2,340.0 lb / 2,775.0 lb
      435.0 lb below maximum

      CG
      Possible CG: 81.10-81.31 in
      Allowed: 82.40-85.30 in
      Some possible fuel splits are within limits and some are not.

      Based on the saved aircraft profile. Verify against current aircraft records.
      [Change Load] [Advanced / Landing]
```

Tapping **Advanced / Landing** (or **Exact tank split** at the fuel question) switches to the
full per-tank flow, where entering the actual gallons in each tank gives a definitive single
CG instead of a range.

### Advanced Setup + Advanced calculation (full detail)

```
You:  /start
Bot:  Weight & Balance assistant for privately owned GA aircraft.
      This bot performs deterministic Weight & Balance math on aircraft data that
      *you* enter and confirm. It does not look anything up, and it does not guess.
      Main menu: [keyboard: ✈️ Calculate | 🛩 Aircraft | ⚙️ More]

You:  🛩 Aircraft > Add Aircraft
Bot:  Quick Setup asks only what's needed for a valid calculation... [⚡ Quick Setup] [🛠 Advanced Setup]
You:  (taps "🛠 Advanced Setup")
Bot:  Enter the tail number (registration):
You:  N12345
Bot:  Aircraft nickname (optional):
You:  Skip
Bot:  Manufacturer (optional):
You:  Cessna
Bot:  Model:
You:  172N
Bot:  Basic Empty Weight, in pounds:
You:  1500
Bot:  Do you know the empty moment, or the empty CG?  [I know the empty CG] [I know the empty moment]
You:  (taps "I know the empty CG")
Bot:  Basic Empty CG, in inches:
You:  39.0
Bot:  The entered Basic Empty Weight and Moment/CG are taken from the aircraft's current
      Weight & Balance record, and all required installed equipment, operating fluids,
      and unusable fuel are represented according to that record.  [Yes] [No]
You:  (taps "Yes")
Bot:  Maximum Ramp Weight, in pounds (optional, Skip if not published):
You:  2560
Bot:  Maximum Takeoff Weight, in pounds (required):
You:  2550
...  (landing weight, ZFW, known useful load -- all Skip or entered)
Bot:  Let's configure stations. Add a station?  [➕ Add another station] [✅ Done adding stations]
You:  (taps "➕ Add another station")
Bot:  Station type:  [Front Seats] [Rear Seats] [Baggage] [Fuel] [Custom]
You:  (taps "Front Seats")
Bot:  Station name -- or just use the suggested default below.  [✅ Use "Front Seats"]
You:  (taps "✅ Use \"Front Seats\"")
Bot:  ARM, in inches:
You:  37.0
Bot:  Station "Front Seats" added.  [➕ Add another station] [✅ Done adding stations] [🗑 Remove a station]
...  (repeat for Rear Seats, Baggage Area 1, Main Fuel -- Main Fuel additionally asks only for
      max fuel volume in gallons; fuel density is fixed at 6.0 lb/gal (standard avgas) and
      never asked. Seats, baggage, and fuel tanks are always fixed-ARM -- only Custom stations
      are asked whether their ARM is fixed or adjustable, since those are the only ones that
      plausibly move.)
You:  (taps "No")
Bot:  CG envelope row: weight, forward_limit, aft_limit (one per message).
      Example: 2200, 35.0, 47.3
You:  2200, 35.0, 47.3
Bot:  Row added (1 so far). Send another, or press Done.
You:  2400, 37.0, 47.3
Bot:  Row added (2 so far). Send another, or press Done.
You:  2550, 41.0, 47.3
Bot:  Row added (3 so far). Send another, or press Done.
You:  (taps "✅ Done")
Bot:  Please review the aircraft profile: [full summary] [✅ Confirm] [✏️ Edit] [✖ Cancel]
You:  (taps "✅ Confirm")
Bot:  Aircraft profile saved.

You:  (from a Quick result, taps "Advanced / Landing")
Bot:  N12345 (rev. 1)
Bot:  Front Seats weight, in lb:              [0] [◀ Back] [✖ Cancel]
You:  340
Bot:  Rear Seats weight, in lb:               [0] [◀ Back] [✖ Cancel]
You:  0
Bot:  Baggage Area 1 weight, in lb:           [0] [◀ Back] [✖ Cancel]
You:  20
Bot:  Starting fuel in Main Fuel, in US gal:
You:  30
Bot:  Planned fuel burn from Main Fuel, in US gal (Skip = landing not evaluated):
You:  10
Bot:  Please confirm your inputs: [summary] [✅ Confirm] [✏️ Edit] [✖ Cancel]
You:  (taps "✅ Confirm")
Bot:  ✅ WITHIN ENTERED LIMITS

      Aircraft: N12345
      Profile revision: 1

      RAMP
      Weight: 2,040.0 lb
      Limit: 2,560.0 lb
      Weight margin: 520.0 lb
      CG: ...

      TAKEOFF
      ...

      LANDING
      ...

      Weight & Balance calculation only. Verify all values against the current POH/AFM,
      supplements, equipment list, and aircraft-specific Weight & Balance records. Fuel
      planning, aircraft performance, runway, weather, and legal reserve requirements are
      not evaluated.
```

## Known MVP simplifications

Documented here rather than hidden, per the "no invented behavior" principle of this project:

- **Editing during aircraft creation** ("✏️ Edit" on the final review screen) restarts the
  wizard from the top. True single-field editing is implemented for the **Update Aircraft**
  flow instead (each step offers a "↩️ Keep current" option pre-filled from the latest
  revision, so only the field(s) you actually want to change need new input).
- **Stations and CG envelope during Update Aircraft** are edited as a whole list (press
  "Done"/"No" immediately to keep the existing list unchanged, or re-enter the full list to
  replace it) rather than editing one station/row at a time.
- **Enroute fuel burn of exactly 0** is treated the same as "not provided" (landing not
  evaluated), since the bot cannot distinguish "I plan to burn zero fuel" from "I don't know
  yet" from a bare `0`. Enter a non-zero burn, or use the minimum-fuel field, if you need a
  landing condition evaluated with a genuinely tiny burn.
- **Taxi fuel burn is not asked for.** For private GA aircraft it's typically negligible for
  W&B purposes, so Takeoff = Ramp. The domain layer still fully supports it
  (`FuelStationInput.taxi_burn_gal`) if this ever needs to change; it's just always 0 from the
  bot today.
- **Adjustable ARM is only offered for Custom stations.** Seats, baggage compartments,
  and fuel tanks are fixed locations in the airframe and are always treated as fixed-ARM --
  the fixed/adjustable question isn't asked for them at all.
- **Fuel density is fixed at 6.0 lb/gal (standard avgas) and never asked.** One question fewer
  for a value that's effectively constant across the aircraft this bot targets.
- **Seats and baggage compartments are never asked for a "maximum station weight."** There's
  no such published limit for them -- the real constraints are max ramp/takeoff weight and the
  CG envelope, both already collected separately. Only fuel tanks have a genuine per-station
  capacity (usable fuel volume), which is still asked. `Station.maximum_weight_lb` remains in
  the data model and is still enforced by the calculator/recommendation engine if a value is
  present (e.g. on aircraft configured via the database or an older revision), it's just never
  prompted for anymore.
- **A "Front Seats"/"Rear Seats" load entry is the combined weight of everyone at that
  station** (e.g. pilot + front passenger together), not per-person -- the bot has no notion
  of individual seats within a station.
- **FIXED_ALLOCATION fuel mode has no guided setup UI yet.** The domain math
  (`compute_fixed_allocation`) and DB columns (`FuelSystemTank.allocation_order`,
  `fixed_full_quantity_gal`) exist and are tested, but there's no wizard step to confirm a
  fixed fill rule for a specific aircraft -- Quick Setup's fuel configuration only ever
  auto-detects the two safe modes (`SINGLE_ARM` when tanks share an ARM, otherwise
  `UNKNOWN_SPLIT_RANGE`), never a guessed "main tanks first" rule.
- **"Temporary / Rental Aircraft"** runs the same Quick Setup and tags the aircraft
  `is_temporary`, but there's no automatic archiving job yet (calculation history is
  unaffected either way -- it's never deleted).
- **Legacy CUSTOM-typed stations that look like fuel** (name contains "fuel"/"tank"/"main"/
  "aux") are not auto-detected or auto-fixed. They're simply never picked up by the fuel-group
  auto-detection (which only looks at stations already typed `FUEL`), so quick-calculate's
  "Full" button and total-fuel math won't include them until the station is retyped via
  Advanced Setup -- nothing is silently reclassified or mis-summed.
- **Advanced Setup's editing is list-based, not the fully sectioned Identity/Empty Weight/
  Weight Limits/Seats & Baggage/Fuel System/CG Envelope/Advanced picker described in the
  original spec.** Update Aircraft's per-field "Keep current" flow (see above) already gives
  single-field editing for every scalar; stations/envelope remain whole-list edits.

None of these simplifications affect the calculation engine itself, which is fully
deterministic and fully tested regardless of how data was entered.

## Aviation limitations and disclaimer

This bot performs **Weight & Balance calculation only**, from values a pilot enters and
confirms manually. It does not:

- Search the FAA registry or any other database.
- Search the internet, download, or read a POH/AFM or any other document.
- Use AI, an LLM, or OCR for any part of the calculation.
- Invent, default, or assume any missing aircraft value (unusable fuel, oil weight, ARMs,
  envelope limits -- all must be entered explicitly), with one deliberate exception: fuel
  density is fixed at 6.0 lb/gal (standard avgas) instead of being asked.
- Evaluate fuel planning, aircraft performance, runway requirements, weather, or legal fuel
  reserves.
- Guarantee airworthiness or flight approval in any way.

Every aircraft profile is marked **UNVERIFIED** and every result carries the disclaimer that
it must be checked against the current POH/AFM, supplements, equipment list, and the
aircraft's own Weight & Balance records before flight. The pilot in command remains solely
responsible for verifying all values and for the final go/no-go decision.
