"""Клавиатуры для Telegram-бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.settings import Settings


# ---------------------------------------------------------------------------
# Главное меню (кнопки на /start)
# ---------------------------------------------------------------------------

def start_menu_keyboard(has_project: bool = False) -> InlineKeyboardMarkup:
    """Главное меню после /start."""
    rows = [
        [
            InlineKeyboardButton(text="Выбрать проект", callback_data="menu:project"),
            InlineKeyboardButton(text="Статус", callback_data="menu:status"),
        ],
        [
            InlineKeyboardButton(text="Расходы", callback_data="menu:costs"),
            InlineKeyboardButton(text="Очистить историю", callback_data="menu:clear"),
        ],
        [
            InlineKeyboardButton(text="Управление проектами", callback_data="help:manage"),
            InlineKeyboardButton(text="Авторизация", callback_data="help:auth"),
        ],
        [
            InlineKeyboardButton(text="Справка", callback_data="menu:help"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# /help — навигация по категориям
# ---------------------------------------------------------------------------

def help_main_keyboard() -> InlineKeyboardMarkup:
    """Основное меню справки — категории."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Основные", callback_data="help:main"),
                InlineKeyboardButton(text="Управление", callback_data="help:manage"),
            ],
            [
                InlineKeyboardButton(text="Авторизация", callback_data="help:auth"),
                InlineKeyboardButton(text="Работа с агентом", callback_data="help:agent"),
            ],
        ]
    )


def help_category_keyboard(category: str) -> InlineKeyboardMarkup:
    """Кнопки внутри категории справки — быстрые действия + назад."""
    rows: list[list[InlineKeyboardButton]] = []

    if category == "main":
        rows = [
            [
                InlineKeyboardButton(text="Выбрать проект", callback_data="menu:project"),
                InlineKeyboardButton(text="Статус", callback_data="menu:status"),
            ],
            [
                InlineKeyboardButton(text="Расходы", callback_data="menu:costs"),
                InlineKeyboardButton(text="Очистить историю", callback_data="menu:clear"),
            ],
        ]
    elif category == "manage":
        rows = [
            [
                InlineKeyboardButton(text="Создать проект", callback_data="menu:addproject"),
                InlineKeyboardButton(text="Удалить проект", callback_data="menu:deleteproject"),
            ],
        ]
    elif category == "auth":
        rows = [
            [
                InlineKeyboardButton(text="Gmail", callback_data="menu:authgmail"),
                InlineKeyboardButton(text="Telegram", callback_data="menu:authtelegram"),
            ],
            [
                InlineKeyboardButton(text="Slack", callback_data="menu:authslack"),
                InlineKeyboardButton(text="Atlassian", callback_data="menu:authatlassian"),
            ],
        ]

    rows.append([InlineKeyboardButton(text="<< Назад к справке", callback_data="help:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_selector(settings: Settings) -> InlineKeyboardMarkup:
    """Клавиатура выбора проекта."""
    buttons = []
    for project_id, project in settings.projects.items():
        buttons.append([
            InlineKeyboardButton(
                text=project.display_name,
                callback_data=f"project:{project_id}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def approval_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения/отклонения действия."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Подтвердить",
                callback_data=f"approve:{approval_id}",
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"reject:{approval_id}",
            ),
        ]]
    )


def services_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора сервисов для нового проекта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Gmail + Calendar", callback_data="addproj_svc:both")],
            [InlineKeyboardButton(text="Только Gmail", callback_data="addproj_svc:gmail")],
            [InlineKeyboardButton(text="Только Calendar", callback_data="addproj_svc:calendar")],
            [InlineKeyboardButton(text="Без сервисов", callback_data="addproj_svc:none")],
        ]
    )


def confirm_create_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения создания проекта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Создать", callback_data="addproj_confirm:yes"),
            InlineKeyboardButton(text="Отмена", callback_data="addproj_confirm:no"),
        ]]
    )


def confirm_delete_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления проекта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="Удалить", callback_data="delproj_confirm:yes"),
            InlineKeyboardButton(text="Отмена", callback_data="delproj_confirm:no"),
        ]]
    )


def delete_project_selector(settings: Settings) -> InlineKeyboardMarkup:
    """Клавиатура выбора проекта для удаления."""
    buttons = []
    for project_id, project in settings.projects.items():
        buttons.append([
            InlineKeyboardButton(
                text=f"{project.display_name} ({project_id})",
                callback_data=f"delproj_select:{project_id}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="Отмена", callback_data="delproj_select:_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def model_selector() -> InlineKeyboardMarkup:
    """Клавиатура выбора модели."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Sonnet 4.6", callback_data="model:claude-sonnet-4-6"),
                InlineKeyboardButton(text="Opus 4.6", callback_data="model:claude-opus-4-6"),
            ],
        ]
    )
