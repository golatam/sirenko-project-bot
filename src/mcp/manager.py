"""Менеджер жизненного цикла MCP-серверов (instance-based)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from src.mcp.client import MCPClient
from src.mcp.factory import create_server_params
from src.mcp.registry import ToolRegistry
from src.mcp.types import TOOL_PREFIX_MAP, McpInstanceConfig, McpServerType
from src.settings import ProjectConfig, Settings

logger = logging.getLogger(__name__)


class MCPManager:
    """Управление запуском/остановкой MCP-серверов для всех проектов.

    Instance-based: один MCP-процесс может обслуживать несколько проектов.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.instances: dict[str, MCPClient] = {}  # instance_id → MCPClient
        self.registry = ToolRegistry()
        self._instance_refcount: dict[str, set[str]] = {}  # instance_id → {project_ids}
        self._orphaned_stacks: list[AsyncExitStack] = []
        self._lock = asyncio.Lock()  # Защита от concurrent start/stop

    async def start_all(self) -> None:
        """Запустить MCP-серверы для всех проектов.

        Каждый instance запускается один раз, даже если используется
        несколькими проектами.
        """
        # Собираем все нужные instances из всех проектов
        needed: dict[str, McpInstanceConfig] = {}
        for project_id, project in self.settings.projects.items():
            for instance_id in project.mcp_services:
                config = self.settings.global_config.mcp_instances.get(instance_id)
                if config:
                    needed[instance_id] = config
                    # Трекинг refcount
                    self._instance_refcount.setdefault(instance_id, set()).add(project_id)
                else:
                    logger.warning(
                        "Проект '%s': instance '%s' не найден в mcp_instances",
                        project_id, instance_id,
                    )

        # Запускаем каждый instance один раз
        for instance_id, config in needed.items():
            await self._start_instance(instance_id, config)

    async def start_project(self, project_id: str, project: ProjectConfig) -> None:
        """Запустить MCP-серверы для одного проекта.

        Если instance уже запущен (используется другим проектом),
        просто увеличиваем refcount.
        """
        async with self._lock:
            for instance_id in project.mcp_services:
                config = self.settings.global_config.mcp_instances.get(instance_id)
                if not config:
                    logger.warning(
                        "Проект '%s': instance '%s' не найден", project_id, instance_id,
                    )
                    continue

                self._instance_refcount.setdefault(instance_id, set()).add(project_id)

                if instance_id not in self.instances:
                    await self._start_instance(instance_id, config)
                else:
                    logger.info(
                        "Instance '%s' уже запущен, добавляем проект '%s'",
                        instance_id, project_id,
                    )

    async def stop_project(self, project_id: str) -> None:
        """Остановить MCP-серверы проекта.

        Instance останавливается только если ни один другой проект
        его не использует (refcount = 0).
        """
        async with self._lock:
            project = self.settings.projects.get(project_id)
            instance_ids = project.mcp_services if project else []

            for instance_id in instance_ids:
                refs = self._instance_refcount.get(instance_id)
                if refs:
                    refs.discard(project_id)
                    if not refs:
                        self._instance_refcount.pop(instance_id, None)
                        client = self.instances.pop(instance_id, None)
                        if client:
                            self.registry.unregister_instance(instance_id)
                            client._session = None
                            client._tools = []
                            if client._exit_stack:
                                self._orphaned_stacks.append(client._exit_stack)
                                client._exit_stack = None
                        logger.info(
                            "Instance '%s' остановлен (проект '%s' был последним)",
                            instance_id, project_id,
                        )
                    else:
                        logger.info(
                            "Instance '%s' продолжает работу (используется: %s)",
                            instance_id, ", ".join(refs),
                        )

            logger.info("Проект '%s': MCP-серверы отвязаны", project_id)

    async def stop_all(self) -> None:
        """Остановить все MCP-серверы."""
        for client in self.instances.values():
            await client.disconnect()
        for stack in self._orphaned_stacks:
            try:
                await stack.aclose()
            except BaseException:
                pass
        self._orphaned_stacks.clear()
        self.instances.clear()
        self.registry.clear()
        self._instance_refcount.clear()
        logger.info("Все MCP-серверы остановлены")

    async def _start_instance(
        self, instance_id: str, config: McpInstanceConfig,
    ) -> None:
        """Запустить один MCP-инстанс через factory."""
        try:
            server_params = create_server_params(config)
            client = MCPClient(name=instance_id, server_params=server_params)
            await client.connect()

            prefix = TOOL_PREFIX_MAP.get(config.type, "")
            self.registry.register_instance(instance_id, client, prefix=prefix)
            self.instances[instance_id] = client

            logger.info(
                "Instance '%s' (%s) запущен, инструментов: %d",
                instance_id, config.type.value, len(client.get_tools()),
            )
        except Exception:
            logger.exception(
                "Не удалось запустить instance '%s' (%s)",
                instance_id, config.type.value,
            )

    def get_project_tools(self, project_id: str) -> list[dict[str, Any]]:
        """Получить инструменты, доступные для проекта с учётом фазы."""
        project = self.settings.projects.get(project_id)
        if not project:
            return []

        policy = project.get_active_policy()
        return self.registry.filter_tools_for_instances(
            project.mcp_services, policy.allowed_prefixes,
        )

    def get_tools_requiring_approval(self, project_id: str) -> list[str]:
        """Получить список инструментов, требующих подтверждения."""
        project = self.settings.projects.get(project_id)
        if not project:
            return []
        return project.get_active_policy().requires_approval

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any],
        project_id: str | None = None,
    ) -> str:
        """Вызвать инструмент через соответствующий MCP-клиент.

        Учитывает namespace prefix: tool_name может содержать prefix
        (например tg_send_message), но MCP-сервер ожидает оригинальное
        имя (send_message).

        project_id — для корректной маршрутизации при одинаковых tool names
        (например, два Gmail-инстанса для разных проектов).
        """
        # Приоритетный lookup по инстансам проекта
        client = None
        if project_id:
            project = self.settings.projects.get(project_id)
            if project:
                client = self.registry.get_client_for_tool_in_instances(
                    tool_name, project.mcp_services,
                )
        if not client:
            client = self.registry.get_client_for_tool(tool_name)
        if not client:
            raise ValueError(f"Инструмент '{tool_name}' не найден в реестре")

        if not client.is_connected:
            logger.warning("MCP '%s' отключён, переподключение...", client.name)
            await client.reconnect()
            # Найдём config для повторной регистрации
            config = self.settings.global_config.mcp_instances.get(client.name)
            if config:
                prefix = TOOL_PREFIX_MAP.get(config.type, "")
                self.registry.register_instance(client.name, client, prefix=prefix)
            else:
                self.registry.register_client(client)

        # Преобразуем prefixed name → original name для вызова
        original_name = self.registry.get_original_tool_name(tool_name)
        return await client.call_tool(original_name, arguments)
