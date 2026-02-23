"""Точка входа: запуск бота + MCP-серверов."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from src.agent.core import AgentCore
from src.bootstrap_credentials import bootstrap_credentials
from src.bot.handlers import (
    approvals, auth, auth_atlassian, auth_slack, auth_telegram,
    commands, mcp_management, planning, project_management, queries,
)
from src.bot.middlewares.auth import AuthMiddleware
from src.bot.middlewares.project_context import ProjectContextMiddleware
from src.db.database import Database
from src.mcp.manager import MCPManager
from src.scheduler import Scheduler
from src.settings import load_settings
from src.utils.logging import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()

    # --- Credentials из env vars (для контейнера) ---
    bootstrap_credentials()

    # --- Конфигурация ---
    settings = load_settings()

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        sys.exit(1)
    if settings.global_config.auth_method == "oauth":
        if not settings.anthropic_auth_token:
            logger.error("OAuth токен не найден (Keychain / ANTHROPIC_AUTH_TOKEN)")
            sys.exit(1)
        logger.info("Auth: OAuth от подписки Claude (%s)", settings.global_config.auth_method)
    elif not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY не задан")
        sys.exit(1)

    # --- База данных ---
    db = Database(settings.global_config.db_path)
    await db.connect()

    # --- MCP ---
    mcp_manager = MCPManager(settings)
    try:
        await mcp_manager.start_all()
    except Exception:
        logger.exception("Ошибка запуска MCP-серверов")
        # Продолжаем работу — бот может быть полезен и без MCP

    # --- Агент ---
    agent = AgentCore(settings, db, mcp_manager)

    # --- Telegram Bot ---
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares
    dp.message.middleware(AuthMiddleware(settings))
    dp.callback_query.middleware(AuthMiddleware(settings))
    dp.message.middleware(ProjectContextMiddleware(settings))
    dp.callback_query.middleware(ProjectContextMiddleware(settings))

    # Роутеры (порядок важен — commands до queries)
    dp.include_router(commands.router)
    dp.include_router(project_management.router)
    dp.include_router(auth.router)
    dp.include_router(auth_telegram.router)
    dp.include_router(auth_slack.router)
    dp.include_router(auth_atlassian.router)
    dp.include_router(mcp_management.router)
    dp.include_router(planning.router)
    dp.include_router(approvals.router)
    dp.include_router(queries.router)  # Catch-all для свободного текста — последний

    # --- Планировщик ---
    scheduler = Scheduler(settings=settings, agent=agent, bot=bot)

    # Dependency injection через workflow_data
    dp.workflow_data.update({
        "settings": settings,
        "db": db,
        "agent": agent,
        "mcp_manager": mcp_manager,
        "scheduler": scheduler,
    })

    # --- Graceful Shutdown ---
    _shutdown_done = False

    async def shutdown() -> None:
        nonlocal _shutdown_done
        if _shutdown_done:
            return
        _shutdown_done = True
        logger.info("Остановка...")
        await scheduler.stop()
        await mcp_manager.stop_all()
        await db.close()
        await bot.session.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    # --- Heartbeat для диагностики ---
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(15)
            logger.debug("[heartbeat] event loop alive")

    hb_task = asyncio.create_task(heartbeat())

    # --- Планировщик: запуск фонового цикла ---
    scheduler.start()

    # --- Регистрация команд в меню Telegram ---
    await bot.set_my_commands(commands.BOT_COMMANDS)
    logger.info("Зарегистрировано %d команд в меню Telegram", len(commands.BOT_COMMANDS))

    # --- Запуск ---
    logger.info("Бот запускается (long-polling)...")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        hb_task.cancel()
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
