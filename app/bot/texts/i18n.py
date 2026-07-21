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
    "aircraft_menu": {"en": "Aircraft menu:", "ru": "Меню самолёта:"},
    "more_menu": {"en": "More options:", "ru": "Дополнительные функции:"},
    "menu_placeholder": {"en": "Choose an action", "ru": "Выберите действие"},
    "menu_my_aircraft": {"en": "My Aircraft", "ru": "Мои ВС"},
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
    "btn_keep": {"en": "↩️ Keep current", "ru": "↩️ Оставить текущее"},
    "btn_keep_cg_moment": {
        "en": "↩️ Keep current CG / moment",
        "ru": "↩️ Оставить текущие CG / момент",
    },
    "btn_confirm": {"en": "✅ Confirm", "ru": "✅ Подтвердить"},
    "btn_edit": {"en": "✏️ Edit", "ru": "✏️ Изменить"},
    "btn_cancel": {"en": "✖ Cancel", "ru": "✖ Отмена"},
    "btn_know_cg": {"en": "I know the empty CG", "ru": "Известна центровка (CG)"},
    "btn_know_moment": {"en": "I know the empty moment", "ru": "Известен момент"},
    "btn_yes": {"en": "Yes", "ru": "Да"},
    "btn_no": {"en": "No", "ru": "Нет"},
    "btn_calculate": {"en": "Calculate", "ru": "Рассчитать"},
    "btn_quick_takeoff": {
        "en": "Takeoff — Quick",
        "ru": "Взлёт — быстро",
    },
    "btn_takeoff_landing": {
        "en": "Takeoff + Landing — Advanced",
        "ru": "Взлёт + посадка — расширенно",
    },
    "btn_main_menu": {"en": "Main menu", "ru": "Главное меню"},
    "btn_change_load": {"en": "Change load", "ru": "Изменить загрузку"},
    "btn_advanced_landing": {
        "en": "Advanced / Landing",
        "ru": "Расширенный / Посадка",
    },
    "btn_exact_tank_split": {
        "en": "Enter exact tank quantities",
        "ru": "Указать топливо по каждому баку",
    },
    "btn_quick_setup": {
        "en": "⚡ Quick Setup (recommended)",
        "ru": "⚡ Быстрая настройка (рекомендуется)",
    },
    "btn_advanced_setup": {
        "en": "🛠 Advanced Setup",
        "ru": "🛠 Расширенная настройка",
    },
    "btn_edit_station": {"en": "✏️ Edit a station", "ru": "✏️ Изменить станцию"},
    "btn_remove_station": {"en": "🗑 Remove a station", "ru": "🗑 Удалить станцию"},
    "btn_rename": {"en": "✏️ Rename", "ru": "✏️ Переименовать"},
    "btn_change_type": {"en": "🔁 Change type", "ru": "🔁 Изменить тип"},
    "btn_clear_limit": {"en": "Clear limit", "ru": "Удалить ограничение"},
    "btn_done": {"en": "✅ Done", "ru": "✅ Готово"},
    "btn_done_no_more_stations": {
        "en": "✅ Done — no more stations",
        "ru": "✅ Готово — больше станций нет",
    },
    "btn_remove_row": {"en": "🗑 Remove a row", "ru": "🗑 Удалить строку"},
    "btn_skip_envelope": {
        "en": "⚠️ Skip — do not evaluate CG",
        "ru": "⚠️ Пропустить — не оценивать CG",
    },
    "btn_use_suggested": {
        "en": "✅ Use \"{value}\"",
        "ru": "✅ Использовать «{value}»",
    },
    "btn_done_adding_stations": {"en": "Done adding stations", "ru": "Готово, станций достаточно"},
    "btn_add_another_station": {"en": "Add another station", "ru": "Добавить ещё станцию"},
    "cancelled": {"en": "Cancelled.", "ru": "Отменено."},
    "no_aircraft_yet": {
        "en": "You have no aircraft yet. Use \"Add Aircraft\" to create one.",
        "ru": "У вас пока нет ВС. Используйте «Добавить ВС», чтобы создать профиль.",
    },
    "no_aircraft_selected": {
        "en": "No aircraft selected. Use \"Change Aircraft\" first.",
        "ru": "ВС не выбрано. Сначала используйте «Сменить ВС».",
    },
    "aircraft_not_found": {
        "en": "Aircraft not found. It may have been archived.",
        "ru": "Самолёт не найден. Возможно, он был архивирован.",
    },
    "aircraft_archived": {
        "en": "{aircraft} archived.",
        "ru": "{aircraft} перемещён в архив.",
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
        "en": "Which Basic Empty value is listed in the aircraft records: CG or moment?",
        "ru": "Что указано в документах для базового пустого ВС: центровка (CG) или момент?",
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
        "en": (
            "Published Maximum Zero Fuel Weight (MZFW), in pounds. Enter this only if the "
            "current POH/AFM or supplement explicitly publishes an MZFW; otherwise tap Skip:"
        ),
        "ru": (
            "Опубликованный максимальный вес без топлива (MZFW), в фунтах. Вводите только "
            "если MZFW прямо указан в актуальном РЛЭ/AFM или дополнении; иначе нажмите «Пропустить»:"
        ),
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
    "stations_added": {"en": "Added so far:", "ru": "Уже добавлены:"},
    "ask_remove_station": {
        "en": "Which station do you want to remove?",
        "ru": "Какую станцию удалить?",
    },
    "ask_edit_station": {
        "en": "Which station do you want to edit?",
        "ru": "Какую станцию изменить?",
    },
    "station_removed": {"en": "Removed {station}.", "ru": "Станция {station} удалена."},
    "station_added": {"en": "Station \"{station}\" added.", "ru": "Станция «{station}» добавлена."},
    "station_updated": {"en": "Station updated.", "ru": "Станция изменена."},
    "station_name_updated": {"en": "Station name updated.", "ru": "Название станции изменено."},
    "station_type_updated": {"en": "Station type updated.", "ru": "Тип станции изменён."},
    "row_removed": {"en": "Row removed.", "ru": "Строка удалена."},
    "not_set": {"en": "not set", "ru": "не задано"},
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
    "ask_station_max_weight": {
        "en": "Maximum load for this station, in pounds (optional; Skip if not published):",
        "ru": "Максимальная нагрузка этой станции, в фунтах (необязательно; пропустите, если не опубликована):",
    },
    "ask_fuel_max_volume": {
        "en": "Maximum usable fuel volume for this tank, in US gal:",
        "ru": "Максимальный полезный объём топлива в этом баке, в US гал:",
    },
    "ask_fuel_density": {
        "en": (
            "Fuel type/density is needed to convert gallons to weight. Enter lb per US gal "
            "or use the 100LL value:"
        ),
        "ru": (
            "Тип/плотность топлива нужны для перевода галлонов в вес. Введите фунт/US гал "
            "или используйте значение для 100LL:"
        ),
    },
    "btn_use_100ll_density": {
        "en": "Use 6.0 lb/gal (100LL)",
        "ru": "Использовать 6.0 фунт/гал (100LL)",
    },
    "station_type_front": {"en": "Front Seats", "ru": "Передние места"},
    "station_type_rear": {"en": "Rear Seats", "ru": "Задние места"},
    "station_type_baggage": {"en": "Baggage Area", "ru": "Багажный отсек"},
    "station_type_fuel": {"en": "Fuel Tank", "ru": "Топливный бак"},
    "station_type_custom": {"en": "Custom Station", "ru": "Другая станция"},
    "advanced_label": {"en": "Advanced", "ru": "Расширенно"},
    "setup_started": {"en": "Starting aircraft setup…", "ru": "Начинаем настройку самолёта…"},
    "setup_intro": {
        "en": (
            "Quick Setup collects the data required for a normal calculation: Basic Empty "
            "Weight and CG/moment, maximum takeoff weight, stations, fuel tanks, and the CG "
            "envelope. Advanced Setup also collects optional ramp, landing, and zero-fuel "
            "limits plus a useful-load consistency check."
        ),
        "ru": (
            "Быстрая настройка собирает данные для обычного расчёта: базовый вес пустого ВС "
            "и CG/момент, максимальный взлётный вес, станции, баки и диапазон центровки. "
            "Расширенная настройка также запрашивает необязательные ограничения для руления, "
            "посадки и веса без топлива, а также проверяет полезную нагрузку."
        ),
    },
    "rental_setup_started": {
        "en": "Setting up a temporary/rental aircraft with Quick Setup.",
        "ru": "Настраиваем временный/арендованный самолёт в быстром режиме.",
    },
    "current_value_hint": {
        "en": "current: {value} — send a new value or keep the current one",
        "ru": "текущее значение: {value} — отправьте новое или оставьте текущее",
    },
    "suggested_station_name": {
        "en": "Or use the suggested name below.",
        "ru": "Или используйте предложенное ниже название.",
    },
    "ask_edit_station_arm": {
        "en": "ARM for {station}, in inches (currently {current}):",
        "ru": "Плечо ARM станции {station}, в дюймах (сейчас {current}):",
    },
    "ask_edit_station_name": {
        "en": "New name for station \"{station}\":",
        "ru": "Новое название станции «{station}»: ",
    },
    "ask_edit_station_type": {
        "en": "Type for {station} (currently {current}):",
        "ru": "Тип станции {station} (сейчас {current}):",
    },
    "ask_edit_fuel_volume": {
        "en": "Maximum usable fuel volume for {station}, in US gal (currently {current}):",
        "ru": "Максимальный полезный объём бака {station}, US гал (сейчас {current}):",
    },
    "ask_edit_station_max_weight": {
        "en": "Maximum weight for {station}, in lb (currently {current}):",
        "ru": "Максимальный вес для станции {station}, в фунтах (сейчас {current}):",
    },
    "ask_edit_fuel_density": {
        "en": (
            "Fuel type/density for {station}, used to convert gallons to weight, in lb per "
            "US gal (currently {current}):"
        ),
        "ru": (
            "Тип/плотность топлива для бака {station}, используемые для перевода галлонов "
            "в вес, фунт/US гал (сейчас {current}):"
        ),
    },
    "fuel_like_name_edit_error": {
        "en": (
            "That name looks like a fuel tank. Change the station type to Fuel Tank first so "
            "the bot records gallons, usable capacity, and density."
        ),
        "ru": (
            "Название похоже на топливный бак. Сначала измените тип станции на «Топливный "
            "бак», чтобы бот учитывал галлоны, полезный объём и плотность."
        ),
    },
    "fuel_like_name_new_error": {
        "en": (
            "This name looks like a fuel tank, but the selected type is not Fuel Tank. Go back "
            "and choose Fuel Tank so the bot records gallons, usable capacity, and density."
        ),
        "ru": (
            "Название похоже на топливный бак, но выбран другой тип. Вернитесь назад и выберите "
            "«Топливный бак», чтобы бот учитывал галлоны, полезный объём и плотность."
        ),
    },
    "updating_aircraft": {
        "en": "Updating {aircraft}.",
        "ru": "Изменение {aircraft}.",
    },
    "envelope_prompt": {
        "en": (
            "Enter one CG-envelope row per message as: weight, forward limit, aft limit.\n"
            "Example: 2200, 35.0, 47.3\n\n"
            "For a CG range that does not vary with weight, enter the same limits twice: once "
            "at the minimum published weight and once at the maximum. Add at least two rows in "
            "increasing weight order, then tap Done. If no envelope data is available, tap Skip; "
            "CG will not be evaluated."
        ),
        "ru": (
            "Отправляйте по одной строке диапазона CG в формате: вес, передний предел, задний "
            "предел.\nПример: 2200, 35.0, 47.3\n\n"
            "Если пределы CG не меняются с весом, введите их дважды: для минимального и "
            "максимального опубликованного веса. Добавьте минимум две строки по возрастанию "
            "веса и нажмите «Готово». Если данных нет, нажмите «Пропустить»; CG оцениваться не будет."
        ),
    },
    "envelope_rows_added": {"en": "Rows entered:", "ru": "Введённые строки:"},
    "ask_remove_envelope_row": {
        "en": "Which CG-envelope row do you want to remove?",
        "ru": "Какую строку диапазона CG удалить?",
    },
    "envelope_skipped": {
        "en": (
            "⚠️ CG envelope skipped. Calculations will check entered weight limits only; CG "
            "will show as NOT EVALUATED until an envelope is added through Edit Aircraft."
        ),
        "ru": (
            "⚠️ Диапазон CG пропущен. Расчёты будут проверять только введённые ограничения "
            "веса; CG будет отмечен как НЕ ОЦЕНЕНА, пока диапазон не будет добавлен через "
            "«Изменить ВС»."
        ),
    },
    "review_aircraft_summary": {"en": "✈️ AIRCRAFT PROFILE — REVIEW", "ru": "✈️ ПРОВЕРКА ПРОФИЛЯ ВС"},
    "profile_nickname": {"en": "Nickname: {value}", "ru": "Позывной: {value}"},
    "profile_manufacturer": {"en": "Manufacturer: {value}", "ru": "Производитель: {value}"},
    "profile_empty_aircraft": {"en": "EMPTY AIRCRAFT", "ru": "ПУСТОЙ САМОЛЁТ"},
    "profile_empty_weight": {"en": "Weight: {value}", "ru": "Вес: {value}"},
    "profile_empty_cg": {"en": "CG: {value}", "ru": "CG: {value}"},
    "profile_weight_limits": {"en": "WEIGHT LIMITS", "ru": "ОГРАНИЧЕНИЯ ВЕСА"},
    "profile_limit_ramp": {"en": "Ramp: {value}", "ru": "На перроне: {value}"},
    "profile_limit_takeoff": {"en": "Takeoff: {value}", "ru": "Взлёт: {value}"},
    "profile_limit_landing": {"en": "Landing: {value}", "ru": "Посадка: {value}"},
    "profile_limit_mzfw": {"en": "MZFW: {value}", "ru": "MZFW: {value}"},
    "profile_load_stations": {"en": "LOAD STATIONS ({count})", "ru": "СТАНЦИИ ЗАГРУЗКИ ({count})"},
    "profile_fuel_tanks": {"en": "FUEL TANKS ({tanks})", "ru": "ТОПЛИВНЫЕ БАКИ ({tanks})"},
    "profile_total_usable_fuel": {
        "en": "Total usable fuel: {value}",
        "ru": "Общий полезный объём: {value}",
    },
    "profile_arm_fixed": {"en": "ARM {value}", "ru": "ARM {value}"},
    "profile_arm_adjustable": {
        "en": "ARM {minimum}–{maximum} (default {default})",
        "ru": "ARM {minimum}–{maximum} (по умолчанию {default})",
    },
    "profile_station_max_load": {"en": "Maximum load: {value}", "ru": "Максимальная нагрузка: {value}"},
    "profile_tank_usable": {"en": "Usable: {value}", "ru": "Полезный объём: {value}"},
    "profile_cg_envelope": {"en": "CG ENVELOPE ({count} POINTS)", "ru": "ДИАПАЗОН CG ({count} ТОЧКИ)"},
    "profile_cg_envelope_missing": {
        "en": "⚠️ CG ENVELOPE NOT SAVED — CG WILL NOT BE EVALUATED",
        "ru": "⚠️ ДИАПАЗОН CG НЕ СОХРАНЁН — CG НЕ БУДЕТ ОЦЕНИВАТЬСЯ",
    },
    "aircraft_saved": {"en": "Aircraft profile saved.", "ru": "Профиль ВС сохранён."},
    "revision_saved": {
        "en": "Aircraft changes saved. Previous calculations are unchanged.",
        "ru": "Изменения самолёта сохранены. Предыдущие расчёты не изменены.",
    },
    "my_aircraft_header": {"en": "Your aircraft:", "ru": "Ваши ВС:"},
    "result_footer": {
        "en": "Based on the saved aircraft profile. Verify against current aircraft records.",
        "ru": "На основе сохранённого профиля ВС. Сверьте с актуальной документацией ВС.",
    },
    "select_aircraft_prompt": {"en": "Select an aircraft:", "ru": "Выберите ВС:"},
    "aircraft_selected": {"en": "Active aircraft set.", "ru": "Активное ВС установлено."},
    "aircraft_profile_invalid": {
        "en": "Aircraft profile is invalid: {detail}",
        "ru": "Профиль самолёта содержит ошибку: {detail}",
    },
    "fuel_station_type_error": {
        "en": (
            "Aircraft profile error: these stations look like fuel tanks but are not configured "
            "as Fuel Tank: {stations}. Edit the aircraft profile before calculating; fuel must "
            "be entered in gallons, not pounds."
        ),
        "ru": (
            "Ошибка профиля: эти станции похожи на топливные баки, но имеют другой тип: "
            "{stations}. Измените профиль перед расчётом; топливо вводится в галлонах, а не "
            "в фунтах."
        ),
    },
    "quick_front_prompt": {
        "en": "Combined weight on the front seats, in lb:",
        "ru": "Общий вес на передних местах, в фунтах:",
    },
    "quick_rear_prompt": {
        "en": "Combined weight on the rear seats, in lb:",
        "ru": "Общий вес на задних местах, в фунтах:",
    },
    "quick_baggage_prompt": {
        "en": "Total baggage weight, in lb:",
        "ru": "Общий вес багажа, в фунтах:",
    },
    "quick_fuel_prompt": {
        "en": "Total usable fuel on board at takeoff, in US gal:",
        "ru": "Общий полезный объём топлива на взлёте, в US гал:",
    },
    "quick_fuel_prompt_tanks": {
        "en": "Total usable fuel on board at takeoff ({tanks}), in US gal:",
        "ru": "Общий полезный объём топлива на взлёте ({tanks}), в US гал:",
    },
    "btn_use_last": {"en": "Use last: {value} {unit}", "ru": "Как в прошлый раз: {value} {unit}"},
    "btn_full_fuel": {
        "en": "Full tanks — {value} (saved capacity)",
        "ru": "Полные баки — {value} (сохранённый объём)",
    },
    "btn_full_tank": {"en": "Full tank — {value}", "ru": "Полный бак — {value}"},
    "quick_review_front": {"en": "Front seats", "ru": "Передние места"},
    "quick_review_rear": {"en": "Rear seats", "ru": "Задние места"},
    "quick_review_baggage": {"en": "Baggage", "ru": "Багаж"},
    "quick_review_fuel": {"en": "Usable fuel", "ru": "Полезное топливо"},
    "fuel_capacity_exceeded": {
        "en": "Fuel exceeds the combined usable capacity ({capacity}).",
        "ru": "Топливо превышает общий полезный объём баков ({capacity}).",
    },
    "fuel_tank_capacity_exceeded": {
        "en": "Fuel exceeds this tank's usable capacity ({capacity}).",
        "ru": "Топливо превышает полезный объём этого бака ({capacity}).",
    },
    "fuel_burn_exceeded": {
        "en": "Fuel burn cannot exceed starting fuel ({available}).",
        "ru": "Расход не может превышать запас топлива на взлёте ({available}).",
    },
    "exact_tank_split_required": {
        "en": "Enter the actual gallons in each tank for an exact result.",
        "ru": "Для точного результата укажите фактический объём в каждом баке.",
    },
    "what_next": {"en": "What would you like to do next?", "ru": "Что сделать дальше?"},
    "choose_calculation_mode": {
        "en": (
            "Choose a calculation type:\n\n"
            "Takeoff — Quick asks for combined seat and baggage weights plus total usable fuel.\n\n"
            "Takeoff + Landing — Advanced asks for every configured station and fuel tank, then "
            "lets you enter planned fuel burn to evaluate the landing condition."
        ),
        "ru": (
            "Выберите тип расчёта:\n\n"
            "Взлёт — быстро: общий вес на местах, багаж и общий полезный объём топлива.\n\n"
            "Взлёт + посадка — расширенно: каждая станция и каждый бак, затем плановый расход "
            "топлива для оценки посадочного состояния."
        ),
    },
    "ask_load_at_station": {
        "en": "Weight at {station}, in lb:",
        "ru": "Вес на станции «{station}», в фунтах:",
    },
    "ask_load_at_adjustable_station": {
        "en": (
            "{station}\n"
            "Enter weight in lb and actual ARM in inches as: weight / ARM\n"
            "Allowed ARM: {minimum}–{maximum} in"
        ),
        "ru": (
            "{station}\n"
            "Введите вес в фунтах и фактическое ARM в дюймах как: вес / ARM\n"
            "Допустимое ARM: {minimum}–{maximum} дюйма"
        ),
    },
    "ask_fuel_starting": {
        "en": (
            "Usable fuel in {station} at takeoff, in US gal:\n"
            "Saved usable capacity: {capacity}"
        ),
        "ru": (
            "Полезное топливо в баке {station} на взлёте, в US гал:\n"
            "Сохранённый полезный объём: {capacity}"
        ),
    },
    "ask_fuel_enroute": {
        "en": (
            "Planned fuel burn from {station}, in US gal:\n"
            "Available at takeoff: {available}\n"
            "Skip = do not evaluate landing."
        ),
        "ru": (
            "Плановый расход из бака {station}, в US гал:\n"
            "Доступно на взлёте: {available}\n"
            "Пропустить = не оценивать посадку."
        ),
    },
    "review_flight_inputs": {"en": "Please confirm your inputs:", "ru": "Подтвердите введённые данные:"},
    "calculation_running": {"en": "Calculating...", "ru": "Выполняется расчёт..."},
    "landing_not_evaluated": {
        "en": "⚠️ Landing condition not evaluated (no landing fuel or enroute burn entered).",
        "ru": "⚠️ Посадочное состояние не оценивалось (не введён расход или остаток топлива на посадку).",
    },
    "status_within": {"en": "✅ LOADING WITHIN SAVED LIMITS", "ru": "✅ ЗАГРУЗКА В СОХРАНЁННЫХ ПРЕДЕЛАХ"},
    "status_on_limit": {"en": "⚠️ LOADING ON A SAVED LIMIT", "ru": "⚠️ ЗАГРУЗКА НА ГРАНИЦЕ СОХРАНЁННОГО ОГРАНИЧЕНИЯ"},
    "status_out_of_limits": {"en": "❌ LOADING OUT OF LIMITS", "ru": "❌ ЗАГРУЗКА ВНЕ ОГРАНИЧЕНИЙ"},
    "phase_ramp": {"en": "RAMP", "ru": "НА ПЕРРОНЕ"},
    "phase_takeoff": {"en": "TAKEOFF", "ru": "ВЗЛЁТ"},
    "phase_landing": {"en": "LANDING", "ru": "ПОСАДКА"},
    "phase_status_within": {"en": "✅ WITHIN LIMITS", "ru": "✅ В ПРЕДЕЛАХ"},
    "phase_status_on_limit": {"en": "⚠️ ON A LIMIT", "ru": "⚠️ НА ГРАНИЦЕ"},
    "phase_status_out_of_limits": {"en": "❌ NOT WITHIN LIMITS", "ru": "❌ ВНЕ ОГРАНИЧЕНИЙ"},
    "result_weight": {"en": "Weight: {value}", "ru": "Вес: {value}"},
    "result_max_ramp_weight": {"en": "Maximum ramp weight: {value}", "ru": "Максимальный вес на перроне: {value}"},
    "result_max_takeoff_weight": {"en": "Maximum takeoff weight: {value}", "ru": "Максимальный взлётный вес: {value}"},
    "result_max_landing_weight": {"en": "Maximum landing weight: {value}", "ru": "Максимальный посадочный вес: {value}"},
    "result_weight_below": {"en": "Weight margin: {value} below maximum", "ru": "Запас по весу: {value} до максимума"},
    "result_weight_over": {"en": "❌ Weight exceeds maximum by {value}", "ru": "❌ Вес превышает максимум на {value}"},
    "result_weight_on_limit": {"en": "⚠️ Weight is exactly at the maximum", "ru": "⚠️ Вес точно равен максимуму"},
    "result_weight_limit_not_saved": {
        "en": "⚠️ No separate {phase} weight limit is saved.",
        "ru": "⚠️ Отдельное ограничение веса для этапа «{phase}» не сохранено.",
    },
    "result_cg": {"en": "CG: {value}", "ru": "Центровка (CG): {value}"},
    "result_allowed_cg": {
        "en": "Allowed CG range: {forward}–{aft}",
        "ru": "Допустимый диапазон CG: {forward}–{aft}",
    },
    "result_cg_forward_exceeded": {
        "en": "❌ CG is {value} forward of the permitted limit.",
        "ru": "❌ CG находится на {value} впереди допустимого предела.",
    },
    "result_cg_aft_exceeded": {
        "en": "❌ CG is {value} aft of the permitted limit.",
        "ru": "❌ CG находится на {value} позади допустимого предела.",
    },
    "result_cg_on_limit": {"en": "⚠️ CG is exactly on a saved limit.", "ru": "⚠️ CG точно на сохранённой границе."},
    "result_cg_within": {"en": "✅ CG is within the saved range.", "ru": "✅ CG в сохранённом диапазоне."},
    "result_cg_envelope_not_defined": {
        "en": "❌ The saved CG envelope is not defined at this aircraft weight.",
        "ru": "❌ Сохранённый диапазон CG не определён для этого веса самолёта.",
    },
    "result_cg_not_evaluated": {
        "en": "⚠️ CG not evaluated because no CG envelope is saved.",
        "ru": "⚠️ CG не оценена: диапазон CG не сохранён.",
    },
    "result_station_limit_exceeded": {
        "en": "❌ {station} exceeds its saved station weight limit.",
        "ru": "❌ «{station}» превышает сохранённое ограничение веса станции.",
    },
    "result_tank_capacity_exceeded": {
        "en": "❌ {station} exceeds its saved usable tank capacity.",
        "ru": "❌ «{station}» превышает сохранённый полезный объём бака.",
    },
    "overall_result": {"en": "OVERALL RESULT", "ru": "ОБЩИЙ РЕЗУЛЬТАТ"},
    "overall_within": {
        "en": "✅ Every evaluated condition is within the saved limits.",
        "ru": "✅ Все оценённые состояния находятся в сохранённых пределах.",
    },
    "overall_on_limit": {
        "en": "⚠️ At least one evaluated condition is exactly on a saved limit. Verify input precision and aircraft records.",
        "ru": "⚠️ Хотя бы одно состояние точно на сохранённой границе. Проверьте точность данных и документы самолёта.",
    },
    "overall_out_of_limits": {
        "en": "❌ This loading is not acceptable because:",
        "ru": "❌ Эта загрузка неприемлема по следующим причинам:",
    },
    "overall_reason_weight": {
        "en": "{phase} weight exceeds its saved limit by {value}.",
        "ru": "Вес на этапе «{phase}» превышает сохранённый предел на {value}.",
    },
    "overall_reason_cg_weight": {
        "en": "{phase} weight is outside the published weight range of the saved CG envelope.",
        "ru": "Вес на этапе «{phase}» вне опубликованного диапазона веса сохранённой диаграммы CG.",
    },
    "overall_reason_forward_cg": {
        "en": "{phase} CG is {value} forward of the permitted limit.",
        "ru": "CG на этапе «{phase}» на {value} впереди допустимого предела.",
    },
    "overall_reason_aft_cg": {
        "en": "{phase} CG is {value} aft of the permitted limit.",
        "ru": "CG на этапе «{phase}» на {value} позади допустимого предела.",
    },
    "overall_reason_station": {
        "en": "{phase}: {station} exceeds its station weight limit.",
        "ru": "{phase}: «{station}» превышает ограничение веса станции.",
    },
    "overall_reason_tank": {
        "en": "{phase}: {station} exceeds its usable tank capacity.",
        "ru": "{phase}: «{station}» превышает полезный объём бака.",
    },
    "overall_reason_zfw": {
        "en": "Zero-fuel weight exceeds its saved limit by {value}.",
        "ru": "Вес без топлива превышает сохранённый предел на {value}.",
    },
    "overall_adjust_and_recalculate": {
        "en": "Adjust the loading and calculate again.",
        "ru": "Измените загрузку и выполните расчёт снова.",
    },
    "status_incomplete": {
        "en": "⚠️ INCOMPLETE — LANDING CONDITION NOT EVALUATED",
        "ru": "⚠️ НЕПОЛНО — ПОСАДОЧНОЕ СОСТОЯНИЕ НЕ ОЦЕНЕНО",
    },
    "recommendations_header": {"en": "Suggested adjustments:", "ru": "Возможные варианты корректировки:"},
    "no_recommendations": {
        "en": (
            "No verified baggage or fuel adjustment brings every evaluated condition within "
            "limits. Change the planned cargo or fuel load and recalculate. Passenger reseating "
            "is not suggested."
        ),
        "ru": (
            "Не найдено подтверждённой корректировки багажа или топлива, которая приводит все "
            "проверяемые состояния в допустимые пределы. Измените груз или запас топлива и "
            "пересчитайте. Пересадка пассажиров не предлагается."
        ),
    },
    "history_empty": {"en": "No calculations recorded yet.", "ru": "Расчётов пока нет."},
    "help_text": {
        "en": (
            "This bot calculates Weight & Balance (ramp, takeoff, landing) from aircraft data "
            "you enter yourself. It does not search any database, does not read documents, and "
            "does not use AI to calculate. All aircraft data must be entered and confirmed by "
            "you. Use /menu at any time to return to the main menu, add or select an aircraft, "
            "and run a calculation."
        ),
        "ru": (
            "Бот рассчитывает центровку и загрузку (руление, взлёт, посадка) на основе данных, "
            "которые вводите вы сами. Он не ищет базы данных, не читает документы и не "
            "использует ИИ для расчётов. Все данные по ВС должны быть введены и подтверждены "
            "вами. Команда /menu в любой момент возвращает в главное меню, где можно добавить "
            "или выбрать самолёт и выполнить расчёт."
        ),
    },
    "already_first_step": {
        "en": "You are already at the first step.",
        "ru": "Вы уже на первом шаге.",
    },
    "unsupported_wizard_message": {
        "en": "Please send the requested text or number, or use one of the buttons shown.",
        "ru": "Отправьте запрошенный текст или число либо используйте одну из показанных кнопок.",
    },
    "command_start": {"en": "Start the bot", "ru": "Запустить бота"},
    "command_menu": {"en": "Open the main menu", "ru": "Открыть главное меню"},
    "command_calculate": {"en": "Run a Weight & Balance calculation", "ru": "Рассчитать вес и центровку"},
    "command_aircraft": {"en": "Manage aircraft", "ru": "Управление самолётами"},
    "command_history": {"en": "View calculation history", "ru": "История расчётов"},
    "command_help": {"en": "Show help", "ru": "Показать справку"},
    "command_cancel": {"en": "Cancel the current operation", "ru": "Отменить текущую операцию"},
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
