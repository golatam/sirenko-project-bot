"""Обработчики команд планирования: /planday, /planweek, /report."""

from __future__ import annotations

import asyncio
import logging

import anthropic
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.scheduler.scheduler import Scheduler
from src.settings import Settings
from src.utils.formatting import bold, format_agent_response

logger = logging.getLogger(__name__)

router = Router(name="planning")

_TYPING_INTERVAL = 4.0


async def _keep_typing(chat_id: int, bot, stop: asyncio.Event) -> None:
    """Периодически отправляет typing-индикатор."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, "typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=_TYPING_INTERVAL)
            break
        except asyncio.TimeoutError:
            continue


async def _run_planning_command(
    message: Message,
    scheduler: Scheduler,
    project_id: str | None,
    task_type: str,
    label: str,
) -> None:
    """Общая логика для команд планирования."""
    if not project_id:
        await message.answer("Сначала выбери проект командой /project")
        return

    status_msg = await message.answer(f"Формирую {label.lower()}...")
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(
        _keep_typing(message.chat.id, message.bot, stop_typing)
    )

    try:
        text = await scheduler.run_manual(project_id, task_type)
    except anthropic.AuthenticationError:
        stop_typing.set()
        await typing_task
        await status_msg.edit_text(
            "Ошибка аутентификации. OAuth токен истёк."
        )
        return
    except anthropic.APIStatusError as e:
        stop_typing.set()
        await typing_task
        if e.status_code == 529:
            error_text = "API Claude перегружен. Попробуй через пару минут."
        elif e.status_code == 429:
            error_text = "Превышен лимит запросов. Подожди немного."
        else:
            error_text = f"Ошибка API (код {e.status_code})."
        await status_msg.edit_text(error_text)
        return
    except Exception:
        stop_typing.set()
        await typing_task
        logger.exception("Ошибка планирования '%s'", task_type)
        await status_msg.edit_text("Произошла ошибка. Попробуй ещё раз.")
        return
    finally:
        stop_typing.set()
        await typing_task

    try:
        await status_msg.delete()
    except Exception:
        pass

    header = f"{bold(label)}\n\n"
    formatted = format_agent_response(text)
    try:
        await message.answer(header + formatted, parse_mode="HTML")
    except Exception:
        logger.exception("Ошибка отправки HTML, fallback")
        await message.answer(f"{label}\n\n{text}")


@router.message(Command("planday"))
async def cmd_planday(
    message: Message,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """План на сегодня."""
    await _run_planning_command(
        message, scheduler, project_id,
        task_type="daily_plan",
        label="План на сегодня",
    )


@router.message(Command("planweek"))
async def cmd_planweek(
    message: Message,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """План на неделю."""
    await _run_planning_command(
        message, scheduler, project_id,
        task_type="weekly_plan",
        label="План на неделю",
    )


@router.message(Command("report"))
async def cmd_report(
    message: Message,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """Отчёт за неделю."""
    await _run_planning_command(
        message, scheduler, project_id,
        task_type="weekly_report",
        label="Отчёт за неделю",
    )
