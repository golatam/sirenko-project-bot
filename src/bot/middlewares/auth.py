"""Middleware для проверки доступа: только владелец может использовать бота."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.settings import Settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Пропускает только сообщения от owner_telegram_id."""

    def __init__(self, settings: Settings) -> None:
        self.owner_id = settings.global_config.owner_telegram_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            return  # Игнорируем события без пользователя

        if user_id != self.owner_id:
            logger.warning("Неавторизованный доступ от user_id=%d", user_id)
            if isinstance(event, Message):
                await event.answer("Доступ запрещён.")
            return

        return await handler(event, data)
