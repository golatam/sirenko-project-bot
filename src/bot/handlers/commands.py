"""Обработчики команд: /start, /project, /help, /status, /clear."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import project_selector
from src.db.database import Database
from src.db.queries import clear_conversation, get_costs_summary
from src.settings import Settings
from src.utils.formatting import bold, code, escape
from src.utils.tokens import format_cost, format_tokens

logger = logging.getLogger(__name__)

router = Router(name="commands")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, settings: Settings, **kwargs) -> None:
    """Приветствие и выбор проекта."""
    projects_list = "\n".join(
        f"  • {bold(p.display_name)} ({code(pid)})"
        for pid, p in settings.projects.items()
    )
    await message.answer(
        f"Привет! Я твой AI-ассистент для управления проектами.\n\n"
        f"Доступные проекты:\n{projects_list}\n\n"
        f"Используй /project чтобы выбрать проект, затем просто пиши запросы.",
        parse_mode="HTML",
    )

    # Если только один проект — сразу устанавливаем его
    if len(settings.projects) == 1:
        project_id = next(iter(settings.projects))
        await state.update_data(active_project=project_id)
        project = settings.projects[project_id]
        await message.answer(
            f"Автоматически выбран проект: {bold(project.display_name)}\n"
            f"Фаза: {code(project.phase)}\n\n"
            f"Можешь начинать работу!",
            parse_mode="HTML",
        )


@router.message(Command("project"))
async def cmd_project(message: Message, settings: Settings, **kwargs) -> None:
    """Выбор активного проекта."""
    if len(settings.projects) == 0:
        await message.answer("Нет доступных проектов в конфигурации.")
        return

    await message.answer(
        "Выбери проект:",
        reply_markup=project_selector(settings),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("project:"))
async def on_project_select(callback: CallbackQuery, state: FSMContext,
                            settings: Settings, **kwargs) -> None:
    """Обработка выбора проекта."""
    project_id = callback.data.split(":", 1)[1]
    project = settings.projects.get(project_id)

    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    await state.update_data(active_project=project_id)
    await callback.answer(f"Выбран: {project.display_name}")
    await callback.message.edit_text(
        f"Активный проект: {bold(project.display_name)}\n"
        f"Фаза: {code(project.phase)}\n\n"
        f"Теперь пиши запросы — я буду работать в контексте этого проекта.",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, **kwargs) -> None:
    """Справка по командам."""
    await message.answer(
        f"{bold('Доступные команды:')}\n\n"
        f"/start — Приветствие\n"
        f"/project — Выбрать активный проект\n"
        f"/addproject — Создать новый проект\n"
        f"/deleteproject — Удалить проект\n"
        f"/authgmail — Авторизация Gmail для проекта\n"
        f"/status — Статус текущего проекта\n"
        f"/clear — Очистить историю разговора\n"
        f"/costs — Расходы за последние 7 дней\n"
        f"/help — Эта справка\n\n"
        f"{bold('Работа с агентом:')}\n"
        f"Просто пиши запросы текстом. Например:\n"
        f"• «Покажи последние 5 писем»\n"
        f"• «Что у меня в календаре на завтра?»\n"
        f"• «Найди письма от John»",
        parse_mode="HTML",
    )


@router.message(Command("status"))
async def cmd_status(message: Message, project_id: str | None = None,
                     settings: Settings = None, **kwargs) -> None:
    """Статус текущего проекта."""
    if not project_id:
        await message.answer("Проект не выбран. Используй /project.")
        return

    project = settings.projects.get(project_id)
    if not project:
        await message.answer(f"Проект '{project_id}' не найден.")
        return

    await message.answer(
        f"{bold('Статус проекта')}\n\n"
        f"Проект: {bold(project.display_name)}\n"
        f"ID: {code(project_id)}\n"
        f"Фаза: {code(project.phase)}\n"
        f"Gmail: {'включён' if project.gmail.enabled else 'отключён'}\n"
        f"Calendar: {'включён' if project.calendar.enabled else 'отключён'}\n"
        f"TG Monitor: {'включён' if project.telegram_monitor.enabled else 'отключён'}",
        parse_mode="HTML",
    )


@router.message(Command("clear"))
async def cmd_clear(message: Message, project_id: str | None = None,
                    db: Database = None, **kwargs) -> None:
    """Очистить историю разговора текущего проекта."""
    if not project_id:
        await message.answer("Проект не выбран. Используй /project.")
        return

    await clear_conversation(db, project_id)
    await message.answer("История разговора очищена.")


@router.message(Command("costs"))
async def cmd_costs(message: Message, db: Database = None, **kwargs) -> None:
    """Показать расходы за последние 7 дней."""
    records = await get_costs_summary(db, days=7)
    if not records:
        await message.answer("Нет данных о расходах за последние 7 дней.")
        return

    total_cost = sum(r.cost_usd for r in records)
    total_input = sum(r.tokens_input for r in records)
    total_output = sum(r.tokens_output for r in records)
    total_requests = sum(r.requests_count for r in records)

    lines = [f"{bold('Расходы за 7 дней')}\n"]
    for r in records:
        lines.append(
            f"  {r.date} | {code(r.project_id)} | {r.model} | "
            f"{r.requests_count} зап. | {format_cost(r.cost_usd)}"
        )
    lines.append(f"\n{bold('Итого:')}")
    lines.append(f"  Запросов: {total_requests}")
    lines.append(f"  Токенов: {format_tokens(total_input)} in / {format_tokens(total_output)} out")
    lines.append(f"  Стоимость: {bold(format_cost(total_cost))}")

    await message.answer("\n".join(lines), parse_mode="HTML")
