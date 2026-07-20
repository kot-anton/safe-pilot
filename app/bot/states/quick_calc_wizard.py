from aiogram.fsm.state import State, StatesGroup


class QuickCalcWizard(StatesGroup):
    front = State()
    rear = State()
    baggage = State()
    fuel = State()
    fuel_exact_split = State()
    review = State()
