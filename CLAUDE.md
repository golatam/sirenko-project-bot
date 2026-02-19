# CLAUDE.md

## Проект

AI-агент для управления бизнес-проектами через Telegram. Python 3.12, Anthropic SDK, MCP-серверы, aiogram 3.

## Языки

- Код: Python (type hints, async/await)
- Комментарии и docstrings: русский
- Коммиты: русский или английский
- Общение с пользователем: русский

## Команды

```bash
# Активация окружения
source .venv/bin/activate

# Запуск
python3.12 -m src.main

# Проверка синтаксиса
python3.12 -m py_compile src/agent/core.py

# Проверка импортов
python3.12 -c "from src.agent.core import AgentCore"

# Тесты (когда будут)
python3.12 -m pytest tests/
```

## Архитектура

- `src/main.py` — точка входа (bot + MCP + DB)
- `src/agent/core.py` — ядро: цикл tool_use с Claude API
- `src/agent/classifier.py` — Haiku-классификатор запросов
- `src/agent/summarizer.py` — автосжатие истории
- `src/mcp/manager.py` — запуск/остановка MCP-серверов
- `src/bot/handlers/` — обработчики Telegram-команд
- `src/settings.py` — конфигурация из YAML + env
- `src/db/` — SQLite через aiosqlite

## Правила

- Используй `python3.12` (не `python3` — на системе 3.9)
- venv в `.venv/` — уже создан
- Модели: `claude-sonnet-4-6` (default), `claude-opus-4-6` (complex), `claude-haiku-4-5` (classifier)
- Не хардкодь API-ключи — только через env vars
- SQLite миграции в `src/db/migrations/` — нумерация `001_`, `002_`...
- Конфиг проектов в `config/projects.yaml`
- Системные промпты в `config/prompts/`
