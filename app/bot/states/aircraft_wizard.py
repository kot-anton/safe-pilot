from aiogram.fsm.state import State, StatesGroup


class AircraftWizard(StatesGroup):
    tail_number = State()
    nickname = State()
    empty_weight = State()
    cg_or_moment_choice = State()
    empty_cg = State()
    empty_moment = State()
    max_ramp_weight = State()
    max_takeoff_weight = State()
    max_landing_weight = State()

    station_add_prompt = State()
    station_name = State()
    station_type = State()
    station_arm = State()
    station_fuel_max_volume = State()
    station_edit_name = State()
    station_edit_type = State()
    station_edit_arm = State()
    station_edit_fuel_volume = State()

    envelope_rows = State()
    envelope_edit_row = State()

    review = State()
