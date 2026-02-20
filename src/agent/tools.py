"""Конвертация MCP-инструментов в формат Anthropic API с минимизацией токенов."""

from __future__ import annotations

import copy
from typing import Any

# Лимит длины description для экономии токенов
MAX_DESCRIPTION_LENGTH = 100


def mcp_tools_to_anthropic(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Преобразовать MCP-инструменты в формат Anthropic API.

    Оптимизации:
    - Обрезка description до MAX_DESCRIPTION_LENGTH символов
    - Удаление description из properties в input_schema
    """
    anthropic_tools = []
    for tool in mcp_tools:
        schema = _minimize_schema(tool.get("input_schema", {}))

        description = tool.get("description", tool["name"])
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH].rstrip() + "…"

        anthropic_tools.append({
            "name": tool["name"],
            "description": description,
            "input_schema": schema,
        })
    return anthropic_tools


def _minimize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Убрать лишние поля из input_schema для экономии токенов."""
    schema = copy.deepcopy(schema)
    if "type" not in schema:
        schema["type"] = "object"
    if "properties" not in schema:
        schema["properties"] = {}

    # Удаляем description из каждого property
    for prop in schema.get("properties", {}).values():
        if isinstance(prop, dict):
            prop.pop("description", None)

    return schema
