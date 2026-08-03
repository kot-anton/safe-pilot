import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import BotCommandScopeAllPrivateChats, MenuButtonCommands

from app.bot.commands import COMMAND_TEXT_KEYS, bot_commands, configure_bot_ui
from app.bot.handlers.aircraft_wizard import render_summary, start_wizard
from app.bot.handlers.menu import _aircraft_banner, cmd_start
from app.bot.handlers.flight_calculation import _fuel_start_keyboard, _load_keyboard
from app.bot.handlers.quick_calculate import (
    _fuel_keyboard,
    _step_keyboard,
    calculation_mode_keyboard,
    show_calculation_options,
)
from app.bot.keyboards.common import aircraft_list_keyboard, envelope_keyboard, main_menu_keyboard
from app.bot.middlewares.db_session import preferred_language
from app.bot.states.aircraft_wizard import AircraftWizard
from app.bot.texts.i18n import STRINGS


class _FakeBot:
    def __init__(self):
        self.command_calls = []
        self.menu_calls = []

    async def set_my_commands(self, commands, **kwargs):
        self.command_calls.append((commands, kwargs))

    async def set_chat_menu_button(self, **kwargs):
        self.menu_calls.append(kwargs)


class _FakeState:
    def __init__(self):
        self.cleared = False
        self.data = {}
        self.current_state = None

    async def clear(self):
        self.cleared = True
        self.data = {}
        self.current_state = None

    async def get_data(self):
        return self.data

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current_state = state

    async def get_state(self):
        return self.current_state.state if hasattr(self.current_state, "state") else self.current_state


class _FakeMessage:
    def __init__(self):
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


async def test_telegram_command_menu_is_registered():
    bot = _FakeBot()

    await configure_bot_ui(bot)

    assert len(bot.command_calls) == 1
    english, english_kwargs = bot.command_calls[0]
    assert [command.command for command in english] == [item[0] for item in COMMAND_TEXT_KEYS]
    assert isinstance(english_kwargs["scope"], BotCommandScopeAllPrivateChats)
    assert "language_code" not in english_kwargs
    assert len(bot.menu_calls) == 1
    assert isinstance(bot.menu_calls[0]["menu_button"], MenuButtonCommands)


def test_bot_commands_satisfy_telegram_length_rules():
    for lang in ("en",):
        commands = bot_commands(lang)
        assert commands
        assert all(1 <= len(command.command) <= 32 for command in commands)
        assert all(1 <= len(command.description) <= 256 for command in commands)


def test_main_menu_reply_keyboard_is_persistent_and_localized():
    english = main_menu_keyboard("en")

    assert english.is_persistent is True
    assert english.input_field_placeholder == STRINGS["menu_placeholder"]


def test_download_data_menu_string_exists():
    assert STRINGS["menu_download_data"] == "📥 Download Data"


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


def test_aircraft_review_is_compact_and_hides_internal_station_enums():
    data = {
        "tail_number": "N4508D",
        "model": "Bonanza",
        "nickname": None,
        "manufacturer": None,
        "basic_empty_weight_lb": "1960.8",
        "basic_empty_cg_in": "79.1300",
        "basic_empty_moment_lb_in": "155158.1040",
        "max_ramp_weight_lb": "2785",
        "max_takeoff_weight_lb": "2775",
        "max_landing_weight_lb": "2775",
        "stations": [
            {
                "name": "Rear Seats",
                "station_type": "REAR_SEATS",
                "default_arm_in": "118",
                "maximum_volume_gal": None,
                "fuel_density_lb_per_gal": None,
            },
            {
                "name": "Main Fuel Tanks",
                "station_type": "FUEL",
                "default_arm_in": "75",
                "maximum_volume_gal": "40",
                "fuel_density_lb_per_gal": "6",
            },
            {
                "name": "Front Seats",
                "station_type": "FRONT_SEATS",
                "default_arm_in": "89",
                "maximum_volume_gal": None,
                "fuel_density_lb_per_gal": None,
            },
            {
                "name": "Aux Fuel Tanks",
                "station_type": "FUEL",
                "default_arm_in": "94",
                "maximum_volume_gal": "13.0000",
                "fuel_density_lb_per_gal": "6",
            },
        ],
        "envelope_rows": [
            {
                "weight_lb": "2265",
                "forward_cg_limit_in": "76.5",
                "aft_cg_limit_in": "85.7",
            }
        ],
    }

    summary = render_summary(data, "en")

    assert "REAR_SEATS" not in summary
    assert "FRONT_SEATS" not in summary
    assert "(FUEL)" not in summary
    assert "N4508D — Bonanza" in summary
    assert "CG: 79.13 in" in summary
    assert "Moment:" not in summary
    assert "LOAD STATIONS (2)" in summary
    assert "FUEL TANKS (Main, Aux)" in summary
    assert "Total usable fuel: 53 gal" in summary
    assert "• Main — ARM 75 in" in summary
    assert "• Aux — ARM 94 in" in summary
    assert "Usable: 40 gal" in summary
    assert "Usable: 13 gal" in summary
    assert "Density:" not in summary
    assert summary.index("Front Seats") < summary.index("Rear Seats")


