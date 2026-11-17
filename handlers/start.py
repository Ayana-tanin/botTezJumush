import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext

from database.db_connection import insert_user

logger = logging.getLogger(__name__)
router = Router()


def get_vacancy_thread_id(job_type):
    """Возвращает ID топика для публикации вакансии по типу: резюме/постоянные/подработки."""
    from database.models import JobType
    from config import REGULAR_THREAD_ID, PART_JOB_THREAD_ID
    
    if job_type == JobType.LONG_TERM:
        return REGULAR_THREAD_ID if REGULAR_THREAD_ID else None   # постоянные вакансии
    else:
        return PART_JOB_THREAD_ID if PART_JOB_THREAD_ID else None  # подработки (разовые)


kb_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Моё резюме")],
        [KeyboardButton(text="✉️ Выложить вакансию")],
        [KeyboardButton(text="📋 Мои вакансии")],
        [KeyboardButton(text="📞 Связаться с админом")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие"
)

# Клавиатура с кнопкой отмены для процесса заполнения
kb_cancel = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❌ Отменить")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Введите данные или отмените"
)


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(msg: Message, state: FSMContext):
    """Приветствие и меню"""
    try:
        insert_user(msg.from_user.id, msg.from_user.username or "")
    except Exception as e:
        logger.error(f"Ошибка при добавлении пользователя: {e}")

    # Очищаем состояние, если оно было
    await state.clear()

    await msg.answer(
        "👋 Привет! Я бот для публикации вакансий.\n\n"
        "Если вы хотите <b>найти работу</b>, то Выберите опцию: <b>Моё резюме</b>\n"
        "Если вы хотите <b>разместить вакансию</b>, то Выберите опцию: <b>Выложить вакансию</b>\n\n"
        "https://t.me/tezJumush  ссылка на наш канал с вакансиями и резюме ",
        reply_markup=kb_menu
    )

