"""Типы и метаданные MCP-серверов."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class McpServerType(str, Enum):
    """Типы поддерживаемых MCP-серверов."""
    gmail = "gmail"
    calendar = "calendar"
    telegram = "telegram"
    whatsapp = "whatsapp"
    slack = "slack"
    confluence = "confluence"
    jira = "jira"


class McpInstanceConfig(BaseModel):
    """Конфигурация одного MCP-инстанса (type + произвольные параметры)."""
    type: McpServerType
    # Произвольные параметры для конкретного типа сервера
    credentials_dir: str = ""
    account_id: str = ""
    # Путь к локальному серверу (для клонированных репо, запуск через uv)
    server_dir: str = ""
    # Atlassian
    site_name: str = ""
    user_email: str = ""
    api_token_env: str = ""
    # Telegram (chigwell/telegram-mcp)
    api_id_env: str = ""      # имя env var для TELEGRAM_API_ID
    api_hash_env: str = ""    # имя env var для TELEGRAM_API_HASH
    session_string_env: str = ""  # имя env var для TELEGRAM_SESSION_STRING
    # Slack
    token_env: str = ""

    model_config = {"extra": "allow"}


class McpTypeMeta:
    """Метаданные типа MCP-сервера для classifier, prompts и policy."""

    def __init__(
        self,
        category: str,
        display_name: str,
        capability_description: str,
        tool_prefixes_read: list[str],
        tool_prefixes_write: list[str],
        approval_tools: list[str],
    ) -> None:
        self.category = category
        self.display_name = display_name
        self.capability_description = capability_description
        self.tool_prefixes_read = tool_prefixes_read
        self.tool_prefixes_write = tool_prefixes_write
        self.approval_tools = approval_tools

    @property
    def all_prefixes(self) -> list[str]:
        """Все префиксы инструментов (чтение + запись)."""
        return self.tool_prefixes_read + self.tool_prefixes_write


# --- Namespace prefix для каждого типа ---
# Gmail и Calendar без prefix (backward compat, у них и так уникальные имена)
TOOL_PREFIX_MAP: dict[McpServerType, str] = {
    McpServerType.gmail: "",
    McpServerType.calendar: "",
    McpServerType.telegram: "tg_",
    McpServerType.whatsapp: "wa_",
    McpServerType.slack: "slack_",
    McpServerType.confluence: "confluence_",
    McpServerType.jira: "jira_",
}


# --- Метаданные для каждого типа ---
MCP_TYPE_META: dict[McpServerType, McpTypeMeta] = {
    McpServerType.gmail: McpTypeMeta(
        category="gmail",
        display_name="Gmail",
        capability_description="Поиск и чтение email-переписки через Gmail",
        tool_prefixes_read=[
            "search_emails", "read_email", "list_email_labels",
            "list_filters", "get_filter", "download_attachment",
        ],
        tool_prefixes_write=[
            "draft_email", "send_email", "modify_email", "delete_email",
            "batch_modify_emails", "batch_delete_emails",
            "create_label", "update_label", "delete_label",
            "get_or_create_label", "create_filter", "delete_filter",
        ],
        approval_tools=[
            "send_email", "delete_email", "modify_email",
            "batch_modify_emails", "batch_delete_emails",
        ],
    ),
    McpServerType.calendar: McpTypeMeta(
        category="calendar",
        display_name="Google Calendar",
        capability_description="Управление событиями в Google Calendar",
        tool_prefixes_read=[
            "list-events", "search-events", "get-event",
            "list-calendars", "list-colors", "get-freebusy",
            "get-current-time",
        ],
        tool_prefixes_write=[
            "create-event", "update-event", "delete-event",
            "respond-to-event", "manage-accounts",
        ],
        approval_tools=[
            "update-event", "delete-event", "respond-to-event",
        ],
    ),
    # Для типов с namespace prefix (tg_, wa_, slack_, confluence_, jira_):
    # tool names здесь — ОРИГИНАЛЬНЫЕ имена от MCP-сервера (без prefix).
    # Prefix добавляется автоматически в registry и default_tool_policy.
    McpServerType.telegram: McpTypeMeta(
        category="telegram",
        display_name="Telegram",
        capability_description="Чтение и отправка сообщений в Telegram-чатах (MTProto User API)",
        # 87 инструментов от chigwell/telegram-mcp.
        # Используем широкие префиксы: get_/list_/search_/resolve_ → все read tools.
        tool_prefixes_read=[
            "get_", "list_", "search_", "resolve_", "export_contacts",
        ],
        tool_prefixes_write=[
            "send_", "reply_", "edit_", "delete_", "forward_",
            "create_", "pin_", "unpin_", "mark_", "ban_", "unban_",
            "promote_", "demote_", "invite_", "leave_", "join_",
            "subscribe_", "import_", "block_", "unblock_",
            "save_", "clear_", "set_", "update_", "mute_", "unmute_",
            "archive_", "unarchive_", "add_", "remove_", "reorder_",
            "press_", "export_chat_invite",
        ],
        approval_tools=[
            "send_message", "delete_message", "ban_user", "leave_chat",
            "create_group", "create_channel", "forward_message",
            "block_user", "promote_admin", "demote_admin",
        ],
    ),
    McpServerType.whatsapp: McpTypeMeta(
        category="whatsapp",
        display_name="WhatsApp",
        capability_description="Чтение и отправка сообщений в WhatsApp",
        tool_prefixes_read=[
            "get_chats", "search_messages", "get_messages",
        ],
        tool_prefixes_write=[
            "send_message",
        ],
        approval_tools=[
            "send_message",
        ],
    ),
    McpServerType.slack: McpTypeMeta(
        category="slack",
        display_name="Slack",
        capability_description="Чтение каналов и отправка сообщений в Slack",
        tool_prefixes_read=[
            "list_channels", "read_channel", "search_messages",
            "get_thread", "get_users",
        ],
        tool_prefixes_write=[
            "send_message", "reply_to_thread",
        ],
        approval_tools=[
            "send_message", "reply_to_thread",
        ],
    ),
    McpServerType.confluence: McpTypeMeta(
        category="confluence",
        display_name="Confluence",
        capability_description="Поиск и чтение страниц в Confluence",
        tool_prefixes_read=[
            "search", "get_page", "list_spaces", "get_comments",
        ],
        tool_prefixes_write=[
            "create_page", "update_page",
        ],
        approval_tools=[
            "create_page", "update_page",
        ],
    ),
    McpServerType.jira: McpTypeMeta(
        category="jira",
        display_name="Jira",
        capability_description="Поиск и управление задачами в Jira",
        tool_prefixes_read=[
            "search", "get_issue", "list_projects", "get_transitions",
        ],
        tool_prefixes_write=[
            "create_issue", "update_issue",
            "add_comment", "transition_issue",
        ],
        approval_tools=[
            "create_issue", "update_issue", "transition_issue",
        ],
    ),
}
