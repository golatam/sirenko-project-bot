"""Утилиты для подсчёта и оценки токенов."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Грубая оценка количества токенов по символам.

    Примерное соотношение: 1 токен ~ 4 символа для английского,
    ~2-3 символа для русского/испанского.
    """
    if not text:
        return 0
    # Используем среднее значение ~3.5 символа на токен
    return max(1, len(text) // 3)


def format_cost(cost_usd: float) -> str:
    """Форматировать стоимость в читаемый вид."""
    if cost_usd < 0.01:
        return f"${cost_usd:.4f}"
    return f"${cost_usd:.2f}"


def format_tokens(count: int) -> str:
    """Форматировать количество токенов."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
