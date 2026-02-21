"""Сборка системных промптов для агента."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.settings import PROJECT_ROOT, ProjectConfig


def build_system_prompt(project_id: str, project: ProjectConfig, phase: str) -> str:
    """Собрать системный промпт из файла + контекст проекта + правила фазы."""
    parts: list[str] = []

    # 1. Базовый промпт из файла (поддержка относительных путей через PROJECT_ROOT)
    prompt_path = Path(project.system_prompt_file)
    if not prompt_path.is_absolute():
        prompt_path = PROJECT_ROOT / prompt_path
    if prompt_path.exists():
        parts.append(prompt_path.read_text().strip())
    else:
        parts.append(f"Ты — AI-ассистент для проекта '{project.display_name}'.")

    # 2. Текущий контекст
    parts.append(f"\n## Текущий контекст\n")
    parts.append(f"- Дата и время: {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    parts.append(f"- Проект: {project.display_name} (ID: {project_id})")
    parts.append(f"- Фаза: {phase}")

    # 3. Правила фазы
    phase_rules = _get_phase_rules(phase)
    parts.append(f"\n## Правила текущей фазы ({phase})\n")
    parts.append(phase_rules)

    return "\n".join(parts)


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
    gmail: bool,
    calendar: bool,
) -> Path:
    """Создать файл системного промпта из шаблона. Возвращает путь к файлу."""
    capabilities: list[str] = []
    if gmail:
        capabilities.append("- Поиск и чтение email-переписки через Gmail")
    if calendar:
        capabilities.append("- Управление событиями в Google Calendar")
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
