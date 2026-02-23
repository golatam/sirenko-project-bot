"""Конвертация MCP-инструментов в формат Anthropic API с минимизацией токенов."""

from __future__ import annotations

import copy
from typing import Any

# Лимит длины description для экономии токенов
MAX_DESCRIPTION_LENGTH = 100

# Инструменты, для которых НЕЛЬЗЯ обрезать description и удалять описания параметров.
# Gmail search: модель должна знать Gmail query syntax (from:, subject:, OR, -label: и т.д.)
# и параметр maxResults для управления объёмом выдачи.
CRITICAL_TOOLS: set[str] = {
    "search_emails", "read_email", "list_email_labels",
    "list-events", "search-events",
}


def mcp_tools_to_anthropic(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Преобразовать MCP-инструменты в формат Anthropic API.

    Оптимизации (НЕ применяются к CRITICAL_TOOLS):
    - Обрезка description до MAX_DESCRIPTION_LENGTH символов
    - Удаление description из properties в input_schema
    """
    anthropic_tools = []
    for tool in mcp_tools:
        name = tool["name"]
        is_critical = name in CRITICAL_TOOLS

        schema = _minimize_schema(tool.get("input_schema", {}), keep_descriptions=is_critical)

        description = tool.get("description", name)
        if not is_critical and len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH].rstrip() + "…"

        anthropic_tools.append({
            "name": name,
            "description": description,
            "input_schema": schema,
        })
    return anthropic_tools


def _minimize_schema(schema: dict[str, Any], *, keep_descriptions: bool = False) -> dict[str, Any]:
    """Убрать лишние поля из input_schema для экономии токенов.

    keep_descriptions=True — сохранить description у параметров (для критичных tools).
    """
    schema = copy.deepcopy(schema)
    if "type" not in schema:
        schema["type"] = "object"
    if "properties" not in schema:
        schema["properties"] = {}

    if not keep_descriptions:
        for prop in schema.get("properties", {}).values():
            if isinstance(prop, dict):
                prop.pop("description", None)

    return schema
