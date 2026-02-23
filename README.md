# Sirenko Project Bot

AI-агент для управления бизнес-проектами через Telegram. Один бот, несколько проектов — каждый со своими MCP-сервисами (Gmail, Calendar, Telegram, Slack, Confluence, Jira, WhatsApp).

## Что умеет

- **Email** — чтение, поиск, отправка через Gmail MCP
- **Календарь** — события, создание, управление через Google Calendar MCP
- **Telegram** — мониторинг чатов, отправка сообщений через Telegram MCP (MTProto User API, 87 tools)
- **Slack** — чтение каналов, отправка сообщений через Slack MCP (14 tools)
- **Confluence** — чтение и создание страниц через Confluence MCP
- **Jira** — задачи и проекты через Jira MCP
- **WhatsApp** — сообщения через WhatsApp MCP (Baileys)
- **Мульти-проект** — полная изоляция данных, инструментов и аккаунтов между проектами
- **Human-in-the-loop** — подтверждение опасных действий через inline-кнопки в Telegram
- **Трекинг расходов** — стоимость API по дням, проектам и моделям
- **OAuth авто-рефреш** — access_token обновляется автоматически через refresh_token при истечении

## Архитектура

```
Владелец ←→ Telegram Bot (aiogram 3, long-polling)
                  ↓
             Project Router (FSM: активный проект)
                  ↓
             Haiku Classifier → нужны ли tools? какие категории?
                  ↓
             Agent Core (Anthropic SDK, tool_use loop)
               │  Sonnet 4.6 — рутинные задачи
               │  Opus 4.6   — сложные задачи (по запросу)
               │  Haiku 4.5  — классификация + простые ответы
                  ↓
             MCP Client Manager (instance-based, refcount sharing)
             ├── Gmail MCP        (npx, инстанс на аккаунт)
             ├── Calendar MCP     (npx, нативный multi-account)
             ├── Telegram MCP     (uv, инстанс на аккаунт)
             ├── Slack MCP        (npx, инстанс на workspace)
             ├── Confluence MCP   (npx, инстанс на site)
             ├── Jira MCP         (npx, инстанс на site)
             └── WhatsApp MCP     (node, инстанс на аккаунт)

+ SQLite         — история, расходы, подтверждения
+ Prompt Caching — экономия ~60-70% на повторных запросах
+ Summarization  — автосжатие истории через Haiku
+ OAuth Refresh  — авто-обновление токена при 401
```

## Быстрый старт

### Требования

- Python 3.12+
- Node.js 20+ (для npx MCP-серверов)
- Аккаунт Anthropic (API key или подписка Claude Max для OAuth)
- Telegram Bot Token (от @BotFather)

### Установка

```bash
git clone git@github.com:golatam/sirenko-project-bot.git
cd sirenko-project-bot

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install anthropic "mcp>=1.9" "aiogram>=3.25" aiosqlite pyyaml pydantic "pydantic-settings>=2.7" "apscheduler>=3.11"
```

### Настройка

1. **Переменные окружения** (`.env` или export):

```bash
# Обязательные
TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
OWNER_TELEGRAM_ID="123456789"

# Вариант 1: API key
ANTHROPIC_API_KEY="sk-ant-api03-..."

# Вариант 2: OAuth (подписка Claude Max)
ANTHROPIC_AUTH_TOKEN="sk-ant-oat01-..."
ANTHROPIC_REFRESH_TOKEN="sk-ant-ort01-..."  # для авто-рефреша
AUTH_METHOD=oauth
```

2. **OAuth-авторизация** (если подписка Claude Max):

```bash
python3.12 -m src.auth_setup
# Извлекает access + refresh token из macOS Keychain
# Сохраняет в .env, refresh_token позволяет авто-обновление каждые 8 часов
```

3. **Конфигурация проекта** — `config/projects.yaml`:

```yaml
global:
  owner_telegram_id: 123456789
  auth_method: oauth  # или api_key
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
```

