from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.texts.i18n import t
from app.database.models import Aircraft, StationTypeEnum


def _back_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=t("btn_back", lang), callback_data="wizard:back")


def _keep_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=t("btn_keep", lang), callback_data="wizard:keep")


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text=t("menu_new_calc", lang)),
            KeyboardButton(text=t("menu_aircraft_submenu", lang)),
            KeyboardButton(text=t("menu_more_submenu", lang)),
        ],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t("menu_placeholder", lang),
    )


def aircraft_submenu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_select_aircraft", lang)), KeyboardButton(text=t("menu_add_aircraft", lang))],
        [KeyboardButton(text=t("menu_update_aircraft", lang)), KeyboardButton(text=t("menu_rental_aircraft", lang))],
        [KeyboardButton(text=t("menu_archive_aircraft", lang)), KeyboardButton(text=t("menu_my_aircraft", lang))],
        [KeyboardButton(text=t("menu_back", lang))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t("menu_placeholder", lang),
    )


def more_submenu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_history", lang)), KeyboardButton(text=t("menu_help", lang))],
        [KeyboardButton(text=t("menu_back", lang))],
    ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=t("menu_placeholder", lang),
    )


def aircraft_card_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("menu_new_calc", lang), callback_data="card:calculate"),
                InlineKeyboardButton(text=t("menu_select_aircraft", lang), callback_data="card:change_aircraft"),
            ]
        ]
    )


def skip_cancel_keyboard(
    lang: str, *, show_keep: bool = False, show_skip: bool = True, show_back: bool = True
) -> InlineKeyboardMarkup:
    row = []
    if show_keep:
        row.append(_keep_button(lang))
    if show_skip:
        row.append(InlineKeyboardButton(text=t("btn_skip", lang), callback_data="wizard:skip"))
    rows = [row]
    footer = []
    if show_back:
        footer.append(_back_button(lang))
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def keep_cancel_keyboard(lang: str, *, show_keep: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    """For required fields: no Skip, but Keep current is offered in update mode."""
    rows = []
    if show_keep:
        rows.append([_keep_button(lang)])
    footer = []
    if show_back:
        footer.append(_back_button(lang))
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_only_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    row = []
    if show_back:
        row.append(_back_button(lang))
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def confirm_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="wizard:confirm")]
    if show_back:
        row.append(_back_button(lang))
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def cg_or_moment_keyboard(lang: str, *, show_keep: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("btn_know_cg", lang), callback_data="wizard:know_cg")],
        [InlineKeyboardButton(text=t("btn_know_moment", lang), callback_data="wizard:know_moment")],
    ]
    if show_keep:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_keep_cg_moment", lang),
                    callback_data="wizard:keep_cg_moment",
                )
            ]
        )
    if show_back:
        rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def arm_fixed_adjustable_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    """Fixed ARM is the common case (one published number) and gets the prominent button.
    Adjustable (a published forward/aft range, e.g. some adjustable seat rails) is offered
    as a secondary, opt-in option -- not asked as if it were equally likely by default."""
    rows = [
        [InlineKeyboardButton(text=f"✅ {t('btn_arm_fixed', lang)}", callback_data="wizard:arm_fixed")],
        [
            InlineKeyboardButton(
                text=f"⚙️ {t('advanced_label', lang)}: {t('btn_arm_adjustable', lang)}",
                callback_data="wizard:arm_adjustable",
            )
        ],
    ]
    if show_back:
        rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


STATION_TYPE_DEFAULT_NAMES = {
    StationTypeEnum.FRONT_SEATS: "Front Seats",
    StationTypeEnum.REAR_SEATS: "Rear Seats",
    StationTypeEnum.BAGGAGE: "Baggage Area",
    StationTypeEnum.CUSTOM: "Custom Station",
    StationTypeEnum.FUEL: "Fuel Tank",
}
STATION_TYPE_TEXT_KEYS = {
    StationTypeEnum.FRONT_SEATS: "station_type_front",
    StationTypeEnum.REAR_SEATS: "station_type_rear",
    StationTypeEnum.BAGGAGE: "station_type_baggage",
    StationTypeEnum.FUEL: "station_type_fuel",
    StationTypeEnum.CUSTOM: "station_type_custom",
}
# PASSENGER is deliberately excluded from the offered station types: occupants are always the
# fixed FRONT_SEATS/REAR_SEATS combined-weight stations, never their own station type.


def station_type_keyboard(lang: str, *, show_back: bool = True, show_done: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(STATION_TYPE_TEXT_KEYS[key], lang), callback_data=f"stype:{key.value}")]
        for key in STATION_TYPE_DEFAULT_NAMES
    ]
    if show_done:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_done_no_more_stations", lang),
                    callback_data="wizard:done_stations",
                )
            ]
        )
    footer = []
    if show_back:
        footer.append(_back_button(lang))
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def station_name_keyboard(lang: str, default_name: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t("btn_use_suggested", lang, value=default_name),
                callback_data="wizard:use_default_name",
            )
        ]
    ]
    footer = []
    if show_back:
        footer.append(_back_button(lang))
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def envelope_keyboard(lang: str, *, has_rows: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t("btn_done", lang), callback_data="wizard:envelope_done")]]
    if has_rows:
        rows.append(
            [InlineKeyboardButton(text=t("btn_remove_row", lang), callback_data="wizard:remove_row_prompt")]
        )
    if not has_rows:
        rows.append(
            [InlineKeyboardButton(text=t("btn_skip_envelope", lang), callback_data="wizard:skip_envelope")]
        )
    footer = []
    if show_back:
        footer.append(_back_button(lang))
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def aircraft_list_keyboard(aircraft_list: list[Aircraft], prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{a.tail_number} ({a.model})", callback_data=f"{prefix}:{a.id}")]
        for a in aircraft_list
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