def test_envelope_keyboard_offers_edit_alongside_remove_only_once_rows_exist():
    """Fixing one typo in an envelope row used to mean deleting the whole row and re-typing all
    three numbers. Edit now sits next to Remove, matching the Edit/Remove pattern already used
    for stations -- but neither makes sense to show before any row has been entered."""
    no_rows = envelope_keyboard("en", has_rows=False)
    with_rows = envelope_keyboard("en", has_rows=True)

    no_rows_callbacks = _inline_callbacks(no_rows)
    with_rows_callbacks = _inline_callbacks(with_rows)
    assert "wizard:edit_row_prompt" not in no_rows_callbacks
    assert "wizard:remove_row_prompt" not in no_rows_callbacks
    assert "wizard:edit_row_prompt" in with_rows_callbacks
    assert "wizard:remove_row_prompt" in with_rows_callbacks


def test_aircraft_picker_label_uses_nickname_not_model():
    """Manufacturer/model are no longer collected by the wizard, so aircraft pickers (Update,
    Select, Archive) must key their label off nickname instead of the old "{tail} ({model})"
    format."""
    named = SimpleNamespace(id=1, tail_number="N100AA", nickname="The Trainer")
    unnamed = SimpleNamespace(id=2, tail_number="N200BB", nickname=None)

    keyboard = aircraft_list_keyboard([named, unnamed], "update")

    assert keyboard.inline_keyboard[0][0].text == "N100AA — The Trainer"
    assert keyboard.inline_keyboard[1][0].text == "N200BB"


async def test_add_aircraft_goes_straight_to_tail_number_without_a_mode_picker():
    """The Quick/Advanced Setup picker was removed entirely -- Add Aircraft should ask for the
    tail number immediately instead of an intermediate mode-choice screen."""
    state = _FakeState()
    message = _FakeMessage()
    user = SimpleNamespace(id=1, language="en")

    await start_wizard(message, state, user)

    assert state.current_state == AircraftWizard.tail_number
    assert not any("Quick Setup" in text or "Advanced Setup" in text for text, _ in message.answers)
    assert any("tail number" in text.lower() for text, _ in message.answers)


