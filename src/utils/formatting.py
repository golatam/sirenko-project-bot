"""Форматирование сообщений для Telegram (HTML)."""

from __future__ import annotations

import html


def escape(text: str) -> str:
    """Экранировать HTML-символы для Telegram."""
    return html.escape(str(text))


def bold(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def italic(text: str) -> str:
    return f"<i>{escape(text)}</i>"


def code(text: str) -> str:
    return f"<code>{escape(text)}</code>"


def pre(text: str, lang: str = "") -> str:
    if lang:
        return f'<pre><code class="language-{escape(lang)}">{escape(text)}</code></pre>'
    return f"<pre>{escape(text)}</pre>"


def link(text: str, url: str) -> str:
    return f'<a href="{escape(url)}">{escape(text)}</a>'


def truncate(text: str, max_length: int = 4000) -> str:
    """Обрезать текст для Telegram (лимит 4096 символов)."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 20] + "\n\n...обрезано..."


def format_agent_response(text: str) -> str:
    """Преобразовать Markdown-ответ агента в Telegram HTML.

    Базовое преобразование наиболее частых паттернов.
    """
    # Telegram поддерживает ограниченный HTML, поэтому делаем минимум
    # Claude обычно отвечает в Markdown — конвертируем основное
    result = text
    # **bold** -> <b>bold</b>
    import re
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    # *italic* -> <i>italic</i>
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", result)
    # `code` -> <code>code</code>
    result = re.sub(r"`([^`]+)`", r"<code>\1</code>", result)
    return truncate(result)
