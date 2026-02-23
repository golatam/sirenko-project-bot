"""Сборка системных промптов для агента."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.mcp.types import MCP_TYPE_META, McpServerType
from src.settings import PROJECT_ROOT, ProjectConfig


def build_system_prompt(
    project_id: str,
    project: ProjectConfig,
    phase: str,
    connected_services: list[str] | None = None,
) -> str:
    """Собрать системный промпт из файла + контекст проекта + правила фазы.

    connected_services — список display_name подключённых MCP-сервисов
    (например, ["Gmail", "Google Calendar", "Slack"]).
    """
    parts: list[str] = []

    # 1. Базовый промпт из файла (поддержка относительных путей через PROJECT_ROOT)
    if project.system_prompt_file:
        prompt_path = Path(project.system_prompt_file)
        if not prompt_path.is_absolute():
            prompt_path = PROJECT_ROOT / prompt_path
        if prompt_path.is_file():
            parts.append(prompt_path.read_text().strip())
        else:
            parts.append(f"Ты — AI-ассистент для проекта '{project.display_name}'.")
    else:
        parts.append(f"Ты — AI-ассистент для проекта '{project.display_name}'.")

    # 2. Текущий контекст
    parts.append(f"\n## Текущий контекст\n")
    parts.append(f"- Дата и время: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    parts.append(f"- Проект: {project.display_name} (ID: {project_id})")
    parts.append(f"- Фаза: {phase}")

    # 3. Подключённые сервисы (динамически из конфига)
    if connected_services:
        parts.append(f"\n## Подключённые сервисы\n")
        parts.append("У тебя есть доступ к следующим сервисам:")
        for svc in connected_services:
            parts.append(f"- {svc}")
    else:
        parts.append(f"\n## Подключённые сервисы\n")
        parts.append("К проекту не подключены MCP-сервисы.")

    # 4. Правила работы с почтой (если Gmail подключён)
    if connected_services and any("Gmail" in s for s in connected_services):
        parts.append(_get_email_search_rules())

    # 5. Правила фазы
    phase_rules = _get_phase_rules(phase)
    parts.append(f"\n## Правила текущей фазы ({phase})\n")
    parts.append(phase_rules)

    return "\n".join(parts)


def _get_email_search_rules() -> str:
    """Правила поиска почты — query planner + валидация результатов."""
    return (
        "\n## Правила поиска почты (Gmail)\n"
        "\n"
        "### Стратегия поиска\n"
        "При поиске контактов, партнёров или информации в почте:\n"
        "1. **Разбивай на несколько узких запросов** вместо одного широкого. "
        "Например, для поиска платёжных партнёров:\n"
        '   - `search_emails(query="subject:(payment OR payout OR acquiring OR PSP)", maxResults=30)`\n'
        '   - `search_emails(query="subject:(merchant OR processing OR gateway)", maxResults=30)`\n'
        '   - НЕ делай: `search_emails(query="in:inbox", maxResults=10)` — слишком широко\n'
        "2. **Используй операторы Gmail**: `from:`, `to:`, `subject:`, `has:attachment`, "
        "`after:YYYY/MM/DD`, `before:YYYY/MM/DD`, `OR`, `-` (exclude)\n"
        "3. **Исключай нерелевантное** через `-`: "
        '`-subject:(invoice OR receipt)` если ищешь не счета\n'
        "4. **Ставь maxResults=30-50** для поисковых запросов (по умолчанию только 10)\n"
        "\n"
        "### Валидация результатов\n"
        "5. После поиска **проверяй релевантность**: если результат не соответствует запросу "
        "пользователя — не включай его в ответ\n"
        "6. Если нужны детали — используй `read_email` для проверки содержимого\n"
        "7. В ответе **группируй по типу/теме**, а не просто перечисляй\n"
        "\n"
        "### Полнота выдачи\n"
        "8. Если результатов мало — сделай дополнительный запрос с другими ключевыми словами "
        "или расширенным временным диапазоном\n"
        "9. Сообщи пользователю если поиск мог быть неполным: "
        '"Найдено N писем по запросу X. Для более полного поиска уточни период или ключевые слова."\n'
    )


def _get_phase_rules(phase: str) -> str:
    """Получить текстовое описание правил для фазы."""
    rules = {
        "read_only": (
            "- Можно ТОЛЬКО читать данные: искать email, читать сообщения, просматривать календарь\n"
            "- НЕЛЬЗЯ отправлять, удалять, создавать что-либо\n"
            "- Если пользователь просит выполнить действие — объясни, что сейчас режим только чтения"
        ),
        "drafts": (
            "- Можно читать данные и создавать черновики\n"
            "- Создание черновиков и событий ТРЕБУЕТ подтверждения пользователя\n"
            "- НЕЛЬЗЯ отправлять сообщения напрямую"
        ),
        "controlled": (
            "- Доступны все действия\n"
            "- Отправка email, удаление, отправка сообщений ТРЕБУЮТ подтверждения\n"
            "- Чтение и поиск выполняются автоматически"
        ),
    }
    return rules.get(phase, rules["read_only"])


def generate_default_prompt_file(
    project_id: str,
    display_name: str,
    description: str,
    enabled_types: list[McpServerType] | None = None,
    *,
    gmail: bool = False,
    calendar: bool = False,
) -> Path:
    """Создать файл системного промпта из шаблона. Возвращает путь к файлу.

    Поддерживает как новый формат (enabled_types), так и legacy (gmail, calendar).
    """
    # Legacy compat
    if enabled_types is None:
        enabled_types = []
        if gmail:
            enabled_types.append(McpServerType.gmail)
        if calendar:
            enabled_types.append(McpServerType.calendar)

    capabilities: list[str] = []
    for stype in enabled_types:
        meta = MCP_TYPE_META.get(stype)
        if meta:
            capabilities.append(f"- {meta.capability_description}")
    capabilities.append("- Форматирование ответов для удобного чтения в Telegram")

    cap_block = "\n".join(capabilities)

    content = (
        f'Ты — персональный AI-ассистент для проекта "{display_name}".\n'
        f"\n"
        f"## Контекст проекта\n"
        f"\n"
        f"{description}\n"
        f"\n"
        f"## Твои возможности\n"
        f"\n"
        f"{cap_block}\n"
        f"\n"
        f"## Правила работы\n"
        f"\n"
        f"1. Всегда отвечай на языке запроса\n"
        f"2. При работе с email — показывай краткую сводку, а не полный текст\n"
        f"3. Конфиденциальная информация — не повторяй полные email-адреса или телефоны без необходимости\n"
        f"4. Если нужно выполнить действие с побочными эффектами — запрашивай подтверждение\n"
        f"\n"
        f"## Формат ответов\n"
        f"\n"
        f"- Используй краткие, структурированные ответы\n"
        f"- Для списков — нумерованные списки\n"
        f"- Для важной информации — используй **жирный** текст\n"
    )

    prompts_dir = PROJECT_ROOT / "config" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompts_dir / f"{project_id}.md"
    prompt_path.write_text(content, encoding="utf-8")
    # Возвращаем относительный путь для сохранения в YAML
    return prompt_path.relative_to(PROJECT_ROOT)
