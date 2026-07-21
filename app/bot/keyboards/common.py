from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.bot.texts.i18n import t
from app.database.models import Aircraft, StationTypeEnum

BACK_BUTTON = InlineKeyboardButton(text="◀ Back", callback_data="wizard:back")
KEEP_BUTTON = InlineKeyboardButton(text="↩️ Keep current", callback_data="wizard:keep")


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text=t("menu_new_calc", lang)),
            KeyboardButton(text=t("menu_aircraft_submenu", lang)),
            KeyboardButton(text=t("menu_more_submenu", lang)),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def aircraft_submenu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_select_aircraft", lang)), KeyboardButton(text=t("menu_add_aircraft", lang))],
        [KeyboardButton(text=t("menu_update_aircraft", lang)), KeyboardButton(text=t("menu_rental_aircraft", lang))],
        [KeyboardButton(text=t("menu_archive_aircraft", lang)), KeyboardButton(text=t("menu_my_aircraft", lang))],
        [KeyboardButton(text=t("menu_back", lang))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def more_submenu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=t("menu_history", lang)), KeyboardButton(text=t("menu_help", lang))],
        [KeyboardButton(text=t("menu_back", lang))],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


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
        row.append(KEEP_BUTTON)
    if show_skip:
        row.append(InlineKeyboardButton(text=t("btn_skip", lang), callback_data="wizard:skip"))
    rows = [row]
    footer = []
    if show_back:
        footer.append(BACK_BUTTON)
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def zero_cancel_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    """For mandatory-but-sometimes-zero fields (e.g. a station with nobody in it): unlike
    skip_cancel_keyboard, this is not an optional field being skipped -- the pilot is recording
    a real answer of zero, so the button says "0" rather than "Skip"."""
    row = [InlineKeyboardButton(text="0", callback_data="wizard:skip")]
    if show_back:
        row.append(BACK_BUTTON)
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def keep_cancel_keyboard(lang: str, *, show_keep: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    """For required fields: no Skip, but Keep current is offered in update mode."""
    rows = []
    if show_keep:
        rows.append([KEEP_BUTTON])
    footer = []
    if show_back:
        footer.append(BACK_BUTTON)
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_only_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    row = []
    if show_back:
        row.append(BACK_BUTTON)
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def confirm_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text=t("btn_confirm", lang), callback_data="wizard:confirm")]
    if show_back:
        row.append(BACK_BUTTON)
    row.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def cg_or_moment_keyboard(lang: str, *, show_keep: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t("btn_know_cg", lang), callback_data="wizard:know_cg")],
        [InlineKeyboardButton(text=t("btn_know_moment", lang), callback_data="wizard:know_moment")],
    ]
    if show_keep:
        rows.append([InlineKeyboardButton(text="↩️ Keep current CG/Moment", callback_data="wizard:keep_cg_moment")])
    if show_back:
        rows.append([BACK_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def arm_fixed_adjustable_keyboard(lang: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    """Fixed ARM is the common case (one published number) and gets the prominent button.
    Adjustable (a published forward/aft range, e.g. some adjustable seat rails) is offered
    as a secondary, opt-in option -- not asked as if it were equally likely by default."""
    rows = [
        [InlineKeyboardButton(text=f"✅ {t('btn_arm_fixed', lang)}", callback_data="wizard:arm_fixed")],
        [InlineKeyboardButton(text=f"⚙️ Advanced: {t('btn_arm_adjustable', lang)}", callback_data="wizard:arm_adjustable")],
    ]
    if show_back:
        rows.append([BACK_BUTTON])
    return InlineKeyboardMarkup(inline_keyboard=rows)


STATION_TYPE_DEFAULT_NAMES = {
    StationTypeEnum.FRONT_SEATS: "Front Seats",
    StationTypeEnum.REAR_SEATS: "Rear Seats",
    StationTypeEnum.BAGGAGE: "Baggage Area",
    StationTypeEnum.FUEL: "Fuel Tank",
    StationTypeEnum.CUSTOM: "Custom Station",
}
# PASSENGER is deliberately excluded from the offered station types: occupants are always the
# fixed FRONT_SEATS/REAR_SEATS combined-weight stations, never their own station type.


def station_type_keyboard(lang: str, *, show_back: bool = True, show_done: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=name, callback_data=f"stype:{key.value}")]
        for key, name in STATION_TYPE_DEFAULT_NAMES.items()
    ]
    if show_done:
        rows.append([InlineKeyboardButton(text="✅ Done, no more stations", callback_data="wizard:done_stations")])
    footer = []
    if show_back:
        footer.append(BACK_BUTTON)
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def station_name_keyboard(lang: str, default_name: str, *, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"✅ Use \"{default_name}\"", callback_data="wizard:use_default_name")]]
    footer = []
    if show_back:
        footer.append(BACK_BUTTON)
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def envelope_keyboard(lang: str, *, has_rows: bool = False, show_back: bool = True) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="✅ Done", callback_data="wizard:envelope_done")]]
    if has_rows:
        rows.append([InlineKeyboardButton(text="🗑 Remove a row", callback_data="wizard:remove_row_prompt")])
    if not has_rows:
        rows.append(
            [InlineKeyboardButton(text="⚠️ Skip -- don't check CG for this aircraft", callback_data="wizard:skip_envelope")]
        )
    footer = []
    if show_back:
        footer.append(BACK_BUTTON)
    footer.append(InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="wizard:cancel"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def aircraft_list_keyboard(aircraft_list: list[Aircraft], prefix: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{a.tail_number} ({a.model})", callback_data=f"{prefix}:{a.id}")]
        for a in aircraft_list
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
