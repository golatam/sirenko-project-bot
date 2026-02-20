"""Обработчик свободного текста → запуск цикла агента."""

from __future__ import annotations

import asyncio
import json
import logging

import anthropic
from aiogram import Router
from aiogram.types import Message

from src.agent.core import AgentCore
from src.bot.keyboards import approval_keyboard
from src.db.database import Database
from src.db.queries import create_approval
from src.settings import Settings
from src.utils.formatting import bold, code, escape, format_agent_response
from src.utils.tokens import format_cost, format_tokens

logger = logging.getLogger(__name__)

router = Router(name="queries")

# Таймаут typing-индикатора в Telegram ~5 сек, обновляем каждые 4
_TYPING_INTERVAL = 4.0


async def _keep_typing(chat_id: int, bot, stop: asyncio.Event) -> None:
    """Периодически отправляет typing-индикатор пока stop не установлен."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=_TYPING_INTERVAL)
            break
        except asyncio.TimeoutError:
            continue


@router.message()
async def handle_query(
    message: Message,
    project_id: str | None = None,
    settings: Settings = None,
    db: Database = None,
    agent: AgentCore = None,
    **kwargs,
) -> None:
    """Обработка любого текстового сообщения → запуск агента."""
    if not message.text:
        return

    if not project_id:
        await message.answer(
            "Сначала выбери проект командой /project"
        )
        return

    # Статусное сообщение + фоновый typing
    status_msg = await message.answer("Думаю...")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing(message.chat.id, message.bot, stop_typing)
    )

    try:
        logger.info("[handler] Запуск agent.run для проекта '%s'", project_id)
        result = await agent.run(
            project_id=project_id,
            user_message=message.text,
        )
        logger.info("[handler] agent.run завершён, text=%d chars", len(result.text or ""))
    except anthropic.APIStatusError as e:
        stop_typing.set()
        await typing_task
        logger.exception("API ошибка для проекта '%s'", project_id)
        if e.status_code == 529:
            error_text = "API Claude перегружен. Попробуй через пару минут."
        elif e.status_code == 429:
            error_text = "Превышен лимит запросов. Подожди немного."
        else:
            error_text = f"Ошибка API (код {e.status_code}). Попробуй ещё раз."
        await status_msg.edit_text(error_text)
        return
    except Exception:
        stop_typing.set()
        await typing_task
        logger.exception("Ошибка агента для проекта '%s'", project_id)
        await status_msg.edit_text(
            "Произошла ошибка при обработке запроса. Попробуй ещё раз."
        )
        return
    finally:
        stop_typing.set()
        await typing_task  # Дожидаемся завершения typing-задачи

    # Удаляем статусное сообщение — дальше отправляем финальный ответ
    logger.info("[handler] Удаляем статусное сообщение")
    try:
        await status_msg.delete()
    except Exception:
        pass

    # Если требуется подтверждение
    if result.pending_approval:
        approval = result.pending_approval
        logger.info("[handler] Требуется подтверждение: %s", approval.tool_name)
        # Сохраняем в БД
        approval_id = await create_approval(
            db=db,
            project_id=project_id,
            tool_name=approval.tool_name,
            tool_input=approval.tool_input,
            conversation_context=json.dumps(
                approval.messages_snapshot, ensure_ascii=False, default=str
            ),
        )

        text_parts = []
        if result.text:
            text_parts.append(format_agent_response(result.text))
            text_parts.append("")

        text_parts.append(f"Требуется подтверждение действия:\n")
        text_parts.append(f"Инструмент: {bold(approval.tool_name)}")

        # Показываем параметры (с обрезкой)
        input_str = json.dumps(approval.tool_input, ensure_ascii=False, indent=2)
        if len(input_str) > 500:
            input_str = input_str[:500] + "..."
        text_parts.append(f"\nПараметры:\n<pre>{escape(input_str)}</pre>")

        sent = await message.answer(
            "\n".join(text_parts),
            parse_mode="HTML",
            reply_markup=approval_keyboard(approval_id),
        )

        # Обновляем telegram_message_id
        await db.execute(
            "UPDATE approval_requests SET telegram_message_id = ? WHERE id = ?",
            (sent.message_id, approval_id),
        )
        await db.commit()
        return

    # Обычный ответ
    response_text = format_agent_response(result.text) if result.text else "Нет ответа."

    # Добавляем мета-информацию
    meta_parts = [
        result.model,
        f"{format_tokens(result.tokens_input)}→{format_tokens(result.tokens_output)}",
    ]
    if result.tool_calls_count:
        meta_parts.append(f"{result.tool_calls_count} tools")
    if result.cache_stats:
        meta_parts.append(result.cache_stats)
    meta = f"\n\n<i>{' | '.join(meta_parts)}</i>"

    logger.info("[handler] Отправка ответа (%d chars)", len(response_text))
    try:
        await message.answer(
            response_text + meta,
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Ошибка отправки HTML, пробую без parse_mode")
        # Fallback: отправляем как plain text
        plain = result.text or "Нет ответа."
        meta_plain = f"\n\n{' | '.join(meta_parts)}"
        await message.answer(plain + meta_plain)
    logger.info("[handler] Обработка завершена")
