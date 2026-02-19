# Sirenko Project Bot

AI-агент для управления бизнес-проектами через Telegram. Один бот, несколько проектов — каждый со своими аккаунтами Gmail, Google Calendar и Telegram.

## Что умеет

- **Чтение и поиск email** через Gmail MCP
- **Управление календарём** через Google Calendar MCP
- **Мониторинг Telegram-чатов** через Telegram MCP (Phase 4)
- **Переключение между проектами** — полная изоляция данных и инструментов
- **Human-in-the-loop** — подтверждение опасных действий через inline-кнопки
- **Трекинг расходов** — стоимость API по дням, проектам и моделям

## Архитектура

```
Владелец ←→ Telegram Bot (aiogram 3, long-polling)
                  ↓
             Project Router (FSM: активный проект)
                  ↓
             Haiku Classifier → нужны ли tools? какие?
                  ↓
             Agent Core (Anthropic SDK, tool_use loop)
               │  Sonnet 4.6 — рутинные задачи
               │  Opus 4.6   — сложные задачи (по запросу)
                  ↓
             MCP Client Manager
             ├── Gmail MCP (npx, инстанс на аккаунт)
             ├── Calendar MCP (npx, нативный multi-account)
             └── Telegram MCP (uv, инстанс на аккаунт)

+ SQLite         — история, расходы, подтверждения
+ Prompt Caching — экономия ~60-70% на повторных запросах
+ Summarization  — автосжатие истории через Haiku
```

## Быстрый старт

### Требования

- Python 3.12+
- Node.js 20+ (для npx MCP-серверов)
- Аккаунт Anthropic с API-ключом
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

1. **Переменные окружения:**

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
export ANTHROPIC_API_KEY="sk-ant-..."
export OWNER_TELEGRAM_ID="123456789"  # твой Telegram user ID
```

2. **Конфигурация проекта** — отредактируй `config/projects.yaml`:

```yaml
global:
  owner_telegram_id: 123456789  # ← твой ID
  default_model: "claude-sonnet-4-6"
  phase: "read_only"

projects:
  alpha:
    display_name: "Мой проект"
    gmail:
      enabled: true
      credentials_dir: "credentials/project_alpha/gmail"
    calendar:
      enabled: true
      account_id: "my@gmail.com"
```

3. **Gmail OAuth** (если включён Gmail):

```bash
# Положить client_secret.json от Google Cloud Console в:
mkdir -p credentials/project_alpha/gmail
cp ~/Downloads/client_secret_*.json credentials/project_alpha/gmail/credentials.json

# При первом запуске MCP-сервер откроет браузер для авторизации
```

4. **Системный промпт** — отредактируй `config/prompts/project_alpha.md` под свой проект.

### Запуск

```bash
source .venv/bin/activate
python3.12 -m src.main
```

Открой бота в Telegram → `/start` → пиши запросы.

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие, автовыбор проекта |
| `/project` | Переключить активный проект |
| `/status` | Статус проекта (фаза, сервисы) |
| `/costs` | Расходы за последние 7 дней |
| `/clear` | Очистить историю разговора |
| `/help` | Справка по командам |

## Фазы работы

Агент работает в одной из трёх фаз — каждая определяет, какие инструменты доступны:

| Фаза | Чтение | Черновики | Отправка |
|------|--------|-----------|----------|
| `read_only` | да | нет | нет |
| `drafts` | да | с подтверждением | нет |
| `controlled` | да | да | с подтверждением |

Фаза задаётся в `config/projects.yaml` для каждого проекта.

## Структура проекта

```
sirenko-project-bot/
├── pyproject.toml                 # Зависимости
├── config/
│   ├── projects.yaml              # Конфигурация проектов
│   └── prompts/
│       └── project_alpha.md       # Системный промпт проекта
├── credentials/                   # .gitignored — OAuth-токены
├── src/
│   ├── main.py                    # Точка входа
│   ├── settings.py                # Pydantic-конфиг из YAML + env
│   ├── agent/
│   │   ├── core.py                # Агентный цикл (tool_use loop)
│   │   ├── classifier.py          # Haiku-классификатор запросов
│   │   ├── summarizer.py          # Автосжатие истории
│   │   ├── prompts.py             # Сборка системного промпта
│   │   ├── context.py             # Управление контекстным окном
│   │   └── tools.py               # MCP → Anthropic schema
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── commands.py        # /start /project /help /status
│   │   │   ├── queries.py         # Свободный текст → агент
│   │   │   └── approvals.py       # Inline-кнопки подтверждения
│   │   ├── middlewares/
│   │   │   ├── auth.py            # Доступ только владельцу
│   │   │   └── project_context.py # Инъекция активного проекта
│   │   ├── keyboards.py           # Inline-клавиатуры
│   │   └── states.py              # FSM-состояния
│   ├── mcp/
│   │   ├── manager.py             # Жизненный цикл MCP-серверов
│   │   ├── client.py              # Подключение к одному MCP
│   │   └── registry.py            # Маршрутизация tool → server
│   ├── db/
│   │   ├── database.py            # aiosqlite + автомиграции
│   │   ├── models.py              # Dataclass-модели
│   │   ├── queries.py             # CRUD + трекинг расходов
│   │   └── migrations/
│   │       └── 001_initial.sql    # Таблицы: conversations, tool_calls, costs...
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
- Если нужны — какие категории (gmail, calendar, telegram)
- Простые запросы ("спасибо", "ок") обрабатываются без tools

### History Summarization
При > 16 сообщений в истории, старые автоматически сжимаются в резюме через Haiku (~$0.003). Вместо 30K токенов истории → ~5K.

### Оценка расходов

| Сценарий | Claude API | Railway | Итого |
|----------|-----------|---------|-------|
| Лёгкий (15 запросов/день) | $15/мес | $5-8 | **$20-23** |
| Средний (40 запросов/день) | $30-40/мес | $5-8 | **$35-48** |

## MCP-серверы

| Сервис | Пакет | Мультиаккаунт |
|--------|-------|---------------|
| Gmail | `npx @gongrzhe/server-gmail-autoauth-mcp` | Отдельные инстансы на аккаунт |
| Calendar | `npx @cocal/google-calendar-mcp` | Нативный (manage-accounts) |
| Telegram | `uv run` chigwell/telegram-mcp | Отдельные инстансы на аккаунт |

## Деплой на Railway

```
Dockerfile: Python 3.12 + Node.js 20 (multi-stage)
RAM: 1 GB (512 MB без Telegram MCP)
Volume: 1 GB для SQLite + credentials
Стоимость: ~$5-8/мес
```

## Дорожная карта

- [x] Phase 1 — Бот + агентный цикл + Gmail read-only
- [x] Phase 1b — Prompt caching, Haiku-классификатор, summarization
- [ ] Phase 2 — Второй проект + Calendar + /context + /remember
- [ ] Phase 3 — Approvals + Drafts + inline-подтверждения
- [ ] Phase 4 — Telegram MCP + мониторинг чатов + шедулер
- [ ] Phase 5 — Railway деплой + Dockerfile + health checks

## Лицензия

Приватный проект.
