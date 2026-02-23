"""Фабрика StdioServerParameters для MCP-серверов по типу."""

from __future__ import annotations

import logging
import os

from mcp import StdioServerParameters

from src.mcp.types import McpInstanceConfig, McpServerType
from src.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Безопасные системные переменные для дочерних MCP-процессов
_SAFE_ENV_KEYS = {
    "PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TEMP", "TMP", "NODE_PATH", "NODE_OPTIONS",
    "npm_config_cache", "NPM_CONFIG_PREFIX", "XDG_CONFIG_HOME",
    "XDG_DATA_HOME", "XDG_CACHE_HOME", "VIRTUAL_ENV",
    "UV_CACHE_DIR", "UV_PYTHON",
}


def _safe_base_env() -> dict[str, str]:
    """Базовый env для MCP-процессов — только безопасные системные переменные."""
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}


def create_server_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Создать параметры запуска MCP-сервера по типу инстанса."""
    builders = {
        McpServerType.gmail: _gmail_params,
        McpServerType.calendar: _calendar_params,
        McpServerType.telegram: _telegram_params,
        McpServerType.whatsapp: _whatsapp_params,
        McpServerType.slack: _slack_params,
        McpServerType.confluence: _confluence_params,
        McpServerType.jira: _jira_params,
    }
    builder = builders.get(config.type)
    if not builder:
        raise ValueError(f"Неизвестный тип MCP-сервера: {config.type}")
    return builder(config)


def _gmail_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Gmail MCP: @gongrzhe/server-gmail-autoauth-mcp."""
    creds_dir = str(PROJECT_ROOT / config.credentials_dir)
    oauth_path = os.path.join(creds_dir, "credentials.json")
    token_path = os.path.join(creds_dir, "token.json")
    logger.info(
        "Gmail MCP: oauth=%s (exists=%s), token=%s (exists=%s)",
        oauth_path, os.path.exists(oauth_path),
        token_path, os.path.exists(token_path),
    )
    return StdioServerParameters(
        command="npx",
        args=["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
        env={
            **_safe_base_env(),
            "GMAIL_OAUTH_PATH": oauth_path,
            "GMAIL_CREDENTIALS_PATH": token_path,
        },
    )


def _calendar_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Calendar MCP: @cocal/google-calendar-mcp.

    Требует GOOGLE_OAUTH_CREDENTIALS — путь к Google Cloud OAuth credentials.json.
    Токены сохраняются в GOOGLE_CALENDAR_MCP_TOKEN_PATH (отдельно от Gmail).

    Credentials могут поступить двумя путями:
    1. credentials_dir в конфиге → строим пути к файлам
    2. Env vars из bootstrap_credentials (Railway) → пробрасываем напрямую
    _safe_base_env() НЕ включает эти vars — нужен явный проброс.
    """
    env = _safe_base_env()
    if config.credentials_dir:
        creds_dir = str(PROJECT_ROOT / config.credentials_dir)
        oauth_path = os.path.join(creds_dir, "credentials.json")
        token_path = os.path.join(creds_dir, "calendar_tokens.json")
        logger.info(
            "Calendar MCP: oauth=%s (exists=%s), token=%s (exists=%s)",
            oauth_path, os.path.exists(oauth_path),
            token_path, os.path.exists(token_path),
        )
        env["GOOGLE_OAUTH_CREDENTIALS"] = oauth_path
        env["GOOGLE_CALENDAR_MCP_TOKEN_PATH"] = token_path
    else:
        # Fallback: bootstrap_credentials устанавливает env vars напрямую
        # (Railway: CRED_CALENDAR_KEYS → gcp-oauth.keys.json, CRED_CALENDAR_TOKENS → tokens.json).
        # _safe_base_env() их не включает — пробрасываем явно.
        for key in ("GOOGLE_OAUTH_CREDENTIALS", "GOOGLE_CALENDAR_MCP_TOKEN_PATH"):
            val = os.environ.get(key)
            if val:
                env[key] = val
                logger.info("Calendar MCP: %s=%s (из env)", key, val)
    if config.account_id:
        env["CALENDAR_ACCOUNT"] = config.account_id

    has_oauth = "GOOGLE_OAUTH_CREDENTIALS" in env
    has_token = "GOOGLE_CALENDAR_MCP_TOKEN_PATH" in env
    if not has_oauth:
        logger.warning("Calendar MCP: GOOGLE_OAUTH_CREDENTIALS не задан — сервер может не стартовать!")
    if not has_token:
        logger.warning("Calendar MCP: GOOGLE_CALENDAR_MCP_TOKEN_PATH не задан")

    return StdioServerParameters(
        command="npx",
        args=["-y", "@cocal/google-calendar-mcp"],
        env=env,
    )


def _telegram_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Telegram MCP: chigwell/telegram-mcp (Telethon/MTProto).

    Требует клонированный репозиторий (server_dir).
    Запуск: uv --directory <server_dir> run main.py
    Env: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING
    """
    env = _safe_base_env()
    if config.api_id_env:
        env["TELEGRAM_API_ID"] = os.environ.get(config.api_id_env, "")
    if config.api_hash_env:
        env["TELEGRAM_API_HASH"] = os.environ.get(config.api_hash_env, "")
    if config.session_string_env:
        env["TELEGRAM_SESSION_STRING"] = os.environ.get(config.session_string_env, "")

    if config.server_dir:
        # Локальный клонированный репозиторий
        server_dir = str(PROJECT_ROOT / config.server_dir) if not os.path.isabs(config.server_dir) else config.server_dir
        return StdioServerParameters(
            command="uv",
            args=["--directory", server_dir, "run", "main.py"],
            env=env,
        )
    # Fallback: попытка через uvx (может не работать, т.к. пакет не на PyPI)
    return StdioServerParameters(
        command="uvx",
        args=["telegram-mcp"],
        env=env,
    )


def _whatsapp_params(config: McpInstanceConfig) -> StdioServerParameters:
    """WhatsApp MCP: jlucaso1/whatsapp-mcp-ts (Baileys, Node >= 23.10).

    Требует клонированный репозиторий (server_dir) и Node.js >= 23.10.
    Запуск: node src/main.ts (из директории сервера).
    Auth: QR-код при первом запуске → auth_info/ directory.
    """
    if not config.server_dir:
        raise ValueError("WhatsApp MCP требует server_dir (путь к клонированному репозиторию)")

    server_dir = str(PROJECT_ROOT / config.server_dir) if not os.path.isabs(config.server_dir) else config.server_dir
    return StdioServerParameters(
        command="node",
        args=[os.path.join(server_dir, "src", "main.ts")],
        env=_safe_base_env(),
    )


def _slack_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Slack MCP: korotovsky/slack-mcp-server (npm: slack-mcp-server).

    Env: SLACK_MCP_XOXP_TOKEN (User OAuth Token, xoxp-*)
    Опционально: SLACK_MCP_ADD_MESSAGE_TOOL=true для write tools.
    """
    env = _safe_base_env()
    if config.token_env:
        env["SLACK_MCP_XOXP_TOKEN"] = os.environ.get(config.token_env, "")
    # Включаем write tools (отправка сообщений, реакции)
    env["SLACK_MCP_ADD_MESSAGE_TOOL"] = "true"
    return StdioServerParameters(
        command="npx",
        args=["-y", "slack-mcp-server@latest", "--transport", "stdio"],
        env=env,
    )


def _confluence_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Confluence MCP: @aashari/mcp-server-atlassian-confluence."""
    env = _safe_base_env()
    if config.site_name:
        env["ATLASSIAN_SITE_NAME"] = config.site_name
    if config.user_email:
        env["ATLASSIAN_USER_EMAIL"] = config.user_email
    if config.api_token_env:
        env["ATLASSIAN_API_TOKEN"] = os.environ.get(config.api_token_env, "")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@aashari/mcp-server-atlassian-confluence"],
        env=env,
    )


def _jira_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Jira MCP: @aashari/mcp-server-atlassian-jira."""
    env = _safe_base_env()
    if config.site_name:
        env["ATLASSIAN_SITE_NAME"] = config.site_name
    if config.user_email:
        env["ATLASSIAN_USER_EMAIL"] = config.user_email
    if config.api_token_env:
        env["ATLASSIAN_API_TOKEN"] = os.environ.get(config.api_token_env, "")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@aashari/mcp-server-atlassian-jira"],
        env=env,
    )
