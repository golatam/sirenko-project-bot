"""Haiku-классификатор запросов: определяет нужны ли инструменты и какие."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "claude-haiku-4-5"

CLASSIFICATION_PROMPT = """Ты — классификатор запросов. Определи, что нужно для ответа на запрос пользователя.

Доступные категории инструментов:
- gmail: поиск, чтение email
- calendar: события, расписание
- telegram: сообщения, контакты в Telegram-чатах
- none: инструменты не нужны, обычный разговор

Ответь ТОЛЬКО валидным JSON без markdown:
{"needs_tools": true/false, "categories": ["gmail", "calendar"], "is_simple": true/false}

- needs_tools: нужны ли внешние инструменты для ответа
- categories: какие категории нужны (пустой список если needs_tools=false)
- is_simple: можно ли ответить коротко без глубокого анализа (приветствие, благодарность, ок, простой вопрос)"""


@dataclass
class RequestClassification:
    needs_tools: bool
    categories: list[str]
    is_simple: bool

    @property
    def tool_prefixes(self) -> list[str]:
        """Преобразовать категории в префиксы для фильтрации инструментов."""
        prefix_map = {
            "gmail": ["search_emails", "read_email", "draft_email", "send_email",
                       "gmail", "list_email", "get_email"],
            "calendar": ["list_events", "create_event", "update_event", "delete_event",
                         "calendar", "get_event", "freebusy"],
            "telegram": ["get_messages", "send_message", "search_messages",
                         "telegram", "get_contacts", "get_chats"],
        }
        prefixes = []
        for cat in self.categories:
            prefixes.extend(prefix_map.get(cat, [cat]))
        return prefixes


async def classify_request(
    client: anthropic.AsyncAnthropic,
    user_message: str,
    available_categories: list[str],
) -> RequestClassification:
    """Классифицировать запрос пользователя через Haiku.

    Стоимость: ~200 input + ~50 output токенов = ~$0.0003
    """
    try:
        response = await client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=100,
            system=CLASSIFICATION_PROMPT,
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
        # Fallback: считаем что нужны все инструменты
        return RequestClassification(
            needs_tools=True,
            categories=available_categories,
            is_simple=False,
        )
