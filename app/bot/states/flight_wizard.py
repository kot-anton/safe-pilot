from aiogram.fsm.state import State, StatesGroup


class FlightWizard(StatesGroup):
    select_aircraft = State()
    load_at_station = State()
    fuel_starting = State()
    fuel_enroute = State()
    review = State()
