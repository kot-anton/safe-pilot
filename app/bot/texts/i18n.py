"""Centralized user-facing strings. English is the default; Russian is supported.

Add a new language by adding another key to each entry -- no other code needs to change.
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "welcome": {
        "en": (
            "Weight & Balance assistant for privately owned GA aircraft.\n\n"
            "This bot performs deterministic Weight & Balance math on aircraft data that "
            "*you* enter and confirm. It does not look anything up, and it does not guess."
        ),
        "ru": (
            "Помощник по расчёту центровки и загрузки для частных ВС.\n\n"
            "Бот выполняет детерминированные расчёты на основе данных, которые вводите "
            "и подтверждаете *вы сами*. Он ничего не ищет и ничего не додумывает."
        ),
    },
    "main_menu": {
        "en": "Main menu:",
        "ru": "Главное меню:",
    },
    "menu_my_aircraft": {"en": "My Aircrafts", "ru": "Мои ВС"},
    "menu_add_aircraft": {"en": "Add Aircraft", "ru": "Добавить ВС"},
    "menu_select_aircraft": {"en": "🛩 Change Aircraft", "ru": "🛩 Сменить ВС"},
    "menu_update_aircraft": {"en": "Edit Aircraft", "ru": "Изменить ВС"},
    "menu_archive_aircraft": {"en": "Archive Aircraft", "ru": "Архивировать ВС"},
    "menu_rental_aircraft": {"en": "Temporary / Rental Aircraft", "ru": "Временное / арендованное ВС"},
    "menu_new_calc": {"en": "✈️ Calculate", "ru": "✈️ Рассчитать"},
    "menu_aircraft_submenu": {"en": "🛩 Aircraft", "ru": "🛩 Самолёт"},
    "menu_more_submenu": {"en": "⚙️ More", "ru": "⚙️ Ещё"},
    "menu_back": {"en": "« Main menu", "ru": "« Главное меню"},
    "menu_history": {"en": "Calculation History", "ru": "История расчётов"},
    "menu_help": {"en": "Help", "ru": "Помощь"},
    "menu_cancel": {"en": "Cancel", "ru": "Отмена"},
    "btn_back": {"en": "« Back", "ru": "« Назад"},
    "btn_skip": {"en": "Skip", "ru": "Пропустить"},
    "btn_confirm": {"en": "✅ Confirm", "ru": "✅ Подтвердить"},
    "btn_edit": {"en": "✏️ Edit", "ru": "✏️ Изменить"},
    "btn_cancel": {"en": "✖ Cancel", "ru": "✖ Отмена"},
    "btn_know_cg": {"en": "I know the empty CG", "ru": "Известна центровка (CG)"},
    "btn_know_moment": {"en": "I know the empty moment", "ru": "Известен момент"},
    "btn_yes": {"en": "Yes", "ru": "Да"},
    "btn_no": {"en": "No", "ru": "Нет"},
    "btn_done_adding_stations": {"en": "Done adding stations", "ru": "Готово, станций достаточно"},
    "btn_add_another_station": {"en": "Add another station", "ru": "Добавить ещё станцию"},
    "cancelled": {"en": "Cancelled.", "ru": "Отменено."},
    "no_aircraft_yet": {
        "en": "You have no aircraft yet. Use \"Add Aircraft\" to create one.",
        "ru": "У вас пока нет ВС. Используйте «Добавить ВС», чтобы создать профиль.",
    },
    "no_aircraft_selected": {
        "en": "No aircraft selected. Use \"Select Aircraft\" first.",
        "ru": "ВС не выбрано. Сначала используйте «Выбрать ВС».",
    },
    "ask_tail_number": {"en": "Enter the tail number (registration):", "ru": "Введите бортовой номер:"},
    "ask_nickname": {"en": "Aircraft nickname (optional):", "ru": "Название/прозвище ВС (необязательно):"},
    "ask_manufacturer": {"en": "Manufacturer (optional):", "ru": "Производитель (необязательно):"},
    "ask_model": {"en": "Model:", "ru": "Модель:"},
    "ask_empty_weight": {
        "en": "Basic Empty Weight, in pounds:",
        "ru": "Базовый вес пустого ВС (Basic Empty Weight), в фунтах:",
    },
    "ask_cg_or_moment": {
        "en": "Do you know the empty moment, or the empty CG?",
        "ru": "Что вам известно: момент пустого ВС или центровка (CG)?",
    },
    "ask_empty_cg": {"en": "Basic Empty CG, in inches:", "ru": "Центровка пустого ВС (CG), в дюймах:"},
    "ask_empty_moment": {
        "en": "Basic Empty Moment, in pound-inches:",
        "ru": "Момент пустого ВС, в фунто-дюймах:",
    },
    "ask_max_ramp_weight": {
        "en": "Maximum Ramp Weight, in pounds (optional, Skip if not published):",
        "ru": "Максимальный вес на рулении (Ramp Weight), в фунтах (необязательно):",
    },
    "ask_max_takeoff_weight": {
        "en": "Maximum Takeoff Weight, in pounds (required):",
        "ru": "Максимальный взлётный вес, в фунтах (обязательно):",
    },
    "ask_max_landing_weight": {
        "en": "Maximum Landing Weight, in pounds (optional):",
        "ru": "Максимальный посадочный вес, в фунтах (необязательно):",
    },
    "ask_max_zfw": {
        "en": "Maximum Zero Fuel Weight, in pounds (optional):",
        "ru": "Максимальный вес без топлива (ZFW), в фунтах (необязательно):",
    },
    "ask_known_useful_load": {
        "en": "Known Useful Load, in pounds (optional, consistency check only):",
        "ru": "Известная полезная нагрузка, в фунтах (необязательно, только для проверки):",
    },
    "useful_load_ok": {
        "en": "Useful load check: entered value matches the calculated useful load.",
        "ru": "Проверка полезной нагрузки: введённое значение совпадает с расчётным.",
    },
    "ask_add_station": {
        "en": "Let's configure stations (seats, baggage, fuel tanks). Add a station?",
        "ru": "Настроим станции (места, багаж, топливные баки). Добавить станцию?",
    },
    "ask_station_name": {"en": "Station name:", "ru": "Название станции:"},
    "ask_station_type": {"en": "Station type:", "ru": "Тип станции:"},
    "ask_station_arm": {"en": "ARM, in inches:", "ru": "Плечо (ARM), в дюймах:"},
    "ask_station_arm_fixed_or_adjustable": {
        "en": "Is this ARM fixed, or adjustable (e.g. an adjustable seat)?",
        "ru": "Плечо фиксированное или регулируемое (например, сиденье)?",
    },
    "btn_arm_fixed": {"en": "Fixed", "ru": "Фиксированное"},
    "btn_arm_adjustable": {"en": "Adjustable", "ru": "Регулируемое"},
    "ask_station_min_arm": {"en": "Minimum ARM, in inches:", "ru": "Минимальное плечо, в дюймах:"},
    "ask_station_max_arm": {"en": "Maximum ARM, in inches:", "ru": "Максимальное плечо, в дюймах:"},
    "ask_fuel_max_volume": {
        "en": "Maximum fuel volume for this tank, in US gal:",
        "ru": "Максимальный объём топлива в этом баке, в US гал:",
    },
    "review_aircraft_summary": {"en": "Please review the aircraft profile:", "ru": "Проверьте профиль ВС:"},
    "aircraft_saved": {"en": "Aircraft profile saved.", "ru": "Профиль ВС сохранён."},
    "revision_saved": {
        "en": "New aircraft revision saved. Historical data and past calculations are unaffected.",
        "ru": "Сохранена новая ревизия ВС. Исторические данные и прошлые расчёты не изменены.",
    },
    "my_aircraft_header": {"en": "Your aircrafts:", "ru": "Ваши ВС:"},
    "result_footer": {
        "en": "Based on the saved aircraft profile. Verify against current aircraft records.",
        "ru": "На основе сохранённого профиля ВС. Сверьте с актуальной документацией ВС.",
    },
    "select_aircraft_prompt": {"en": "Select an aircraft:", "ru": "Выберите ВС:"},
    "aircraft_selected": {"en": "Active aircraft set.", "ru": "Активное ВС установлено."},
    "ask_load_at_station": {"en": "{station} weight, in lb:", "ru": "Вес на «{station}», в фунтах:"},
    "ask_fuel_starting": {"en": "Starting fuel in {station}, in US gal:", "ru": "Начальное топливо в {station}, в US гал:"},
    "ask_fuel_enroute": {
        "en": "Planned fuel burn from {station}, in US gal (Skip = landing not evaluated):",
        "ru": "Плановый расход из {station}, US гал (Пропустить = посадка не оценивается):",
    },
    "review_flight_inputs": {"en": "Please confirm your inputs:", "ru": "Подтвердите введённые данные:"},
    "calculation_running": {"en": "Calculating...", "ru": "Выполняется расчёт..."},
    "landing_not_evaluated": {
        "en": "⚠️ Landing condition not evaluated (no landing fuel or enroute burn entered).",
        "ru": "⚠️ Посадочное состояние не оценивалось (не введён расход или остаток топлива на посадку).",
    },
    "status_within": {"en": "✅ WITHIN ENTERED LIMITS", "ru": "✅ В ПРЕДЕЛАХ ВВЕДЁННЫХ ОГРАНИЧЕНИЙ"},
    "status_on_limit": {"en": "⚠️ ON LIMIT", "ru": "⚠️ НА ГРАНИЦЕ ОГРАНИЧЕНИЯ"},
    "status_out_of_limits": {"en": "❌ OUT OF LIMITS", "ru": "❌ ВНЕ ОГРАНИЧЕНИЙ"},
    "status_incomplete": {
        "en": "⚠️ INCOMPLETE — LANDING CONDITION NOT EVALUATED",
        "ru": "⚠️ НЕПОЛНО — ПОСАДОЧНОЕ СОСТОЯНИЕ НЕ ОЦЕНЕНО",
    },
    "recommendations_header": {"en": "Suggested adjustments:", "ru": "Возможные варианты корректировки:"},
    "no_recommendations": {
        "en": (
            "No single fuel, baggage, or load-move adjustment brings every phase within limits "
            "at once. A different loading arrangement (who sits where, how fuel is split) may "
            "still work, but isn't something this solver searches for automatically."
        ),
        "ru": (
            "Ни одна корректировка топлива, багажа или груза не приводит все фазы полёта в "
            "пределы одновременно. Другая схема загрузки (кто где сидит, как разлито топливо) "
            "может сработать, но автоматически не подбирается."
        ),
    },
    "history_empty": {"en": "No calculations recorded yet.", "ru": "Расчётов пока нет."},
    "help_text": {
        "en": (
            "This bot calculates Weight & Balance (ramp, takeoff, landing) from aircraft data "
            "you enter yourself. It does not search any database, does not read documents, and "
            "does not use AI to calculate. All aircraft data must be entered and confirmed by "
            "you. Use the menu to add an aircraft, select it, and run a new calculation."
        ),
        "ru": (
            "Бот рассчитывает центровку и загрузку (руление, взлёт, посадка) на основе данных, "
            "которые вводите вы сами. Он не ищет базы данных, не читает документы и не "
            "использует ИИ для расчётов. Все данные по ВС должны быть введены и подтверждены "
            "вами. Используйте меню, чтобы добавить ВС, выбрать его и выполнить расчёт."
        ),
    },
    "error_invalid_number": {"en": "Please enter a valid number.", "ru": "Пожалуйста, введите корректное число."},
    "error_negative": {"en": "Value cannot be negative.", "ru": "Значение не может быть отрицательным."},
    "error_generic": {
        "en": "Something went wrong with that input: {detail}",
        "ru": "Ошибка во введённых данных: {detail}",
    },
}


def t(key: str, lang: str = "en", **kwargs) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    template = entry.get(lang, entry.get("en", key))
    return template.format(**kwargs) if kwargs else template
