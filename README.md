# Safe Pilot -- Weight & Balance Telegram Bot

A Telegram bot that performs deterministic Weight & Balance calculations (ramp, takeoff,
landing) for privately owned general aviation aircraft, using only data that the pilot
enters and confirms.

**This is not an aviation safety authority.** It does not search the FAA registry, does not
read POH/AFM documents, does not use AI or OCR, and does not invent missing aircraft values.
Every number that goes into a calculation is typed in by a pilot. See
[Aviation limitations and disclaimer](#aviation-limitations-and-disclaimer).

## Contents

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

## Architecture

```
app/
  bot/            Telegram presentation layer (aiogram 3): handlers, keyboards, FSM states,
                  middlewares, centralized i18n strings. Contains no calculation logic.
  domain/         Pure Python calculation engine. No aiogram or SQLAlchemy imports.
    units.py        Decimal unit conversions (lb / kg / gal)
    envelope.py      Weight-dependent CG envelope with linear interpolation
    models.py        Dataclasses: AircraftProfile, StationProfile, CalculationInput/Result
    calculator.py    Ramp / takeoff / landing calculation
    recommendations.py  Deterministic load-adjustment solver
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

31 tests cover: moment/CG calculation, CG envelope interpolation (including exact-boundary
"ON LIMIT" behavior and forward/aft violations), overweight and station/tank-capacity
violations, ramp -> takeoff -> landing fuel subtraction across multiple tanks with different
arms, useful-load consistency warnings, empty CG <-> empty moment conversion, the
recommendation solver (fuel reduction, baggage reduction, load moves, and the rule that fuel
is never suggested below the pilot's stated minimum), multi-user data isolation, aircraft
revision history, and persistence across a simulated application restart.

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
   - **Ramp** = empty aircraft + all entered load + starting fuel in every tank.
   - **Takeoff** = Ramp minus pilot-entered taxi fuel burn, per tank (never assumed).
   - **Landing** = Takeoff minus pilot-entered enroute fuel burn, per tank. If no enroute burn
     or landing fuel is entered for any tank, landing is **not evaluated** -- the bot never
     invents a landing fuel state.
4. **CG envelope**: a list of `(weight, forward_limit, aft_limit)` rows. Between rows, both
   limits are linearly interpolated by weight. Outside the lowest/highest published weight,
   the result is `OUT_OF_LIMITS`. A CG exactly equal to a limit (within a tiny floating-point
   epsilon, not an operational safety margin) is reported as `ON_LIMIT`, not `WITHIN`.
5. **Checks per phase**: total weight vs. the applicable maximum (ramp/takeoff/landing/ZFW),
   CG vs. the interpolated envelope, each station's own weight limit, and each fuel tank's
   volume capacity.
6. **Recommendation solver** (`app/domain/recommendations.py`): when a phase is `ON_LIMIT` or
   `OUT_OF_LIMITS`, the solver searches for adjustments -- moving load between non-passenger
   stations, reducing baggage, reducing fuel (never below the pilot's stated minimum, never
   changing which tank burns first), adding fuel, or (only if explicitly enabled per aircraft)
   adding ballast. Every candidate is applied to a copy of the input and re-run through the
   full ramp/takeoff/landing calculation before being offered -- nothing is suggested that the
   engine hasn't itself verified lands inside all configured limits. Up to three options are
   returned, smallest change first.

The engine never guesses: if a value wasn't entered (e.g. no enroute fuel burn), the
corresponding check is simply not run, and the bot says so explicitly ("Landing condition not
evaluated") rather than assuming a number.

## Sample conversation

```
You:  /start
Bot:  Weight & Balance assistant for privately owned GA aircraft.
      This bot performs deterministic Weight & Balance math on aircraft data that
      *you* enter and confirm. It does not look anything up, and it does not guess.
      Main menu: [keyboard: New Calculation | Calculation History | My Aircraft | ...]

You:  Add Aircraft
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
Bot:  Let's configure stations. Add a station?  [Yes] [No]
You:  (taps "Yes")
Bot:  Station name:
You:  Front Seats
Bot:  Station type:  [Front Seats] [Rear Seats] [Passenger] [Baggage] [Fuel] [Ballast] [Custom]
You:  (taps "Front Seats")
Bot:  ARM, in inches:
You:  37.0
Bot:  Is this ARM fixed, or adjustable?  [Fixed] [Adjustable]
You:  (taps "Fixed")
Bot:  Maximum station weight, in pounds (optional):
You:  Skip
Bot:  Station "Front Seats" added.  [Add another station] [Done adding stations]
...  (repeat for Rear Seats, Baggage Area 1, Main Fuel -- Main Fuel additionally asks for
      max fuel volume in gallons and fuel density in lb/gal, never defaulted silently)
You:  (taps "Done adding stations")
Bot:  Enter CG envelope rows, one per message, as: weight, forward_limit, aft_limit
      Example format only (not real data): 2200, 35.0, 47.3
You:  2200, 35.0, 47.3
Bot:  Row added (1 so far). Send another, or press Done.
You:  2400, 37.0, 47.3
Bot:  Row added (2 so far). Send another, or press Done.
You:  2550, 41.0, 47.3
Bot:  Row added (3 so far). Send another, or press Done.
You:  (taps "✅ Done")
Bot:  Source document name (optional, e.g. "W&B report #4"):
You:  Skip
Bot:  Source document date, YYYY-MM-DD (optional):
You:  Skip
Bot:  Please review the aircraft profile: [full summary] [✅ Confirm] [✏️ Edit] [✖ Cancel]
You:  (taps "✅ Confirm")
Bot:  Aircraft profile saved.

You:  New Calculation
Bot:  UNVERIFIED -- Calculations use user-entered aircraft values...
      N12345 -- rev. 1
      Load at Front Seats, in lb (Enter 0 if none):
You:  340
Bot:  Load at Rear Seats, in lb (Enter 0 if none):
You:  0
Bot:  Load at Baggage Area 1, in lb (Enter 0 if none):
You:  20
Bot:  Starting fuel in Main Fuel, in US gal:
You:  30
Bot:  Taxi fuel burn from Main Fuel, in US gal (optional, Skip = 0):
You:  1
Bot:  Planned enroute fuel burn from Main Fuel, in US gal (optional -- Skip if unknown;
      landing will then not be evaluated):
You:  10
Bot:  Minimum required takeoff fuel in Main Fuel, in US gal (optional):
You:  15
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

Neither simplification affects the calculation engine itself, which is fully deterministic
and fully tested regardless of how data was entered.

## Aviation limitations and disclaimer

This bot performs **Weight & Balance calculation only**, from values a pilot enters and
confirms manually. It does not:

- Search the FAA registry or any other database.
- Search the internet, download, or read a POH/AFM or any other document.
- Use AI, an LLM, or OCR for any part of the calculation.
- Invent, default, or assume any missing aircraft value (fuel density, unusable fuel, oil
  weight, ARMs, envelope limits -- all must be entered explicitly).
- Evaluate fuel planning, aircraft performance, runway requirements, weather, or legal fuel
  reserves.
- Guarantee airworthiness or flight approval in any way.

Every aircraft profile is marked **UNVERIFIED** and every result carries the disclaimer that
it must be checked against the current POH/AFM, supplements, equipment list, and the
aircraft's own Weight & Balance records before flight. The pilot in command remains solely
responsible for verifying all values and for the final go/no-go decision.
