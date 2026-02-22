"""Авторизация Atlassian (Jira + Confluence) через бот (/authatlassian).

Оба MCP-сервера используют одинаковые credentials:
- ATLASSIAN_SITE_NAME — субдомен (company для company.atlassian.net)
- ATLASSIAN_USER_EMAIL — email аккаунта
- ATLASSIAN_API_TOKEN — токен с https://id.atlassian.com/manage-profile/security/api-tokens

Один токен работает для обоих серверов (Confluence + Jira).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.bot.states import AuthAtlassianStates
from src.mcp.manager import MCPManager
from src.mcp.types import McpInstanceConfig, McpServerType
from src.settings import (
    Settings,
    default_tool_policy,
    get_instance_types,
    save_settings,
)
from src.utils.formatting import bold, code

logger = logging.getLogger(__name__)

router = Router(name="auth_atlassian")

ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"


def _update_env_var(key: str, value: str) -> None:
    """Добавить или обновить переменную в .env файле."""
    lines: list[str] = []
    found = False

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n")
    os.environ[key] = value


def _atlassian_services_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора Atlassian-сервисов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Confluence + Jira", callback_data="authatlassian_svc:both")],
            [InlineKeyboardButton(text="Только Confluence", callback_data="authatlassian_svc:confluence")],
            [InlineKeyboardButton(text="Только Jira", callback_data="authatlassian_svc:jira")],
        ]
    )


@router.message(Command("authatlassian"))
async def cmd_authatlassian(message: Message, state: FSMContext,
                            settings: Settings, **kwargs) -> None:
    """Авторизация Atlassian для проекта."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        all_projects = "\n".join(
            f"  {code(pid)}" for pid in settings.projects
        )
        await message.answer(
            f"Использование: /authatlassian {code('project_id')}\n\n"
            f"Проекты:\n{all_projects}\n\n"
            f"Confluence и/или Jira будут добавлены к проекту.",
            parse_mode="HTML",
        )
        return

    pid = args[1].strip().lower()
    project = settings.projects.get(pid)
    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    await state.update_data(auth_atl_project_id=pid)
    await state.set_state(AuthAtlassianStates.site_name)
    await message.answer(
        f"{bold('Авторизация Atlassian')} для {code(pid)}\n\n"
        f"Шаг 1/4: Введи {bold('Site Name')}\n\n"
        f"Это субдомен: для {code('company.atlassian.net')} введи {code('company')}",
        parse_mode="HTML",
    )


@router.message(AuthAtlassianStates.site_name)
async def on_site_name(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод Atlassian site name."""
    site = message.text.strip().lower()
    if not site or "." in site or " " in site:
        await message.answer("Введи только субдомен (без .atlassian.net). Попробуй ещё раз.")
        return

    await state.update_data(atl_site_name=site)
    await state.set_state(AuthAtlassianStates.user_email)
    await message.answer(
        f"Шаг 2/4: Введи {bold('Email')} аккаунта Atlassian",
        parse_mode="HTML",
    )


@router.message(AuthAtlassianStates.user_email)
async def on_user_email(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод email."""
    email = message.text.strip()
    if not email or "@" not in email:
        await message.answer("Введи корректный email.")
        return

    await state.update_data(atl_user_email=email)
    await state.set_state(AuthAtlassianStates.api_token)
    await message.answer(
        f"Шаг 3/4: Введи {bold('API Token')}\n\n"
        f"Создай токен на:\nhttps://id.atlassian.com/manage-profile/security/api-tokens",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(AuthAtlassianStates.api_token)
async def on_api_token(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод API token."""
    token = message.text.strip()
    if len(token) < 10:
        await message.answer("Токен слишком короткий. Попробуй ещё раз.")
        return

    await state.update_data(atl_api_token=token)
    await state.set_state(AuthAtlassianStates.services)

    # Удаляем сообщение с токеном
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        "Шаг 4/4: Какие сервисы подключить?",
        reply_markup=_atlassian_services_keyboard(),
    )


@router.callback_query(AuthAtlassianStates.services, F.data.startswith("authatlassian_svc:"))
async def on_services_select(callback: CallbackQuery, state: FSMContext,
                             settings: Settings, mcp_manager: MCPManager,
                             **kwargs) -> None:
    """Выбор сервисов и сохранение."""
    choice = callback.data.split(":")[1]
    await callback.answer()

    data = await state.get_data()
    pid = data["auth_atl_project_id"]
    site_name = data["atl_site_name"]
    user_email = data["atl_user_email"]
    api_token = data["atl_api_token"]

    # Сохраняем credentials в .env
    token_env = f"ATL_{pid.upper()}_API_TOKEN"
    _update_env_var(token_env, api_token)

    project = settings.projects[pid]
    add_confluence = choice in ("confluence", "both")
    add_jira = choice in ("jira", "both")
    created_instances: list[str] = []

    if add_confluence:
        instance_id = f"{pid}_confluence"
        settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
            type=McpServerType.confluence,
            site_name=site_name,
            user_email=user_email,
            api_token_env=token_env,
        )
        if instance_id not in project.mcp_services:
            project.mcp_services.append(instance_id)
        created_instances.append(instance_id)

    if add_jira:
        instance_id = f"{pid}_jira"
        settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
            type=McpServerType.jira,
            site_name=site_name,
            user_email=user_email,
            api_token_env=token_env,
        )
        if instance_id not in project.mcp_services:
            project.mcp_services.append(instance_id)
        created_instances.append(instance_id)

    # Обновляем tool_policy
    enabled_types = get_instance_types(settings, project.mcp_services)
    project.tool_policy = default_tool_policy(enabled_types)

    save_settings(settings)
    await state.clear()

    services_text = " + ".join(
        ["Confluence"] * add_confluence + ["Jira"] * add_jira
    )
    instances_text = "\n".join(f"  {code(iid)}" for iid in created_instances)

    await callback.message.edit_text(
        f"Atlassian авторизован для {bold(project.display_name)}!\n\n"
        f"Сервисы: {services_text}\n"
        f"Сайт: {code(site_name)}.atlassian.net\n"
        f"Email: {code(user_email)}\n"
        f"Instances:\n{instances_text}\n\n"
        f"MCP-серверы запускаются...",
        parse_mode="HTML",
    )

    # Запускаем MCP в фоне
    async def _start_atl_mcp() -> None:
        try:
            await asyncio.wait_for(
                mcp_manager.start_project(pid, project), timeout=30.0,
            )
            logger.info("Atlassian MCP для '%s' запущен", pid)
        except asyncio.TimeoutError:
            logger.error("Таймаут запуска Atlassian MCP для '%s'", pid)
        except Exception:
            logger.exception("Ошибка запуска Atlassian MCP для '%s'", pid)

    asyncio.create_task(_start_atl_mcp())
