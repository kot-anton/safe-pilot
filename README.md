# SafetyPilot — Telegram Weight & Balance Bot

SafetyPilot is a small, deterministic Telegram bot for general-aviation Weight & Balance calculations. It is designed for one pilot and a few friends, not as a fleet-management system.

The bot does **not** search FAA records, download a POH/AFM, use OCR, or use an LLM for aviation math. The pilot creates and confirms the aircraft profile from the current aircraft-specific Weight & Balance records and applicable POH/AFM data.

## Normal workflow

Send `/start` once after opening the bot. Telegram's persistent command menu and the reply
keyboard both provide access to calculations, aircraft management, history, help, and cancel.
Use `/menu` at any time to abandon an unfinished wizard and restore the main menu.

Selecting **Calculate** first offers **Takeoff — Quick** or **Takeoff + Landing — Advanced**.
The quick calculation asks only:

1. Combined front-seat weight, lb
2. Combined rear-seat weight, lb, when configured
3. Combined baggage weight, lb, when configured
4. Total usable fuel on board, US gal

The result shows:

- takeoff weight and margin;
- zero-fuel and station limits, when configured;
- exact CG or a mathematically possible CG range;
- the interpolated allowable CG range at that weight;
- `WITHIN LIMITS`, `ON LIMIT`, or a specific out-of-limits reason;
- verified baggage/fuel corrections when the solver finds one.

The recommendation engine does **not** suggest reseating passengers. It may:

- move existing baggage between configured baggage compartments;
- remove baggage;
- add permitted and secured baggage only when a compartment maximum is stored;
- reduce fuel when the recalculated loading is valid.

A fuel-reduction suggestion is Weight & Balance math only. The pilot remains responsible for trip fuel, legal reserves, fuel-system limitations, and performance.

## Multiple tanks and one total-fuel number

When all configured fuel tanks use the same ARM, one total-gallons input produces an exact CG.

When tanks have different ARMs and the actual split is unknown, the bot does not invent a split. It computes:

- the minimum possible fuel moment by placing fuel in the lowest-ARM tanks first;
- the maximum possible fuel moment by placing fuel in the highest-ARM tanks first;
- the resulting forward-most and aft-most possible CG.

The result is classified as:

- `WITHIN LIMITS FOR ALL POSSIBLE FUEL SPLITS`;
- `OUT OF LIMITS FOR ALL POSSIBLE FUEL SPLITS`; or
- `EXACT TANK SPLIT REQUIRED`.

At full usable capacity every configured tank is full, so the range collapses to one exact value.

## Aircraft setup

### Quick Setup

Quick Setup collects the minimum profile needed for the normal workflow:

- aircraft identifier/tail number;
- model;
- Basic Empty Weight;
- Basic Empty CG or Basic Empty Moment;
- Maximum Takeoff Weight;
- front/rear/baggage stations and their ARMs;
- each usable fuel tank capacity, ARM, and confirmed fuel density;
- weight-dependent CG envelope rows.

Each tank's saved usable capacity is authoritative. The bot adds those configured values to
show the aircraft's total usable fuel and to build the **Full tanks** shortcut; it does not
keep a second hidden or hardcoded total. Fuel density is configurable because gallons must be
converted to weight for the calculation, but it is omitted from the normal profile review.

Basic Empty Moment is likewise not an aircraft template constant. If the pilot enters Basic
Empty CG, the bot derives moment as `Basic Empty Weight × Basic Empty CG`; if the aircraft
records publish moment instead, the bot stores that entered moment and derives CG.

### Advanced Setup

Advanced Setup additionally collects optional ramp, landing, and zero-fuel weight limits, known useful load for a consistency check, nickname, and manufacturer.

### Updating stations

`Aircraft → Update Aircraft` creates a new immutable aircraft revision. Historical calculations remain linked to the revision used at the time.

Inside the station screen a station can be:

- renamed;
- converted to another station type;
- assigned a new ARM;
- given a new baggage/custom maximum weight;
- given a new usable fuel capacity and density.

This also repairs legacy profiles where a station such as `Fuel Aux Tanks` was accidentally stored as `CUSTOM` and requested in pounds. Convert it to `Fuel Tank`, then enter usable gallons and density.

## Advanced / Landing calculation

The optional Advanced flow asks for every configured load station and every individual fuel tank. It can calculate a landing condition when a complete planned burn is entered for **every** tank.

The standard UI treats the entered tank quantity as fuel at takeoff; it does not ask for taxi burn or minimum required fuel. If landing burn is skipped, the takeoff result remains authoritative and the bot only adds `Landing condition not evaluated`.

For an adjustable custom station, enter `weight / actual ARM`, for example:

```text
25 / 90.5
```

## Calculation model

All core values use Python `Decimal`:

```text
item moment = item weight × item ARM

total weight = Basic Empty Weight + all loads + usable fuel

total moment = Basic Empty Moment + all load moments + fuel moments

CG = total moment ÷ total weight
```

The forward and aft CG limits are linearly interpolated between entered envelope rows. A point on a published boundary is reported as `ON LIMIT`; the numerical epsilon is only for decimal comparison and is not an operational safety margin.

The domain package is independent of Telegram and SQLAlchemy.

## Technology

- Python 3.12+
- aiogram 3
- SQLAlchemy 2 async
- Alembic
- SQLite by default, PostgreSQL-compatible
- Pydantic Settings
- Docker / Docker Compose
- pytest

## Local installation

```bash
cp .env.example .env
```

Put the BotFather token in `.env`:

```env
BOT_TOKEN=your_new_token_here
```

Create a virtual environment and install:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
python -m app.main
```

Run tests:

```bash
pytest -q
```

Current review build: **105 tests passing**.

## Docker

```bash
cp .env.example .env
# add BOT_TOKEN to .env
docker compose up --build -d
docker compose logs -f bot
```

The image runs `alembic upgrade head` before starting the bot. SQLite data is stored in the named Docker volume `safe_pilot_data`.

Stop it with:

```bash
docker compose down
```

Do not add `-v` unless you intentionally want to delete the named database volume.

## Database backup

For the local non-Docker SQLite configuration, stop the bot and copy:

```text
data/safe_pilot.db
```

For Docker, create a consistent copy from the volume while the bot is stopped, or use SQLite's backup command from a temporary container. For PostgreSQL, use `pg_dump`.

## Security

- Never commit or share `.env`.
- A Telegram token found in a shared archive must be revoked and regenerated in BotFather.
- The returned distribution ZIP intentionally excludes `.env`, `.git`, virtual environments, caches, and build artifacts.
- Every aircraft and calculation query is scoped to the owning Telegram user.
- SQLite foreign-key enforcement is enabled on every application connection.

## Important aviation limitation

This software performs only Weight & Balance arithmetic using data entered by the user.

It does not determine airworthiness, approve a flight, guarantee safety, calculate runway/performance limitations, verify weather, determine legal fuel reserves, or validate the aircraft profile against current records.

Always verify the saved profile and each result against the current aircraft-specific Weight & Balance records, equipment list, POH/AFM, supplements, placards, and applicable limitations.

## Repository layout

```text
app/
  bot/            Telegram handlers, keyboards, FSM states, texts
  domain/         Decimal calculation, envelope, fuel allocation, recommendations
  services/       Application orchestration and snapshots
  repositories/   User-scoped database access
  database/       SQLAlchemy models and session setup
alembic/           Database migrations
tests/             Synthetic, demonstration-only test aircraft data
```

A detailed engineering review is in [`CODE_REVIEW.md`](CODE_REVIEW.md).
