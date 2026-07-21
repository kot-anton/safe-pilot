# SafetyPilot engineering review

Review date: 2026-07-21  
Reviewed scope: Telegram handlers/FSM, domain calculations, recommendations, persistence, migrations, tests, packaging, and the supplied Telegram conversation.

## Executive summary

The application already had a sound high-level structure: Telegram was separated from deterministic Weight & Balance mathematics, core values used `Decimal`, aircraft revisions preserved historical calculations, and database access was scoped by Telegram user. The main weaknesses were state-machine defects, an unnecessarily long normal workflow, unsafe ambiguity around fuel stations, incomplete limit reporting, and recommendation logic that did not match the intended physical actions.

The supplied conversation demonstrates two of the product defects directly: `Fuel Aux Tanks` was accidentally stored as `CUSTOM` and requested in pounds, and the normal calculation asked for `Minimum required takeoff fuel...` even though that value was not needed for the requested calculation. fileciteturn3file0

This revision keeps the existing architecture and database history while correcting the flow and strengthening validation.

## Critical and high-priority findings fixed

### 1. Station edit could not be completed

**Root cause:** after editing a station ARM, the handler rendered the station list but left the FSM in `station_edit_arm`. The subsequent `Done adding stations` callback is registered for `station_add_prompt`, so Telegram received a button press for which no handler matched. The edit looked saved in memory but the wizard could not finish and persist the new aircraft revision.

**Fix:** every successful station-edit path now transitions explicitly back to `AircraftWizard.station_add_prompt` before the station hub is rendered. Regression coverage verifies the state transition and persistence path.

Station editing was also extended so the user can safely change the station name, type, ARM, baggage/custom maximum, fuel capacity, and fuel density without deleting and recreating the station.

### 2. Legacy AUX fuel station could be treated as pounds

**Risk:** a station named like a fuel tank could still be stored as `CUSTOM`; the calculation wizard then requested pounds instead of gallons. That can produce a numerically plausible but physically incorrect moment.

**Fix:** the bot detects suspicious legacy `CUSTOM` fuel-like stations and blocks calculation until the profile is corrected. It does not silently reclassify aviation data by name. The station editor provides a controlled conversion to `FUEL`, clears incompatible pound-limit metadata, and requires usable gallon capacity and fuel density.

### 3. Standard fuel workflow was too complex

**Fix:** the normal calculation now asks only for combined front seats, combined rear seats, baggage, and total usable fuel. The routine minimum-fuel question was removed. Taxi burn is no longer requested in the standard or current advanced takeoff flow.

Landing remains optional. A landing condition is calculated only when a complete burn distribution is supplied for every configured tank; otherwise the takeoff result remains the primary result and the bot states that landing was not evaluated.

### 4. Total fuel with different tank ARMs could imply false precision

**Risk:** total gallons do not define one exact moment when the fuel may be distributed among tanks with different ARMs.

**Fix:** the quick calculator computes the minimum and maximum physically possible fuel moments subject to each tank's usable capacity. It then reports an exact CG when the range collapses, a CG interval when the split is unknown, or `EXACT TANK SPLIT REQUIRED` when only some possible distributions satisfy the envelope.

The engine never invents a main/AUX split.

### 5. Recommendations did not match the intended actions

**Fix:** passenger reseating recommendations were removed. Every returned recommendation is applied to a copy of the load and recalculated before display. The solver can now:

- move existing baggage between configured baggage compartments;
- remove baggage;
- add permitted, secured load to a baggage compartment only when an explicit compartment maximum is stored;
- reduce fuel when the resulting loading is valid.

Fuel-reduction output explicitly states that route fuel, legal reserve, and tank limitations are not evaluated. Added load is never suggested for an unbounded or ambiguous station.

For an unknown fuel split, a recommendation is accepted only if it works for every feasible split; otherwise the user must enter the exact tank quantities.

### 6. Published CG envelope weight range was not distinguished from CG position

**Risk:** when aircraft weight was outside the entered envelope's published weight range, the UI could show the nearest row as though it were a valid interpolated limit and label the result merely forward/aft.

**Fix:** the envelope result now carries an explicit `weight_within_envelope` flag. Weight outside the configured envelope range is reported separately, and nearest-row values are not presented as valid limits for that weight.

### 7. Zero-fuel and station violations were incomplete in output

**Fix:** maximum zero-fuel weight is evaluated and included in the phase/global status. Station over-limit conditions are returned as explicit calculation violations instead of generic parsing failures. Advanced and quick results display the relevant violation details.

### 8. Partial landing input could be mistaken for a complete landing calculation

**Fix:** landing is evaluated only when every fuel tank has an explicit burn value, including an explicit zero where appropriate. Skipping one tank no longer silently assumes zero while using burn from another tank.

