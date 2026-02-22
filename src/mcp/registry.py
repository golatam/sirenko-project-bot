"""Реестр инструментов: маршрутизация tool_name → MCP-сервер.

Instance-aware: каждый MCP-инстанс регистрируется с namespace prefix,
позволяя разным серверам иметь одинаковые имена инструментов.
"""

from __future__ import annotations

import logging
from typing import Any

from src.mcp.client import MCPClient

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Маппинг имён инструментов на MCP-клиенты с поддержкой instance prefix."""

    def __init__(self) -> None:
        self._tool_to_client: dict[str, MCPClient] = {}
        self._all_tools: list[dict[str, Any]] = []
        # Instance tracking: instance_id → (client, prefix, original_tool_names)
        self._instances: dict[str, tuple[MCPClient, str, list[str]]] = {}

    def register_instance(
        self, instance_id: str, client: MCPClient, prefix: str = "",
    ) -> None:
        """Зарегистрировать MCP-инстанс с namespace prefix.

        При непустом prefix все инструменты клиента переименовываются:
        tool_name → prefix + tool_name (например, send_message → tg_send_message).
        """
        original_names: list[str] = []
        for tool in client.get_tools():
            orig_name = tool["name"]
            prefixed_name = prefix + orig_name if prefix else orig_name
            original_names.append(orig_name)

            if prefixed_name in self._tool_to_client:
                logger.warning(
                    "Инструмент '%s' уже зарегистрирован от '%s', перезаписываю на '%s'",
                    prefixed_name,
                    self._tool_to_client[prefixed_name].name,
                    client.name,
                )
                self._all_tools = [
                    t for t in self._all_tools if t["name"] != prefixed_name
                ]

            self._tool_to_client[prefixed_name] = client
            # Сохраняем tool definition с prefixed name
            prefixed_tool = {**tool, "name": prefixed_name}
            self._all_tools.append(prefixed_tool)

        self._instances[instance_id] = (client, prefix, original_names)
        logger.info(
            "Instance '%s': зарегистрировано %d инструментов (prefix='%s')",
            instance_id, len(original_names), prefix,
        )

    def register_client(self, client: MCPClient) -> None:
        """Зарегистрировать все инструменты клиента (без prefix, backward compat)."""
        for tool in client.get_tools():
            tool_name = tool["name"]
            if tool_name in self._tool_to_client:
                logger.warning(
                    "Инструмент '%s' уже зарегистрирован от '%s', перезаписываю на '%s'",
                    tool_name, self._tool_to_client[tool_name].name, client.name,
                )
                self._all_tools = [t for t in self._all_tools if t["name"] != tool_name]
            self._tool_to_client[tool_name] = client
            self._all_tools.append(tool)

    def unregister_instance(self, instance_id: str) -> None:
        """Удалить все инструменты MCP-инстанса из реестра."""
        entry = self._instances.pop(instance_id, None)
        if not entry:
            return

        client, prefix, original_names = entry
        prefixed_names = [prefix + n if prefix else n for n in original_names]

        for name in prefixed_names:
            self._tool_to_client.pop(name, None)
        self._all_tools = [
            t for t in self._all_tools if t["name"] not in prefixed_names
        ]
        logger.info(
            "Instance '%s': удалено %d инструментов", instance_id, len(prefixed_names),
        )

    def unregister_client(self, client: MCPClient) -> None:
        """Удалить все инструменты клиента из реестра."""
        # Удаляем из instances если есть
        to_remove_ids = [
            iid for iid, (c, _, _) in self._instances.items() if c is client
        ]
        for iid in to_remove_ids:
            self.unregister_instance(iid)

        # Fallback: прямое удаление по клиенту
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

    def get_original_tool_name(self, prefixed_name: str) -> str:
        """Получить оригинальное имя инструмента (без namespace prefix).

        Нужно при вызове tool через MCP-клиент, который не знает о prefix.
        """
        for _iid, (_client, prefix, original_names) in self._instances.items():
            if not prefix:
                continue
            if prefixed_name.startswith(prefix):
                orig = prefixed_name[len(prefix):]
                if orig in original_names:
                    return orig
        # Если prefix не найден — возвращаем как есть
        return prefixed_name

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

    def filter_tools_for_instances(
        self,
        instance_ids: list[str],
        allowed_prefixes: list[str],
    ) -> list[dict[str, Any]]:
        """Получить инструменты из указанных instances с учётом policy.

        Сначала собирает все tools из запрошенных instances,
        потом фильтрует по allowed_prefixes.
        """
        # Собираем все prefixed names из запрошенных instances
        instance_tool_names: set[str] = set()
        for iid in instance_ids:
            entry = self._instances.get(iid)
            if not entry:
                continue
            _client, prefix, original_names = entry
            for orig in original_names:
                instance_tool_names.add(prefix + orig if prefix else orig)

        # Фильтруем _all_tools
        instance_tools = [
            t for t in self._all_tools if t["name"] in instance_tool_names
        ]

        if "*" in allowed_prefixes:
            return instance_tools

        return [
            t for t in instance_tools
            if any(t["name"].startswith(p) for p in allowed_prefixes)
        ]

    def clear(self) -> None:
        """Очистить реестр."""
        self._tool_to_client.clear()
        self._all_tools.clear()
        self._instances.clear()
