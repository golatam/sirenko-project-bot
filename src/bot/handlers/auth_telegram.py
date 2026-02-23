"""Авторизация Telegram MCP через бот (/authtelegram).

Telegram MCP (chigwell/telegram-mcp) требует:
- TELEGRAM_API_ID — получить на https://my.telegram.org/apps
- TELEGRAM_API_HASH — оттуда же
- TELEGRAM_SESSION_STRING — Telethon StringSession (генерируется скриптом)

Поток:
1. /authtelegram project_id — начало
2. Ввод API ID
3. Ввод API Hash
4. Инструкции + ввод session string
5. Сохранение в .env, создание/обновление MCP instance
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.states import AuthTelegramStates
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

router = Router(name="auth_telegram")

ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"


def _update_env_var(key: str, value: str) -> None:
    """Добавить или обновить переменную в .env файле (атомарно)."""
    env_path = ENV_PATH
    lines: list[str] = []
    found = False

    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    content = "\n".join(lines) + "\n"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=env_path.parent, suffix=".tmp", prefix=".env_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, env_path)
    except BaseException:
        os.unlink(tmp_path)
        raise
    # Обновляем текущий процесс
    os.environ[key] = value


@router.message(Command("authtelegram"))
async def cmd_authtelegram(message: Message, state: FSMContext,
                           settings: Settings, **kwargs) -> None:
    """Авторизация Telegram MCP для проекта."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        # Показать проекты с Telegram instance
        tg_projects: list[str] = []
        for pid, proj in settings.projects.items():
            for iid in proj.mcp_services:
                inst = settings.global_config.mcp_instances.get(iid)
                if inst and inst.type == McpServerType.telegram:
                    tg_projects.append(f"  {code(pid)}")
                    break

        all_projects = "\n".join(
            f"  {code(pid)}" for pid in settings.projects
        )
        await message.answer(
            f"Использование: /authtelegram {code('project_id')}\n\n"
            + (f"Проекты с Telegram MCP:\n{chr(10).join(tg_projects)}\n\n" if tg_projects else "")
            + f"Все проекты:\n{all_projects}\n\n"
            f"Telegram MCP будет добавлен к выбранному проекту.",
            parse_mode="HTML",
        )
        return

    pid = args[1].strip().lower()
    project = settings.projects.get(pid)
    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    await state.update_data(auth_tg_project_id=pid)
    await state.set_state(AuthTelegramStates.api_id)
    await message.answer(
        f"{bold('Авторизация Telegram MCP')} для {code(pid)}\n\n"
        f"Шаг 1/3: Введи {bold('API ID')}\n\n"
        f"Получить на https://my.telegram.org/apps\n"
        f"(раздел API development tools → App api_id)",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(AuthTelegramStates.api_id)
async def on_api_id(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод Telegram API ID."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    text = message.text.strip()

    if not text.isdigit():
        await message.answer("API ID должен быть числом. Попробуй ещё раз.")
        return

    await state.update_data(tg_api_id=text)
    await state.set_state(AuthTelegramStates.api_hash)
    await message.answer(
        f"Шаг 2/3: Введи {bold('API Hash')}\n\n"
        f"Находится рядом с API ID на той же странице\n"
        f"(формат: hex-строка, 32 символа)",
        parse_mode="HTML",
    )


@router.message(AuthTelegramStates.api_hash)
async def on_api_hash(message: Message, state: FSMContext, **kwargs) -> None:
    """Ввод Telegram API Hash."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    text = message.text.strip()

    if not re.match(r"^[a-f0-9]{32}$", text):
        await message.answer(
            "API Hash должен быть hex-строкой (32 символа, a-f, 0-9). Попробуй ещё раз."
        )
        return

    await state.update_data(tg_api_hash=text)
    await state.set_state(AuthTelegramStates.session_string)

    data = await state.get_data()
    pid = data["auth_tg_project_id"]

    api_id_val = data["tg_api_id"]
    echo_id = f'echo "TELEGRAM_API_ID={api_id_val}" > .env'
    echo_hash = f'echo "TELEGRAM_API_HASH={text}" >> .env'

    await message.answer(
        f"Шаг 3/3: Введи {bold('Session String')}\n\n"
        f"Для генерации:\n"
        f"1. Клонируй репозиторий:\n"
        f"   {code('git clone https://github.com/chigwell/telegram-mcp.git')}\n"
        f"2. Перейди в директорию:\n"
        f"   {code('cd telegram-mcp')}\n"
        f"3. Создай .env с API_ID и API_HASH:\n"
        f"   {code(echo_id)}\n"
        f"   {code(echo_hash)}\n"
        f"4. Запусти генератор:\n"
        f"   {code('uv run session_string_generator.py')}\n"
        f"5. Следуй инструкциям (телефон → код из Telegram)\n"
        f"6. Скопируй полученную строку и вставь сюда",
        parse_mode="HTML",
    )


@router.message(AuthTelegramStates.session_string)
async def on_session_string(message: Message, state: FSMContext,
                            settings: Settings, mcp_manager: MCPManager,
                            **kwargs) -> None:
    """Ввод Telegram Session String и сохранение."""
    if not message.text:
        await message.answer("Отправь текстовое сообщение.")
        return
    session_str = message.text.strip()

    # Telethon StringSession: длинная base64-подобная строка (300+ символов)
    if len(session_str) < 100:
        await message.answer(
            "Session string слишком короткая (ожидается 300+ символов).\n"
            "Убедись, что скопировал строку полностью."
        )
        return

    data = await state.get_data()
    pid = data["auth_tg_project_id"]
    api_id = data["tg_api_id"]
    api_hash = data["tg_api_hash"]

    # Формируем имена env vars (уникальные для проекта)
    api_id_env = f"TG_{pid.upper()}_API_ID"
    api_hash_env = f"TG_{pid.upper()}_API_HASH"
    session_env = f"TG_{pid.upper()}_SESSION"

    # Сохраняем в .env
    _update_env_var(api_id_env, api_id)
    _update_env_var(api_hash_env, api_hash)
    _update_env_var(session_env, session_str)

    # Создаём/обновляем MCP instance
    instance_id = f"{pid}_telegram"
    settings.global_config.mcp_instances[instance_id] = McpInstanceConfig(
        type=McpServerType.telegram,
        api_id_env=api_id_env,
        api_hash_env=api_hash_env,
        session_string_env=session_env,
        server_dir="",  # пользователь укажет позже или uvx
    )

    # Привязываем к проекту если ещё нет
    project = settings.projects[pid]
    if instance_id not in project.mcp_services:
        project.mcp_services.append(instance_id)
        # Обновляем tool_policy с учётом нового типа
        enabled_types = get_instance_types(settings, project.mcp_services)
        project.tool_policy = default_tool_policy(enabled_types)

    save_settings(settings)
    await state.clear()

    # Удаляем сообщение с session string (секрет!)
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"Telegram MCP авторизован для {bold(project.display_name)}!\n\n"
        f"Credentials сохранены в {code('.env')}:\n"
        f"  {code(api_id_env)} = {api_id}\n"
        f"  {code(api_hash_env)} = (сохранён)\n"
        f"  {code(session_env)} = (сохранён)\n\n"
        f"Instance: {code(instance_id)}\n\n"
        f"{bold('Важно:')} для запуска нужен клонированный репозиторий.\n"
        f"Укажи путь в конфиге: {code('server_dir')} в mcp_instances.\n"
        f"Или сервер запустится при следующем старте бота.",
        parse_mode="HTML",
    )

    # Пробуем запустить MCP в фоне
    async def _start_tg_mcp() -> None:
        try:
            await asyncio.wait_for(
                mcp_manager.start_project(pid, project), timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.error("Таймаут запуска Telegram MCP для '%s'", pid)
        except Exception:
            logger.exception("Ошибка запуска Telegram MCP для '%s'", pid)

    asyncio.create_task(_start_tg_mcp())
