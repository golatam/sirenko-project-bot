"""Конфигурация приложения из YAML + переменных окружения."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.mcp.types import MCP_TYPE_META, McpInstanceConfig, McpServerType, TOOL_PREFIX_MAP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "projects.yaml"

logger = logging.getLogger(__name__)


# --- Модели конфигурации ---


class GmailConfig(BaseModel):
    """Legacy: конфигурация Gmail (для backward compat)."""
    enabled: bool = False
    credentials_dir: str = ""


class CalendarConfig(BaseModel):
    """Legacy: конфигурация Calendar (для backward compat)."""
    enabled: bool = False
    account_id: str = ""


class MonitoredChat(BaseModel):
    chat_id: int = 0
    name: str = ""
    check_interval_minutes: int = 15


class TelegramMonitorConfig(BaseModel):
    """Legacy: конфигурация Telegram Monitor (для backward compat)."""
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
    # Новый формат: ссылки на instance_id из global.mcp_instances
    mcp_services: list[str] = Field(default_factory=list)
    # Legacy поля (для backward compat при чтении YAML)
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
    auth_method: str = "api_key"
    # Именованные MCP-инстансы (instance_id → config)
    mcp_instances: dict[str, McpInstanceConfig] = Field(default_factory=dict)


class Settings(BaseModel):
    """Корневая конфигурация приложения."""
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)

    # Переменные окружения (не из YAML)
    telegram_bot_token: str = ""
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""

    model_config = {"populate_by_name": True}


def _migrate_legacy_mcp(data: dict[str, Any]) -> dict[str, Any]:
    """Конвертация старого формата (gmail/calendar поля) в mcp_instances.

    Автоматически создаёт mcp_instances в global и mcp_services в projects
    на основе legacy gmail/calendar/telegram_monitor полей.
    """
    global_data = data.get("global", {})
    projects_data = data.get("projects", {})

    # Если уже есть mcp_instances — миграция не нужна
    if global_data.get("mcp_instances"):
        return data

    mcp_instances: dict[str, dict[str, Any]] = {}
    migrated = False

    for pid, proj in projects_data.items():
        services: list[str] = []

        # Gmail
        gmail = proj.get("gmail", {})
        if gmail.get("enabled"):
            instance_id = f"{pid}_gmail"
            mcp_instances[instance_id] = {
                "type": "gmail",
                "credentials_dir": gmail.get("credentials_dir", ""),
            }
            services.append(instance_id)
            migrated = True

        # Calendar
        calendar = proj.get("calendar", {})
        if calendar.get("enabled"):
            instance_id = f"{pid}_calendar"
            mcp_instances[instance_id] = {
                "type": "calendar",
                "account_id": calendar.get("account_id", ""),
            }
            services.append(instance_id)
            migrated = True

        if services:
            proj["mcp_services"] = services

    if migrated:
        global_data["mcp_instances"] = mcp_instances
        data["global"] = global_data
        logger.info(
            "Миграция legacy MCP: создано %d инстансов", len(mcp_instances),
        )

    return data


def load_settings(config_path: Path | None = None) -> Settings:
    """Загрузить настройки из YAML-файла и переменных окружения."""
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)

    path = config_path or CONFIG_PATH

    if path.exists():
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    # Миграция legacy формата
    data = _migrate_legacy_mcp(data)

    settings = Settings(**data)

    # Переопределения из переменных окружения
    settings.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    settings.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if owner_id := os.environ.get("OWNER_TELEGRAM_ID"):
        settings.global_config.owner_telegram_id = int(owner_id)

    if db_path := os.environ.get("DB_PATH"):
        settings.global_config.db_path = db_path

    if auth_method := os.environ.get("AUTH_METHOD"):
        settings.global_config.auth_method = auth_method

    if settings.global_config.auth_method == "oauth":
        settings.anthropic_auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")

    return settings


def save_settings(settings: Settings, config_path: Path | None = None) -> None:
    """Атомарно сохранить настройки в YAML (через tmp + rename)."""
    path = config_path or CONFIG_PATH

    # Сериализация mcp_instances
    mcp_instances_data = {}
    for iid, inst in settings.global_config.mcp_instances.items():
        inst_dict = inst.model_dump(exclude_defaults=True)
        # Всегда сохраняем type
        inst_dict["type"] = inst.type.value
        mcp_instances_data[iid] = inst_dict

    global_data = settings.global_config.model_dump(exclude={"mcp_instances"})
    if mcp_instances_data:
        global_data["mcp_instances"] = mcp_instances_data

    data = {
        "global": global_data,
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


def default_tool_policy(
    enabled_types: list[McpServerType] | None = None,
    *,
    gmail_enabled: bool = False,
    calendar_enabled: bool = False,
) -> ToolPolicy:
    """Сгенерировать стандартную ToolPolicy на основе включённых MCP-типов.

    Поддерживает как новый формат (enabled_types), так и legacy (gmail/calendar).
    """
    # Legacy compat
    if enabled_types is None:
        enabled_types = []
        if gmail_enabled:
            enabled_types.append(McpServerType.gmail)
        if calendar_enabled:
            enabled_types.append(McpServerType.calendar)

    prefixes_ro: list[str] = []
    prefixes_drafts: list[str] = []
    approval_drafts: list[str] = []
    approval_controlled: list[str] = []

    for stype in enabled_types:
        meta = MCP_TYPE_META.get(stype)
        if not meta:
            continue

        prefix = TOOL_PREFIX_MAP.get(stype, "")

        # Read-only: только чтение
        for p in meta.tool_prefixes_read:
            prefixes_ro.append(prefix + p if prefix else p)

        # Drafts: чтение + запись (но запись через approval)
        for p in meta.tool_prefixes_read:
            prefixes_drafts.append(prefix + p if prefix else p)
        for p in meta.tool_prefixes_write:
            prefixed = prefix + p if prefix else p
            prefixes_drafts.append(prefixed)
            # Все write tools в drafts требуют подтверждения
            if prefixed not in approval_drafts:
                approval_drafts.append(prefixed)

        # Controlled: approval только для опасных
        for a in meta.approval_tools:
            prefixed = prefix + a if prefix else a
            if prefixed not in approval_controlled:
                approval_controlled.append(prefixed)

    return ToolPolicy(
        read_only=ToolPolicyPhase(allowed_prefixes=prefixes_ro, requires_approval=[]),
        drafts=ToolPolicyPhase(allowed_prefixes=prefixes_drafts, requires_approval=approval_drafts),
        controlled=ToolPolicyPhase(allowed_prefixes=["*"], requires_approval=approval_controlled),
    )


def get_instance_types(settings: Settings, instance_ids: list[str]) -> list[McpServerType]:
    """Получить типы MCP-серверов для списка instance_ids."""
    types = []
    for iid in instance_ids:
        inst = settings.global_config.mcp_instances.get(iid)
        if inst and inst.type not in types:
            types.append(inst.type)
    return types
