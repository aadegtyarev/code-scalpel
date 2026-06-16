from aiogram.fsm.state import StatesGroup, State


class AddBook(StatesGroup):
    title = State()
    author = State()
    description = State()
