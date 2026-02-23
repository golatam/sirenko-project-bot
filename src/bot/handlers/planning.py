"""Обработчики команд планирования: /planday, /planweek, /report.

FSM-диалог: команда → вопрос о мыслях/приоритетах → генерация плана.
"""

from __future__ import annotations

import asyncio
import logging

import anthropic
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import skip_planning_keyboard
from src.bot.states import PlanningStates
from src.scheduler.scheduler import Scheduler
from src.settings import Settings
from src.utils.formatting import bold, format_agent_response

logger = logging.getLogger(__name__)

router = Router(name="planning")

_TYPING_INTERVAL = 4.0

# Маппинг task_type → (label, вопрос)
_TASK_META: dict[str, tuple[str, str]] = {
    "daily_plan": (
        "План на сегодня",
        "Какие у тебя приоритеты и мысли на сегодня?",
    ),
    "weekly_plan": (
        "План на неделю",
        "Какие у тебя приоритеты и мысли на эту неделю?",
    ),
    "weekly_report": (
        "Отчёт за неделю",
        "Что важного хочешь отметить в отчёте?",
    ),
}


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
    user_thoughts: str | None = None,
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
        text = await scheduler.run_manual(project_id, task_type, user_thoughts)
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


async def _start_planning_fsm(
    message: Message,
    state: FSMContext,
    project_id: str | None,
    task_type: str,
) -> None:
    """Запуск FSM-диалога: спросить мысли перед генерацией."""
    if not project_id:
        await message.answer("Сначала выбери проект командой /project")
        return

    label, question = _TASK_META[task_type]
    await state.set_state(PlanningStates.waiting_thoughts)
    await state.update_data(task_type=task_type, label=label)
    await message.answer(
        f"{bold(label)}\n\n{question}\n\n"
        "Напиши свои мысли или нажми «Пропустить».",
        parse_mode="HTML",
        reply_markup=skip_planning_keyboard(),
    )


# --- Команды ---

@router.message(Command("planday"))
async def cmd_planday(
    message: Message,
    state: FSMContext,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """План на сегодня."""
    await _start_planning_fsm(message, state, project_id, "daily_plan")


@router.message(Command("planweek"))
async def cmd_planweek(
    message: Message,
    state: FSMContext,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """План на неделю."""
    await _start_planning_fsm(message, state, project_id, "weekly_plan")


@router.message(Command("report"))
async def cmd_report(
    message: Message,
    state: FSMContext,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """Отчёт за неделю."""
    await _start_planning_fsm(message, state, project_id, "weekly_report")


# --- FSM: получение мыслей (текст) ---

@router.message(PlanningStates.waiting_thoughts)
async def on_planning_thoughts(
    message: Message,
    state: FSMContext,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """Пользователь написал мысли/приоритеты."""
    data = await state.get_data()
    await state.clear()

    task_type = data["task_type"]
    label = data["label"]

    await _run_planning_command(
        message, scheduler, project_id,
        task_type=task_type,
        label=label,
        user_thoughts=message.text,
    )


# --- FSM: кнопка «Пропустить» ---

@router.callback_query(F.data == "plan_skip")
async def on_planning_skip(
    callback: CallbackQuery,
    state: FSMContext,
    project_id: str | None = None,
    scheduler: Scheduler = None,
    **kwargs,
) -> None:
    """Пользователь нажал «Пропустить» — генерация без мыслей."""
    data = await state.get_data()
    await state.clear()

    task_type = data.get("task_type")
    label = data.get("label")

    if not task_type or not label:
        await callback.answer("Сессия устарела. Вызови команду заново.")
        return

    await callback.answer()

    # Убираем кнопку из сообщения с вопросом
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _run_planning_command(
        callback.message, scheduler, project_id,
        task_type=task_type,
        label=label,
        user_thoughts=None,
    )
