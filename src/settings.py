"""Конфигурация приложения из YAML + переменных окружения."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).parent.parent / "config" / "projects.yaml"


# --- Модели конфигурации ---


class GmailConfig(BaseModel):
    enabled: bool = False
    credentials_dir: str = ""


class CalendarConfig(BaseModel):
    enabled: bool = False
    account_id: str = ""


class MonitoredChat(BaseModel):
    chat_id: int = 0
    name: str = ""
    check_interval_minutes: int = 15


class TelegramMonitorConfig(BaseModel):
    enabled: bool = False
    session_string_env: str = ""
    monitored_chats: list[MonitoredChat] = Field(default_factory=list)


class ToolPolicyPhase(BaseModel):
    allowed_prefixes: list[str] = Field(default_factory=list)
    requires_approval: list[str] = Field(default_factory=list)


class ToolPolicy(BaseModel):
    read_only: ToolPolicyPhase = Field(default_factory=ToolPolicyPhase)
    drafts: ToolPolicyPhase = Field(default_factory=ToolPolicyPhase)
    controlled: ToolPolicyPhase = Field(default_factory=ToolPolicyPhase)


class ProjectConfig(BaseModel):
    display_name: str = ""
    phase: str = "read_only"
    system_prompt_file: str = ""
    gmail: GmailConfig = Field(default_factory=GmailConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    telegram_monitor: TelegramMonitorConfig = Field(default_factory=TelegramMonitorConfig)
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)

    def get_active_policy(self) -> ToolPolicyPhase:
        """Получить политику инструментов для текущей фазы."""
        return getattr(self.tool_policy, self.phase)


class GlobalConfig(BaseModel):
    owner_telegram_id: int = 0
    default_model: str = "claude-sonnet-4-6"
    complex_model: str = "claude-opus-4-6"
    max_tokens: int = 4096
    phase: str = "read_only"
    db_path: str = "data/agent.db"


class Settings(BaseModel):
    """Корневая конфигурация приложения."""
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)

    # Переменные окружения (не из YAML)
    telegram_bot_token: str = ""
    anthropic_api_key: str = ""

    model_config = {"populate_by_name": True}


def load_settings(config_path: Path | None = None) -> Settings:
    """Загрузить настройки из YAML-файла и переменных окружения."""
    path = config_path or CONFIG_PATH

    if path.exists():
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    settings = Settings(**data)

    # Переопределения из переменных окружения
    settings.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if owner_id := os.environ.get("OWNER_TELEGRAM_ID"):
        settings.global_config.owner_telegram_id = int(owner_id)

    if db_path := os.environ.get("DB_PATH"):
        settings.global_config.db_path = db_path

    return settings
