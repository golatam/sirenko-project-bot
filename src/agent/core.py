"""Ядро агента: цикл tool_use с Claude API.

Оптимизации:
- Prompt caching: system prompt + tools кешируются (экономия ~60-70%)
- Haiku-классификатор: определяет нужны ли tools и какие (~$0.0003/запрос)
- History summarization: сжимает старую историю через Haiku
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from src.agent.classifier import RequestClassification, classify_request
from src.agent.context import build_messages_from_history, trim_messages
from src.agent.prompts import build_system_prompt
from src.agent.summarizer import maybe_summarize
from src.agent.tools import mcp_tools_to_anthropic
from src.db.database import Database
from src.db.queries import (
    get_conversation_history,
    log_tool_call,
    save_message,
    track_cost,
)
from src.mcp.manager import MCPManager
from src.settings import Settings

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 15
MAX_TOKENS_BUDGET = 50_000  # Лимит по токенам на один запрос пользователя


@dataclass
class AgentResponse:
    """Результат работы агента."""
    text: str
    tool_calls_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model: str = ""
    pending_approval: PendingApproval | None = None
    cache_stats: str = ""  # "read:X write:Y" для диагностики


@dataclass
class PendingApproval:
    """Инструмент, ожидающий подтверждения пользователя."""
    tool_name: str
    tool_input: dict[str, Any]
    tool_use_id: str
    messages_snapshot: list[dict[str, Any]] = field(default_factory=list)


class AgentCore:
    """Основной цикл агента с оптимизациями токенов."""

    def __init__(self, settings: Settings, db: Database, mcp_manager: MCPManager) -> None:
        self.settings = settings
        self.db = db
        self.mcp = mcp_manager
        self.client = self._create_client(settings)

    @staticmethod
    def _create_client(settings: Settings) -> anthropic.AsyncAnthropic:
        """Создать Anthropic-клиент с учётом метода авторизации."""
        if settings.global_config.auth_method == "oauth" and settings.anthropic_auth_token:
            logger.info("Используем OAuth от подписки Claude")
            return anthropic.AsyncAnthropic(
                auth_token=settings.anthropic_auth_token,
                max_retries=2,
                timeout=60.0,
                default_headers={"anthropic-beta": "oauth-2025-04-20"},
            )
        logger.info("Используем API key")
        return anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=2,
            timeout=60.0,
        )

    async def run(
        self,
        project_id: str,
        user_message: str,
        model: str | None = None,
    ) -> AgentResponse:
        """Выполнить один цикл агента для пользовательского запроса."""
        project = self.settings.projects.get(project_id)
        if not project:
            return AgentResponse(text=f"Проект '{project_id}' не найден.")

        model = model or self.settings.global_config.default_model
        phase = project.phase

        # === Оптимизация 1: Haiku-классификатор ===
        available_categories = self._get_available_categories(project_id)
        classification = await classify_request(
            self.client, user_message, available_categories,
        )
        logger.info(
            "Классификация: tools=%s, categories=%s, simple=%s",
            classification.needs_tools, classification.categories, classification.is_simple,
        )

        # Простой запрос без инструментов → отвечаем через Haiku
        if classification.is_simple and not classification.needs_tools:
            return await self._simple_response(project_id, project, user_message, phase)

        # 1. Системный промпт
        system_prompt = build_system_prompt(project_id, project, phase)

        # 2. История из БД
        history = await get_conversation_history(self.db, project_id, limit=20)
        messages = build_messages_from_history(history)

        # === Оптимизация 3: Summarization ===
        messages = await maybe_summarize(self.client, self.db, project_id, messages)

        # Добавляем новое сообщение
        messages.append({"role": "user", "content": user_message})
        messages = trim_messages(messages)

        # 3. Инструменты — фильтруем по классификации
        if classification.needs_tools:
            project_tools = self.mcp.get_project_tools(project_id)
            # Дополнительная фильтрация по категориям от классификатора
            if classification.categories:
                prefixes = classification.tool_prefixes
                project_tools = [
                    t for t in project_tools
                    if any(t["name"].startswith(p) for p in prefixes)
                ] or project_tools  # fallback: все инструменты если фильтр пустой
            anthropic_tools = mcp_tools_to_anthropic(project_tools)
            logger.info(
                "Инструменты: %d из %d (префиксы: %s)",
                len(anthropic_tools),
                len(self.mcp.get_project_tools(project_id)),
                classification.tool_prefixes if classification.categories else "все",
            )
        else:
            anthropic_tools = []

        approval_list = self.mcp.get_tools_requiring_approval(project_id)

        # 4. Цикл tool_use
        total_input = 0
        total_output = 0
        total_cache_read = 0
        total_cache_write = 0
        tool_calls_count = 0

        # Логируем размер запроса для диагностики
        from src.utils.tokens import estimate_tokens
        est_sys = estimate_tokens(system_prompt)
        est_msgs = sum(
            estimate_tokens(str(m.get("content", ""))) + 10 for m in messages
        )
        est_tools = sum(
            estimate_tokens(str(t)) for t in anthropic_tools
        ) if anthropic_tools else 0
        logger.info(
            "Размер запроса: system~%d + msgs~%d + tools~%d = ~%d tokens",
            est_sys, est_msgs, est_tools, est_sys + est_msgs + est_tools,
        )

        for iteration in range(MAX_TOOL_ITERATIONS):
            logger.info("Итерация %d/%d, сообщений: %d, токены: %d",
                        iteration + 1, MAX_TOOL_ITERATIONS, len(messages),
                        total_input + total_output)

            # Проверка бюджета токенов
            if total_input + total_output > MAX_TOKENS_BUDGET:
                logger.warning("Бюджет токенов исчерпан (%d > %d)",
                               total_input + total_output, MAX_TOKENS_BUDGET)
                # Финальный вызов без tools — пусть Claude подведёт итог
                response = await self._call_claude(
                    model=model, system=system_prompt,
                    messages=messages, tools=None,
                )
                total_input += response.usage.input_tokens
                total_output += response.usage.output_tokens
                text = self._extract_text(response) or "Бюджет токенов исчерпан. Вот что удалось выяснить."
                break

            response = await self._call_claude(
                model=model,
                system=system_prompt,
                messages=messages,
                tools=anthropic_tools if anthropic_tools else None,
            )

            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens
            if hasattr(response.usage, "cache_read_input_tokens"):
                total_cache_read += response.usage.cache_read_input_tokens or 0
            if hasattr(response.usage, "cache_creation_input_tokens"):
                total_cache_write += response.usage.cache_creation_input_tokens or 0

            if response.stop_reason == "end_turn":
                text = self._extract_text(response)
                break

            if response.stop_reason == "tool_use":
                tool_blocks = [b for b in response.content if b.type == "tool_use"]
                messages.append({"role": "assistant", "content": self._serialize_content(response.content)})

                tool_results = []
                for tool_block in tool_blocks:
                    tool_name = tool_block.name
                    tool_input = tool_block.input
                    tool_use_id = tool_block.id

                    if tool_name in approval_list:
                        logger.info("Инструмент '%s' требует подтверждения", tool_name)
                        await save_message(self.db, project_id, "user", json.dumps(user_message))
                        await track_cost(self.db, project_id, model, total_input, total_output)

                        return AgentResponse(
                            text=self._extract_text(response),
                            tool_calls_count=tool_calls_count,
                            tokens_input=total_input,
                            tokens_output=total_output,
                            model=model,
                            pending_approval=PendingApproval(
                                tool_name=tool_name,
                                tool_input=tool_input,
                                tool_use_id=tool_use_id,
                                messages_snapshot=messages,
                            ),
                        )

                    tool_calls_count += 1
                    start = time.monotonic()
                    try:
                        result_text = await self.mcp.call_tool(tool_name, tool_input)
                        latency = int((time.monotonic() - start) * 1000)
                        await log_tool_call(
                            self.db, project_id, tool_name, tool_input,
                            result_text, model, latency_ms=latency,
                        )
                    except Exception as e:
                        latency = int((time.monotonic() - start) * 1000)
                        error_msg = f"Ошибка: {e}"
                        await log_tool_call(
                            self.db, project_id, tool_name, tool_input,
                            error_msg, model, latency_ms=latency, is_error=True,
                        )
                        result_text = error_msg

                    # Обрезаем результат чтобы не раздувать контекст
                    truncated = self._truncate_tool_result(result_text)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": truncated,
                    })

                messages.append({"role": "user", "content": tool_results})

                # Тримим messages если раздулись (сохраняем первое + последние)
                messages = trim_messages(messages)
                continue

            text = self._extract_text(response)
            break
        else:
            # Лимит итераций — финальный вызов без tools для подведения итога
            logger.warning("Достигнут лимит итераций (%d)", MAX_TOOL_ITERATIONS)
            response = await self._call_claude(
                model=model, system=system_prompt,
                messages=messages, tools=None,
            )
            total_input += response.usage.input_tokens
            total_output += response.usage.output_tokens
            text = self._extract_text(response) or "Достигнут лимит итераций."

        # 5. Сохраняем в БД
        await save_message(self.db, project_id, "user", json.dumps(user_message))
        await save_message(
            self.db, project_id, "assistant", json.dumps(text),
            tokens_input=total_input, tokens_output=total_output,
        )
        await track_cost(self.db, project_id, model, total_input, total_output)

        cache_stats = ""
        if total_cache_read or total_cache_write:
            cache_stats = f"cache read:{total_cache_read} write:{total_cache_write}"
            logger.info("Prompt cache: %s", cache_stats)

        return AgentResponse(
            text=text,
            tool_calls_count=tool_calls_count,
            tokens_input=total_input,
            tokens_output=total_output,
            model=model,
            cache_stats=cache_stats,
        )

    async def _simple_response(
        self, project_id: str, project, user_message: str, phase: str,
    ) -> AgentResponse:
        """Быстрый ответ на простой запрос через Haiku без tools.

        Экономия: Haiku ($1/M vs $3/M) + нет tool definitions (~2000 токенов меньше).
        """
        system_prompt = build_system_prompt(project_id, project, phase)
        model = "claude-haiku-4-5"

        # Берём минимум истории для контекста
        history = await get_conversation_history(self.db, project_id, limit=6)
        messages = build_messages_from_history(history)
        messages.append({"role": "user", "content": user_message})

        response = await self._call_claude(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=None,
        )

        text = self._extract_text(response)

        await save_message(self.db, project_id, "user", json.dumps(user_message))
        await save_message(
            self.db, project_id, "assistant", json.dumps(text),
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
        )
        await track_cost(self.db, project_id, model,
                         response.usage.input_tokens, response.usage.output_tokens)

        return AgentResponse(
            text=text, model=model,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
        )

    async def execute_approved_tool(
        self,
        project_id: str,
        approval: PendingApproval,
    ) -> AgentResponse:
        """Выполнить инструмент после подтверждения и продолжить цикл агента."""
        model = self.settings.global_config.default_model
        messages = approval.messages_snapshot

        start = time.monotonic()
        try:
            result_text = await self.mcp.call_tool(approval.tool_name, approval.tool_input)
            latency = int((time.monotonic() - start) * 1000)
            await log_tool_call(
                self.db, project_id, approval.tool_name, approval.tool_input,
                result_text, model, latency_ms=latency,
            )
        except Exception as e:
            latency = int((time.monotonic() - start) * 1000)
            result_text = f"Ошибка: {e}"
            await log_tool_call(
                self.db, project_id, approval.tool_name, approval.tool_input,
                result_text, model, latency_ms=latency, is_error=True,
            )

        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": approval.tool_use_id,
                "content": result_text,
            }],
        })

        project = self.settings.projects[project_id]
        system_prompt = build_system_prompt(project_id, project, project.phase)
        project_tools = self.mcp.get_project_tools(project_id)
        anthropic_tools = mcp_tools_to_anthropic(project_tools)

        response = await self._call_claude(
            model=model,
            system=system_prompt,
            messages=messages,
            tools=anthropic_tools if anthropic_tools else None,
        )

        text = self._extract_text(response)

        await save_message(
            self.db, project_id, "assistant", json.dumps(text),
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
        )
        await track_cost(
            self.db, project_id, model,
            response.usage.input_tokens, response.usage.output_tokens,
        )

        return AgentResponse(
            text=text,
            tool_calls_count=1,
            tokens_input=response.usage.input_tokens,
            tokens_output=response.usage.output_tokens,
            model=model,
        )

    async def _call_claude(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> anthropic.types.Message:
        """Вызвать Claude Messages API с prompt caching."""
        # === Оптимизация 2: Prompt Caching ===
        # System prompt кешируется — повторные запросы платят 10% за кешированную часть
        system_with_cache = [{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }]

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": self.settings.global_config.max_tokens,
            "system": system_with_cache,
            "messages": messages,
        }

        if tools:
            # Кешируем и tools — они тоже повторяются
            # cache_control на последнем tool — кеширует весь блок tools
            cached_tools = list(tools)
            if cached_tools:
                cached_tools[-1] = {
                    **cached_tools[-1],
                    "cache_control": {"type": "ephemeral"},
                }
            kwargs["tools"] = cached_tools

        logger.info("→ API вызов: model=%s, max_tokens=%d, msgs=%d, tools=%s",
                    model, kwargs["max_tokens"], len(messages),
                    len(tools) if tools else 0)
        try:
            result = await self.client.messages.create(**kwargs)
            logger.info("← API ответ: input=%d, output=%d, stop=%s",
                        result.usage.input_tokens, result.usage.output_tokens,
                        result.stop_reason)
            return result
        except Exception as e:
            logger.error("← API ошибка: %s", e)
            raise

    def _get_available_categories(self, project_id: str) -> list[str]:
        """Определить доступные категории инструментов для проекта."""
        project = self.settings.projects.get(project_id)
        if not project:
            return []

        categories = []
        if project.gmail.enabled:
            categories.append("gmail")
        if project.calendar.enabled:
            categories.append("calendar")
        if project.telegram_monitor.enabled:
            categories.append("telegram")
        return categories

    @staticmethod
    def _truncate_tool_result(text: str, max_chars: int = 2000) -> str:
        """Обрезать результат инструмента для экономии токенов."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[обрезано]"

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts) if parts else ""

    @staticmethod
    def _serialize_content(content: list) -> list[dict[str, Any]]:
        result = []
        for block in content:
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        return result
