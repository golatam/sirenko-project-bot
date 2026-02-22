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

# Настройка OAuth (из подписки Claude Max)
python3.12 -m src.auth_setup

# Запуск
PYTHONUNBUFFERED=1 python3.12 -m src.main

# Проверка синтаксиса
python3.12 -m py_compile src/agent/core.py

# Проверка импортов
python3.12 -c "from src.agent.core import AgentCore"

# Тесты (когда будут)
python3.12 -m pytest tests/
```

## Архитектура

### Ядро агента
- `src/main.py` — точка входа (bot + MCP + DB + set_my_commands)
- `src/agent/core.py` — ядро: цикл tool_use с Claude API
- `src/agent/classifier.py` — Haiku-классификатор запросов (динамический по MCP-типам)
- `src/agent/summarizer.py` — автосжатие истории
- `src/agent/prompts.py` — сборка системных промптов + генерация промпт-файлов

### MCP-инфраструктура (instance-based)
- `src/mcp/types.py` — McpServerType enum (7 типов), McpInstanceConfig, McpTypeMeta, TOOL_PREFIX_MAP
- `src/mcp/factory.py` — фабрика StdioServerParameters по типу (npx/uv/node)
- `src/mcp/manager.py` — lifecycle менеджер с refcount (кросс-проектное sharing)
- `src/mcp/registry.py` — реестр инструментов с namespace prefix и original name mapping
- `src/mcp/client.py` — MCP клиент (stdio transport)

### Telegram-бот (aiogram 3)
- `src/bot/handlers/commands.py` — /start, /project, /help, /status, /clear, /costs + меню callbacks
- `src/bot/handlers/project_management.py` — /addproject, /deleteproject (FSM)
- `src/bot/handlers/mcp_management.py` — /addmcp, /removemcp (динамическое управление MCP)
- `src/bot/handlers/auth.py` — /authgmail (OAuth через Telegram)
- `src/bot/handlers/auth_telegram.py` — /authtelegram (MTProto: API ID → Hash → Session)
- `src/bot/handlers/auth_slack.py` — /authslack (xoxp-токен)
- `src/bot/handlers/auth_atlassian.py` — /authatlassian (site → email → token → Confluence/Jira)
- `src/bot/handlers/queries.py` — обработка свободного текста (catch-all)
- `src/bot/handlers/approvals.py` — inline-кнопки подтверждения/отклонения действий
- `src/bot/states.py` — FSM-состояния (8 StatesGroup)
- `src/bot/keyboards.py` — inline-клавиатуры (меню, help-навигация, MCP type/instance selectors)
- `src/bot/middlewares/project_context.py` — инъекция активного проекта

### Конфигурация и данные
- `src/settings.py` — конфигурация из YAML + env, save_settings, default_tool_policy, миграция legacy
- `src/auth_setup.py` — настройка OAuth авторизации через Claude CLI → `.env`
- `src/bootstrap_credentials.py` — восстановление credentials из env vars (для контейнера)
- `src/db/` — SQLite через aiosqlite
- `config/projects.yaml` — конфигурация проектов + mcp_instances
- `config/prompts/` — системные промпты проектов
- `credentials/google/credentials.json` — общий OAuth client (копируется в проекты)

## MCP-серверы

| Тип | Пакет | Транспорт | Prefix | Tools |
|-----|-------|-----------|--------|-------|
| Gmail | `@gongrzhe/server-gmail-autoauth-mcp` | npx | — | search_emails, read_email, send_email... |
| Calendar | `@cocal/google-calendar-mcp` | npx | — | list-events, create-event, get-event... |
| Telegram | `chigwell/telegram-mcp` | uv (local) | `tg_` | 87 tools (MTProto User API) |
| Slack | `slack-mcp-server` | npx | `slack_` | 14 tools (xoxp token) |
| Confluence | `@aashari/mcp-server-atlassian-confluence` | npx | — | conf_get/post/put/patch/delete |
| Jira | `@aashari/mcp-server-atlassian-jira` | npx | — | jira_get/post/put/patch/delete |
| WhatsApp | `jlucaso1/whatsapp-mcp-ts` | node (local) | `wa_` | 7 tools (Baileys, Node >= 23.10) |

**Namespace prefix**: Gmail/Calendar без prefix (уникальные имена), Telegram `tg_`, Slack `slack_`. Confluence/Jira — tools уже с встроенным prefix (`conf_*`, `jira_*`), namespace prefix пустой.

**Instance sharing**: один MCP-процесс обслуживает несколько проектов через refcount.

## Telegram-команды бота (14)

| Команда | Описание |
|---------|----------|
| /start | Приветствие + интерактивное меню |
| /project | Выбрать активный проект |
| /status | Статус проекта и MCP-сервисов |
| /costs | Расходы за 7 дней |
| /clear | Очистить историю разговора |
| /help | Навигируемая справка по категориям |
| /addproject | Создать новый проект (FSM-диалог) |
| /deleteproject | Удалить проект |
| /addmcp | Подключить MCP-сервис к проекту |
| /removemcp | Отключить MCP-сервис |
| /authgmail | Авторизация Gmail (OAuth) |
| /authtelegram | Авторизация Telegram MCP (MTProto) |
| /authslack | Авторизация Slack (xoxp-токен) |
| /authatlassian | Авторизация Jira/Confluence |

Все команды зарегистрированы через `set_my_commands` — видны в меню Telegram при `/`.

## Правила

- Используй `python3.12` (не `python3` — на системе 3.9)
- venv в `.venv/` — уже создан
- Модели: `claude-sonnet-4-6` (default), `claude-opus-4-6` (complex), `claude-haiku-4-5` (classifier)
- Auth: два метода — `api_key` (ANTHROPIC_API_KEY) или `oauth` (ANTHROPIC_AUTH_TOKEN от подписки Claude)
- Переключение: `auth_method: oauth` в `config/projects.yaml` → global
- Не хардкодь API-ключи — только через env vars
- SQLite миграции в `src/db/migrations/` — нумерация `001_`, `002_`...
- Конфиг проектов в `config/projects.yaml`
- Системные промпты в `config/prompts/`

## Агентский цикл

- `MAX_TOOL_ITERATIONS=15` — агент работает до `end_turn` или лимита итераций
- `MAX_TOKENS_BUDGET=50000` — защита от бесконечных циклов по расходу токенов
- При исчерпании лимита — финальный вызов без tools для подведения итога
- Prompt caching: system prompt + tools кешируются (экономия ~60-70%)
- Classifier (Haiku) определяет нужны ли tools и какие категории (динамически из MCP_TYPE_META)

## Фазы проекта (tool_policy)

- `read_only` — только чтение (search, read, list)
- `drafts` — + создание черновиков (draft_email, create-event), с подтверждением
- `controlled` — все инструменты, опасные (send, delete) требуют подтверждения через Telegram

## Формат конфига (config/projects.yaml)

```yaml
global:
  owner_telegram_id: 123456789
  mcp_instances:
    flexify_gmail:
      type: gmail
      credentials_dir: credentials/flexify/gmail
    flexify_calendar:
      type: calendar
      account_id: user@gmail.com
    flexify_slack:
      type: slack
      token_env: SLACK_FLEXIFY_TOKEN

projects:
  flexify:
    display_name: Flexify
    phase: controlled
    mcp_services:
      - flexify_gmail
      - flexify_calendar
      - flexify_slack
    tool_policy: { ... }
```

## История и память

- История из БД: последние 20 сообщений
- Summarization порог: 20 сообщений, сохраняет 10 последних нетронутыми
- Tool results обрезаются до 2000 символов
- Summary сохраняет email, имена, даты, выполненные действия

## Deploy

- Railway: `Dockerfile` + `railway.toml`
- Node.js 20 в контейнере для npx MCP-серверов
- Credentials из env vars через `bootstrap_credentials.py`
- SQLite в `/app/data/` (Railway volume)
