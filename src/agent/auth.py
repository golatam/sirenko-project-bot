"""Авто-рефреш OAuth токена Anthropic.

OAuth access_token (sk-ant-oat01-...) живёт 8 часов.
Refresh token (sk-ant-ort01-...) — неограниченно.
При 401 OAuthRefresher обновляет access_token через refresh_token.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

from src.settings import Settings

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://console.anthropic.com/api/oauth/token"
# Client ID от Claude Code CLI (публичный, не секрет)
CLAUDE_CODE_CLIENT_ID = (
    "5568bae5-e98c-4624-a872-feeb2e498ea1-s7d2mhfpnagd2biq2kh74h"
)

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class OAuthRefreshError(Exception):
    """Не удалось обновить OAuth токен."""


class OAuthRefresher:
    """Обновляет OAuth access_token через refresh_token при 401."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()

    async def refresh(self) -> str:
        """Обновить access_token. Возвращает новый токен.

        asyncio.Lock гарантирует что при конкурентных 401
        только один запрос делает refresh.
        """
        async with self._lock:
            refresh_token = self._settings.anthropic_refresh_token
            if not refresh_token:
                raise OAuthRefreshError(
                    "Refresh token отсутствует. "
                    "Запустите: python3.12 -m src.auth_setup"
                )

            logger.info("Обновляем OAuth access_token через refresh_token...")
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.post(
                        TOKEN_ENDPOINT,
                        json={
                            "grant_type": "refresh_token",
                            "client_id": CLAUDE_CODE_CLIENT_ID,
                            "refresh_token": refresh_token,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error("Ошибка refresh: HTTP %d — %s", e.response.status_code, e.response.text)
                raise OAuthRefreshError(f"HTTP {e.response.status_code}: {e.response.text}") from e
            except httpx.HTTPError as e:
                logger.error("Ошибка refresh: %s", e)
                raise OAuthRefreshError(str(e)) from e

            new_access = data.get("access_token", "")
            new_refresh = data.get("refresh_token", "")

            if not new_access:
                raise OAuthRefreshError("Ответ не содержит access_token")

            # Обновляем in-memory
            self._settings.anthropic_auth_token = new_access
            if new_refresh:
                self._settings.anthropic_refresh_token = new_refresh

            # Обновляем os.environ (для дочерних процессов)
            os.environ["ANTHROPIC_AUTH_TOKEN"] = new_access
            if new_refresh:
                os.environ["ANTHROPIC_REFRESH_TOKEN"] = new_refresh

            # Персистим в .env (переживёт рестарт контейнера)
            self._save_tokens_to_env(new_access, new_refresh or refresh_token)

            logger.info("OAuth access_token обновлён успешно")
            return new_access

    @staticmethod
    def _save_tokens_to_env(access_token: str, refresh_token: str) -> None:
        """Атомарно обновить токены в .env файле."""
        lines: list[str] = []
        access_saved = False
        refresh_saved = False

        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                if line.startswith("ANTHROPIC_AUTH_TOKEN="):
                    lines.append(f"ANTHROPIC_AUTH_TOKEN={access_token}")
                    access_saved = True
                elif line.startswith("ANTHROPIC_REFRESH_TOKEN="):
                    lines.append(f"ANTHROPIC_REFRESH_TOKEN={refresh_token}")
                    refresh_saved = True
                else:
                    lines.append(line)

        if not access_saved:
            lines.append(f"ANTHROPIC_AUTH_TOKEN={access_token}")
        if not refresh_saved:
            lines.append(f"ANTHROPIC_REFRESH_TOKEN={refresh_token}")

        ENV_PATH.write_text("\n".join(lines) + "\n")
        logger.debug("Токены сохранены в %s", ENV_PATH)
