"""Декодирование credentials из base64 env vars при старте в контейнере.

Маппинг переменных окружения → файлы:
  CRED_GOOGLE_CREDENTIALS       → credentials/google/credentials.json
  CRED_FLEXIFY_GMAIL_CREDENTIALS → credentials/flexifai/gmail/credentials.json
  CRED_FLEXIFY_GMAIL_TOKEN       → credentials/flexifai/gmail/token.json
  CRED_CALENDAR_KEYS             → credentials/calendar/gcp-oauth.keys.json
  CRED_CALENDAR_TOKENS           → credentials/calendar/tokens.json
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path

from src.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

# env var → относительный путь от PROJECT_ROOT
_CRED_MAP: dict[str, str] = {
    "CRED_GOOGLE_CREDENTIALS": "credentials/google/credentials.json",
    "CRED_FLEXIFY_GMAIL_CREDENTIALS": "credentials/flexifai/gmail/credentials.json",
    "CRED_FLEXIFY_GMAIL_TOKEN": "credentials/flexifai/gmail/token.json",
    "CRED_CALENDAR_KEYS": "credentials/calendar/gcp-oauth.keys.json",
    "CRED_CALENDAR_TOKENS": "credentials/calendar/tokens.json",
}


def bootstrap_credentials() -> None:
    """Декодировать base64 env vars в файлы credentials (если заданы)."""
    restored = 0
    for env_var, rel_path in _CRED_MAP.items():
        value = os.environ.get(env_var)
        if not value:
            continue

        target = PROJECT_ROOT / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = base64.b64decode(value)
            target.write_bytes(data)
            restored += 1
            logger.info("Credentials: %s → %s", env_var, rel_path)
        except Exception:
            logger.exception("Ошибка декодирования %s", env_var)

    # Calendar MCP: установить env vars с путями к credentials/token
    cal_keys = PROJECT_ROOT / "credentials" / "calendar" / "gcp-oauth.keys.json"
    cal_tokens = PROJECT_ROOT / "credentials" / "calendar" / "tokens.json"
    if cal_keys.exists():
        os.environ.setdefault("GOOGLE_OAUTH_CREDENTIALS", str(cal_keys))
    if cal_tokens.exists():
        os.environ.setdefault("GOOGLE_CALENDAR_MCP_TOKEN_PATH", str(cal_tokens))

    if restored:
        logger.info("Bootstrap credentials: восстановлено %d файлов", restored)
    else:
        logger.debug("Bootstrap credentials: env vars не заданы, пропуск")
