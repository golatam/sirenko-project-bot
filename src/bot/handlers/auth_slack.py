"""Авторизация Slack MCP через бот (/authslack).

Slack MCP (korotovsky/slack-mcp-server) требует:
- SLACK_MCP_XOXP_TOKEN — User OAuth Token (xoxp-*)

Получение токена:
1. Создать Slack App на https://api.slack.com/apps
2. Добавить User Token Scopes (channels:history, search:read, chat:write и др.)
3. Установить приложение в workspace
4. Скопировать User OAuth Token (xoxp-...)
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.states import AuthSlackStates
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

router = Router(name="auth_slack")

ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"


def _update_env_var(key: str, value: str) -> None:
    """Добавить или обновить переменную в .env файле (атомарно)."""
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

    content = "\n".join(lines) + "\n"
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=ENV_PATH.parent, suffix=".tmp", prefix=".env_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, ENV_PATH)
    except BaseException:
        os.unlink(tmp_path)
        raise
    os.environ[key] = value


@router.message(Command("authslack"))
async def cmd_authslack(message: Message, state: FSMContext,
                        settings: Settings, **kwargs) -> None:
    """Авторизация Slack MCP для проекта."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        all_projects = "\n".join(
            f"  {code(pid)}" for pid in settings.projects
        )
        await message.answer(
            f"Использование: /authslack {code('project_id')}\n\n"
            f"Проекты:\n{all_projects}\n\n"
            f"Slack MCP будет добавлен к выбранному проекту.",
            parse_mode="HTML",
        )
        return

    pid = args[1].strip().lower()
    project = settings.projects.get(pid)
    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    await state.update_data(auth_slack_project_id=pid)
    await state.set_state(AuthSlackStates.token)
    await message.answer(
        f"{bold('Авторизация Slack MCP')} для {code(pid)}\n\n"
        f"Введи {bold('User OAuth Token')} (начинается с {code('xoxp-')} или {code('xoxe.xoxp-')})\n\n"
        f"Как получить:\n"
        f"1. Открой https://api.slack.com/apps и создай App\n"
        f"2. Перейди в OAuth & Permissions\n"
        f"3. Добавь User Token Scopes:\n"
        f"   {code('channels:history, channels:read, groups:history,')}\n"
        f"   {code('groups:read, im:history, im:read, im:write,')}\n"
        f"   {code('mpim:history, mpim:read, users:read,')}\n"
        f"   {code('chat:write, search:read, usergroups:read')}\n"
        f"4. Установи приложение в workspace\n"
        f"5. Скопируй User OAuth Token",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(AuthSlackStates.token)
async def on_slack_token(message: Message, state: FSMContext,
                         settings: Settings, mcp_manager: MCPManager,
                         **kwargs) -> None:
    """Ввод Slack User OAuth Token."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    token = message.text.strip()

    if not (token.startswith("xoxp-") or token.startswith("xoxe.xoxp-")):
        await message.answer(
            f"Токен должен начинаться с {code('xoxp-')} или {code('xoxe.xoxp-')}.\n"
            f"Это User OAuth Token, не Bot Token (xoxb-).",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    pid = data["auth_slack_project_id"]

    # Уникальное имя env var для проекта
    token_env = f"SLACK_{pid.upper()}_TOKEN"

    # Сохраняем в .env
    _update_env_var(token_env, token)

    # Создаём MCP instance
    instance_id = f"{pid}_slack"
    settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
        type=McpServerType.slack,
        token_env=token_env,
    )

    # Привязываем к проекту
    project = settings.projects[pid]
    if instance_id not in project.mcp_services:
        project.mcp_services.append(instance_id)
        enabled_types = get_instance_types(settings, project.mcp_services)
        project.tool_policy = default_tool_policy(enabled_types)

    save_settings(settings)
    await state.clear()

    # Удаляем сообщение с токеном (секрет!)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"Slack MCP авторизован для {bold(project.display_name)}!\n\n"
        f"Токен сохранён в {code('.env')} как {code(token_env)}\n"
        f"Instance: {code(instance_id)}\n\n"
        f"MCP-сервер запускается...",
        parse_mode="HTML",
    )

    # Запускаем MCP в фоне
    async def _start_slack_mcp() -> None:
        try:
            await asyncio.wait_for(
                mcp_manager.start_project(pid, project), timeout=30.0,
            )
            logger.info("Slack MCP для '%s' запущен", pid)
        except asyncio.TimeoutError:
            logger.error("Таймаут запуска Slack MCP для '%s'", pid)
        except Exception:
            logger.exception("Ошибка запуска Slack MCP для '%s'", pid)

    asyncio.create_task(_start_slack_mcp())