### 9. Calculation history snapshots were not reliably structured

**Fix:** inputs and results are saved as structured JSON snapshots. History still tolerates legacy opaque string snapshots and keeps every result attached to the aircraft revision used at calculation time.

### 10. Persistence and PostgreSQL migration integrity

SQLite foreign-key enforcement is now enabled on every application connection.

A new migration, `9c7e4f2a1b6d_fix_postgresql_integrity_constraints`, repairs two PostgreSQL-specific issues from the original migration chain:

- circular foreign keys declared with `use_alter=True` but never emitted by the generated migration;
- the PostgreSQL `stationtypeenum` retaining obsolete `BALLAST` after the application enum removed it.

The PostgreSQL migration SQL was generated and inspected offline. No live PostgreSQL server was available in the review environment, so production deployment should still run the migration first against a backup/staging database.

### 11. Tests and database migrations required a Telegram secret

**Risk:** the global settings object required `BOT_TOKEN` at import time. A sanitized source archive without `.env` therefore could not run Alembic or the complete test suite, even though neither operation needs Telegram credentials.

**Fix:** configuration remains importable without a token, while the executable Telegram entry point validates `BOT_TOKEN` immediately before Bot creation and fails with a clear setup message. This keeps secrets out of source distributions without weakening runtime validation.

## Additional validation improvements

The domain and service layers now reject or report:

- `NaN` and infinite numeric input;
- zero/negative Basic Empty Weight;
- inconsistent Basic Empty CG/Moment conversion;
- invalid adjustable ARM ranges or actual ARM outside the range;
- duplicate station IDs in one calculation;
- the same station supplied as both load and fuel;
- fuel entered above usable capacity;
- total burn exceeding starting fuel;
- mixed fuel densities in one total-input fuel group;
- duplicate/unsorted envelope rows;
- invalid aircraft weight-limit relationships;
- quick-mode profiles containing custom/unsupported load stations that would otherwise be silently omitted.

A new aircraft is selected automatically after creation. Editing still creates an immutable aircraft revision.

## Verification performed

- Python bytecode compilation: passed
- Static undefined/import check with `pyflakes`: passed
- Whitespace/conflict-marker check with `git diff --check`: passed
- Automated test suite: **83 passed**
- SQLite database migration from the supplied revision to Alembic head: passed
- SQLite `PRAGMA integrity_check`: `ok`
- SQLite foreign-key check: no violations
- PostgreSQL migration SQL generation: covered by automated test

All automated aircraft fixtures are synthetic demonstration data, not approved data for flight use.

## Known limitations and residual risks

1. **Aircraft data is manual.** The bot does not verify a profile against FAA records, the current POH/AFM, supplements, STCs, equipment list, or aircraft-specific Weight & Balance records.
2. **Quick mode is intentionally constrained.** It supports at most one front-seat aggregate, one rear-seat aggregate, and one baggage aggregate. Multiple compartments, custom stations, and adjustable stations require Advanced mode.
3. **Fuel-system rules are conservative.** Quick mode derives the possible range from configured `FUEL` stations. It does not model an aircraft-specific automatic transfer schedule or selectable-tank operating procedure unless the user enters exact tank quantities in Advanced mode.
4. **No legal fuel planning.** Fuel recommendations do not calculate trip fuel, reserves, unusable fuel, performance, runway, weather, or regulatory compliance.
5. **Recommendations are mathematical.** The pilot must verify that baggage/added load is permitted, correctly located, and secured, and that any fuel change is operationally acceptable.
6. **In-progress wizard state is volatile.** aiogram `MemoryStorage` loses an unfinished conversation if the process restarts. Saved aircraft revisions and calculation history remain persistent in the database.
7. **Search resolution is discrete.** Recommendation search uses 1 lb and 0.1 US gal increments and a 5,000-step cap. This is practical for the intended GA loads but is not a continuous optimizer.
8. **Concurrent revision edits.** Revision numbering is adequate for a personal/few-user bot, but two simultaneous edits to the same aircraft could race at commit time; the database uniqueness constraint prevents duplicate revision numbers, and the user would need to retry.
9. **PostgreSQL was not integration-tested live.** SQL generation and migration structure were tested, but a staging migration is still required before production use.

## Security finding

The uploaded archive contained a real Telegram `BOT_TOKEN` in `.env`. The corrected distribution excludes `.env`, `.git`, virtual environments, caches, and build artifacts. The exposed token must be revoked and regenerated in BotFather before the bot is run again.

## Aviation limitation

SafetyPilot performs deterministic Weight & Balance arithmetic using user-entered data. It does not establish airworthiness, approve a flight, guarantee safety, or evaluate performance, runway, weather, or legal fuel requirements. Every profile and result must be checked against the current documents and limitations for the specific aircraft.
