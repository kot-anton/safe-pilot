from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.texts.i18n import t
from app.database.models import Aircraft, StationTypeEnum
from app.domain.recommendations import BALLAST_DISCLAIMER  # noqa: F401  (re-exported for handlers)


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_new_calc", lang)), KeyboardButton(text=t("menu_history", lang))],
        [KeyboardButton(text=t("menu_my_aircraft", lang)), KeyboardButton(text=t("menu_add_aircraft", lang))],
        [
            KeyboardButton(text=t("menu_select_aircraft", lang)),
            KeyboardButton(text=t("menu_update_aircraft", lang)),
        ],
        [KeyboardButton(text=t("menu_archive_aircraft", lang)), KeyboardButton(text=t("menu_help", lang))],
        [KeyboardButton(text=t("menu_cancel", lang))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def skip_cancel_keyboard(lang: str, *, show_keep: bool = False) -> InlineKeyboardMarkup:
    row = []
    if show_keep:
        row.append(InlineKeyboardButton(text="↩️ Keep current", callback_data="wizard:keep"))
    row.append(InlineKeyboardButton(text=t("btn_skip", lang), callback_data="wizard:skip"))
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def keep_cancel_keyboard(lang: str, *, show_keep: bool = False) -> InlineKeyboardMarkup:
    """For required fields: no Skip, but Keep current is offered in update mode."""
    row = []
    if show_keep:
        row.append(InlineKeyboardButton(text="↩️ Keep current", callback_data="wizard:keep"))
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def cancel_only_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel")]]
    )


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="wizard:confirm"),
                InlineKeyboardButton(text=t("btn_edit", lang), callback_data="wizard:edit"),
                InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"),
            ]
        ]
    )


def yes_no_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_yes", lang), callback_data="wizard:yes"),
                InlineKeyboardButton(text=t("btn_no", lang), callback_data="wizard:no"),
            ]
        ]
    )


def cg_or_moment_keyboard(lang: str, *, show_keep: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("btn_know_cg", lang), callback_data="wizard:know_cg")],
        [InlineKeyboardButton(text=t("btn_know_moment", lang), callback_data="wizard:know_moment")],
    ]
    if show_keep:
        rows.append([InlineKeyboardButton(text="↩️ Keep current CG/Moment", callback_data="wizard:keep_cg_moment")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def arm_fixed_adjustable_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_arm_fixed", lang), callback_data="wizard:arm_fixed"),
                InlineKeyboardButton(text=t("btn_arm_adjustable", lang), callback_data="wizard:arm_adjustable"),
            ]
        ]
    )


STATION_TYPE_DEFAULT_NAMES = {
    StationTypeEnum.FRONT_SEATS: "Front Seats",
    StationTypeEnum.REAR_SEATS: "Rear Seats",
    StationTypeEnum.PASSENGER: "Passenger",
    StationTypeEnum.BAGGAGE: "Baggage Area",
    StationTypeEnum.FUEL: "Fuel Tank",
    StationTypeEnum.BALLAST: "Ballast",
    StationTypeEnum.CUSTOM: "Custom Station",
}


def station_type_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"stype:{key.value}")]
        for key, name in STATION_TYPE_DEFAULT_NAMES.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_another_station_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_add_another_station", lang), callback_data="wizard:add_station")],
            [InlineKeyboardButton(text=t("btn_done_adding_stations", lang), callback_data="wizard:stations_done")],
        ]
    )


def aircraft_list_keyboard(aircraft_list: list[Aircraft], prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{a.tail_number} ({a.model})", callback_data=f"{prefix}:{a.id}")]
        for a in aircraft_list
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
