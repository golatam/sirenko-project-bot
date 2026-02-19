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
- `src/agent/prompts.py` — сборка системных промптов + генерация промпт-файлов
- `src/mcp/manager.py` — запуск/остановка MCP-серверов (поддержка динамического start/stop)
- `src/mcp/registry.py` — реестр инструментов (register/unregister)
- `src/bot/handlers/commands.py` — /start, /project, /help, /status, /clear, /costs
- `src/bot/handlers/project_management.py` — /addproject, /deleteproject (FSM-диалоги)
- `src/bot/handlers/auth.py` — /authgmail (OAuth через Telegram)
- `src/bot/handlers/queries.py` — обработка свободного текста (catch-all)
- `src/bot/states.py` — FSM-состояния (AddProject, DeleteProject, AuthGmail)
- `src/bot/keyboards.py` — inline-клавиатуры
- `src/bot/middlewares/project_context.py` — инъекция активного проекта (динамический default)
- `src/settings.py` — конфигурация из YAML + env, save_settings, default_tool_policy
- `src/db/` — SQLite через aiosqlite
- `credentials/google/credentials.json` — общий OAuth client (копируется в проекты)

## Правила

- Используй `python3.12` (не `python3` — на системе 3.9)
- venv в `.venv/` — уже создан
- Модели: `claude-sonnet-4-6` (default), `claude-opus-4-6` (complex), `claude-haiku-4-5` (classifier)
- Не хардкодь API-ключи — только через env vars
- SQLite миграции в `src/db/migrations/` — нумерация `001_`, `002_`...
- Конфиг проектов в `config/projects.yaml`
- Системные промпты в `config/prompts/`
