"""Haiku-классификатор запросов: определяет нужны ли инструменты и какие.

Динамически формирует промпт на основе доступных категорий из MCP_TYPE_META.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from src.mcp.types import MCP_TYPE_META, TOOL_PREFIX_MAP, McpServerType

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "claude-haiku-4-5"


def _build_classification_prompt(available_categories: list[str]) -> str:
    """Собрать промпт классификатора из доступных категорий."""
    category_lines = []
    for cat in available_categories:
        # Ищем meta по category name
        meta = None
        for stype, m in MCP_TYPE_META.items():
            if m.category == cat:
                meta = m
                break
        if meta:
            category_lines.append(f"- {cat}: {meta.capability_description}")
        else:
            category_lines.append(f"- {cat}")

    category_lines.append("- none: инструменты не нужны, обычный разговор")
    categories_block = "\n".join(category_lines)

    return (
        "Ты — классификатор запросов. Определи, что нужно для ответа на запрос пользователя.\n\n"
        f"Доступные категории инструментов:\n{categories_block}\n\n"
        'Ответь ТОЛЬКО валидным JSON без markdown:\n'
        '{"needs_tools": true/false, "categories": ["gmail", "calendar"], "is_simple": true/false}\n\n'
        "- needs_tools: нужны ли внешние инструменты для ответа\n"
        "- categories: какие категории нужны (пустой список если needs_tools=false)\n"
        "- is_simple: можно ли ответить коротко без глубокого анализа "
        "(приветствие, благодарность, ок, простой вопрос)"
    )


def _build_tool_prefixes(categories: list[str]) -> list[str]:
    """Преобразовать категории в префиксы для фильтрации инструментов.

    Собирает все tool_prefixes (read + write) из MCP_TYPE_META
    с учётом namespace prefix из TOOL_PREFIX_MAP.
    """
    prefixes: list[str] = []
    for cat in categories:
        for stype, meta in MCP_TYPE_META.items():
            if meta.category == cat:
                ns_prefix = TOOL_PREFIX_MAP.get(stype, "")
                for p in meta.all_prefixes:
                    prefixes.append(ns_prefix + p if ns_prefix else p)
                break
    return prefixes


@dataclass
class RequestClassification:
    needs_tools: bool
    categories: list[str]
    is_simple: bool

    @property
    def tool_prefixes(self) -> list[str]:
        """Преобразовать категории в префиксы для фильтрации инструментов."""
        return _build_tool_prefixes(self.categories)


async def classify_request(
    client: anthropic.AsyncAnthropic,
    user_message: str,
    available_categories: list[str],
) -> RequestClassification:
    """Классифицировать запрос пользователя через Haiku.

    Стоимость: ~200 input + ~50 output токенов = ~$0.0003
    """
    prompt = _build_classification_prompt(available_categories)

    try:
        response = await client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=100,
            system=prompt,
            messages=[{
                "role": "user",
                "content": f"Доступные категории: {', '.join(available_categories)}\n\nЗапрос: {user_message}",
            }],
        )

        text = response.content[0].text.strip()
        data = json.loads(text)

        # Фильтруем категории — оставляем только реально доступные
        categories = [c for c in data.get("categories", []) if c in available_categories]

        return RequestClassification(
            needs_tools=data.get("needs_tools", True),
            categories=categories,
            is_simple=data.get("is_simple", False),
        )
    except Exception:
        logger.debug("Классификатор не смог разобрать ответ, используем все инструменты")
        return RequestClassification(
            needs_tools=True,
            categories=available_categories,
            is_simple=False,
        )
