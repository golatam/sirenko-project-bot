"""Менеджер жизненного цикла MCP-серверов."""

from __future__ import annotations

import logging
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import StdioServerParameters

from src.mcp.client import MCPClient
from src.mcp.registry import ToolRegistry
from src.settings import ProjectConfig, Settings

logger = logging.getLogger(__name__)


class MCPManager:
    """Управление запуском/остановкой MCP-серверов для всех проектов."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.clients: dict[str, MCPClient] = {}  # client_id → MCPClient
        self.registry = ToolRegistry()
        self._project_clients: dict[str, list[str]] = {}  # project_id → [client_ids]
        self._orphaned_stacks: list[AsyncExitStack] = []  # от удалённых проектов

    async def start_all(self) -> None:
        """Запустить MCP-серверы для всех проектов."""
        for project_id, project in self.settings.projects.items():
            await self._start_project_servers(project_id, project)

    async def start_project(self, project_id: str, project: ProjectConfig) -> None:
        """Запустить MCP-серверы для одного проекта (публичная обёртка)."""
        await self._start_project_servers(project_id, project)

    async def stop_project(self, project_id: str) -> None:
        """Остановить и очистить MCP-серверы одного проекта.

        Не вызывает disconnect (anyio cancel scopes ломают event loop
        при вызове из хендлера). Отключаем клиент от реестра и чистим
        состояние; exit_stack и дочерние процессы будут убиты при shutdown.
        """
        client_ids = self._project_clients.pop(project_id, [])
        for cid in client_ids:
            client = self.clients.pop(cid, None)
            if client:
                self.registry.unregister_client(client)
                # Очищаем состояние без вызова exit_stack.aclose()
                client._session = None
                client._tools = []
                # Сохраняем exit_stack для очистки при shutdown
                if client._exit_stack:
                    self._orphaned_stacks.append(client._exit_stack)
                    client._exit_stack = None
        logger.info("Проект '%s': остановлено %d MCP-серверов", project_id, len(client_ids))

    async def stop_all(self) -> None:
        """Остановить все MCP-серверы."""
        for client in self.clients.values():
            await client.disconnect()
        # Закрываем orphaned stacks от удалённых проектов
        for stack in self._orphaned_stacks:
            try:
                await stack.aclose()
            except BaseException:
                pass
        self._orphaned_stacks.clear()
        self.clients.clear()
        self.registry.clear()
        self._project_clients.clear()
        logger.info("Все MCP-серверы остановлены")

    async def _start_project_servers(self, project_id: str, project: ProjectConfig) -> None:
        """Запустить MCP-серверы для одного проекта."""
        client_ids: list[str] = []

        if project.gmail.enabled:
            client_id = f"{project_id}_gmail"
            client = self._create_gmail_client(client_id, project)
            try:
                await client.connect()
                self.clients[client_id] = client
                self.registry.register_client(client)
                client_ids.append(client_id)
            except Exception:
                logger.error("Не удалось запустить Gmail MCP для '%s'", project_id)

        if project.calendar.enabled:
            client_id = f"{project_id}_calendar"
            client = self._create_calendar_client(client_id, project)
            try:
                await client.connect()
                self.clients[client_id] = client
                self.registry.register_client(client)
                client_ids.append(client_id)
            except Exception:
                logger.error("Не удалось запустить Calendar MCP для '%s'", project_id)

        self._project_clients[project_id] = client_ids
        logger.info("Проект '%s': запущено %d MCP-серверов", project_id, len(client_ids))

    def _create_gmail_client(self, client_id: str, project: ProjectConfig) -> MCPClient:
        """Создать MCP-клиент для Gmail."""
        creds_dir = os.path.abspath(project.gmail.credentials_dir)
        return MCPClient(
            name=client_id,
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
                env={
                    **os.environ,
                    "GMAIL_CREDENTIALS_DIR": creds_dir,
                },
            ),
        )

    def _create_calendar_client(self, client_id: str, project: ProjectConfig) -> MCPClient:
        """Создать MCP-клиент для Google Calendar."""
        return MCPClient(
            name=client_id,
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@cocal/google-calendar-mcp"],
                env={
                    **os.environ,
                    "CALENDAR_ACCOUNT": project.calendar.account_id,
                },
            ),
        )

    def get_project_tools(self, project_id: str) -> list[dict[str, Any]]:
        """Получить инструменты, доступные для проекта с учётом фазы."""
        project = self.settings.projects.get(project_id)
        if not project:
            return []

        policy = project.get_active_policy()
        return self.registry.filter_tools(policy.allowed_prefixes)

    def get_tools_requiring_approval(self, project_id: str) -> list[str]:
        """Получить список инструментов, требующих подтверждения."""
        project = self.settings.projects.get(project_id)
        if not project:
            return []
        return project.get_active_policy().requires_approval

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Вызвать инструмент через соответствующий MCP-клиент."""
        client = self.registry.get_client_for_tool(tool_name)
        if not client:
            raise ValueError(f"Инструмент '{tool_name}' не найден в реестре")

        if not client.is_connected:
            logger.warning("MCP '%s' отключён, переподключение...", client.name)
            await client.reconnect()
            self.registry.register_client(client)

        return await client.call_tool(tool_name, arguments)
