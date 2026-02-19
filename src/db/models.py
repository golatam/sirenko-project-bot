"""Модели данных для работы с БД."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Conversation:
    id: int
    project_id: str
    role: str
    content: str  # JSON
    tokens_input: int = 0
    tokens_output: int = 0
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ToolCall:
    id: int
    project_id: str
    tool_name: str
    tool_input: str | None
    tool_result: str | None
    model: str
    tokens_input: int = 0
    tokens_output: int = 0
    latency_ms: int = 0
    is_error: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class CostRecord:
    date: str
    project_id: str
    model: str
    requests_count: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


@dataclass
class ApprovalRequest:
    id: int
    project_id: str
    tool_name: str
    tool_input: str  # JSON
    status: str = "pending"
    telegram_message_id: int | None = None
    conversation_context: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    resolved_at: datetime | None = None
