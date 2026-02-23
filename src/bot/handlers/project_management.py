"""Обработчики /addproject и /deleteproject — динамическое управление проектами."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.agent.prompts import generate_default_prompt_file
from src.bot.keyboards import (
    confirm_create_keyboard,
    confirm_delete_keyboard,
    delete_project_selector,
)
from src.bot.states import AddProjectStates, DeleteProjectStates
from src.mcp.manager import MCPManager
from src.settings import (
    ProjectConfig,
    Settings,
    save_settings,
)
from src.utils.formatting import bold, code, escape

logger = logging.getLogger(__name__)

router = Router(name="project_management")

PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


# ─── Команды (регистрируются ПЕРВЫМИ, приоритет над FSM) ─────


@router.message(Command("addproject"))
async def cmd_addproject(message: Message, state: FSMContext, **kwargs) -> None:
    """Начало диалога создания проекта."""
    await state.set_state(AddProjectStates.project_id)
    await message.answer(
        f"{bold('Создание нового проекта')}\n\n"
        f"Введи ID проекта (латиница, цифры, _, от 2 до 31 символа).\n"
        f"Пример: {code('my_project')}",
        parse_mode="HTML",
    )


@router.message(Command("deleteproject"))
async def cmd_deleteproject(message: Message, state: FSMContext,
                            settings: Settings, **kwargs) -> None:
    """Начало диалога удаления проекта."""
    if not settings.projects:
        await message.answer("Нет проектов для удаления.")
        return

    await state.set_state(DeleteProjectStates.selection)
    await message.answer(
        "Выбери проект для удаления:",
        reply_markup=delete_project_selector(settings),
    )


# ─── /addproject FSM ─────────────────────────────────────────


@router.message(AddProjectStates.project_id)
async def on_project_id(message: Message, state: FSMContext,
                        settings: Settings, **kwargs) -> None:
    """Ввод ID проекта."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    pid = message.text.strip().lower()

    if not PROJECT_ID_RE.match(pid):
        await message.answer(
            "Некорректный ID. Допустимы: латиница, цифры, _ (начинается с буквы, 2-31 символ)."
        )
        return

    if pid in settings.projects:
        await message.answer(f"Проект {code(pid)} уже существует. Введи другой ID.", parse_mode="HTML")
        return

    await state.update_data(project_id=pid)
    await state.set_state(AddProjectStates.display_name)
    await message.answer("Введи отображаемое имя проекта:")


@router.message(AddProjectStates.display_name)
async def on_display_name(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод отображаемого имени."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым.")
        return

    await state.update_data(display_name=name)
    await state.set_state(AddProjectStates.description)
    await message.answer("Введи краткое описание проекта (станет основой системного промпта):")


@router.message(AddProjectStates.description)
async def on_description(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод описания проекта."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    desc = message.text.strip()
    if not desc:
        await message.answer("Описание не может быть пустым.")
        return

    await state.update_data(description=desc)
    await state.set_state(AddProjectStates.confirm)

    data = await state.get_data()
    await message.answer(
        _format_summary(data),
        reply_markup=confirm_create_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(AddProjectStates.confirm, F.data.startswith("addproj_confirm:"))
async def on_create_confirm(callback: CallbackQuery, state: FSMContext,
                            settings: Settings, **kwargs) -> None:
    """Подтверждение/отмена создания проекта."""
    if callback.data.split(":")[1] != "yes":
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.edit_text("Создание проекта отменено.")
        return

    await callback.answer()
    data = await state.get_data()
    pid = data["project_id"]
    display_name = data["display_name"]
    description = data["description"]

    # Генерируем промпт-файл
    prompt_path = generate_default_prompt_file(pid, display_name, description)

    # Собираем конфиг проекта
    project = ProjectConfig(
        display_name=display_name,
        phase="read_only",
        system_prompt_file=str(prompt_path),
        mcp_services=[],
    )

    # Добавляем в settings (in-memory) + сохраняем YAML
    settings.projects[pid] = project
    save_settings(settings)

    await state.clear()

    await callback.message.edit_text(
        f"Проект {bold(display_name)} ({code(pid)}) создан!\n\n"
        f"Используй /addmcp чтобы подключить сервисы.\n"
        f"Используй /project чтобы переключиться на него.",
        parse_mode="HTML",
    )


def _format_summary(data: dict) -> str:
    """Сформировать сводку нового проекта для подтверждения."""
    desc = data["description"]
    if len(desc) > 200:
        desc = desc[:200] + "..."

    return (
        f"{bold('Сводка нового проекта')}\n\n"
        f"ID: {code(data['project_id'])}\n"
        f"Имя: {bold(data['display_name'])}\n"
        f"Описание: {escape(desc)}\n"
        f"\nСоздать проект?"
    )


# ─── /deleteproject FSM ──────────────────────────────────────


@router.callback_query(DeleteProjectStates.selection, F.data.startswith("delproj_select:"))
async def on_delete_select(callback: CallbackQuery, state: FSMContext,
                           settings: Settings, **kwargs) -> None:
    """Выбор проекта для удаления."""
    pid = callback.data.split(":", 1)[1]

    if pid == "_cancel":
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.edit_text("Удаление отменено.")
        return

    project = settings.projects.get(pid)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    await callback.answer()
    await state.update_data(delete_project_id=pid)
    await state.set_state(DeleteProjectStates.confirm)
    await callback.message.edit_text(
        f"Удалить проект {bold(project.display_name)} ({code(pid)})?\n\n"
        f"MCP-серверы будут остановлены, проект удалён из конфигурации.",
        reply_markup=confirm_delete_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(DeleteProjectStates.confirm, F.data.startswith("delproj_confirm:"))
async def on_delete_confirm(callback: CallbackQuery, state: FSMContext,
                            settings: Settings, mcp_manager: MCPManager,
                            **kwargs) -> None:
    """Подтверждение/отмена удаления проекта."""
    if callback.data.split(":")[1] != "yes":
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.edit_text("Удаление отменено.")
        return

    await callback.answer()
    data = await state.get_data()
    pid = data["delete_project_id"]
    project = settings.projects.get(pid)
    display_name = project.display_name if project else pid

    # Останавливаем MCP
    await mcp_manager.stop_project(pid)

    # Удаляем MCP instances, принадлежащие только этому проекту
    if project:
        for instance_id in project.mcp_services:
            # Проверяем, не используется ли instance другими проектами
            used_by_others = any(
                instance_id in p.mcp_services
                for p_id, p in settings.projects.items()
                if p_id != pid
            )
            if not used_by_others:
                settings.global_config.mcp_instances.pop(instance_id, None)

    # Удаляем из settings (in-memory)
    settings.projects.pop(pid, None)

    # Сохраняем YAML
    save_settings(settings)

    await state.clear()
    await callback.message.edit_text(
        f"Проект {bold(display_name)} ({code(pid)}) удалён.\n"
        f"MCP-серверы остановлены, YAML обновлён.",
        parse_mode="HTML",
    )
