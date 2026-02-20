"""Обработчик inline-кнопок подтверждения/отклонения действий."""

from __future__ import annotations

import json
import logging

from aiogram import Router
from aiogram.types import CallbackQuery

from src.agent.core import AgentCore, PendingApproval
from src.db.database import Database
from src.db.queries import get_pending_approval, resolve_approval
from src.utils.formatting import bold, format_agent_response
from src.utils.tokens import format_tokens

logger = logging.getLogger(__name__)

router = Router(name="approvals")


@router.callback_query(lambda c: c.data and c.data.startswith("approve:"))
async def on_approve(callback: CallbackQuery, db: Database = None,
                     agent: AgentCore = None, **kwargs) -> None:
    """Пользователь подтвердил действие."""
    approval_id = int(callback.data.split(":", 1)[1])
    approval_req = await get_pending_approval(db, approval_id)

    if not approval_req:
        await callback.answer("Запрос не найден или уже обработан", show_alert=True)
        return

    await callback.answer("Выполняю...")
    await resolve_approval(db, approval_id, "approved")

    # Восстанавливаем контекст и выполняем инструмент
    messages_snapshot = json.loads(approval_req.conversation_context) if approval_req.conversation_context else []
    tool_input = json.loads(approval_req.tool_input)

    # Извлекаем tool_use_id из messages_snapshot (последнее assistant-сообщение)
    tool_use_id = ""
    for msg in reversed(messages_snapshot):
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == approval_req.tool_name:
                    tool_use_id = block.get("id", "")
                    break
            if tool_use_id:
                break
    if not tool_use_id:
        # Fallback: генерируем валидный ID
        import uuid
        tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"

    pending = PendingApproval(
        tool_name=approval_req.tool_name,
        tool_input=tool_input,
        tool_use_id=tool_use_id,
        messages_snapshot=messages_snapshot,
    )

    try:
        result = await agent.execute_approved_tool(
            project_id=approval_req.project_id,
            approval=pending,
        )
        response_text = format_agent_response(result.text) if result.text else "Действие выполнено."
        meta = (
            f"\n\n<i>{result.model} | "
            f"{format_tokens(result.tokens_input)}→{format_tokens(result.tokens_output)}</i>"
        )
        await callback.message.edit_text(
            f"Подтверждено\n\n{response_text}{meta}",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Ошибка при выполнении подтверждённого действия #%d", approval_id)
        await callback.message.edit_text(
            f"Ошибка при выполнении {bold(approval_req.tool_name)}. Попробуй ещё раз.",
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("reject:"))
async def on_reject(callback: CallbackQuery, db: Database = None, **kwargs) -> None:
    """Пользователь отклонил действие."""
    approval_id = int(callback.data.split(":", 1)[1])
    approval_req = await get_pending_approval(db, approval_id)

    if not approval_req:
        await callback.answer("Запрос не найден или уже обработан", show_alert=True)
        return

    await resolve_approval(db, approval_id, "rejected")
    await callback.answer("Отклонено")
    await callback.message.edit_text(
        f"Действие {bold(approval_req.tool_name)} отклонено.",
        parse_mode="HTML",
    )
