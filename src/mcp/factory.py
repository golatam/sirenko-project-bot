"""Фабрика StdioServerParameters для MCP-серверов по типу."""

from __future__ import annotations

import os

from mcp import StdioServerParameters

from src.mcp.types import McpInstanceConfig, McpServerType
from src.settings import PROJECT_ROOT


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
    return StdioServerParameters(
        command="npx",
        args=["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
        env={
            **os.environ,
            "GMAIL_OAUTH_PATH": oauth_path,
            "GMAIL_CREDENTIALS_PATH": token_path,
        },
    )


def _calendar_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Calendar MCP: @cocal/google-calendar-mcp."""
    return StdioServerParameters(
        command="npx",
        args=["-y", "@cocal/google-calendar-mcp"],
        env={
            **os.environ,
            "CALENDAR_ACCOUNT": config.account_id,
        },
    )


def _telegram_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Telegram MCP: chigwell/telegram-mcp (Telethon/MTProto).

    Требует клонированный репозиторий (server_dir).
    Запуск: uv --directory <server_dir> run main.py
    Env: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING
    """
    env = {**os.environ}
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
    """WhatsApp MCP: jlucaso1/whatsapp-mcp-ts (Baileys)."""
    return StdioServerParameters(
        command="npx",
        args=["-y", "whatsapp-mcp"],
        env={**os.environ},
    )


def _slack_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Slack MCP: korotovsky/slack-mcp-server."""
    env = {**os.environ}
    if config.token_env:
        env["SLACK_USER_TOKEN"] = os.environ.get(config.token_env, "")
    return StdioServerParameters(
        command="npx",
        args=["-y", "@anthropic/slack-mcp-server"],
        env=env,
    )


def _confluence_params(config: McpInstanceConfig) -> StdioServerParameters:
    """Confluence MCP: @aashari/mcp-server-atlassian-confluence."""
    env = {**os.environ}
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
    env = {**os.environ}
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
