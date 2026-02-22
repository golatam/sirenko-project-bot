"""Обработчики команд: /start, /project, /help, /status, /clear, /costs + меню."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, CallbackQuery, Message

from src.bot.keyboards import (
    help_category_keyboard,
    help_main_keyboard,
    project_selector,
    start_menu_keyboard,
)
from src.db.database import Database
from src.db.queries import clear_conversation, get_costs_summary
from src.mcp.manager import MCPManager
from src.settings import Settings
from src.utils.formatting import bold, code, escape
from src.utils.tokens import format_cost, format_tokens

logger = logging.getLogger(__name__)

router = Router(name="commands")

# ---------------------------------------------------------------------------
# Регистрация команд в Telegram — вызывается из main.py перед polling
# ---------------------------------------------------------------------------

BOT_COMMANDS = [
    BotCommand(command="start", description="Приветствие и главное меню"),
    BotCommand(command="project", description="Выбрать активный проект"),
    BotCommand(command="status", description="Статус текущего проекта"),
    BotCommand(command="costs", description="Расходы за 7 дней"),
    BotCommand(command="clear", description="Очистить историю разговора"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="addproject", description="Создать новый проект"),
    BotCommand(command="deleteproject", description="Удалить проект"),
    BotCommand(command="authgmail", description="Авторизация Gmail"),
    BotCommand(command="authtelegram", description="Авторизация Telegram MCP"),
    BotCommand(command="authslack", description="Авторизация Slack MCP"),
    BotCommand(command="authatlassian", description="Авторизация Jira/Confluence"),
]


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, settings: Settings, **kwargs) -> None:
    """Приветствие и выбор проекта."""
    projects_list = "\n".join(
        f"  • {bold(p.display_name)} ({code(pid)})"
        for pid, p in settings.projects.items()
    )
    has_project = False

    # Если только один проект — сразу устанавливаем его
    if len(settings.projects) == 1:
        project_id = next(iter(settings.projects))
        await state.update_data(active_project=project_id)
        project = settings.projects[project_id]
        has_project = True
        await message.answer(
            f"Привет! Я твой AI-ассистент для управления проектами.\n\n"
            f"Активный проект: {bold(project.display_name)}\n"
            f"Фаза: {code(project.phase)}\n\n"
            f"Можешь начинать работу — просто пиши запросы текстом.",
            parse_mode="HTML",
            reply_markup=start_menu_keyboard(has_project=True),
        )
    else:
        await message.answer(
            f"Привет! Я твой AI-ассистент для управления проектами.\n\n"
            f"Доступные проекты:\n{projects_list}\n\n"
            f"Выбери проект кнопкой ниже или командой /project.",
            parse_mode="HTML",
            reply_markup=start_menu_keyboard(has_project=False),
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
        _help_main_text(),
        parse_mode="HTML",
        reply_markup=help_main_keyboard(),
    )


@router.message(Command("status"))
async def cmd_status(message: Message, project_id: str | None = None,
                     settings: Settings = None, mcp_manager: MCPManager = None,
                     **kwargs) -> None:
    """Статус текущего проекта."""
    if not project_id:
        await message.answer("Проект не выбран. Используй /project.")
        return

    await message.answer(
        _build_status_text(project_id, settings, mcp_manager),
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
    text = await _build_costs_text(db)
    await message.answer(text, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Callback-хендлеры меню (menu:* и help:*)
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("menu:"))
async def on_menu_action(callback: CallbackQuery, state: FSMContext,
                         settings: Settings, db: Database = None,
                         mcp_manager: MCPManager = None, **kwargs) -> None:
    """Обработка кнопок главного меню."""
    action = callback.data.split(":", 1)[1]
    await callback.answer()

    if action == "project":
        if len(settings.projects) == 0:
            await callback.message.answer("Нет доступных проектов.")
            return
        await callback.message.answer(
            "Выбери проект:",
            reply_markup=project_selector(settings),
        )

    elif action == "status":
        data = await state.get_data()
        pid = data.get("active_project")
        if not pid:
            await callback.message.answer("Проект не выбран. Используй /project.")
            return
        await callback.message.answer(
            _build_status_text(pid, settings, mcp_manager),
            parse_mode="HTML",
        )

    elif action == "costs":
        text = await _build_costs_text(db)
        await callback.message.answer(text, parse_mode="HTML")

    elif action == "clear":
        data = await state.get_data()
        pid = data.get("active_project")
        if not pid:
            await callback.message.answer("Проект не выбран. Используй /project.")
            return
        await clear_conversation(db, pid)
        await callback.message.answer("История разговора очищена.")

    elif action == "help":
        await callback.message.answer(
            _help_main_text(),
            parse_mode="HTML",
            reply_markup=help_main_keyboard(),
        )

    elif action == "addproject":
        await callback.message.answer(
            "Для создания проекта отправь команду:\n/addproject"
        )

    elif action == "deleteproject":
        await callback.message.answer(
            "Для удаления проекта отправь команду:\n/deleteproject"
        )

    elif action in ("authgmail", "authtelegram", "authslack", "authatlassian"):
        # Показываем подсказку с нужной командой
        projects = ", ".join(code(pid) for pid in settings.projects)
        await callback.message.answer(
            f"Отправь команду с ID проекта:\n"
            f"/{action} {code('project_id')}\n\n"
            f"Доступные проекты: {projects}",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("help:"))
async def on_help_navigate(callback: CallbackQuery, **kwargs) -> None:
    """Навигация по разделам справки."""
    category = callback.data.split(":", 1)[1]
    await callback.answer()

    if category == "back":
        await callback.message.edit_text(
            _help_main_text(),
            parse_mode="HTML",
            reply_markup=help_main_keyboard(),
        )
        return

    texts = {
        "main": (
            f"{bold('Основные команды')}\n\n"
            f"/project — Выбрать активный проект\n"
            f"/status — Статус проекта и MCP-сервисов\n"
            f"/costs — Расходы за последние 7 дней\n"
            f"/clear — Очистить историю разговора\n"
        ),
        "manage": (
            f"{bold('Управление проектами')}\n\n"
            f"/addproject — Создать новый проект\n"
            f"  (пошаговый диалог: ID, имя, описание, сервисы)\n\n"
            f"/deleteproject — Удалить проект\n"
            f"  (выбор из списка + подтверждение)\n"
        ),
        "auth": (
            f"{bold('Авторизация сервисов')}\n\n"
            f"/authgmail {code('project_id')} — Gmail (OAuth)\n"
            f"/authtelegram {code('project_id')} — Telegram (MTProto)\n"
            f"/authslack {code('project_id')} — Slack (xoxp-токен)\n"
            f"/authatlassian {code('project_id')} — Jira + Confluence\n\n"
            f"Каждая команда запускает пошаговый диалог авторизации."
        ),
        "agent": (
            f"{bold('Работа с агентом')}\n\n"
            f"Выбери проект через /project, затем просто пиши запросы:\n\n"
            f"• «Покажи последние 5 писем»\n"
            f"• «Что у меня в календаре на завтра?»\n"
            f"• «Найди письма от John»\n"
            f"• «Отправь сообщение в Slack #general»\n"
            f"• «Найди задачу PROJ-123 в Jira»\n\n"
            f"Опасные действия (отправка, удаление) требуют подтверждения."
        ),
    }

    text = texts.get(category)
    if not text:
        return

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=help_category_keyboard(category),
    )


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _help_main_text() -> str:
    """Текст главного экрана справки."""
    return (
        f"{bold('Справка')}\n\n"
        f"Выбери раздел:"
    )


def _build_status_text(project_id: str, settings: Settings,
                       mcp_manager: MCPManager | None) -> str:
    """Формирует текст статуса проекта."""
    project = settings.projects.get(project_id)
    if not project:
        return f"Проект '{project_id}' не найден."

    services_lines: list[str] = []
    for iid in project.mcp_services:
        inst = settings.global_config.mcp_instances.get(iid)
        if inst:
            running = iid in mcp_manager.instances if mcp_manager else False
            status = "запущен" if running else "остановлен"
            services_lines.append(f"  {inst.type.value}: {status} ({code(iid)})")
        else:
            services_lines.append(f"  {code(iid)}: не найден")

    services_block = "\n".join(services_lines) if services_lines else "  нет"

    return (
        f"{bold('Статус проекта')}\n\n"
        f"Проект: {bold(project.display_name)}\n"
        f"ID: {code(project_id)}\n"
        f"Фаза: {code(project.phase)}\n\n"
        f"{bold('MCP-сервисы:')}\n{services_block}"
    )


async def _build_costs_text(db: Database) -> str:
    """Формирует текст расходов."""
    records = await get_costs_summary(db, days=7)
    if not records:
        return "Нет данных о расходах за последние 7 дней."

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

    return "\n".join(lines)