4. **Системный промпт** — создать `config/prompts/<project_id>.md` с описанием проекта.

### Запуск

```bash
source .venv/bin/activate
PYTHONUNBUFFERED=1 python3.12 -m src.main
```

Открой бота в Telegram → `/start` → пиши запросы.

## Команды бота (14)

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие + интерактивное меню |
| `/project` | Переключить активный проект |
| `/status` | Статус проекта и MCP-сервисов |
| `/costs` | Расходы за последние 7 дней |
| `/clear` | Очистить историю разговора |
| `/help` | Навигируемая справка по категориям |
| `/addproject` | Создать новый проект (FSM-диалог) |
| `/deleteproject` | Удалить проект |
| `/addmcp` | Подключить MCP-сервис к проекту |
| `/removemcp` | Отключить MCP-сервис от проекта |
| `/authgmail` | Авторизация Gmail (Google OAuth) |
| `/authtelegram` | Авторизация Telegram MCP (MTProto) |
| `/authslack` | Авторизация Slack (xoxp-токен) |
| `/authatlassian` | Авторизация Jira/Confluence (Atlassian) |

Все команды зарегистрированы через `set_my_commands` — видны в меню Telegram при `/`.

## MCP-серверы (7 типов)

| Тип | Пакет | Транспорт | Prefix | Tools |
|-----|-------|-----------|--------|-------|
| Gmail | `@gongrzhe/server-gmail-autoauth-mcp` | npx | — | search_emails, read_email, send_email... |
| Calendar | `@cocal/google-calendar-mcp` | npx | — | list-events, create-event, get-event... |
| Telegram | `chigwell/telegram-mcp` | uv (local) | `tg_` | 87 tools (MTProto User API) |
| Slack | `slack-mcp-server` | npx | `slack_` | 14 tools (xoxp token) |
| Confluence | `@aashari/mcp-server-atlassian-confluence` | npx | — | conf_get/post/put/patch/delete |
| Jira | `@aashari/mcp-server-atlassian-jira` | npx | — | jira_get/post/put/patch/delete |
| WhatsApp | `jlucaso1/whatsapp-mcp-ts` | node (local) | `wa_` | 7 tools (Baileys, Node >= 23.10) |

**Instance sharing**: один MCP-процесс обслуживает несколько проектов через refcount.

## Фазы работы (tool_policy)

| Фаза | Чтение | Черновики | Отправка/Удаление |
|------|--------|-----------|-------------------|
| `read_only` | да | нет | нет |
| `drafts` | да | с подтверждением | нет |
| `controlled` | да | да | с подтверждением |

Фаза задаётся в `config/projects.yaml` для каждого проекта.

## Структура проекта

