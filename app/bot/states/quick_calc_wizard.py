from aiogram.fsm.state import State, StatesGroup


class QuickCalcWizard(StatesGroup):
    front = State()
    rear = State()
    baggage = State()
    fuel = State()
    review = State()
