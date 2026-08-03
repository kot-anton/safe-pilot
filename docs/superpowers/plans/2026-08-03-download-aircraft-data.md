# Download Aircraft Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "📥 Download Data" button to the Aircraft submenu that lets a pilot pick any of their aircraft and get back a text summary of its current saved data, without entering any edit flow.

**Architecture:** Extract the revision-to-summary-dict shaping logic already inlined in `aircraft_update.py`'s `update_aircraft_chosen` into a standalone `build_revision_summary_data()` function that both the existing Edit Aircraft flow and the new Download Data flow call. The new flow lives in `menu.py` alongside the other aircraft-submenu handlers, reuses `aircraft_list_keyboard()` for the picker and `aircraft_wizard.render_summary()` for the formatted output, and touches no FSM state beyond clearing it.

**Tech Stack:** Python, aiogram (Telegram bot framework), pytest (async tests via `pytest-asyncio`, existing fake Message/State/Callback test doubles in `tests/test_regressions.py` and `tests/test_bot_ui.py`).

---

## Reference: spec

Full design at `docs/superpowers/specs/2026-08-03-download-aircraft-data-design.md`. Key decisions baked into this plan:
- Button label: `'📥 Download Data'`, its own row, 6th aircraft-submenu option (after "My Aircrafts", before "« Main menu").
- Output: plain text message (not a file), same field set as the wizard's review screen.
- Scope: current active revision only, any aircraft the pilot owns (not just the selected one).
- No new domain/service-layer code — this is bot-handler-only, reusing `AircraftService.get_aircraft` / `get_revision_for_user` exactly as `aircraft_update.py` already does.

---

### Task 1: Add the `menu_download_data` text string

**Files:**
- Modify: `app/bot/texts/i18n.py:14` (insert after `menu_archive_aircraft`)
- Test: `tests/test_bot_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bot_ui.py` (anywhere among the other standalone `def test_...` functions, e.g. right after `test_main_menu_reply_keyboard_is_persistent_and_localized`):

```python
def test_download_data_menu_string_exists():
    assert STRINGS["menu_download_data"] == "📥 Download Data"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot_ui.py::test_download_data_menu_string_exists -v`
Expected: FAIL with `KeyError: 'menu_download_data'`

- [ ] **Step 3: Add the string**

In `app/bot/texts/i18n.py`, insert a new line directly after the `menu_archive_aircraft` entry (currently line 14):

```python
    'menu_archive_aircraft': '🗑 Archive Aircraft',
    'menu_download_data': '📥 Download Data',
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bot_ui.py::test_download_data_menu_string_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/bot/texts/i18n.py tests/test_bot_ui.py
git commit -m "Add menu_download_data text string"
```

---

### Task 2: Add the "Download Data" button to the Aircraft submenu keyboard

**Files:**
- Modify: `app/bot/keyboards/common.py:36-48` (`aircraft_submenu_keyboard`)
- Test: `tests/test_bot_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bot_ui.py`:

