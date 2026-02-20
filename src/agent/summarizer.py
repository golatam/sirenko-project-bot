"""Автоматическое сжатие истории разговора через Haiku."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from src.db.database import Database

logger = logging.getLogger(__name__)

SUMMARIZER_MODEL = "claude-haiku-4-5"
# Порог: после скольки сообщений делать summarization
SUMMARIZE_THRESHOLD = 20
# Сколько последних сообщений оставляем как есть
KEEP_RECENT = 10

SUMMARIZE_PROMPT = """Сожми следующую историю разговора в краткое резюме на русском языке.
ОБЯЗАТЕЛЬНО сохрани:
- Все email-адреса, номера телефонов, ссылки
- Имена людей, компании, их роли и язык общения
- Конкретные даты, время, часовые пояса
- Какие действия РЕАЛЬНО выполнены (отправлены письма, созданы события) — с деталями
- Какие договорённости и предпочтения озвучены пользователем (например: "встречи по 30 минут", "не добавлять подпись")

Формат: 5-15 пунктов, каждый — одно конкретное предложение с фактами. Без вводных слов.
Ответь ТОЛЬКО списком пунктов."""


async def maybe_summarize(
    client: anthropic.AsyncAnthropic,
    db: Database,
    project_id: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Если сообщений больше порога — сжать старые в summary.

    Возвращает новый список messages:
    [summary_message] + [последние KEEP_RECENT сообщений]

    Стоимость одного сжатия: ~2K input + ~200 output = ~$0.003
    """
    if len(messages) < SUMMARIZE_THRESHOLD:
        return messages

    # Разделяем: старые (для сжатия) и свежие (оставляем)
    old_messages = messages[:-KEEP_RECENT]
    recent_messages = messages[-KEEP_RECENT:]

    logger.info(
        "Сжатие истории проекта '%s': %d старых → summary, %d свежих сохраняем",
        project_id, len(old_messages), len(recent_messages),
    )

    # Форматируем старые сообщения для Haiku
    history_text = _format_messages_for_summary(old_messages)

    try:
        response = await client.messages.create(
            model=SUMMARIZER_MODEL,
            max_tokens=500,
            system=SUMMARIZE_PROMPT,
            messages=[{"role": "user", "content": history_text}],
        )
        summary = response.content[0].text.strip()
    except Exception:
        logger.exception("Ошибка при сжатии истории, возвращаем как есть")
        return messages

    # Сохраняем summary в БД
    await db.execute(
        "INSERT INTO conversation_summaries (project_id, summary, messages_start_id, messages_end_id) "
        "VALUES (?, ?, 0, 0)",
        (project_id, summary),
    )
    await db.commit()

    # Собираем новый список: summary как user-сообщение + свежие
    summary_message = {
        "role": "user",
        "content": f"[Краткое резюме предыдущего разговора]\n{summary}\n[Конец резюме, продолжаем разговор]",
    }

    # Нужно чтобы первое сообщение после summary было от assistant
    # если recent_messages начинается с user — вставляем summary перед ними
    result = [summary_message]

    # Если первое свежее — от user, нужна прокладка от assistant
    if recent_messages and recent_messages[0]["role"] == "user":
        result.append({"role": "assistant", "content": "Понял, продолжаем."})

    result.extend(recent_messages)

    # Гарантируем чередование ролей
    result = _fix_role_alternation(result)

    logger.info("История сжата: %d → %d сообщений", len(messages), len(result))
    return result


async def get_previous_summary(db: Database, project_id: str) -> str | None:
    """Получить последнее сохранённое резюме для проекта."""
    row = await db.fetchone(
        "SELECT summary FROM conversation_summaries "
        "WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    return row["summary"] if row else None


def _format_messages_for_summary(messages: list[dict[str, Any]]) -> str:
    """Преобразовать сообщения в текст для summarization."""
    parts = []
    for msg in messages:
        role = "Пользователь" if msg["role"] == "user" else "Ассистент"
        content = msg.get("content", "")
        if isinstance(content, list):
            # Извлекаем текст из блоков
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block["text"])
                    elif block.get("type") == "tool_result":
                        texts.append(f"[Результат инструмента: {block.get('content', '')[:200]}]")
                    elif block.get("type") == "tool_use":
                        texts.append(f"[Вызов: {block.get('name', '?')}]")
            content = "\n".join(texts)
        if isinstance(content, str) and content:
            # Обрезаем длинные сообщения
            if len(content) > 500:
                content = content[:500] + "..."
            parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def _fix_role_alternation(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Гарантировать чередование user/assistant в messages."""
    if not messages:
        return messages

    fixed = [messages[0]]
    for msg in messages[1:]:
        if msg["role"] == fixed[-1]["role"]:
            # Вставляем прокладку
            filler_role = "assistant" if msg["role"] == "user" else "user"
            filler_content = "Продолжай." if filler_role == "user" else "Хорошо."
            fixed.append({"role": filler_role, "content": filler_content})
        fixed.append(msg)

    # Первое сообщение должно быть от user
    if fixed[0]["role"] != "user":
        fixed.insert(0, {"role": "user", "content": "Продолжай."})

    return fixed
