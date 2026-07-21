import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from aiogram.types import BotCommandScopeAllPrivateChats, MenuButtonCommands

from app.bot.commands import COMMAND_TEXT_KEYS, bot_commands, configure_bot_ui
from app.bot.handlers.aircraft_wizard import render_summary
from app.bot.handlers.menu import _aircraft_banner, cmd_start
from app.bot.handlers.flight_calculation import _fuel_start_keyboard, _load_keyboard
from app.bot.handlers.quick_calculate import (
    _fuel_keyboard,
    _step_keyboard,
    calculation_mode_keyboard,
    show_calculation_options,
)
from app.bot.keyboards.common import main_menu_keyboard
from app.bot.middlewares.db_session import preferred_language
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

    async def clear(self):
        self.cleared = True


class _FakeMessage:
    def __init__(self):
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


async def test_telegram_command_menu_is_registered_in_english_and_russian():
    bot = _FakeBot()

    await configure_bot_ui(bot)

    assert len(bot.command_calls) == 2
    english, english_kwargs = bot.command_calls[0]
    russian, russian_kwargs = bot.command_calls[1]
    assert [command.command for command in english] == [item[0] for item in COMMAND_TEXT_KEYS]
    assert [command.command for command in russian] == [item[0] for item in COMMAND_TEXT_KEYS]
    assert isinstance(english_kwargs["scope"], BotCommandScopeAllPrivateChats)
    assert "language_code" not in english_kwargs
    assert russian_kwargs["language_code"] == "ru"
    assert len(bot.menu_calls) == 1
    assert isinstance(bot.menu_calls[0]["menu_button"], MenuButtonCommands)


def test_bot_commands_satisfy_telegram_length_rules():
    for lang in ("en", "ru"):
        commands = bot_commands(lang)
        assert commands
        assert all(1 <= len(command.command) <= 32 for command in commands)
        assert all(1 <= len(command.description) <= 256 for command in commands)


def test_main_menu_reply_keyboard_is_persistent_and_localized():
    english = main_menu_keyboard("en")
    russian = main_menu_keyboard("ru")

    assert english.is_persistent is True
    assert russian.is_persistent is True
    assert english.input_field_placeholder == STRINGS["menu_placeholder"]["en"]
    assert russian.input_field_placeholder == STRINGS["menu_placeholder"]["ru"]
    assert english.keyboard[0][0].text != russian.keyboard[0][0].text


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
        "max_zero_fuel_weight_lb": None,
        "stations": [
            {
                "name": "Rear Seats",
                "station_type": "REAR_SEATS",
                "default_arm_in": "118",
                "is_adjustable_arm": False,
                "maximum_weight_lb": None,
                "maximum_volume_gal": None,
                "fuel_density_lb_per_gal": None,
            },
            {
                "name": "Main Fuel Tanks",
                "station_type": "FUEL",
                "default_arm_in": "75",
                "is_adjustable_arm": False,
                "maximum_weight_lb": None,
                "maximum_volume_gal": "40",
                "fuel_density_lb_per_gal": "6",
            },
            {
                "name": "Front Seats",
                "station_type": "FRONT_SEATS",
                "default_arm_in": "89",
                "is_adjustable_arm": False,
                "maximum_weight_lb": None,
                "maximum_volume_gal": None,
                "fuel_density_lb_per_gal": None,
            },
            {
                "name": "Aux Fuel Tanks",
                "station_type": "FUEL",
                "default_arm_in": "94",
                "is_adjustable_arm": False,
                "maximum_weight_lb": None,
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
    assert "Max Zero Fuel Weight" not in summary
    assert summary.index("Front Seats") < summary.index("Rear Seats")


def _inline_callbacks(keyboard):
    return [button.callback_data for row in keyboard.inline_keyboard for button in row]


def test_calculation_shortcuts_do_not_offer_literal_zero_buttons():
    quick_load = _step_keyboard("en", last_value="180.0000", unit="lb")
    quick_fuel = _fuel_keyboard("en", full_gal=Decimal("53.0000"))
    advanced_load = _load_keyboard(
        "en",
        last_value="180.0000",
        last_arm=None,
        adjustable=False,
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
    assert "Full tanks — 53 gal (saved capacity)" == quick_fuel.inline_keyboard[0][0].text
    assert all(
        "Use last" not in button.text
        for keyboard in (quick_fuel, advanced_fuel)
        for row in keyboard.inline_keyboard
        for button in row
    )


def test_new_user_language_follows_supported_telegram_locale():
    assert preferred_language("ru-RU", "en") == "ru"
    assert preferred_language("en-US", "ru") == "en"
    assert preferred_language("de-DE", "ru") == "ru"
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
    assert menu_markup.keyboard[0][0].text == STRINGS["menu_new_calc"]["en"]


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

    russian = calculation_mode_keyboard("ru")
    assert russian.inline_keyboard[1][0].text == STRINGS["btn_takeoff_landing"]["ru"]


def test_every_literal_translation_key_exists_and_has_both_languages():
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
    assert all("en" in translations and "ru" in translations for translations in STRINGS.values())