```python
def test_aircraft_submenu_offers_download_data_as_its_own_row():
    from app.bot.keyboards.common import aircraft_submenu_keyboard

    keyboard = aircraft_submenu_keyboard("en")

    row_texts = [[button.text for button in row] for row in keyboard.keyboard]
    assert [STRINGS["menu_download_data"]] in row_texts
    download_row_index = row_texts.index([STRINGS["menu_download_data"]])
    my_aircraft_row_index = next(
        i for i, row in enumerate(row_texts) if row == [STRINGS["menu_my_aircraft"]]
    )
    back_row_index = next(
        i for i, row in enumerate(row_texts) if row == [STRINGS["menu_back"]]
    )
    assert my_aircraft_row_index < download_row_index < back_row_index
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot_ui.py::test_aircraft_submenu_offers_download_data_as_its_own_row -v`
Expected: FAIL — `[STRINGS["menu_download_data"]] in row_texts` is False (button doesn't exist yet), or the row layout doesn't isolate "My Aircrafts" to its own row yet.

- [ ] **Step 3: Update the keyboard**

In `app/bot/keyboards/common.py`, replace the `aircraft_submenu_keyboard` function body (currently lines 36-48):

```python
def aircraft_submenu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_select_aircraft", lang)), KeyboardButton(text=t("menu_add_aircraft", lang))],
        [KeyboardButton(text=t("menu_update_aircraft", lang)), KeyboardButton(text=t("menu_archive_aircraft", lang))],
        [KeyboardButton(text=t("menu_my_aircraft", lang))],
        [KeyboardButton(text=t("menu_download_data", lang))],
        [KeyboardButton(text=t("menu_back", lang))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t("menu_placeholder", lang),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bot_ui.py::test_aircraft_submenu_offers_download_data_as_its_own_row -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/bot/keyboards/common.py tests/test_bot_ui.py
git commit -m "Add Download Data button to Aircraft submenu"
```

---

### Task 3: Extract `build_revision_summary_data()` in `aircraft_update.py`

This gives both Edit Aircraft and the new Download Data flow a single, shared way to turn an
`(aircraft, revision)` pair into the dict `render_summary()` expects. This task is a pure
refactor: `update_aircraft_chosen`'s behavior (and the existing regression test for it) must not
change.

**Files:**
- Modify: `app/bot/handlers/aircraft_update.py:49-127` (`update_aircraft_chosen`)
- Test: `tests/test_regressions.py` (verify existing test still passes; add one new test for the extracted function)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_regressions.py`, right after `test_update_aircraft_chosen_starts_at_tail_number` (ends at line 1139):

```python
async def test_build_revision_summary_data_shapes_stations_and_envelope():
    class _FakeStation:
        def __init__(self):
            self.name = "Front Seats"
            self.station_type = StationTypeEnum.FRONT_SEATS
            self.display_order = 0
            self.active = True
            self.default_arm_in = D("89")
            self.maximum_volume_gal = None
            self.fuel_density_lb_per_gal = None

    aircraft = SimpleNamespace(
        tail_number="N123AB",
        model="172",
        nickname="Old Bird",
        manufacturer=None,
    )
    revision = SimpleNamespace(
        stations=[_FakeStation()],
        envelope_rows=[],
        basic_empty_weight_lb=D("1500"),
        basic_empty_cg_in=D("39"),
        basic_empty_moment_lb_in=D("58500"),
        max_ramp_weight_lb=None,
        max_takeoff_weight_lb=D("2550"),
        max_landing_weight_lb=None,
    )

    data = aircraft_update.build_revision_summary_data(aircraft, revision)

    assert data["tail_number"] == "N123AB"
    assert data["nickname"] == "Old Bird"
    assert data["basic_empty_weight_lb"] == "1500"
    assert data["basic_empty_cg_in"] == "39"
    assert data["max_ramp_weight_lb"] is None
    assert data["max_takeoff_weight_lb"] == "2550"
    assert data["stations"] == [
        {
            "name": "Front Seats",
            "station_type": "FRONT_SEATS",
            "default_arm_in": "89",
            "maximum_volume_gal": None,
            "fuel_density_lb_per_gal": None,
        }
    ]
    assert data["envelope_rows"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_regressions.py::test_build_revision_summary_data_shapes_stations_and_envelope -v`
Expected: FAIL with `AttributeError: module 'app.bot.handlers.aircraft_update' has no attribute 'build_revision_summary_data'`

- [ ] **Step 3: Extract the function**

In `app/bot/handlers/aircraft_update.py`, replace the body of `update_aircraft_chosen` (currently
lines 49-127) with a new standalone function plus a slimmed-down `update_aircraft_chosen` that
calls it:

```python
def build_revision_summary_data(aircraft, revision) -> dict:
    revision_stations = sorted(
        (station for station in revision.stations if station.active),
        key=lambda station: (
            station_type_order(station.station_type),
            station.display_order,
        ),
    )
    stations = [
        {
            "name": s.name,
            "station_type": s.station_type.value,
            "default_arm_in": compact_decimal(s.default_arm_in),
            "maximum_volume_gal": compact_decimal(s.maximum_volume_gal)
            if s.maximum_volume_gal is not None
            else None,
            "fuel_density_lb_per_gal": compact_decimal(s.fuel_density_lb_per_gal)
            if s.fuel_density_lb_per_gal is not None
            else None,
        }
        for s in revision_stations
    ]
    envelope_rows = [
        {
            "weight_lb": compact_decimal(r.weight_lb),
            "forward_cg_limit_in": compact_decimal(r.forward_cg_limit_in),
            "aft_cg_limit_in": compact_decimal(r.aft_cg_limit_in),
        }
        for r in sorted(revision.envelope_rows, key=lambda r: r.weight_lb)
    ]
    return {
        "tail_number": aircraft.tail_number,
        "model": aircraft.model,
        "nickname": aircraft.nickname,
        "manufacturer": aircraft.manufacturer,
        "basic_empty_weight_lb": compact_decimal(revision.basic_empty_weight_lb),
        "basic_empty_cg_in": compact_decimal(revision.basic_empty_cg_in),
        "basic_empty_moment_lb_in": compact_decimal(revision.basic_empty_moment_lb_in),
        "max_ramp_weight_lb": compact_decimal(revision.max_ramp_weight_lb)
        if revision.max_ramp_weight_lb is not None
        else None,
        "max_takeoff_weight_lb": compact_decimal(revision.max_takeoff_weight_lb),
        "max_landing_weight_lb": compact_decimal(revision.max_landing_weight_lb)
        if revision.max_landing_weight_lb is not None
        else None,
        "stations": stations,
        "envelope_rows": envelope_rows,
    }


@router.callback_query(F.data.startswith("update:"))
async def update_aircraft_chosen(
    callback: CallbackQuery, state: FSMContext, user: User, aircraft_service: AircraftService
) -> None:
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        await callback.answer()
        return
    revision = await aircraft_service.get_revision_for_user(user.id, aircraft.active_revision_id)
    if revision is None:
        await callback.answer()
        return

    summary_data = build_revision_summary_data(aircraft, revision)

    await state.clear()
    await state.update_data(
        update_mode=True,
        aircraft_id=aircraft.id,
        known_useful_load_lb=compact_decimal(revision.known_useful_load_lb)
        if revision.known_useful_load_lb is not None
        else None,
        source_document_name=revision.source_document_name,
        source_document_date=revision.source_document_date.isoformat()
        if revision.source_document_date
        else None,
        **summary_data,
    )
    await callback.message.answer(
        t(
            "updating_aircraft",
            _lang(user),
            aircraft=aircraft.tail_number,
        ),
        reply_markup=ReplyKeyboardRemove(),
    )
    await goto(callback.message, state, user, AircraftWizard.tail_number, render_tail_number, record_history=False)
    await callback.answer()
```

Double-check the rest of the file (imports, `router`, `_lang`) is unchanged — this task only
touches the body between the `update_aircraft_prompt` function and end of file.

- [ ] **Step 4: Run tests to verify everything passes**

Run: `pytest tests/test_regressions.py::test_build_revision_summary_data_shapes_stations_and_envelope tests/test_regressions.py::test_update_aircraft_chosen_starts_at_tail_number -v`
Expected: both PASS — the second one is the pre-existing regression test, confirming the refactor didn't change `update_aircraft_chosen`'s behavior.

- [ ] **Step 5: Commit**

```bash
git add app/bot/handlers/aircraft_update.py tests/test_regressions.py
git commit -m "Extract build_revision_summary_data from update_aircraft_chosen"
```

---

### Task 4: Add the Download Data handlers to `menu.py`

**Files:**
- Modify: `app/bot/handlers/menu.py` (add imports at top; add two new handlers near the end, after `archive_aircraft_chosen`)
- Test: `tests/test_regressions.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_regressions.py`, after `test_update_aircraft_chosen_starts_at_tail_number`:

```python
async def test_download_data_prompt_lists_aircraft():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def list_aircraft(self, user_id):
            return [SimpleNamespace(id=1, tail_number="N123AB", nickname=None)]

    message = _FakeMessage()
    state = _FakeState({})
    user = SimpleNamespace(id=1, language="en")

    await menu.download_data_prompt(
        message, state, user, aircraft_service=FakeAircraftService()
    )

    assert state.data == {}
    prompt, kwargs = message.answers[-1]
    assert prompt == "Select an aircraft:"
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "download:1"


async def test_download_data_prompt_handles_no_aircraft():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def list_aircraft(self, user_id):
            return []

    message = _FakeMessage()
    state = _FakeState({})
    user = SimpleNamespace(id=1, language="en")

    await menu.download_data_prompt(
        message, state, user, aircraft_service=FakeAircraftService()
    )

    assert message.answers[-1][0] == "You have no aircraft yet. Use \"Add Aircraft\" to create one."


async def test_download_data_chosen_replies_with_summary_and_no_state_change():
    from app.bot.handlers import menu

    class _FakeStation:
        def __init__(self):
            self.name = "Front Seats"
            self.station_type = StationTypeEnum.FRONT_SEATS
            self.display_order = 0
            self.active = True
            self.default_arm_in = D("89")
            self.maximum_volume_gal = None
            self.fuel_density_lb_per_gal = None

    aircraft = SimpleNamespace(
        id=1,
        tail_number="N123AB",
        model="172",
        nickname="Old Bird",
        manufacturer=None,
        active_revision_id=9,
    )
    revision = SimpleNamespace(
        stations=[_FakeStation()],
        envelope_rows=[],
        basic_empty_weight_lb=D("1500"),
        basic_empty_cg_in=D("39"),
        basic_empty_moment_lb_in=D("58500"),
        max_ramp_weight_lb=None,
        max_takeoff_weight_lb=D("2550"),
        max_landing_weight_lb=None,
        known_useful_load_lb=None,
        source_document_name=None,
        source_document_date=None,
    )

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return aircraft

        async def get_revision_for_user(self, user_id, revision_id):
            return revision

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState({})
    callback = _FakeCallback(_FakeMessage())
    callback.data = "download:1"

    await menu.download_data_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert state.data == {}
    assert state.current_state is None
    reply_text, _ = callback.message.answers[-1]
    assert "N123AB — 172" in reply_text
    assert "Front Seats" in reply_text
    assert callback.answers == [((), {})]


async def test_download_data_chosen_alerts_when_aircraft_not_found():
    from app.bot.handlers import menu

    class FakeAircraftService:
        async def get_aircraft(self, user_id, aircraft_id):
            return None

    user = SimpleNamespace(id=1, language="en")
    state = _FakeState({})
    callback = _FakeCallback(_FakeMessage())
    callback.data = "download:1"

    await menu.download_data_chosen(
        callback, state, user, aircraft_service=FakeAircraftService()
    )

    assert callback.answers == [
        (("Aircraft not found. It may have been archived.",), {"show_alert": True})
    ]
    assert callback.message.answers == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_regressions.py -k download_data -v`
Expected: all 4 FAIL with `AttributeError: module 'app.bot.handlers.menu' has no attribute 'download_data_prompt'` (and similarly for `download_data_chosen`).

- [ ] **Step 3: Add the handlers**

In `app/bot/handlers/menu.py`, add two imports at the top (with the other `app.bot` imports,
e.g. right after the existing `from app.services.flight_service import FlightService` line):

```python
from app.bot.handlers.aircraft_update import build_revision_summary_data
from app.bot.handlers.aircraft_wizard import render_summary
```

Then add the two new handlers at the end of the file, after `archive_aircraft_chosen`:

```python
@router.message(F.text == t("menu_download_data"))
async def download_data_prompt(
    message: Message,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    await state.clear()
    lang = _lang(user)
    aircraft_list = await aircraft_service.list_aircraft(user.id)
    if not aircraft_list:
        await message.answer(t("no_aircraft_yet", lang))
        return
    await message.answer(
        t("select_aircraft_prompt", lang), reply_markup=aircraft_list_keyboard(aircraft_list, "download")
    )


@router.callback_query(F.data.startswith("download:"))
async def download_data_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    aircraft_service: AircraftService,
) -> None:
    lang = _lang(user)
    aircraft_id = int(callback.data.split(":")[1])
    aircraft = await aircraft_service.get_aircraft(user.id, aircraft_id)
    if aircraft is None or aircraft.active_revision_id is None:
        await callback.answer(t("aircraft_not_found", lang), show_alert=True)
        return
    revision = await aircraft_service.get_revision_for_user(user.id, aircraft.active_revision_id)
    if revision is None:
        await callback.answer(t("aircraft_not_found", lang), show_alert=True)
        return
    summary_data = build_revision_summary_data(aircraft, revision)
    await callback.message.answer(render_summary(summary_data, lang))
    await callback.answer()
```

Also add `aircraft_list_keyboard` to the existing `from app.bot.keyboards.common import (...)`
block at the top of `menu.py` (it currently imports `aircraft_card_keyboard`,
`aircraft_list_keyboard` — check first: it's already imported, since `select_aircraft_prompt`
and `archive_aircraft_prompt` both use it. No change needed there.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_regressions.py -k download_data -v`
Expected: all 4 PASS

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: all tests PASS, including `test_every_literal_translation_key_exists` (confirms
`menu_download_data` resolves) and the untouched Edit/Archive Aircraft tests.

- [ ] **Step 6: Commit**

```bash
git add app/bot/handlers/menu.py tests/test_regressions.py
git commit -m "Add Download Data handlers to the Aircraft submenu"
```

---

## Post-implementation checklist

- [ ] `pytest -v` passes with zero failures.
- [ ] Manually trace the flow once more against the spec: Aircraft submenu → "📥 Download Data" →
  pick an aircraft → reply is a read-only summary, no state left behind, no aircraft/revision
  rows written or changed.
- [ ] Confirm no other file needed changes — this feature is fully contained to
  `i18n.py`, `keyboards/common.py`, `handlers/aircraft_update.py`, `handlers/menu.py`, plus tests.
