"""Клиент для одного MCP-сервера."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Обёртка над одним MCP-сервером (stdio transport)."""

    def __init__(self, name: str, server_params: StdioServerParameters) -> None:
        self.name = name
        self.server_params = server_params
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[dict[str, Any]] = []
        self._pid: int | None = None

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        """Запустить MCP-сервер и установить соединение."""
        self._exit_stack = AsyncExitStack()
        try:
            read_stream, write_stream = await self._exit_stack.enter_async_context(
                stdio_client(self.server_params)
            )
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()

            # Кешируем список инструментов
            tools_result = await self._session.list_tools()
            self._tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                }
                for tool in tools_result.tools
            ]
            logger.info(
                "MCP '%s' подключён, доступно инструментов: %d",
                self.name, len(self._tools),
            )
        except Exception:
            logger.exception("Ошибка подключения MCP '%s'", self.name)
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        """Остановить MCP-сервер."""
        exit_stack = self._exit_stack
        # Очищаем состояние сразу, чтобы клиент считался отключённым
        self._session = None
        self._exit_stack = None
        self._tools = []
        if exit_stack:
            try:
                await asyncio.wait_for(exit_stack.aclose(), timeout=5.0)
            except BaseException:
                # CancelledError (BaseException) + RuntimeError от anyio cancel scopes
                logger.warning(
                    "MCP '%s': корректное отключение не удалось, "
                    "процесс будет остановлен при завершении бота",
                    self.name,
                )

    async def reconnect(self) -> None:
        """Переподключиться к серверу."""
        logger.info("Переподключение MCP '%s'...", self.name)
        await self.disconnect()
        await self.connect()

    def get_tools(self) -> list[dict[str, Any]]:
        """Получить кешированный список инструментов."""
        return self._tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any],
                        timeout: float = 60.0) -> str:
        """Вызвать инструмент MCP-сервера с таймаутом."""
        if not self._session:
            raise RuntimeError(f"MCP '{self.name}' не подключён")

        logger.debug("MCP '%s': вызов %s(%s)", self.name, tool_name, arguments)
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Таймаут вызова %s на MCP '%s' (%ds)", tool_name, self.name, timeout)
            self._session = None  # Помечаем как disconnected
            raise RuntimeError(f"Таймаут вызова {tool_name} на MCP '{self.name}'")
        except Exception:
            logger.exception("Ошибка вызова %s на MCP '%s'", tool_name, self.name)
            raise

        # Извлекаем текст из результата
        if result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)
        return ""
