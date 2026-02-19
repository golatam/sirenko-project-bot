"""Управление контекстным окном: обрезка, сжатие истории."""

from __future__ import annotations

import json
from typing import Any

from src.db.models import Conversation
from src.utils.tokens import estimate_tokens


def build_messages_from_history(history: list[Conversation]) -> list[dict[str, Any]]:
    """Собрать список messages для Anthropic API из истории БД."""
    messages: list[dict[str, Any]] = []
    for msg in history:
        try:
            content = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            content = msg.content

        messages.append({"role": msg.role, "content": content})

    return messages


def trim_messages(messages: list[dict[str, Any]], max_tokens: int = 150_000) -> list[dict[str, Any]]:
    """Обрезать историю сообщений, чтобы уложиться в лимит токенов.

    Стратегия: сохраняем системный промпт + последние N сообщений.
    Удаляем самые старые сообщения первыми.
    """
    if not messages:
        return messages

    total = _estimate_messages_tokens(messages)
    if total <= max_tokens:
        return messages

    # Убираем старые сообщения, начиная с начала (сохраняя последние)
    trimmed = list(messages)
    while len(trimmed) > 2 and _estimate_messages_tokens(trimmed) > max_tokens:
        trimmed.pop(0)

    return trimmed


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Оценить количество токенов в списке сообщений."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        total += estimate_tokens(block["text"])
                    elif "content" in block:
                        total += estimate_tokens(str(block["content"]))
                else:
                    total += estimate_tokens(str(block))
        total += 10  # overhead per message
    return total
