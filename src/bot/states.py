"""FSM-состояния бота."""

from aiogram.fsm.state import State, StatesGroup


class ProjectStates(StatesGroup):
    """Состояния для управления активным проектом."""
    active = State()  # Пользователь работает с выбранным проектом


class AddProjectStates(StatesGroup):
    """FSM для /addproject."""
    project_id = State()
    display_name = State()
    description = State()
    services = State()       # выбор сервисов (Gmail / Calendar / оба / нет)
    google_account = State()  # email Google-аккаунта (если есть сервисы)
    confirm = State()


class DeleteProjectStates(StatesGroup):
    """FSM для /deleteproject."""
    selection = State()
    confirm = State()


class AuthGmailStates(StatesGroup):
    """FSM для /authgmail."""
    waiting_url = State()


class AuthTelegramStates(StatesGroup):
    """FSM для /authtelegram."""
    api_id = State()
    api_hash = State()
    session_string = State()


class AuthSlackStates(StatesGroup):
    """FSM для /authslack."""
    token = State()


class AuthAtlassianStates(StatesGroup):
    """FSM для /authatlassian."""
    site_name = State()
    user_email = State()
    api_token = State()
    services = State()  # confluence / jira / both
