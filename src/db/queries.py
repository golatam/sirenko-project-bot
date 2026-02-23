"""SQL-запросы для работы с данными."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from src.db.database import Database
from src.db.models import ApprovalRequest, Conversation, CostRecord, ToolCall

# --- Conversations ---


async def save_message(db: Database, project_id: str, role: str, content: str,
                       tokens_input: int = 0, tokens_output: int = 0) -> int:
    """Сохранить сообщение в историю разговора."""
    cursor = await db.execute(
        "INSERT INTO conversations (project_id, role, content, tokens_input, tokens_output) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, role, content, tokens_input, tokens_output),
    )
    await db.commit()
    return cursor.lastrowid


async def get_conversation_history(db: Database, project_id: str,
                                   limit: int = 50) -> list[Conversation]:
    """Получить последние N сообщений проекта."""
    rows = await db.fetchall(
        "SELECT * FROM conversations WHERE project_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    )
    return [
        Conversation(
            id=r["id"], project_id=r["project_id"], role=r["role"],
            content=r["content"], tokens_input=r["tokens_input"],
            tokens_output=r["tokens_output"], created_at=r["created_at"],
        )
        for r in reversed(rows)
    ]


async def clear_conversation(db: Database, project_id: str) -> None:
    """Очистить историю разговора проекта."""
    await db.execute("DELETE FROM conversations WHERE project_id = ?", (project_id,))
    await db.commit()


# --- Tool Calls ---


async def log_tool_call(db: Database, project_id: str, tool_name: str,
                        tool_input: dict | None, tool_result: str | None,
                        model: str, tokens_input: int = 0, tokens_output: int = 0,
                        latency_ms: int = 0, is_error: bool = False) -> int:
    """Записать вызов инструмента в лог."""
    input_json = json.dumps(tool_input, ensure_ascii=False) if tool_input else None
    # Обрезаем результат до 10KB для экономии места
    if tool_result and len(tool_result) > 10240:
        tool_result = tool_result[:10240] + "...[обрезано]"
    cursor = await db.execute(
        "INSERT INTO tool_calls "
        "(project_id, tool_name, tool_input, tool_result, model, "
        "tokens_input, tokens_output, latency_ms, is_error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, tool_name, input_json, tool_result, model,
         tokens_input, tokens_output, latency_ms, is_error),
    )
    await db.commit()
    return cursor.lastrowid


# --- Cost Tracking ---

# Стоимость за 1M токенов (input/output)
MODEL_PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


async def track_cost(db: Database, project_id: str, model: str,
                     tokens_input: int, tokens_output: int) -> None:
    """Обновить агрегированные расходы за день."""
    today = datetime.now(timezone.utc).date().isoformat()
    input_price, output_price = MODEL_PRICING.get(model, (3.00, 15.00))
    cost = (tokens_input * input_price + tokens_output * output_price) / 1_000_000

    await db.execute(
        "INSERT INTO cost_tracking (date, project_id, model, requests_count, "
        "tokens_input, tokens_output, cost_usd) VALUES (?, ?, ?, 1, ?, ?, ?) "
        "ON CONFLICT(date, project_id, model) DO UPDATE SET "
        "requests_count = requests_count + 1, "
        "tokens_input = tokens_input + excluded.tokens_input, "
        "tokens_output = tokens_output + excluded.tokens_output, "
        "cost_usd = cost_usd + excluded.cost_usd",
        (today, project_id, model, tokens_input, tokens_output, cost),
    )
    await db.commit()


async def get_costs_summary(db: Database, days: int = 7) -> list[CostRecord]:
    """Получить сводку расходов за последние N дней."""
    rows = await db.fetchall(
        "SELECT date, project_id, model, requests_count, "
        "tokens_input, tokens_output, cost_usd FROM cost_tracking "
        "WHERE date >= date('now', ?) ORDER BY date DESC",
        (f"-{days} days",),
    )
    return [
        CostRecord(
            date=r["date"], project_id=r["project_id"], model=r["model"],
            requests_count=r["requests_count"], tokens_input=r["tokens_input"],
            tokens_output=r["tokens_output"], cost_usd=r["cost_usd"],
        )
        for r in rows
    ]


# --- Approval Requests ---


async def create_approval(db: Database, project_id: str, tool_name: str,
                          tool_input: dict, conversation_context: str | None = None,
                          telegram_message_id: int | None = None) -> int:
    """Создать запрос на подтверждение действия."""
    cursor = await db.execute(
        "INSERT INTO approval_requests "
        "(project_id, tool_name, tool_input, conversation_context, telegram_message_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, tool_name, json.dumps(tool_input, ensure_ascii=False),
         conversation_context, telegram_message_id),
    )
    await db.commit()
    return cursor.lastrowid


async def resolve_approval(db: Database, approval_id: int, status: str) -> bool:
    """Атомарно обновить статус запроса на подтверждение.

    Возвращает True если обновление прошло (запрос был pending).
    Возвращает False если запрос уже обработан (race condition).
    """
    cursor = await db.execute(
        "UPDATE approval_requests SET status = ?, resolved_at = ? "
        "WHERE id = ? AND status = 'pending'",
        (status, datetime.now().isoformat(), approval_id),
    )
    await db.commit()
    return cursor.rowcount > 0


async def get_pending_approval(db: Database, approval_id: int) -> ApprovalRequest | None:
    """Получить ожидающий подтверждения запрос."""
    row = await db.fetchone(
        "SELECT * FROM approval_requests WHERE id = ? AND status = 'pending'",
        (approval_id,),
    )
    if not row:
        return None
    return ApprovalRequest(
        id=row["id"], project_id=row["project_id"],
        tool_name=row["tool_name"], tool_input=row["tool_input"],
        status=row["status"], telegram_message_id=row["telegram_message_id"],
        conversation_context=row["conversation_context"],
        created_at=row["created_at"], resolved_at=row["resolved_at"],
    )
