"""OAuth-авторизация Google-сервисов через Telegram."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.states import AuthGmailStates
from src.mcp.manager import MCPManager
from src.settings import Settings
from src.utils.formatting import bold, code

logger = logging.getLogger(__name__)

router = Router(name="auth")

SHARED_CREDENTIALS = Path("credentials/google/credentials.json")

GMAIL_SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _read_oauth_client(creds_path: Path) -> dict | None:
    """Прочитать OAuth client config из credentials.json."""
    if not creds_path.exists():
        return None
    data = json.loads(creds_path.read_text())
    return data.get("installed") or data.get("web")


def _build_auth_url(client: dict, scopes: list[str]) -> str:
    """Сформировать URL для OAuth consent screen."""
    params = {
        "client_id": client["client_id"],
        "redirect_uri": client["redirect_uris"][0],
        "scope": " ".join(scopes),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{client['auth_uri']}?{urlencode(params)}"


async def _exchange_code(client: dict, auth_code: str) -> dict | None:
    """Обменять authorization code на токены."""
    payload = {
        "code": auth_code,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "redirect_uri": client["redirect_uris"][0],
        "grant_type": "authorization_code",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(client["token_uri"], data=payload) as resp:
            if resp.status == 200:
                return await resp.json()
            error = await resp.text()
            logger.error("OAuth token exchange failed: %s", error)
            return None


def _save_token(token_data: dict, token_path: Path) -> None:
    """Сохранить token.json в формате, совместимом с Gmail MCP."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token_data, indent=2))


@router.message(Command("authgmail"))
async def cmd_authgmail(message: Message, state: FSMContext,
                        settings: Settings, **kwargs) -> None:
    """Авторизация Gmail для проекта. Использование: /authgmail project_id"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        # Показать список проектов с Gmail
        gmail_projects = [
            f"  {code(pid)}" for pid, p in settings.projects.items()
            if p.gmail.enabled
        ]
        if gmail_projects:
            projects_list = "\n".join(gmail_projects)
            await message.answer(
                f"Использование: /authgmail {code('project_id')}\n\n"
                f"Проекты с Gmail:\n{projects_list}",
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"Использование: /authgmail {code('project_id')}\n\n"
                f"Нет проектов с включённым Gmail.",
                parse_mode="HTML",
            )
        return

    pid = args[1].strip().lower()
    project = settings.projects.get(pid)

    if not project:
        await message.answer(f"Проект {code(pid)} не найден.", parse_mode="HTML")
        return

    if not project.gmail.enabled:
        await message.answer(f"Gmail не включён для проекта {code(pid)}.", parse_mode="HTML")
        return

    # Ищем credentials.json
    project_creds = Path(project.gmail.credentials_dir) / "credentials.json"
    if project_creds.exists():
        creds_path = project_creds
    elif SHARED_CREDENTIALS.exists():
        # Копируем общий credentials.json в проект
        project_creds.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SHARED_CREDENTIALS, project_creds)
        creds_path = project_creds
        logger.info("Скопирован credentials.json из общего в '%s'", project_creds)
    else:
        await message.answer(
            f"Не найден {code('credentials.json')}.\n\n"
            f"Положи файл в одно из мест:\n"
            f"• {code(str(project_creds))}\n"
            f"• {code(str(SHARED_CREDENTIALS))}",
            parse_mode="HTML",
        )
        return

    client = _read_oauth_client(creds_path)
    if not client:
        await message.answer("Не удалось прочитать OAuth-конфигурацию из credentials.json.")
        return

    # Генерируем URL
    auth_url = _build_auth_url(client, GMAIL_SCOPES)

    await state.update_data(auth_project_id=pid, auth_creds_path=str(creds_path))
    await state.set_state(AuthGmailStates.waiting_url)

    await message.answer(
        f"{bold('Авторизация Gmail')} для {code(pid)}\n\n"
        f"1. Открой ссылку ниже\n"
        f"2. Войди в аккаунт Google и разреши доступ\n"
        f"3. Браузер перенаправит на {code('http://localhost/...')}\n"
        f"4. Страница не загрузится — это нормально\n"
        f"5. Скопируй URL из адресной строки и вставь сюда\n\n"
        f"<a href=\"{auth_url}\">Открыть авторизацию Google</a>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(AuthGmailStates.waiting_url)
async def on_auth_url(message: Message, state: FSMContext,
                      settings: Settings, mcp_manager: MCPManager,
                      **kwargs) -> None:
    """Получение redirect URL с кодом авторизации."""
    text = message.text.strip()

    # Извлекаем code из URL или принимаем как голый код
    auth_code = None
    if text.startswith("http"):
        parsed = urlparse(text)
        params = parse_qs(parsed.query)
        codes = params.get("code", [])
        if codes:
            auth_code = codes[0]
    else:
        # Может быть голый code
        if len(text) > 10 and "/" not in text:
            auth_code = text

    if not auth_code:
        await message.answer(
            "Не удалось извлечь код авторизации.\n\n"
            "Скопируй полный URL из адресной строки браузера "
            f"(начинается с {code('http://localhost/?code=...')}).",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    pid = data["auth_project_id"]
    creds_path = Path(data["auth_creds_path"])

    client = _read_oauth_client(creds_path)
    if not client:
        await state.clear()
        await message.answer("Ошибка чтения credentials.json.")
        return

    await message.answer("Обмениваю код на токен...")

    token_data = await _exchange_code(client, auth_code)
    if not token_data:
        await message.answer(
            "Не удалось получить токен. Возможно, код истёк.\n"
            "Попробуй /authgmail ещё раз.",
        )
        await state.clear()
        return

    # Сохраняем token.json
    project = settings.projects.get(pid)
    if not project:
        await state.clear()
        await message.answer("Проект не найден.")
        return

    token_path = Path(project.gmail.credentials_dir) / "token.json"
    _save_token(token_data, token_path)

    await state.clear()
    await message.answer(
        f"Gmail авторизован для {bold(project.display_name)}!\n\n"
        f"Токен сохранён: {code(str(token_path))}\n"
        f"MCP-сервер перезапустится при следующем запросе.",
        parse_mode="HTML",
    )
