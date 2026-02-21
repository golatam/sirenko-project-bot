"""Конфигурация приложения из YAML + переменных окружения."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "projects.yaml"


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
    max_tokens: int = 2048
    phase: str = "read_only"
    db_path: str = "data/agent.db"
    # "api_key" — стандартный ANTHROPIC_API_KEY
    # "oauth" — OAuth токен от подписки Claude (из macOS Keychain)
    auth_method: str = "api_key"


class Settings(BaseModel):
    """Корневая конфигурация приложения."""
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)

    # Переменные окружения (не из YAML)
    telegram_bot_token: str = ""
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""  # OAuth токен от подписки

    model_config = {"populate_by_name": True}


def load_settings(config_path: Path | None = None) -> Settings:
    """Загрузить настройки из YAML-файла и переменных окружения."""
    # Загружаем .env из корня проекта
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

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

    # Переопределение auth_method из env (для Railway: AUTH_METHOD=api_key)
    if auth_method := os.environ.get("AUTH_METHOD"):
        settings.global_config.auth_method = auth_method

    # OAuth от подписки: читаем из .env (настраивается через python3.12 -m src.auth_setup)
    if settings.global_config.auth_method == "oauth":
        settings.anthropic_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    return settings


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Атомарно сохранить настройки в YAML (через tmp + rename)."""
    path = config_path or CONFIG_PATH
    data = {
        "global": settings.global_config.model_dump(),
        "projects": {
            pid: proj.model_dump()
            for pid, proj in settings.projects.items()
        },
    }
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, suffix=".yaml.tmp", prefix=".projects_",
    )
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


def default_tool_policy(gmail_enabled: bool, calendar_enabled: bool) -> ToolPolicy:
    """Сгенерировать стандартную ToolPolicy на основе включённых сервисов."""
    prefixes_ro: list[str] = []
    prefixes_drafts: list[str] = []
    approval_drafts: list[str] = []
    approval_controlled: list[str] = []

    if gmail_enabled:
        prefixes_ro.extend(["search_emails", "read_email", "list_email_labels",
                            "list_filters", "get_filter", "download_attachment"])
        prefixes_drafts.extend(["search_emails", "read_email", "draft_email",
                                "list_email_labels", "create_label", "get_or_create_label",
                                "create_filter", "list_filters", "get_filter",
                                "download_attachment"])
        approval_drafts.append("draft_email")
        approval_controlled.extend(["send_email", "delete_email", "modify_email",
                                    "batch_modify_emails", "batch_delete_emails"])

    if calendar_enabled:
        prefixes_ro.extend(["list-events", "search-events", "get-event",
                            "list-calendars", "list-colors", "get-freebusy",
                            "get-current-time"])
        prefixes_drafts.extend(["list-events", "search-events", "get-event",
                                "create-event", "list-calendars", "list-colors",
                                "get-freebusy", "get-current-time"])
        approval_drafts.append("create-event")
        approval_controlled.extend(["update-event", "delete-event", "respond-to-event"])

    return ToolPolicy(
        read_only=ToolPolicyPhase(allowed_prefixes=prefixes_ro, requires_approval=[]),
        drafts=ToolPolicyPhase(allowed_prefixes=prefixes_drafts, requires_approval=approval_drafts),
        controlled=ToolPolicyPhase(allowed_prefixes=["*"], requires_approval=approval_controlled),
    )
