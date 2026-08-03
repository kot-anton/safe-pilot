# Download Aircraft Data — Design

## Problem

Pilots enter aircraft data (weights, stations, CG envelope) once, often years before they need to
revisit it. There is currently no way to view that saved data without going through the "Edit
Aircraft" wizard, which pre-loads the data for editing rather than plain review. Pilots want a
quick, read-only way to pull up what's on file for an aircraft so they can verify it's still
accurate before deciding whether to update it.

## Solution

Add a **"📥 Download Data"** button to the Aircraft submenu. Tapping it shows the same aircraft
picker already used by Edit/Archive Aircraft. Choosing an aircraft replies with a read-only text
summary of that aircraft's current active revision — tail number/model/nickname, empty
weight/CG, weight limits, load stations, fuel tanks, and CG envelope. No FSM state is entered, no
data is created or changed.

This reuses two things that already exist:
- `aircraft_list_keyboard(aircraft_list, prefix)` for the picker (new prefix: `"download"`).
- `render_summary(data, lang)` in `aircraft_wizard.py`, currently used for the wizard's
  "review before saving" screen, for formatting the output. The same field-shaping logic that
  builds the `data` dict from an `AircraftRevision` already exists in
  `aircraft_update.py:update_aircraft_chosen` (lines ~63–118) — the new handler extracts and
  reuses this shaping so both call sites build the dict the same way.

## Components

**Text strings** (`app/bot/texts/i18n.py`):
- `menu_download_data`: `'📥 Download Data'` — new submenu button label.
- Reuses existing keys: `no_aircraft_yet`, `select_aircraft_prompt`, `aircraft_not_found`.

**Keyboard** (`app/bot/keyboards/common.py`):
- `aircraft_submenu_keyboard` gains the new button, paired with "My Aircrafts" in its own row:
  ```
  [Select Aircraft, Add Aircraft]
  [Edit Aircraft, Archive Aircraft]
  [My Aircrafts, Download Data]
  [« Main menu]
  ```

**Shared helper** (`app/bot/handlers/aircraft_update.py`):
- Extract the dict-building block from `update_aircraft_chosen` (revision → `stations` list,
  `envelope_rows` list, and the top-level identity/weight fields) into a standalone function,
  e.g. `build_revision_summary_data(aircraft, revision) -> dict`. `update_aircraft_chosen` calls
  it and adds the wizard-only fields (`update_mode`, `known_useful_load_lb`,
  `source_document_name`, `source_document_date`) on top before `state.update_data(...)`.

**New handler** (`app/bot/handlers/menu.py`, alongside the other aircraft-submenu handlers):
- `@router.message(F.text == t("menu_download_data"))` — clears state, lists aircraft, shows
  `aircraft_list_keyboard(aircraft_list, "download")` with the existing `select_aircraft_prompt`
  text (or `no_aircraft_yet` if the pilot has none).
- `@router.callback_query(F.data.startswith("download:"))` — resolves the aircraft and its
  active revision (mirrors the not-found/no-active-revision guards in
  `update_aircraft_chosen`), builds the data dict via `build_revision_summary_data`, and replies
  with `render_summary(data, lang)` as a plain message. Does not touch `state` beyond what was
  already cleared, and does not call any repository write method.

## Data flow

```
pilot taps "Download Data"
  -> menu.py handler: list_aircraft(user.id) -> aircraft_list_keyboard(..., "download")
pilot picks an aircraft
  -> callback "download:<id>"
  -> aircraft_service.get_aircraft(user_id, aircraft_id)
  -> aircraft_service.get_revision_for_user(user_id, aircraft.active_revision_id)
  -> build_revision_summary_data(aircraft, revision)
  -> render_summary(data, lang)
  -> reply as a message
```

## Error handling

- No aircraft on file → `no_aircraft_yet` (existing behavior, matches Edit/Archive).
- Aircraft not found (e.g. archived between listing and tap) or has no active revision →
  `aircraft_not_found` alert via `callback.answer(..., show_alert=True)` (matches
  `archive_aircraft_chosen` / `update_aircraft_chosen` guard pattern).

## Testing

- Add a bot-UI test (in `tests/test_bot_ui.py`, following existing patterns for Edit/Archive
  Aircraft) that: taps "Download Data", picks an aircraft, and asserts the reply contains the
  expected summary fields (tail number, empty weight, station names, envelope rows).
- Add a case for the empty-aircraft-list path and the aircraft-not-found path.
- No changes to `aircraft_service.py` or the domain layer, so no new unit tests are needed there
  beyond a smoke test of `build_revision_summary_data`.

## Out of scope

- File/document export (JSON, PDF, etc.) — text message reply only, per requirements.
- Viewing historical (non-active) revisions.
- Any mutation of aircraft data — this is strictly read-only.
