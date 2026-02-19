"""Middleware для инъекции активного проекта в контекст обработчика."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from src.settings import Settings


class ProjectContextMiddleware(BaseMiddleware):
    """Добавляет active_project_id в data обработчика."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Проект по умолчанию — первый в текущем конфиге (динамически)
        default_project = next(iter(self.settings.projects), None)

        # Пытаемся достать active_project из FSM state
        fsm_context: FSMContext | None = data.get("state")
        project_id = default_project

        if fsm_context:
            state_data = await fsm_context.get_data()
            saved_id = state_data.get("active_project")
            if saved_id and saved_id in self.settings.projects:
                project_id = saved_id
            else:
                # Fallback: сохранённый проект удалён
                project_id = default_project

        data["project_id"] = project_id
        data["project_config"] = self.settings.projects.get(project_id) if project_id else None

        return await handler(event, data)