def _inline_callbacks(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_calculation_shortcuts_do_not_offer_literal_zero_buttons():
    quick_load = _step_keyboard("en", last_value="180.0000", unit="lb")
    quick_fuel = _fuel_keyboard("en", full_gal=Decimal("53.0000"))
    advanced_load = _load_keyboard(
        "en",
        last_value="180.0000",
        show_back=False,
    )
    advanced_fuel = _fuel_start_keyboard("en", capacity=Decimal("20"))

    for keyboard in (quick_load, quick_fuel, advanced_load, advanced_fuel):
        assert all(
            button.text != "0"
            for row in keyboard.inline_keyboard
            for button in row
        )

    assert "quick:use_last" in _inline_callbacks(quick_load)
    assert "quick:full" in _inline_callbacks(quick_fuel)
    assert "flight:use_last_load" in _inline_callbacks(advanced_load)
    assert "flight:full_fuel" in _inline_callbacks(advanced_fuel)
    assert "quick:use_last" not in _inline_callbacks(quick_fuel)
    assert "flight:use_last_fuel" not in _inline_callbacks(advanced_fuel)
    assert quick_load.inline_keyboard[0][0].text == "Use last: 180 lb"
    assert "Full tanks (53 gal usable)" == quick_fuel.inline_keyboard[0][0].text
    assert all(
        "Use last" not in button.text
        for keyboard in (quick_fuel, advanced_fuel)
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_quick_calc_offers_one_tap_zero_shortcut_for_rear_and_baggage_only():
    """A pilot with an empty rear seat or no baggage can tap a "None" shortcut instead of
    typing it -- the callback this button emits must match what quick_calculate.py listens
    for (quick:zero), reachable buttons registered without a handler are as useless as an
    unreachable handler. Front seat and fuel never offer this shortcut: the front seat always
    carries at least the pilot, and the aircraft could not have taken off with zero usable
    fuel on board, so a "None"/"0" answer there is never actually valid."""
    quick_load = _step_keyboard("en", last_value=None, unit="lb")
    front_load = _step_keyboard("en", last_value=None, unit="lb", show_zero=False)
    quick_fuel = _fuel_keyboard("en", full_gal=Decimal("53.0000"))

    load_callbacks = _inline_callbacks(quick_load)
    fuel_callbacks = _inline_callbacks(quick_fuel)
    assert "quick:zero" in load_callbacks
    assert "quick:zero" not in _inline_callbacks(front_load)
    assert "quick:zero" not in fuel_callbacks

    load_zero_button = next(
        button
        for row in quick_load.inline_keyboard
        for button in row
        if button.callback_data == "quick:zero"
    )
    assert load_zero_button.text == "None"


def test_advanced_load_keyboard_offers_same_none_shortcut_except_for_the_front_seat():
    """Advanced should read like Quick calc: a "None" shortcut (same callback the pre-existing
    Skip handler already listens for) on every station's load question except the front seat,
    which always carries at least the pilot."""
    rear_or_baggage = _load_keyboard(
        "en", last_value=None, show_back=False
    )
    front_seat = _load_keyboard(
        "en", last_value=None, show_back=False, show_zero=False
    )

    assert "wizard:skip" in _inline_callbacks(rear_or_baggage)
    assert "wizard:skip" not in _inline_callbacks(front_seat)

    zero_button = next(
        button
        for row in rear_or_baggage.inline_keyboard
        for button in row
        if button.callback_data == "wizard:skip"
    )
    assert zero_button.text == "None"


def test_advanced_fuel_start_keyboard_only_offers_none_shortcut_for_extra_tanks():
    """A tank isn't offered a "None" shortcut unless it's not the aircraft's only fuel
    source -- same reasoning as Quick calc having no zero-fuel shortcut at all."""
    sole_tank = _fuel_start_keyboard("en", capacity=Decimal("20"))
    one_of_several = _fuel_start_keyboard("en", capacity=Decimal("20"), show_zero=True)

    assert "wizard:skip" not in _inline_callbacks(sole_tank)
    assert "wizard:skip" in _inline_callbacks(one_of_several)


def test_new_user_language_is_always_english():
    assert preferred_language("ru-RU", "en") == "en"
    assert preferred_language("en-US", "ru") == "en"
    assert preferred_language("de-DE", "ru") == "en"
    assert preferred_language(None, "unsupported") == "en"


async def test_start_clears_stale_state_and_always_sends_main_menu():
    message = _FakeMessage()
    state = _FakeState()
    user = SimpleNamespace(id=1, language="en", selected_aircraft_id=None)

    await cmd_start(message, state, user, aircraft_service=SimpleNamespace())

    assert state.cleared is True
    assert len(message.answers) == 2
    menu_markup = message.answers[-1][1]["reply_markup"]
    assert menu_markup.is_persistent is True
    assert menu_markup.keyboard[0][0].text == STRINGS["menu_new_calc"]


def test_aircraft_revision_is_not_exposed_in_user_facing_banner():
    aircraft = SimpleNamespace(
        tail_number="N4508D",
        nickname=None,
        model="Cessna 172",
        active_revision=SimpleNamespace(revision_number=7),
    )

    banner = _aircraft_banner(aircraft)

    assert banner == "N4508D -- Cessna 172"
    assert "rev" not in banner.casefold()


async def test_calculation_offers_quick_and_advanced_modes_before_collecting_inputs():
    message = _FakeMessage()
    state = _FakeState()
    user = SimpleNamespace(language="en")

    await show_calculation_options(message, state, user)

    assert state.cleared is True
    assert "Choose a calculation type" in message.answers[-1][0]
    keyboard = message.answers[-1][1]["reply_markup"]
    callbacks = [row[0].callback_data for row in keyboard.inline_keyboard]
    assert callbacks == ["calc:quick", "calc:advanced", "quick:cancel"]

    keyboard = calculation_mode_keyboard("en")
    assert keyboard.inline_keyboard[1][0].text == STRINGS["btn_takeoff_landing"]


def test_every_literal_translation_key_exists():
    missing_keys = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            key = node.args[0].value
            if key not in STRINGS:
                missing_keys.append((path, node.lineno, key))

    assert missing_keys == []
