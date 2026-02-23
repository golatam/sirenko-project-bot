"""Обработчики /addmcp и /removemcp — динамическое управление MCP-сервисами."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import (
    mcp_existing_instances_keyboard,
    mcp_instance_keyboard,
    mcp_remove_confirm_keyboard,
    mcp_type_keyboard,
    project_selector,
)
from src.bot.states import AddMcpCalendarStates, RemoveMcpStates
from src.mcp.manager import MCPManager
from src.mcp.types import MCP_TYPE_META, McpInstanceConfig, McpServerType
from src.settings import (
    Settings,
    default_tool_policy,
    get_instance_types,
    save_settings,
)
from src.utils.formatting import bold, code

logger = logging.getLogger(__name__)

router = Router(name="mcp_management")


# ---------------------------------------------------------------------------
# /addmcp — подключение MCP-сервиса к проекту
# ---------------------------------------------------------------------------

@router.message(Command("addmcp"))
async def cmd_addmcp(message: Message, settings: Settings, **kwargs) -> None:
    """Подключить MCP-сервис к проекту."""
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        # Без аргумента — показать выбор проекта
        if not settings.projects:
            await message.answer("Нет доступных проектов.")
            return
        await message.answer(
            f"{bold('Подключение MCP-сервиса')}\n\nВыбери проект:",
            parse_mode="HTML",
            reply_markup=_addmcp_project_selector(settings),
        )
        return

    pid = args[1].strip().lower()
    project = settings.projects.get(pid)
    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    connected = _get_connected_types(settings, project.mcp_services)
    await message.answer(
        f"{bold('Подключение MCP')} к {code(pid)}\n\n"
        f"Выбери тип сервиса ([+] = уже подключён):",
        parse_mode="HTML",
        reply_markup=mcp_type_keyboard(pid, connected),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("amcp_p:"))
async def on_addmcp_project(callback: CallbackQuery, settings: Settings, **kwargs) -> None:
    """Выбор проекта для addmcp."""
    pid = callback.data.split(":", 1)[1]
    project = settings.projects.get(pid)
    if not project:
        await callback.answer("Проект не найден", show_alert=True)
        return

    await callback.answer()
    connected = _get_connected_types(settings, project.mcp_services)
    await callback.message.edit_text(
        f"{bold('Подключение MCP')} к {code(pid)}\n\n"
        f"Выбери тип сервиса ([+] = уже подключён):",
        parse_mode="HTML",
        reply_markup=mcp_type_keyboard(pid, connected),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("amcp_t:"))
async def on_addmcp_type(callback: CallbackQuery, state: FSMContext,
                         settings: Settings, **kwargs) -> None:
    """Выбор типа MCP для подключения."""
    parts = callback.data.split(":")
    pid = parts[1]
    type_key = parts[2]
    await callback.answer()

    project = settings.projects.get(pid)
    if not project:
        await callback.message.edit_text("Проект не найден.")
        return

    # Проверяем существующие instances этого типа из других проектов
    reusable = _get_reusable_instances(settings, pid, type_key)
    if reusable:
        meta = MCP_TYPE_META.get(McpServerType(type_key))
        display = meta.display_name if meta else type_key
        await callback.message.edit_text(
            f"{bold(display)} для {code(pid)}\n\n"
            f"Найдены существующие подключения.\n"
            f"Подключить имеющийся или создать новый?",
            parse_mode="HTML",
            reply_markup=mcp_existing_instances_keyboard(pid, type_key, reusable),
        )
        return

    # Нет reusable — старый flow создания нового instance
    await _show_create_new_instructions(callback, pid, type_key, state, settings)


async def _show_create_new_instructions(
    callback: CallbackQuery, pid: str, type_key: str, state: FSMContext,
    settings: Settings | None = None,
) -> None:
    """Показать инструкции по созданию нового MCP instance."""
    auth_commands = {
        "gmail": f"/authgmail {code(pid)}",
        "telegram": f"/authtelegram {code(pid)}",
        "slack": f"/authslack {code(pid)}",
        "confluence": f"/authatlassian {code(pid)}",
        "jira": f"/authatlassian {code(pid)}",
    }

    if type_key == "calendar":
        await state.update_data(amcp_calendar_pid=pid)
        await state.set_state(AddMcpCalendarStates.google_account)
        await callback.message.edit_text(
            f"{bold('Подключение Calendar')} к {code(pid)}\n\n"
            f"Введи email Google-аккаунта:",
            parse_mode="HTML",
        )
        return

    if type_key == "whatsapp":
        await callback.message.edit_text(
            f"{bold('WhatsApp MCP')}\n\n"
            f"WhatsApp требует ручной настройки:\n"
            f"1. Склонируй репо jlucaso1/whatsapp-mcp-ts\n"
            f"2. Запусти {code('npm install')} (Node >= 23.10)\n"
            f"3. Пройди QR-авторизацию\n"
            f"4. Добавь instance в {code('config/projects.yaml')}",
            parse_mode="HTML",
        )
        return

    # Для типов с auth-командой — сначала создаём instance, потом авторизация
    if type_key in auth_commands and settings:
        _create_instance_for_auth(settings, pid, type_key)

    cmd = auth_commands.get(type_key)
    if cmd:
        type_name = MCP_TYPE_META.get(McpServerType(type_key))
        display = type_name.display_name if type_name else type_key
        await callback.message.edit_text(
            f"{bold(display)}\n\n"
            f"Для подключения отправь команду:\n{cmd}",
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text("Неизвестный тип сервиса.")


def _create_instance_for_auth(settings: Settings, pid: str, type_key: str) -> None:
    """Создать MCP instance и подключить к проекту (перед авторизацией)."""
    project = settings.projects.get(pid)
    if not project:
        return

    instance_id = f"{pid}_{type_key}"

    # Не создавать повторно
    if instance_id in settings.global_config.mcp_instances:
        if instance_id not in project.mcp_services:
            project.mcp_services.append(instance_id)
            enabled_types = get_instance_types(settings, project.mcp_services)
            project.tool_policy = default_tool_policy(enabled_types)
            save_settings(settings)
        return

    # Параметры по типу
    kwargs: dict = {}
    if type_key == "gmail":
        kwargs["credentials_dir"] = f"credentials/{pid}/gmail"
    elif type_key == "slack":
        kwargs["token_env"] = f"SLACK_{pid.upper()}_TOKEN"

    settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
        type=McpServerType(type_key),
        **kwargs,
    )
    if instance_id not in project.mcp_services:
        project.mcp_services.append(instance_id)

    enabled_types = get_instance_types(settings, project.mcp_services)
    project.tool_policy = default_tool_policy(enabled_types)
    save_settings(settings)
    logger.info("Создан instance '%s' (%s) для проекта '%s'", instance_id, type_key, pid)


@router.callback_query(lambda c: c.data and c.data.startswith("amcp_e:"))
async def on_addmcp_reuse_existing(
    callback: CallbackQuery, settings: Settings,
    mcp_manager: MCPManager, **kwargs,
) -> None:
    """Подключить существующий MCP instance к проекту."""
    parts = callback.data.split(":")
    pid = parts[1]
    iid = parts[2]
    await callback.answer()

    project = settings.projects.get(pid)
    if not project:
        await callback.message.edit_text("Проект не найден.")
        return

    inst = settings.global_config.mcp_instances.get(iid)
    if not inst:
        await callback.message.edit_text(f"Instance {code(iid)} не найден.", parse_mode="HTML")
        return

    if iid in project.mcp_services:
        await callback.message.edit_text(
            f"{code(iid)} уже подключён к {bold(project.display_name)}.",
            parse_mode="HTML",
        )
        return

    # Подключаем instance к проекту
    project.mcp_services.append(iid)
    enabled_types = get_instance_types(settings, project.mcp_services)
    project.tool_policy = default_tool_policy(enabled_types)
    save_settings(settings)

    meta = MCP_TYPE_META.get(inst.type)
    display = meta.display_name if meta else inst.type.value

    await callback.message.edit_text(
        f"{bold(display)} подключён к {bold(project.display_name)}!\n\n"
        f"Instance: {code(iid)}\n"
        f"MCP-сервер запускается...",
        parse_mode="HTML",
    )

    asyncio.create_task(_start_mcp_bg(mcp_manager, pid, project))


@router.callback_query(lambda c: c.data and c.data.startswith("amcp_n:"))
async def on_addmcp_create_new(
    callback: CallbackQuery, state: FSMContext, settings: Settings, **kwargs,
) -> None:
    """Создать новый MCP instance (старый flow)."""
    parts = callback.data.split(":")
    pid = parts[1]
    type_key = parts[2]
    await callback.answer()

    project = settings.projects.get(pid)
    if not project:
        await callback.message.edit_text("Проект не найден.")
        return

    await _show_create_new_instructions(callback, pid, type_key, state, settings)


@router.callback_query(lambda c: c.data == "amcp_cancel")
async def on_addmcp_cancel(callback: CallbackQuery, **kwargs) -> None:
    """Отмена addmcp."""
    await callback.answer("Отменено")
    await callback.message.edit_text("Подключение MCP отменено.")


# --- Calendar inline FSM ---

@router.message(AddMcpCalendarStates.google_account)
async def on_addmcp_calendar_account(
    message: Message, state: FSMContext,
    settings: Settings, mcp_manager: MCPManager, **kwargs,
) -> None:
    """Ввод Google-аккаунта для Calendar."""
    email = message.text.strip()
    if not email or "@" not in email:
        await message.answer("Введи корректный email-адрес.")
        return

    data = await state.get_data()
    pid = data["amcp_calendar_pid"]
    await state.clear()

    project = settings.projects.get(pid)
    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    # Создаём instance
    instance_id = f"{pid}_calendar"
    settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
        type=McpServerType.calendar,
        account_id=email,
    )
    if instance_id not in project.mcp_services:
        project.mcp_services.append(instance_id)

    # Обновляем tool_policy
    enabled_types = get_instance_types(settings, project.mcp_services)
    project.tool_policy = default_tool_policy(enabled_types)
    save_settings(settings)

    await message.answer(
        f"Calendar подключён к {bold(project.display_name)}!\n\n"
        f"Аккаунт: {code(email)}\n"
        f"Instance: {code(instance_id)}\n\n"
        f"MCP-сервер запускается...",
        parse_mode="HTML",
    )

    # Запускаем MCP в фоне
    asyncio.create_task(_start_mcp_bg(mcp_manager, pid, project))


# ---------------------------------------------------------------------------
# /removemcp — отключение MCP-сервиса от проекта
# ---------------------------------------------------------------------------

@router.message(Command("removemcp"))
async def cmd_removemcp(message: Message, state: FSMContext,
                        settings: Settings, mcp_manager: MCPManager = None,
                        **kwargs) -> None:
    """Отключить MCP-сервис от проекта."""
    args = message.text.split(maxsplit=1)

    if len(args) < 2:
        if not settings.projects:
            await message.answer("Нет доступных проектов.")
            return
        await message.answer(
            f"{bold('Отключение MCP-сервиса')}\n\nВыбери проект:",
            parse_mode="HTML",
            reply_markup=_removemcp_project_selector(settings),
        )
        return

    pid = args[1].strip().lower()
    await _show_removemcp_instances(message, state, settings, mcp_manager, pid)


@router.callback_query(lambda c: c.data and c.data.startswith("rmcp_p:"))
async def on_removemcp_project(callback: CallbackQuery, state: FSMContext,
                               settings: Settings, mcp_manager: MCPManager = None,
                               **kwargs) -> None:
    """Выбор проекта для removemcp."""
    pid = callback.data.split(":", 1)[1]
    await callback.answer()
    await _show_removemcp_instances(
        callback.message, state, settings, mcp_manager, pid, edit=True,
    )


@router.callback_query(RemoveMcpStates.instance_select, F.data.startswith("rmcp_i:"))
async def on_removemcp_instance(callback: CallbackQuery, state: FSMContext,
                                settings: Settings, **kwargs) -> None:
    """Выбор инстанса для удаления."""
    iid = callback.data.split(":", 1)[1]
    await callback.answer()

    inst = settings.global_config.mcp_instances.get(iid)
    type_name = inst.type.value if inst else "unknown"

    await state.update_data(rmcp_instance_id=iid)
    await state.set_state(RemoveMcpStates.confirm)

    await callback.message.edit_text(
        f"Удалить {bold(type_name)} ({code(iid)})?\n\n"
        f"Сервис будет отключён от проекта и остановлен.",
        parse_mode="HTML",
        reply_markup=mcp_remove_confirm_keyboard(iid),
    )


@router.callback_query(RemoveMcpStates.confirm, F.data.startswith("rmcp_y:"))
async def on_removemcp_confirm(callback: CallbackQuery, state: FSMContext,
                               settings: Settings, mcp_manager: MCPManager,
                               **kwargs) -> None:
    """Подтверждение удаления MCP-инстанса."""
    iid = callback.data.split(":", 1)[1]
    await callback.answer()

    data = await state.get_data()
    pid = data.get("rmcp_project_id", "")
    await state.clear()

    project = settings.projects.get(pid)
    if not project:
        await callback.message.edit_text("Проект не найден.")
        return

    # Удаляем из mcp_services проекта
    if iid in project.mcp_services:
        project.mcp_services.remove(iid)

    # Проверяем, не используется ли instance другими проектами
    used_by_others = any(
        iid in p.mcp_services
        for p_id, p in settings.projects.items()
        if p_id != pid
    )

    if not used_by_others:
        settings.global_config.mcp_instances.pop(iid, None)

    # Обновляем tool_policy
    enabled_types = get_instance_types(settings, project.mcp_services)
    project.tool_policy = default_tool_policy(enabled_types)
    save_settings(settings)

    # Останавливаем MCP
    await mcp_manager.stop_project(pid)
    # Перезапускаем оставшиеся
    if project.mcp_services:
        asyncio.create_task(_start_mcp_bg(mcp_manager, pid, project))

    inst_type = "сервис"
    await callback.message.edit_text(
        f"MCP {code(iid)} отключён от {bold(project.display_name)}.\n\n"
        f"Конфигурация обновлена.",
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "rmcp_cancel")
async def on_removemcp_cancel(callback: CallbackQuery, state: FSMContext, **kwargs) -> None:
    """Отмена removemcp."""
    await state.clear()
    await callback.answer("Отменено")
    await callback.message.edit_text("Отключение MCP отменено.")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _instance_description(iid: str, config: McpInstanceConfig) -> str:
    """Краткое описание instance для кнопки."""
    detail = (
        config.account_id
        or config.user_email
        or config.site_name
        or config.token_env
        or config.credentials_dir
    )
    if detail:
        return f"{iid} ({detail})"
    return iid


def _get_reusable_instances(
    settings: Settings, project_id: str, type_key: str,
) -> list[tuple[str, str]]:
    """Найти существующие instances данного типа, не подключённые к проекту."""
    project = settings.projects.get(project_id)
    connected = set(project.mcp_services) if project else set()
    result: list[tuple[str, str]] = []
    for iid, config in settings.global_config.mcp_instances.items():
        if config.type.value == type_key and iid not in connected:
            result.append((iid, _instance_description(iid, config)))
    return result


def _get_connected_types(settings: Settings, instance_ids: list[str]) -> set[str]:
    """Получить множество подключённых типов MCP для проекта."""
    result = set()
    for iid in instance_ids:
        inst = settings.global_config.mcp_instances.get(iid)
        if inst:
            result.add(inst.type.value)
    return result


def _addmcp_project_selector(settings: Settings) -> object:
    """Клавиатура выбора проекта для addmcp."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    buttons = []
    for pid, project in settings.projects.items():
        n_services = len(project.mcp_services)
        label = f"{project.display_name} ({n_services} MCP)"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"amcp_p:{pid}",
        )])
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="amcp_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _removemcp_project_selector(settings: Settings) -> object:
    """Клавиатура выбора проекта для removemcp."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    buttons = []
    for pid, project in settings.projects.items():
        if not project.mcp_services:
            continue
        n_services = len(project.mcp_services)
        label = f"{project.display_name} ({n_services} MCP)"
        buttons.append([InlineKeyboardButton(
            text=label, callback_data=f"rmcp_p:{pid}",
        )])
    if not buttons:
        buttons.append([InlineKeyboardButton(
            text="Нет проектов с MCP", callback_data="rmcp_cancel",
        )])
    else:
        buttons.append([InlineKeyboardButton(text="Отмена", callback_data="rmcp_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_removemcp_instances(
    message: Message, state: FSMContext, settings: Settings,
    mcp_manager: MCPManager | None, pid: str, *, edit: bool = False,
) -> None:
    """Показать список MCP-инстансов проекта для удаления."""
    project = settings.projects.get(pid)
    if not project:
        text = f"Проект {code(pid)} не найден."
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
        return

    if not project.mcp_services:
        text = f"У проекта {bold(project.display_name)} нет подключённых MCP-сервисов."
        if edit:
            await message.edit_text(text, parse_mode="HTML")
        else:
            await message.answer(text, parse_mode="HTML")
        return

    # Сохраняем project_id в FSM для последующих callbacks
    await state.update_data(rmcp_project_id=pid)
    await state.set_state(RemoveMcpStates.instance_select)

    instances = []
    for iid in project.mcp_services:
        inst = settings.global_config.mcp_instances.get(iid)
        if inst:
            meta = MCP_TYPE_META.get(inst.type)
            type_name = meta.display_name if meta else inst.type.value
            running = iid in mcp_manager.instances if mcp_manager else False
            instances.append((iid, type_name, running))

    text = (
        f"{bold('MCP-сервисы')} проекта {code(pid)}\n\n"
        f"Выбери сервис для отключения:"
    )

    if edit:
        await message.edit_text(
            text, parse_mode="HTML",
            reply_markup=mcp_instance_keyboard(instances),
        )
    else:
        await message.answer(
            text, parse_mode="HTML",
            reply_markup=mcp_instance_keyboard(instances),
        )


async def _start_mcp_bg(mcp_manager: MCPManager, pid: str, project: object) -> None:
    """Фоновый запуск MCP-серверов проекта."""
    try:
        await asyncio.wait_for(
            mcp_manager.start_project(pid, project), timeout=30.0,
        )
        logger.info("MCP для '%s' запущен", pid)
    except asyncio.TimeoutError:
        logger.error("Таймаут запуска MCP для '%s'", pid)
    except Exception:
        logger.exception("Ошибка запуска MCP для '%s'", pid)
