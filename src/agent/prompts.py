"""Сборка системных промптов для агента."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.settings import ProjectConfig


def build_system_prompt(project_id: str, project: ProjectConfig, phase: str) -> str:
    """Собрать системный промпт из файла + контекст проекта + правила фазы."""
    parts: list[str] = []

    # 1. Базовый промпт из файла
    prompt_path = Path(project.system_prompt_file)
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
