"""Реестр инструментов: маршрутизация tool_name → MCP-сервер."""

from __future__ import annotations

import logging
from typing import Any

from src.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Маппинг имён инструментов на MCP-клиенты."""

    def __init__(self) -> None:
        self._tool_to_client: dict[str, MCPClient] = {}
        self._all_tools: list[dict[str, Any]] = []

    def register_client(self, client: MCPClient) -> None:
        """Зарегистрировать все инструменты клиента."""
        for tool in client.get_tools():
            tool_name = tool["name"]
            if tool_name in self._tool_to_client:
                logger.warning(
                    "Инструмент '%s' уже зарегистрирован от '%s', перезаписываю на '%s'",
                    tool_name, self._tool_to_client[tool_name].name, client.name,
                )
                # Убираем старую запись из _all_tools, чтобы не было дубликатов
                self._all_tools = [t for t in self._all_tools if t["name"] != tool_name]
            self._tool_to_client[tool_name] = client
            self._all_tools.append(tool)

    def unregister_client(self, client: MCPClient) -> None:
        """Удалить все инструменты клиента из реестра."""
        tools_to_remove = [
            name for name, c in self._tool_to_client.items() if c is client
        ]
        for name in tools_to_remove:
            del self._tool_to_client[name]
        self._all_tools = [
            t for t in self._all_tools if t["name"] not in tools_to_remove
        ]
        if tools_to_remove:
            logger.info("Удалено %d инструментов клиента '%s'", len(tools_to_remove), client.name)

    def get_client_for_tool(self, tool_name: str) -> MCPClient | None:
        """Найти MCP-клиент для данного инструмента."""
        return self._tool_to_client.get(tool_name)

    def get_all_tools(self) -> list[dict[str, Any]]:
        """Получить все зарегистрированные инструменты."""
        return self._all_tools

    def filter_tools(self, allowed_prefixes: list[str]) -> list[dict[str, Any]]:
        """Отфильтровать инструменты по разрешённым префиксам.

        Если в списке '*', возвращаем все инструменты.
        """
        if "*" in allowed_prefixes:
            return self._all_tools

        return [
            tool for tool in self._all_tools
            if any(tool["name"].startswith(prefix) for prefix in allowed_prefixes)
        ]

    def clear(self) -> None:
        """Очистить реестр."""
        self._tool_to_client.clear()
        self._all_tools.clear()
