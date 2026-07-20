from aiogram.fsm.state import State, StatesGroup


class AircraftWizard(StatesGroup):
    tail_number = State()
    nickname = State()
    manufacturer = State()
    model = State()
    empty_weight = State()
    cg_or_moment_choice = State()
    empty_cg = State()
    empty_moment = State()
    confirm_empty_record = State()
    max_ramp_weight = State()
    max_takeoff_weight = State()
    max_landing_weight = State()
    max_zfw = State()
    known_useful_load = State()

    station_add_prompt = State()
    station_name = State()
    station_type = State()
    station_arm = State()
    station_arm_mode = State()
    station_min_arm = State()
    station_max_arm = State()
    station_max_weight = State()
    station_fuel_max_volume = State()
    station_fuel_density = State()

    envelope_rows = State()

    source_doc_name = State()
    source_doc_date = State()

    review = State()
