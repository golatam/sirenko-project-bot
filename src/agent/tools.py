"""Конвертация MCP-инструментов в формат Anthropic API."""

from __future__ import annotations

from typing import Any


def mcp_tools_to_anthropic(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Преобразовать список MCP-инструментов в формат tools для Anthropic Messages API.

    MCP формат:
        {"name": "...", "description": "...", "input_schema": {...}}

    Anthropic формат:
        {"name": "...", "description": "...", "input_schema": {...}}

    Форматы практически идентичны, но мы валидируем и нормализуем.
    """
    anthropic_tools = []
    for tool in mcp_tools:
        schema = tool.get("input_schema", {})
        # Гарантируем наличие обязательных полей schema
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}

        anthropic_tools.append({
            "name": tool["name"],
            "description": tool.get("description", f"Инструмент: {tool['name']}"),
            "input_schema": schema,
        })
    return anthropic_tools