```
sirenko-project-bot/
├── pyproject.toml                 # Зависимости
├── Dockerfile                     # Multi-stage: Python 3.12 + Node.js 20
├── railway.toml                   # Railway deploy config
├── config/
│   ├── projects.yaml              # Конфигурация проектов + MCP instances
│   └── prompts/                   # Системные промпты проектов
├── credentials/                   # .gitignored — OAuth-токены
├── src/
│   ├── main.py                    # Точка входа
│   ├── settings.py                # Pydantic-конфиг из YAML + env
│   ├── auth_setup.py              # Настройка OAuth (Keychain → .env)
│   ├── bootstrap_credentials.py   # Восстановление credentials для контейнера
│   ├── agent/
│   │   ├── core.py                # Агентный цикл (tool_use loop)
│   │   ├── auth.py                # OAuth авто-рефреш (OAuthRefresher)
│   │   ├── classifier.py          # Haiku-классификатор запросов
│   │   ├── summarizer.py          # Автосжатие истории
│   │   ├── prompts.py             # Сборка системного промпта
│   │   ├── context.py             # Управление контекстным окном
│   │   └── tools.py               # MCP → Anthropic schema
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── commands.py        # /start /project /help /status /costs /clear
│   │   │   ├── project_management.py  # /addproject /deleteproject
│   │   │   ├── mcp_management.py  # /addmcp /removemcp
│   │   │   ├── auth.py            # /authgmail
│   │   │   ├── auth_telegram.py   # /authtelegram
│   │   │   ├── auth_slack.py      # /authslack
│   │   │   ├── auth_atlassian.py  # /authatlassian
│   │   │   ├── queries.py         # Свободный текст → агент
│   │   │   └── approvals.py       # Inline-кнопки подтверждения
│   │   ├── middlewares/
│   │   │   ├── auth.py            # Доступ только владельцу
│   │   │   └── project_context.py # Инъекция активного проекта
│   │   ├── keyboards.py           # Inline-клавиатуры
│   │   └── states.py              # FSM-состояния (8 StatesGroup)
│   ├── mcp/
│   │   ├── types.py               # McpServerType enum, McpInstanceConfig, MCP_TYPE_META
│   │   ├── factory.py             # Фабрика StdioServerParameters по типу
│   │   ├── manager.py             # Lifecycle менеджер с refcount
│   │   ├── client.py              # MCP клиент (stdio transport)
│   │   └── registry.py            # Реестр инструментов с namespace prefix
│   ├── db/
│   │   ├── database.py            # aiosqlite + автомиграции
│   │   ├── models.py              # Dataclass-модели
│   │   ├── queries.py             # CRUD + трекинг расходов
│   │   └── migrations/            # SQL-миграции (001_, 002_...)
│   └── utils/
│       ├── logging.py             # Настройка логов
│       ├── tokens.py              # Оценка и форматирование токенов
│       └── formatting.py          # Markdown → Telegram HTML
└── tests/
```

## Оптимизации токенов

### Prompt Caching
System prompt и tool definitions кешируются через Anthropic API. Повторные запросы в течение 5 минут оплачиваются по 10% от стоимости. Экономия ~60-70% на input-токенах.

### Haiku-классификатор
Перед основным вызовом Sonnet, запрос проходит через Haiku (~$0.0003):
- Определяет нужны ли инструменты
- Если нужны — какие категории (gmail, calendar, telegram, slack, confluence, jira, whatsapp)
- Простые запросы ("спасибо", "ок") обрабатываются без tools

### History Summarization
При > 16 сообщений в истории, старые автоматически сжимаются в резюме через Haiku (~$0.003). Вместо 30K токенов истории → ~5K.

## OAuth авторизация

Два метода авторизации Anthropic API:

| Метод | Переменная | Описание |
|-------|-----------|----------|
| `api_key` | `ANTHROPIC_API_KEY` | Стандартный API-ключ |
| `oauth` | `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_REFRESH_TOKEN` | Подписка Claude Max |

**OAuth авто-рефреш**: access_token живёт 8 часов. При получении 401 `OAuthRefresher` автоматически обновляет токен через refresh_token и продолжает работу. Новые токены сохраняются in-memory + `.env`.

Настройка:
```bash
python3.12 -m src.auth_setup  # Извлекает оба токена из macOS Keychain
```

## Деплой на Railway

```
Dockerfile: Python 3.12 + Node.js 20 (multi-stage)
RAM: 1 GB (512 MB без Telegram MCP)
Volume: 1 GB для SQLite + credentials
Стоимость: ~$5-8/мес
```

Env vars в Railway dashboard:
- `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`
- `ANTHROPIC_API_KEY` или `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_REFRESH_TOKEN` + `AUTH_METHOD=oauth`
- `CRED_*` — base64-encoded credentials для bootstrap

## Дорожная карта

- [x] Phase 1 — Бот + агентный цикл + Gmail read-only + prompt caching + Haiku-классификатор + summarization
- [x] Phase 2 — Multi-project + instance-based MCP (7 типов) + 14 команд + динамическое управление MCP + OAuth авто-рефреш
- [ ] Phase 3 — Шедулер + проактивные уведомления
- [ ] Phase 4 — Расширенная аналитика + дашборд
- [ ] Phase 5 — Multi-user + RBAC

## Лицензия

Приватный проект.
