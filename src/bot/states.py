"""FSM-состояния бота."""

from aiogram.fsm.state import State, StatesGroup


class ProjectStates(StatesGroup):
    """Состояния для управления активным проектом."""
    active = State()  # Пользователь работает с выбранным проектом
