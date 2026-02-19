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
