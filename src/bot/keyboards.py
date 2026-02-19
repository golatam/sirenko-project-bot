"""Клавиатуры для Telegram-бота."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.settings import Settings


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
