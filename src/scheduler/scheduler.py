"""Планировщик проактивных задач: утренний план, недельный отчёт.

Использует asyncio-based расписание без внешних зависимостей.
Каждую минуту проверяет, пора ли запускать задачи.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from src.scheduler.prompts import (
    daily_plan_prompt,
    weekly_plan_prompt,
    weekly_report_prompt,
)

logger = logging.getLogger(__name__)

# Маппинг названий дней недели → номер (Monday=0)
_DAY_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# Интервал проверки расписания (секунды)
_CHECK_INTERVAL = 60


class Scheduler:
    """Планировщик проактивных сообщений в Telegram."""

    def __init__(
        self,
        settings: Any,
        agent: Any,
        bot: Any,
    ) -> None:
        from src.settings import Settings
        self.settings: Settings = settings
        self.agent = agent
        self.bot = bot
        self._task: asyncio.Task | None = None
        # Трекинг последнего запуска чтобы не дублировать
        self._last_daily: dict[str, str] = {}   # project_id → "YYYY-MM-DD"
        self._last_weekly: dict[str, str] = {}   # project_id → "YYYY-WW"
        self._last_report: dict[str, str] = {}   # project_id → "YYYY-WW"

    def start(self) -> None:
        """Запустить фоновый цикл планировщика."""
        if self._task and not self._task.done():
            logger.warning("Планировщик уже запущен")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Планировщик запущен")

    async def stop(self) -> None:
        """Остановить планировщик."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Планировщик остановлен")

    async def _loop(self) -> None:
        """Основной цикл: каждую минуту проверяем расписание."""
        while True:
            try:
                await self._check_schedule()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка в цикле планировщика")
            await asyncio.sleep(_CHECK_INTERVAL)

    async def _check_schedule(self) -> None:
        """Проверить все проекты и запустить задачи по расписанию."""
        for project_id, project in self.settings.projects.items():
            reporting = project.reporting
            if not reporting.enabled:
                continue

            now = self._now(reporting.timezone)

            # --- Утренний план ---
            plan_hour, plan_minute = _parse_time(reporting.daily_plan_time)
            today_key = now.strftime("%Y-%m-%d")
            if (
                now.hour == plan_hour
                and now.minute == plan_minute
                and self._last_daily.get(project_id) != today_key
            ):
                self._last_daily[project_id] = today_key
                # Понедельник → план на неделю, иначе → план на день
                if now.weekday() == 0:
                    asyncio.create_task(
                        self._run_task(project_id, "weekly_plan", now)
                    )
                else:
                    asyncio.create_task(
                        self._run_task(project_id, "daily_plan", now)
                    )

            # --- Еженедельный отчёт ---
            report_day = _DAY_MAP.get(reporting.weekly_report_day.lower(), 4)
            report_hour, report_minute = _parse_time(reporting.weekly_report_time)
            week_key = now.strftime("%Y-%W")
            if (
                now.weekday() == report_day
                and now.hour == report_hour
                and now.minute == report_minute
                and self._last_report.get(project_id) != week_key
            ):
                self._last_report[project_id] = week_key
                asyncio.create_task(
                    self._run_task(project_id, "weekly_report", now)
                )

    async def _run_task(self, project_id: str, task_type: str, now: datetime) -> None:
        """Запустить агентскую задачу и отправить результат в Telegram."""
        project = self.settings.projects.get(project_id)
        if not project:
            return

        display_name = project.display_name

        if task_type == "daily_plan":
            prompt = daily_plan_prompt(display_name, now)
            label = f"План на день — {display_name}"
        elif task_type == "weekly_plan":
            prompt = weekly_plan_prompt(display_name, now)
            label = f"План на неделю — {display_name}"
        elif task_type == "weekly_report":
            prompt = weekly_report_prompt(display_name, now)
            label = f"Отчёт за неделю — {display_name}"
        else:
            return

        logger.info("Планировщик: запуск '%s' для проекта '%s'", task_type, project_id)

        try:
            result = await self.agent.run(
                project_id=project_id,
                user_message=prompt,
            )
            text = result.text or "Не удалось сформировать ответ."
        except Exception:
            logger.exception("Ошибка планировщика для '%s' (%s)", project_id, task_type)
            text = f"Не удалось сформировать {label.lower()}. Ошибка при обращении к агенту."

        # Отправляем в Telegram
        chat_id = self.settings.global_config.owner_telegram_id
        if not chat_id:
            logger.warning("owner_telegram_id не задан, пропускаем отправку")
            return

        header = f"<b>{label}</b>\n\n"
        from src.utils.formatting import format_agent_response
        formatted = format_agent_response(text)
        message_text = header + formatted

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode="HTML",
            )
            logger.info("Планировщик: отправлено '%s' для '%s'", task_type, project_id)
        except Exception:
            logger.exception("Ошибка отправки сообщения планировщика")
            # Fallback без HTML
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"{label}\n\n{text}",
                )
            except Exception:
                logger.exception("Ошибка отправки fallback сообщения")

    async def run_manual(self, project_id: str, task_type: str) -> str:
        """Запустить задачу вручную (для команд /planday, /planweek, /report).

        Возвращает текст ответа от агента.
        """
        project = self.settings.projects.get(project_id)
        if not project:
            return f"Проект '{project_id}' не найден."

        now = self._now(project.reporting.timezone)
        display_name = project.display_name

        if task_type == "daily_plan":
            prompt = daily_plan_prompt(display_name, now)
        elif task_type == "weekly_plan":
            prompt = weekly_plan_prompt(display_name, now)
        elif task_type == "weekly_report":
            prompt = weekly_report_prompt(display_name, now)
        else:
            return "Неизвестный тип задачи."

        result = await self.agent.run(
            project_id=project_id,
            user_message=prompt,
        )
        return result.text or "Не удалось сформировать ответ."

    @staticmethod
    def _now(timezone_name: str) -> datetime:
        """Получить текущее время в заданном часовом поясе."""
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(timezone_name))
        except Exception:
            # Fallback на UTC если часовой пояс не найден
            logger.warning("Часовой пояс '%s' не найден, используем UTC", timezone_name)
            return datetime.utcnow()


def _parse_time(time_str: str) -> tuple[int, int]:
    """Разобрать строку HH:MM в (hour, minute)."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])
