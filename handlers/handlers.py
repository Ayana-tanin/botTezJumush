import re
import asyncio
import logging
import signal
import sys

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, \
    KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from datetime import datetime, timedelta
from sqlalchemy import func

from database.db_connection import *
from config import CHANNEL_ID, CHANNEL_URL, ADMINS, ADMIN_USERNAME, RESUME_GROUP_ID, RESUME_THREAD_ID, REGULAR_THREAD_ID, PART_JOB_THREAD_ID
from vacancy_fsm import VacancyForm, EditVacancyForm, ConfirmWorkForm, RatingForm
from resume_fsm import ResumeForm, EditResumeForm
from database.models import JobType, JobStatus, ResponseStatus, User, Job, Resume

logger = logging.getLogger(__name__)
router = Router()


def get_vacancy_thread_id(job_type: JobType):
    """Возвращает ID топика для публикации вакансии по типу: резюме/постоянные/подработки."""
    if job_type == JobType.LONG_TERM:
        return REGULAR_THREAD_ID if REGULAR_THREAD_ID else None   # постоянные вакансии
    else:
        return PART_JOB_THREAD_ID if PART_JOB_THREAD_ID else None  # подработки (разовые)


# Шаблоны полей и телефонный формат
TEMPLATE = {
    "address": r"^📍\s*Адрес:\s*(.+)$",
    "title": r"^📝\s*Задача:\s*(.+)$",
    "payment": r"^💵\s*Оплата:\s*(.+)$",
    "contact": r"^☎️\s*Контакт:\s*(.+)$",
    "extra": r"^📌\s*Примечание:\s*(.*)$",
}
# Обновленное регулярное выражение для телефона (строго +996XXXXXXXXX)
PHONE_RE = re.compile(r"^\+996\d{9}$")

# Клавиатура с кнопкой отмены для процесса заполнения
# kb_cancel = ReplyKeyboardMarkup(
#     keyboard=[
#         [KeyboardButton(text="❌ Отменить")],
#     ],
#     resize_keyboard=True,
#     input_field_placeholder="Введите данные или отмените"
# )


@router.message(Command("my_profile"), F.chat.type == ChatType.PRIVATE)
async def cmd_my_profile(msg: Message):
    """Просмотр и редактирование анкеты"""
    user_id = msg.from_user.id
    
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        
        if not user or not user.name:
            await msg.answer(
                "📝 У вас еще нет резюме.\n\n"
                "Для создания резюме используйте кнопку '📝 Моё резюме'",
                reply_markup=kb_menu
            )
            return
        
        # Формируем текст рейтинга
        rating_text = f"⭐ {user.average_rating:.1f} | {user.completed_jobs} работ | {user.refusals_count} отказ"
        if user.refusals_count != 1:
            rating_text = rating_text.replace("отказ", "отказов")
        
        profile_text = (
            f"👤 <b>Моё резюме</b>\n\n"
            f"{rating_text}\n"
            f"Имя: {user.name or 'не указано'}\n"
            f"Возраст: {user.age or 'не указан'}\n"
            f"Пол: {user.gender or 'не указан'}\n"
            f"Опыт работы: {user.experience or 'не указан'}\n"
            f"О себе: {user.about or 'не указано'}\n"
            f"📅 Последний выход на работу: {user.last_work_date.strftime('%d.%m.%Y') if user.last_work_date else 'нет'}"
        )
        
        if user.is_blacklisted:
            profile_text += f"\n\n🚫 <b>Заблокирован до:</b> {user.blacklist_until.strftime('%d.%m.%Y') if user.blacklist_until else 'неизвестно'}"
        
        edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать резюме", callback_data="edit_my_profile")]
        ])
        
        await msg.answer(
            profile_text,
            parse_mode=ParseMode.HTML,
            reply_markup=edit_keyboard
        )


@router.message(Command("my_rating"), F.chat.type == ChatType.PRIVATE)
async def cmd_my_rating(msg: Message):
    """Просмотр рейтинга и статистики"""
    user_id = msg.from_user.id
    
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        
        if not user:
            await msg.answer(
                "❌ Вы еще не зарегистрированы в системе.",
                reply_markup=kb_menu
            )
            return
        
        # Формируем текст рейтинга
        rating_text = f"⭐ {user.average_rating:.1f} | {user.completed_jobs} работ | {user.refusals_count} отказ"
        if user.refusals_count != 1:
            rating_text = rating_text.replace("отказ", "отказов")
        
        rating_info = (
            f"⭐ <b>Мой рейтинг</b>\n\n"
            f"{rating_text}\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"✅ Выполнено работ: {user.completed_jobs}\n"
            f"❌ Отказов: {user.refusals_count}\n"
            f"📅 Последний выход: {user.last_work_date.strftime('%d.%m.%Y') if user.last_work_date else 'нет'}"
        )
        
        if user.is_blacklisted:
            rating_info += f"\n\n🚫 <b>Статус:</b> Заблокирован до {user.blacklist_until.strftime('%d.%m.%Y') if user.blacklist_until else 'неизвестно'}"
        
        await msg.answer(
            rating_info,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_menu
        )


@router.message(Command("my_vacancies"), F.chat.type == ChatType.PRIVATE)
async def cmd_my_vacancies(msg: Message):
    """Список моих вакансий"""
    await my_vacancies(msg)


# Вспомогательная функция для проверки отмены (используется во всех обработчиках состояний)
async def check_cancel(msg: Message, state: FSMContext) -> bool:
    """
    Проверяет, была ли нажата кнопка отмены. 
    Возвращает True, если была отменена (и уже обработана).
    Вызывайте эту функцию в начале каждого обработчика состояния FSM.
    """
    if msg.text and msg.text.strip() == "❌ Отменить":
        await state.clear()
        await msg.answer(
            "❌ Заполнение отменено.\n\n"
            "Вы вернулись в главное меню.",
            reply_markup=kb_menu
        )
        return True
    return False


@router.message(F.text == "✉️ Выложить вакансию")
async def prepare_vacancy_button(msg: Message, state: FSMContext):
    """Обработчик кнопки создания вакансии"""
    await prepare_vacancy_impl(msg, state)


@router.callback_query(F.data == "create")
async def prepare_vacancy(call: CallbackQuery, state: FSMContext):
    """Обработчик callback для создания вакансии"""
    await call.answer()
    await prepare_vacancy_impl(call.message, state)


async def prepare_vacancy_impl(msg: Message, state: FSMContext):
    """Общая логика подготовки вакансии - начинаем пошаговый опрос"""
    user_id = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id

    # Проверка на спам: 5 минут между публикациями (только для не-админов)
    if user_id not in ADMINS:
        with SessionLocal() as session:
            last_job = session.query(Job).filter(
                Job.user_id == user_id,
                Job.created_at >= datetime.now() - timedelta(minutes=5)
            ).first()
            
            if last_job and (datetime.now() - last_job.created_at).total_seconds() < 300:
                await msg.answer(
                    "⏳ Подождите 5 минут перед публикацией следующей вакансии.",
                    reply_markup=kb_menu
                )
                return

    # Начинаем пошаговый опрос - сначала тип вакансии
    kb_type = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Долгосрочная вакансия")],
            [KeyboardButton(text="⚡ Разовая работа")],
            [KeyboardButton(text="❌ Отменить")],
        ],
        resize_keyboard=True
    )
    await msg.answer(
        "📝 Для публикации вакансии ответьте на несколько вопросов:\n\n"
        "0️⃣ Выберите тип вакансии:",
        reply_markup=kb_type
    )
    await state.set_state(VacancyForm.job_type)


@router.message(F.text == "📋 Мои вакансии")
async def my_vacancies(msg: Message):
    """Показать список вакансий пользователя"""
    try:
        with SessionLocal() as session:
            jobs = (
                session.query(Job)
                .filter(
                    Job.user_id == msg.from_user.id,
                    Job.status != JobStatus.CANCELLED,
                    Job.message_id != None
                )
                .order_by(Job.created_at.desc())
                .all()
            )
            
            if not jobs:
                await msg.answer(
                    "У вас пока нет опубликованных вакансий.",
                    reply_markup=kb_menu
                )
                return
            
            for job in jobs:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_job_{job.id}"),
                        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_job_{job.id}")
                    ]
                ])
                
                # Получаем статус вакансии
                status_text = {
                    JobStatus.OPEN: "🟢 Открыта",
                    JobStatus.IN_PROGRESS: f"🟡 Набрано {job.people_confirmed} из {job.people_needed}",
                    JobStatus.CANDIDATES_SELECTED: "🟠 Кандидаты выбраны",
                    JobStatus.CONFIRMED: "✅ Подтверждена",
                    JobStatus.COMPLETED: "✅ Завершена",
                    JobStatus.CANCELLED: "❌ Отменена"
                }
                
                job_text = (
                    f"<b>📋 {job.all_info['title']}</b>\n\n"
                    f"📍 <b>Адрес:</b> {job.all_info['address']}\n"
                    f"👤 <b>Требования:</b> {job.all_info.get('requirements', 'не указаны')}\n"
                    f"💰 <b>Оплата:</b> {job.all_info['payment']}\n"
                    f"⏰ <b>График:</b> {job.all_info.get('schedule', 'не указан')}\n"
                    f"👥 <b>Требуется:</b> {job.people_needed} человек\n"
                    f"📊 <b>Статус:</b> {status_text.get(job.status, 'Неизвестно')}\n\n"
                    f"📅 Опубликовано: {job.created_at.strftime('%d.%m.%Y %H:%M')}"
                )
                
                await msg.answer(
                    job_text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML
                )
    
    except Exception as e:
        logger.error(f"Ошибка при получении списка вакансий: {e}")
        await msg.answer("❌ Произошла ошибка при получении списка вакансий.")


@router.callback_query(F.data.startswith("edit_job_"))
async def edit_job_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования вакансии - показывает меню выбора поля"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена")
                return
            
            # Сохраняем ID вакансии и текущие данные в состоянии
            await state.update_data(
                editing_job_id=job_id,
                current_address=job.all_info.get('address', ''),
                current_title=job.all_info.get('title', ''),
                current_payment=job.all_info.get('payment', ''),
                current_contact=job.all_info.get('contact', ''),
                current_extra=job.all_info.get('extra', '')
            )
            
            # Показываем меню выбора поля для редактирования
            edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1️⃣ Адрес", callback_data=f"edit_field_address_{job_id}")],
                [InlineKeyboardButton(text="2️⃣ Вакансия", callback_data=f"edit_field_title_{job_id}")],
                [InlineKeyboardButton(text="3️⃣ Оплата", callback_data=f"edit_field_payment_{job_id}")],
                [InlineKeyboardButton(text="4️⃣ Контакт", callback_data=f"edit_field_contact_{job_id}")],
                [InlineKeyboardButton(text="5️⃣ Примечание", callback_data=f"edit_field_extra_{job_id}")],
            ])
            
            await callback.message.edit_text(
                "✏️ Выберите, что хотите отредактировать:",
                reply_markup=edit_keyboard
            )
            await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при редактировании вакансии: {e}")
        await callback.answer("❌ Произошла ошибка при редактировании")


# Обработчики выбора поля для редактирования
@router.callback_query(F.data.startswith("edit_field_address_"))
async def edit_field_address_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования адреса"""
    job_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    current_address = data.get('current_address', 'не указан')
    
    await callback.message.edit_text(
        f"✏️ Редактирование адреса\n\n"
        f"📍 Текущий адрес: {current_address}\n\n"
        "Введите новый адрес:"
    )
    await state.set_state(EditVacancyForm.edit_address)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_title_"))
async def edit_field_title_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования задачи"""
    job_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    current_title = data.get('current_title', 'не указано')
    
    await callback.message.edit_text(
        f"✏️ Редактирование задачи\n\n"
        f"📝 Текущая задача: {current_title}\n\n"
        "Введите новое описание задачи:"
    )
    await state.set_state(EditVacancyForm.edit_title)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_payment_"))
async def edit_field_payment_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования оплаты"""
    job_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    current_payment = data.get('current_payment', 'не указана')
    
    await callback.message.edit_text(
        f"✏️ Редактирование оплаты\n\n"
        f"💵 Текущая оплата: {current_payment}\n\n"
        "Введите новую оплату (только цифры):"
    )
    await state.set_state(EditVacancyForm.edit_payment)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_contact_"))
async def edit_field_contact_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования контакта"""
    job_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    current_contact = data.get('current_contact', 'не указан')
    display_contact = current_contact.replace('+', '') if current_contact.startswith('+') else current_contact
    
    await callback.message.edit_text(
        f"✏️ Редактирование контакта\n\n"
        f"📱 Текущий WhatsApp: {display_contact}\n\n"
        "Введите новый номер WhatsApp:\n"
        "Требования: начинается с 0, ровно 10 цифр\n"
        "(Например: 0555123456)"
    )
    await state.set_state(EditVacancyForm.edit_contact)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_extra_"))
async def edit_field_extra_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования примечания"""
    job_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    current_extra = data.get('current_extra', 'нет')
    if not current_extra or current_extra.lower() == 'нет':
        current_extra = 'не указано'
    
    await callback.message.edit_text(
        f"✏️ Редактирование примечания\n\n"
        f"📌 Текущее примечание: {current_extra}\n\n"
        "Введите новое примечание (или 'нет' для удаления):"
    )
    await state.set_state(EditVacancyForm.edit_extra)
    await callback.answer()


# Обработчики редактирования полей
@router.message(EditVacancyForm.edit_address)
async def process_edit_address(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования адреса"""
    new_address = msg.text.strip()
    if not new_address:
        await msg.answer("❌ Адрес не может быть пустым. Введите адрес:")
        return
    
    await update_vacancy_field(msg, state, bot, 'address', new_address)


@router.message(EditVacancyForm.edit_title)
async def process_edit_title(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования задачи"""
    new_title = msg.text.strip()
    if not new_title:
        await msg.answer("❌ Описание задачи не может быть пустым. Введите описание:")
        return
    
    await update_vacancy_field(msg, state, bot, 'title', new_title)


@router.message(EditVacancyForm.edit_payment)
async def process_edit_payment(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования оплаты"""
    new_payment = msg.text.strip()
    if not new_payment.isdigit():
        await msg.answer("❌ Оплата должна содержать только цифры. Введите оплату:")
        return
    
    await update_vacancy_field(msg, state, bot, 'payment', new_payment)


@router.message(EditVacancyForm.edit_contact)
async def process_edit_contact(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования контакта"""
    whatsapp = msg.text.strip()
    
    # Извлекаем только цифры из номера
    digits_only = re.sub(r'\D', '', whatsapp)
    
    # Проверка: ровно 10 цифр
    if len(digits_only) != 10:
        await msg.answer(
            "❌ Номер должен состоять ровно из 10 цифр!\n"
            "Введите номер еще раз (например: 0555123456):"
        )
        return
    
    # Проверка: начинается с 0
    if not digits_only.startswith('0'):
        await msg.answer(
            "❌ Номер должен начинаться с 0!\n"
            "Введите номер еще раз (например: 0555123456):"
        )
        return
    
    # Форматируем: убираем первый 0, добавляем +996
    whatsapp_formatted = '+996' + digits_only[1:]
    await update_vacancy_field(msg, state, bot, 'contact', whatsapp_formatted)


@router.message(EditVacancyForm.edit_extra)
async def process_edit_extra(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования примечания"""
    new_extra = msg.text.strip()
    if new_extra.lower() == 'нет':
        new_extra = ''
    
    await update_vacancy_field(msg, state, bot, 'extra', new_extra)


async def update_vacancy_field(msg: Message, state: FSMContext, bot: Bot, field_name: str, new_value: str):
    """Обновление одного поля вакансии"""
    try:
        data = await state.get_data()
        job_id = data.get('editing_job_id')
        
        if not job_id:
            await msg.answer("❌ Ошибка: не найден ID вакансии")
            await state.clear()
            return
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=msg.from_user.id).first()
            if not job:
                await msg.answer("❌ Вакансия не найдена")
                await state.clear()
                return
            
            # Обновляем поле в данных вакансии
            job.all_info[field_name] = new_value
            
            # Формируем текст для канала
            vacancy_text = (
                f"<b>Вакансия {job.all_info['title']}</b>\n\n"
                f"📍 <b>Адрес:</b> {job.all_info['address']}\n"
                f"💵 <b>Оплата:</b> {job.all_info['payment']}\n"
                f"☎️ <b>Контакт:</b> {job.all_info['contact']}"
            )
            
            if job.all_info.get('extra'):
                vacancy_text += f"\n📌 <b>Примечание:</b> {job.all_info['extra']}"
            
            # Обновляем сообщение в канале
            await bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=job.message_id,
                text=vacancy_text,
                parse_mode=ParseMode.HTML
            )
            
            # Обновляем кнопку отклика
            response_button = create_response_buttons(job_id=job.id, job=job)
            
            if response_button:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=job.message_id,
                    reply_markup=response_button
                )
            
            session.commit()
            
            # Обновляем текущие данные в состоянии
            await state.update_data(**{f'current_{field_name}': new_value})
            
            field_names = {
                'address': 'Адрес',
                'title': 'Задача',
                'payment': 'Оплата',
                'contact': 'Контакт',
                'extra': 'Примечание'
            }
            
            await msg.answer(
                f"✅ {field_names.get(field_name, 'Поле')} успешно обновлено!\n\n"
                f"📄 Ссылка: {CHANNEL_URL}/{job.message_id}",
                reply_markup=kb_menu
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении поля {field_name}: {e}")
        await msg.answer(
            "❌ Произошла ошибка при обновлении. Попробуйте позже.",
            reply_markup=kb_menu
        )
        await state.clear()


@router.callback_query(F.data.startswith("delete_job_"))
async def delete_job_callback(callback: CallbackQuery):
    """Обработчик удаления вакансии"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена")
                return
            
            # Удаляем сообщение из канала (message_thread_id не нужен для deleteMessage)
            try:
                await callback.bot.delete_message(
                    chat_id=CHANNEL_ID,
                    message_id=job.message_id
                )
            except Exception as e:
                logger.error(f"Не удалось удалить сообщение из канала: {e}")
            
            # Мягкое удаление в БД:
            # физическое удаление может падать из-за связанных откликов/оценок.
            job.status = JobStatus.CANCELLED
            job.message_id = None
            session.commit()
            
            try:
                await callback.message.edit_text(
                    "✅ Вакансия успешно удалена",
                    reply_markup=None
                )
            except Exception as e:
                logger.warning(f"Не удалось обновить сообщение после удаления вакансии: {e}")
            await callback.answer("✅ Вакансия удалена")
    
    except Exception as e:
        logger.error(f"Ошибка при удалении вакансии: {e}")
        await callback.answer("❌ Произошла ошибка при удалении")


@router.callback_query(F.data.startswith("cancel_edit_"))
async def cancel_edit_callback(callback: CallbackQuery, state: FSMContext):
    """Отмена редактирования вакансии"""
    try:
        await state.clear()
        await callback.message.edit_text(
            "❌ Редактирование отменено",
            reply_markup=None
        )
        await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при отмене редактирования: {e}")
        await callback.answer("❌ Произошла ошибка")


# Обработчики редактирования полей анкеты
@router.callback_query(F.data.startswith("edit_resume_field_name_"))
async def edit_resume_field_name(callback: CallbackQuery, state: FSMContext):
    """Редактирование имени в анкете"""
    resume_id_str = callback.data.rsplit("_", 1)[1]  # берёт '0' после последнего '_'
    resume_id = int(resume_id_str)
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        if user:
            current_value = user.name or 'не указано'
            await callback.message.edit_text(
                f"✏️ Редактирование имени\n\n"
                f"📝 Текущее имя: {current_value}\n\n"
                "Введите новое имя:"
            )
            await state.update_data(editing_user_id=callback.from_user.id)
            await state.set_state(EditResumeForm.edit_name)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_resume_field_age_"))
async def edit_resume_field_age(callback: CallbackQuery, state: FSMContext):
    """Редактирование возраста в анкете"""
    resume_id = int(callback.data.split("_")[4])
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        if user:
            current_value = user.age or 'не указан'
            await callback.message.edit_text(
                f"✏️ Редактирование возраста\n\n"
                f"📅 Текущий возраст: {current_value}\n\n"
                "Введите новый возраст:"
            )
            await state.update_data(editing_user_id=callback.from_user.id)
            await state.set_state(EditResumeForm.edit_age)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_resume_field_gender_"))
async def edit_resume_field_gender(callback: CallbackQuery, state: FSMContext):
    """Редактирование пола в анкете"""
    resume_id = int(callback.data.split("_")[4])
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        if user:
            current_value = user.gender or 'не указан'
            gender_keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")],
                    [KeyboardButton(text="❌ Отменить")],
                ],
                resize_keyboard=True
            )
            await callback.message.edit_text(
                f"✏️ Редактирование пола\n\n"
                f"👤 Текущий пол: {current_value}\n\n"
                "Выберите пол:"
            )
            await callback.message.answer("Выберите пол:", reply_markup=gender_keyboard)
            await state.update_data(editing_user_id=callback.from_user.id)
            await state.set_state(EditResumeForm.edit_gender)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_resume_field_experience_"))
async def edit_resume_field_experience(callback: CallbackQuery, state: FSMContext):
    """Редактирование опыта в анкете"""
    resume_id = int(callback.data.split("_")[4])
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        if user:
            current_value = user.experience or 'не указан'
            await callback.message.edit_text(
                f"✏️ Редактирование опыта работы\n\n"
                f"💼 Текущий опыт: {current_value}\n\n"
                "Введите новый опыт работы:"
            )
            await state.update_data(editing_user_id=callback.from_user.id)
            await state.set_state(EditResumeForm.edit_experience)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_resume_field_about_"))
async def edit_resume_field_about(callback: CallbackQuery, state: FSMContext):
    """Редактирование информации о себе в анкете"""
    resume_id = int(callback.data.split("_")[4])
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
        if user:
            current_value = user.about or 'не указано'
            await callback.message.edit_text(
                f"✏️ Редактирование информации о себе\n\n"
                f"📝 Текущая информация: {current_value}\n\n"
                "Введите новую информацию о себе:"
            )
            await state.update_data(editing_user_id=callback.from_user.id)
            await state.set_state(EditResumeForm.edit_about)
    await callback.answer()


# Обработчики сохранения отредактированных полей анкеты
@router.message(EditResumeForm.edit_name)
async def process_edit_resume_name(msg: Message, state: FSMContext):
    """Обработка редактирования имени"""
    if await check_cancel(msg, state):
        return
    await update_user_field(msg, state, 'name', msg.text.strip())


@router.message(EditResumeForm.edit_age)
async def process_edit_resume_age(msg: Message, state: FSMContext):
    """Обработка редактирования возраста"""
    if await check_cancel(msg, state):
        return
    age_text = msg.text.strip()
    if not age_text.isdigit():
        await msg.answer("❌ Возраст должен быть числом. Введите еще раз:", reply_markup=kb_cancel)
        return
    age = int(age_text)
    if age < 14 or age > 100:
        await msg.answer("❌ Возраст должен быть от 14 до 100. Введите еще раз:", reply_markup=kb_cancel)
        return
    await update_user_field(msg, state, 'age', age)


@router.message(EditResumeForm.edit_gender)
async def process_edit_resume_gender(msg: Message, state: FSMContext):
    """Обработка редактирования пола"""
    if await check_cancel(msg, state):
        return
    gender = msg.text.strip()
    if gender.lower() not in ["мужской", "женский", "муж", "жен"]:
        await msg.answer(
            "❌ Пожалуйста, выберите пол:\n"
            "Мужской или Женский",
            reply_markup=kb_cancel
        )
        return
    if gender.lower() in ["мужской", "муж"]:
        gender = "Мужской"
    else:
        gender = "Женский"
    await update_user_field(msg, state, 'gender', gender)


@router.message(EditResumeForm.edit_experience)
async def process_edit_resume_experience(msg: Message, state: FSMContext):
    """Обработка редактирования опыта"""
    if await check_cancel(msg, state):
        return
    await update_user_field(msg, state, 'experience', msg.text.strip())


@router.message(EditResumeForm.edit_about)
async def process_edit_resume_about(msg: Message, state: FSMContext):
    """Обработка редактирования информации о себе"""
    if await check_cancel(msg, state):
        return
    await update_user_field(msg, state, 'about', msg.text.strip())


async def update_user_field(msg: Message, state: FSMContext, field_name: str, new_value):
    """Обновление поля пользователя в анкете"""
    try:
        data = await state.get_data()
        user_id = data.get('editing_user_id', msg.from_user.id)
        
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await msg.answer("❌ Пользователь не найден", reply_markup=kb_menu)
                await state.clear()
                return
            
            # Обновляем поле
            setattr(user, field_name, new_value)
            session.commit()
            
            field_names = {
                'name': 'Имя',
                'age': 'Возраст',
                'gender': 'Пол',
                'experience': 'Опыт работы',
                'about': 'Информация о себе'
            }
            
            await msg.answer(
                f"✅ {field_names.get(field_name, 'Поле')} успешно обновлено!",
                reply_markup=kb_menu
            )
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении поля {field_name}: {e}")
        await msg.answer(
            "❌ Произошла ошибка при обновлении. Попробуйте позже.",
            reply_markup=kb_menu
        )
        await state.clear()


@router.callback_query(F.data.startswith("respond_job_"))
async def respond_to_job(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработчик отклика на вакансию. Заполнение анкеты только в личных сообщениях."""
    try:
        job_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        
        # Если пользователь нажал кнопку в группе/канале — перенаправляем в личные сообщения
        if callback.message.chat.type != ChatType.PRIVATE:
            await callback.answer(
                "📩 Для отклика откройте бота в личные сообщения (ЛС) и нажмите кнопку там.",
                show_alert=True
            )
            try:
                go_private_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="📝 Откликнуться на вакансию",
                        callback_data=callback.data
                    )]
                ])
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        "👋 Вы нажали «Откликнуться» на вакансию в канале/группе.\n\n"
                        "Продолжите отклик здесь — нажмите кнопку ниже:"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=go_private_keyboard
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение в ЛС пользователю {user_id}: {e}")
                # Пользователь ещё не писал боту в ЛС — показываем подсказку в алерте
                await callback.answer(
                    "📩 Сначала напишите боту в личные сообщения (ЛС), затем снова нажмите «Откликнуться» в канале.",
                    show_alert=True
                )
            return
        
        # Получаем информацию о вакансии (далее — только в личном чате)
        with SessionLocal() as session:
            from database.models import JobResponse
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Проверяем, не откликался ли уже пользователь
            existing_response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=user_id
            ).first()
            
            if existing_response:
                await callback.answer("⚠️ Вы уже откликнулись на эту вакансию", show_alert=True)
                return
            
            # Проверяем черный список
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user and user.is_blacklisted:
                if user.blacklist_until and user.blacklist_until > datetime.now():
                    await callback.answer(
                        f"🚫 Вы заблокированы до {user.blacklist_until.strftime('%d.%m.%Y')}",
                        show_alert=True
                    )
                    return
                else:
                    # Разблокировка
                    user.is_blacklisted = False
                    user.blacklist_until = None
                    session.commit()
            
            # Проверяем наличие анкеты у пользователя (проверяем наличие данных в User)
            if user and user.name:  # Если есть имя, значит резюме заполнено
                # Получаем данные пользователя
                rating = user.average_rating
                completed_jobs = user.completed_jobs
                refusals_count = user.refusals_count
                last_work_date = user.last_work_date.strftime('%d.%m.%Y') if user.last_work_date else 'нет'
                
                # Формат рейтинга: ⭐ 4.6 | 12 работ | 1 отказ
                rating_text = f"⭐ {rating:.1f} | {completed_jobs} работ | {refusals_count} отказ"
                if refusals_count != 1:
                    rating_text = rating_text.replace("отказ", "отказов")
                
                # Формируем текст отклика согласно новому ТЗ
                response_text = (
                    f"📨 <b>НОВЫЙ ОТКЛИК</b>\n\n"
                    f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n\n"
                    f"👤 <b>Кандидат:</b>\n"
                    f"Имя: {user.name or 'не указано'}\n"
                    f"Возраст: {user.age or 'не указан'}\n"
                    f"Пол: {user.gender or 'не указан'}\n"
                    f"Опыт работы: {user.experience or 'не указан'}\n"
                    f"О себе: {user.about or 'не указано'}\n"
                    f"📞 Телефон: {user.phone or 'не указан'}\n"
                    f"📅 Последний выход на работу: {last_work_date}\n\n"
                    f"{rating_text}"
                )
                
                # Кнопки для выбора кандидата
                select_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Выбрать",
                        callback_data=f"select_candidate_main_{job_id}_{user_id}"
                    )],
                    [InlineKeyboardButton(
                        text="❌ Отклонить",
                        callback_data=f"reject_candidate_{job_id}_{user_id}"
                    )]
                ])
                
                try:
                    # Отправляем работодателю
                    await bot.send_message(
                        chat_id=job.user_id,
                        text=response_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=select_keyboard
                    )
                    
                    # Отправляем админу
                    for admin_id in ADMINS:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text=response_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=select_keyboard
                            )
                        except Exception as admin_e:
                            logger.error(f"Не удалось отправить отклик админу {admin_id}: {admin_e}")
                    
                    # Сохраняем отклик в БД
                    response = JobResponse(
                        job_id=job_id,
                        user_id=user_id,
                        status=ResponseStatus.PENDING
                    )
                    session.add(response)
                    session.commit()
                    
                    await callback.answer("✅ Ваш отклик отправлен работодателю!", show_alert=True)
                except Exception as e:
                    logger.error(f"Ошибка при отправке отклика работодателю: {e}")
                    await callback.answer("❌ Не удалось отправить отклик. Попробуйте позже.", show_alert=True)
            else:
                # Если анкеты нет — начинаем заполнение в личных сообщениях
                await callback.answer()
                await callback.message.answer(
                    "📝 Для отклика на вакансию нужно заполнить резюме.\n\n"
                    "Ответьте на 6 вопросов (в конце — номер телефона):",
                    reply_markup=kb_cancel
                )
                
                # Сохраняем job_id в состоянии для отправки отклика после заполнения
                await state.update_data(respond_to_job_id=job_id)
                
                # Начинаем заполнение анкеты (имя, возраст, пол, опыт, о себе)
                await callback.message.answer(
                    "1️⃣ Напишите ваше ФИО",
                    reply_markup=kb_cancel
                )
                await state.set_state(ResumeForm.name)
    
    except Exception as e:
        logger.error(f"Ошибка при обработке отклика на вакансию: {e}")
        await callback.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data.startswith("select_candidate_main_"))
async def select_candidate_main(callback: CallbackQuery, bot: Bot):
    """Обработчик выбора основного кандидата"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[3])
        candidate_id = int(parts[4])
        
        with SessionLocal() as session:
            from database.models import JobResponse, JobStatus, ResponseStatus
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена или у вас нет прав", show_alert=True)
                return
            
            # Проверяем количество уже выбранных основных кандидатов
            main_candidates = session.query(JobResponse).filter_by(
                job_id=job_id, is_selected=True, is_reserve=False
            ).count()
            
            if main_candidates >= job.people_needed:
                await callback.answer(f"❌ Уже выбрано {main_candidates} из {job.people_needed} основных кандидатов", show_alert=True)
                return
            
            # Обновляем статус отклика
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=candidate_id
            ).first()
            
            if response:
                response.status = ResponseStatus.ACCEPTED
                response.is_selected = True
                response.is_reserve = False
                
                # Обновляем статус вакансии
                main_candidates_after = main_candidates + 1
                if main_candidates_after < job.people_needed:
                    job.status = JobStatus.IN_PROGRESS
                else:
                    job.status = JobStatus.CANDIDATES_SELECTED
                
                session.commit()
                
                # Отправляем уведомление кандидату
                try:
                    # Получаем данные работодателя
                    employer = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
                    employer_phone = employer.phone if employer else 'не указан'
                    employer_username = f"@{employer.username}" if employer and employer.username else 'нет'
                    
                    await bot.send_message(
                        chat_id=candidate_id,
                        text=(
                            f"🎉 <b>Вас выбрали на работу!</b>\n\n"
                            f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                            f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                            f"⏰ <b>График:</b> {job.all_info.get('schedule', 'не указано')}\n"
                            f"💰 <b>Оплата:</b> {job.all_info.get('payment', 'не указана')}\n\n"
                            f"📞 <b>Контакты работодателя:</b>\n"
                            f"Телефон: <code>{employer_phone}</code>\n"
                            f"Username: {employer_username}"
                        ),
                        parse_mode=ParseMode.HTML
                    )
                    
                    await callback.answer("✅ Кандидат выбран!", show_alert=True)
                    await callback.message.edit_text(
                        callback.message.text + f"\n\n✅ <b>Выбран ({main_candidates_after}/{job.people_needed})</b>",
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления кандидату: {e}")
                    await callback.answer("❌ Не удалось уведомить кандидата", show_alert=True)
            else:
                await callback.answer("❌ Отклик не найден", show_alert=True)
    
    except Exception as e:
        logger.error(f"Ошибка при выборе кандидата: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("select_candidate_reserve_"))
async def select_candidate_reserve(callback: CallbackQuery, bot: Bot):
    """Обработчик выбора резервного кандидата"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[3])
        candidate_id = int(parts[4])
        
        with SessionLocal() as session:
            from database.models import JobResponse, ResponseStatus
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Проверяем количество резервных кандидатов (максимум 4)
            reserve_candidates = session.query(JobResponse).filter_by(
                job_id=job_id, is_reserve=True
            ).count()
            
            if reserve_candidates >= 4:
                await callback.answer("❌ Уже выбрано максимальное количество резервных кандидатов (4)", show_alert=True)
                return
            
            # Обновляем статус отклика
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=candidate_id
            ).first()
            
            if response:
                response.status = ResponseStatus.ACCEPTED
                response.is_selected = False
                response.is_reserve = True
                session.commit()
                
                await callback.answer("✅ Кандидат выбран как резервный!", show_alert=True)
                await callback.message.edit_text(
                    callback.message.text + "\n\n📋 <b>Выбран как резервный</b>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await callback.answer("❌ Отклик не найден", show_alert=True)
    
    except Exception as e:
        logger.error(f"Ошибка при выборе резервного кандидата: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("reject_candidate_"))
async def reject_candidate(callback: CallbackQuery, bot: Bot):
    """Обработчик отклонения кандидата"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        candidate_id = int(parts[3])
        
        with SessionLocal() as session:
            from database.models import ResponseStatus
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=candidate_id
            ).first()
            
            if response:
                response.status = ResponseStatus.REJECTED
                session.commit()
                
                # Уведомляем кандидата об отклонении
                job = session.query(Job).filter_by(id=job_id).first()
                job_title = job.all_info.get('title', 'не указано') if job else 'не указано'
                try:
                    await bot.send_message(
                        chat_id=candidate_id,
                        text=(
                            f"😔 <b>Ваш отклик отклонён</b>\n\n"
                            f"📋 Вакансия: {job_title}\n\n"
                            f"К сожалению, работодатель выбрал другого кандидата."
                        ),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.warning(f"Не удалось уведомить кандидата {candidate_id} об отклонении: {e}")
                
                await callback.answer("❌ Кандидат отклонен", show_alert=True)
                await callback.message.edit_text(
                    callback.message.text + "\n\n❌ <b>Отклонен</b>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await callback.answer("❌ Отклик не найден", show_alert=True)
    
    except Exception as e:
        logger.error(f"Ошибка при отклонении кандидата: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("refuse_work_"))
async def refuse_work(callback: CallbackQuery, bot: Bot):
    """Обработчик отказа от работы"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            from database.models import JobResponse, ResponseStatus, JobStatus
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=callback.from_user.id,
                status=ResponseStatus.ACCEPTED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не выбраны на эту вакансию", show_alert=True)
                return
            
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Обновляем статус отклика
            response.status = ResponseStatus.REFUSED
            
            # Увеличиваем счетчик отказов у пользователя
            user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
            if user:
                user.refusals_count += 1
                
                # Проверяем черный список: 3 отказа = блокировка на 30 дней
                if user.refusals_count >= 3 and not user.is_blacklisted:
                    user.is_blacklisted = True
                    user.blacklist_until = datetime.now() + timedelta(days=30)
                    
                    # Уведомляем пользователя о блокировке
                    try:
                        await bot.send_message(
                            chat_id=callback.from_user.id,
                            text=(
                                f"🚫 <b>Вы заблокированы на 30 дней</b>\n\n"
                                f"Причина: 3 отказа после подтверждения выхода на работу.\n\n"
                                f"Разблокировка: {user.blacklist_until.strftime('%d.%m.%Y')}"
                            ),
                            parse_mode=ParseMode.HTML
                        )
                    except Exception as e:
                        logger.error(f"Не удалось уведомить о блокировке: {e}")
            
            # Если это был основной кандидат, уменьшаем счетчик
            if response.is_selected:
                job.people_confirmed = max(0, job.people_confirmed - 1)
                if job.people_confirmed < job.people_needed:
                    job.status = JobStatus.CANDIDATES_SELECTED
            
            # Если есть резервный кандидат, отправляем ему предложение
            reserve_response = session.query(JobResponse).filter_by(
                job_id=job_id, is_reserve=True, status=ResponseStatus.ACCEPTED
            ).order_by(JobResponse.created_at).first()
            
            session.commit()
            
            if reserve_response:
                # Отправляем предложение резервному кандидату
                try:
                    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="✅ Подтвердить выход",
                            callback_data=f"confirm_work_{job_id}"
                        )],
                        [InlineKeyboardButton(
                            text="❌ Отказаться",
                            callback_data=f"refuse_work_{job_id}"
                        )]
                    ])
                    
                    await bot.send_message(
                        chat_id=reserve_response.user_id,
                        text=(
                            f"🎉 <b>Вас выбрали на работу!</b>\n\n"
                            f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                            f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                            f"⏰ <b>Время:</b> {job.all_info.get('schedule', 'не указано')}\n"
                            f"💰 <b>Оплата:</b> {job.all_info.get('payment', 'не указана')}\n\n"
                            f"⚠️ Подтвердите свой выход на работу и укажите время:"
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_markup=confirm_keyboard
                    )
                    
                    # Меняем статус резервного на основной
                    reserve_response.is_reserve = False
                    reserve_response.is_selected = True
                    session.commit()
                except Exception as e:
                    logger.error(f"Не удалось уведомить резервного кандидата: {e}")
            
            # Уведомляем работодателя и админа
            notification_text = (
                f"⚠️ <b>Кандидат отказался от вакансии</b>\n\n"
                f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                f"👤 <b>Кандидат:</b> {user.name if user else 'Не указано'}\n\n"
                f"Сделать вакансию снова активной?"
            )
            
            reactivate_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, опубликовать снова", callback_data=f"reactivate_job_{job_id}")],
                [InlineKeyboardButton(text="❌ Нет, отменить вакансию", callback_data=f"cancel_job_{job_id}")]
            ])
            
            try:
                await bot.send_message(
                    chat_id=job.user_id,
                    text=notification_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reactivate_keyboard
                )
                
                for admin_id in ADMINS:
                    try:
                        await bot.send_message(
                            chat_id=admin_id,
                            text=notification_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reactivate_keyboard
                        )
                    except Exception as admin_e:
                        logger.error(f"Не удалось отправить уведомление админу {admin_id}: {admin_e}")
            except Exception as e:
                logger.error(f"Не удалось уведомить работодателя: {e}")
            
            await callback.answer("❌ Вы отказались от выполнения вакансии", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ <b>Отказ зарегистрирован</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при отказе от работы: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("confirm_work_"))
async def confirm_work_start(callback: CallbackQuery, state: FSMContext):
    """Начало подтверждения выхода на работу"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, selected_user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
        
        await callback.answer()
        await callback.message.answer(
            "✅ Подтвердите выход на работу\n\n"
            "Укажите время начала работы (формат: ДД.ММ.ГГГГ ЧЧ:ММ)\n"
            "Например: 27.01.2026 09:00",
            reply_markup=kb_cancel
        )
        await state.update_data(confirming_job_id=job_id)
        await state.set_state(ConfirmWorkForm.work_start_time)
    
    except Exception as e:
        logger.error(f"Ошибка при подтверждении выхода: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.message(ConfirmWorkForm.work_start_time)
async def process_work_start_time(msg: Message, state: FSMContext):
    """Обработка времени начала работы"""
    if await check_cancel(msg, state):
        return
    
    try:
        start_time_str = msg.text.strip()
        # Парсим время в формате ЧЧ:ММ
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        
        await state.update_data(work_start_time=start_time_str)
        await msg.answer(
            "✅ Время начала работы сохранено!\n\n"
            "Укажите время окончания работы (формат: ЧЧ:ММ)\n"
            "Например: 18:00",
            reply_markup=kb_cancel
        )
        await state.set_state(ConfirmWorkForm.work_end_time)
    
    except ValueError:
        await msg.answer(
            "❌ Неверный формат времени. Используйте формат: ЧЧ:ММ\n"
            "Например: 09:00",
            reply_markup=kb_cancel
        )


@router.message(ConfirmWorkForm.work_end_time)
async def process_work_end_time(msg: Message, state: FSMContext, bot: Bot):
    """Обработка времени окончания работы и финальное подтверждение"""
    if await check_cancel(msg, state):
        return
    
    try:
        end_time_str = msg.text.strip()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()
        
        data = await state.get_data()
        start_time_str = data.get('work_start_time')
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        job_id = data.get('confirming_job_id')
        
        if end_time <= start_time:
            await msg.answer("❌ Время окончания должно быть позже времени начала. Введите время еще раз:", reply_markup=kb_cancel)
            return
        
        with SessionLocal() as session:
            from database.models import JobResponse, ResponseStatus, JobStatus
            # Проверяем, что пользователь выбран
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=msg.from_user.id,
                status=ResponseStatus.ACCEPTED
            ).first()
            
            if not response:
                await msg.answer("❌ Вы не выбраны на эту вакансию", reply_markup=kb_menu)
                await state.clear()
                return
            
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await msg.answer("❌ Вакансия не найдена", reply_markup=kb_menu)
                await state.clear()
                return
            
            # Обновляем статус отклика
            response.status = ResponseStatus.CONFIRMED
            
            # Обновляем счетчик подтвержденных кандидатов
            job.people_confirmed += 1
            
            # Если все основные кандидаты подтвердили, меняем статус
            if job.people_confirmed >= job.people_needed:
                job.status = JobStatus.CONFIRMED
            
            # Сохраняем время работы (используем сегодняшнюю дату + время)
            today = datetime.now().date()
            job.work_start_time = datetime.combine(today, start_time)
            job.work_end_time = datetime.combine(today, end_time)
            
            # Обновляем last_work_date у пользователя
            user = session.query(User).filter_by(telegram_id=msg.from_user.id).first()
            if user:
                user.last_work_date = datetime.now()
            
            session.commit()
            
            # Обновляем кнопку в канале (меняем "Откликнуться" на "Исполнено")
            try:
                # Удаляем кнопку отклика
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=job.message_id,
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Не удалось обновить кнопку в канале: {e}")
            
            # Обновляем кнопку в канале, если все подтвердили
            if job.status == JobStatus.CONFIRMED:
                try:
                    await bot.edit_message_reply_markup(
                        chat_id=CHANNEL_ID,
                        message_id=job.message_id,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Исполнитель подтвержден", callback_data="completed")]
                        ])
                    )
                except Exception as e:
                    logger.error(f"Не удалось обновить кнопку в канале: {e}")
            
            await msg.answer(
                f"✅ Выход на работу подтвержден!\n\n"
                f"⏰ <b>Начало:</b> {start_time_str}\n"
                f"⏰ <b>Окончание:</b> {end_time_str}\n\n"
                f"Вы получите уведомления за 4 часа и за 45 минут до начала работы.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_menu
            )
            
            # Уведомляем работодателя
            try:
                user = session.query(User).filter_by(telegram_id=msg.from_user.id).first()
                await bot.send_message(
                    chat_id=job.user_id,
                    text=(
                        f"✅ <b>Кандидат подтвердил выход на работу</b>\n\n"
                        f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                        f"👤 <b>Кандидат:</b> {user.name if user else 'Не указано'}\n"
                        f"⏰ <b>Начало:</b> {start_time_str}\n"
                        f"⏰ <b>Окончание:</b> {end_time_str}\n\n"
                        f"Подтверждено: {job.people_confirmed}/{job.people_needed}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить работодателя: {e}")
        
        await state.clear()
    
    except ValueError:
        await msg.answer(
            "❌ Неверный формат времени. Используйте формат: ЧЧ:ММ\n"
            "Например: 18:00",
            reply_markup=kb_cancel
        )


# ЗАКОММЕНТИРОВАНО: Обработчик кнопки оплаты
# @router.message(F.text == "💳 Оплатить")
# async def payment_button(msg: Message):
#     """Обработчик кнопки оплаты"""
#     await msg.answer(
#         "💰 Для оплаты свяжитесь с админом:\n\n"
#         "💵 Стоимость: 30 сом\n"
#         "⏰ После оплаты возможность публикации одной вакнсии",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
#             [InlineKeyboardButton(text="👤 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME}")]
#         ])
#     )


@router.message(F.text == "📞 Связаться с админом")
async def contact_admin_button(msg: Message):
    """Обработчик кнопки связи с админом"""
    await msg.answer(
        "👤 Свяжитесь с админом для решения вопросов:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Написать админу", url=f"https://t.me/jajjajt")]
        ])
    )


def create_response_buttons(job_id: int = None, job: Job = None) -> InlineKeyboardMarkup:
    """
    Создает кнопки для отклика на вакансию
    Args:
        job_id: ID вакансии
        job: Объект Job (если передан, используется для проверки статуса)
    Returns:
        InlineKeyboardMarkup с кнопками для отклика
    """
    buttons = []
    
    if job_id is not None:
        from database.models import JobStatus
        # Если job не передан, получаем из БД
        if job is None:
            with SessionLocal() as session:
                job = session.query(Job).filter_by(id=job_id).first()
        
        if job:
            # Проверяем количество подтвержденных кандидатов
            from database.models import JobResponse, ResponseStatus
            from database.db_connection import SessionLocal
            with SessionLocal() as session:
                confirmed_count = session.query(JobResponse).filter_by(
                    job_id=job.id, status=ResponseStatus.CONFIRMED
                ).count()
            
            # Кнопка отклика активна только при статусах open и in_progress (пока есть места)
            if job.status in [JobStatus.OPEN, JobStatus.IN_PROGRESS] and confirmed_count < job.people_needed:
                buttons.append([
                    InlineKeyboardButton(
                        text="📝 Откликнуться",
                        callback_data=f"respond_job_{job_id}"
                    )
                ])
            elif job.status == JobStatus.CONFIRMED:
                buttons.append([
                    InlineKeyboardButton(
                        text="✅ Исполнитель подтвержден",
                        callback_data="completed"
                    )
                ])
            elif job.status == JobStatus.COMPLETED:
                buttons.append([
                    InlineKeyboardButton(
                        text="✅ Завершено",
                        callback_data="completed"
                    )
                ])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None


# Обработка пошагового опроса для публикации вакансии

@router.message(VacancyForm.job_type)
async def process_job_type(msg: Message, state: FSMContext):
    """Обработка типа вакансии"""
    if await check_cancel(msg, state):
        return
    
    text = msg.text.strip()
    if "долгосрочная" in text.lower() or "долго" in text.lower():
        job_type = JobType.LONG_TERM
    elif "разовая" in text.lower() or "разов" in text.lower():
        job_type = JobType.ONE_TIME
    else:
        await msg.answer(
            "❌ Пожалуйста, выберите тип вакансии:\n"
            "📅 Долгосрочная вакансия\n"
            "⚡ Разовая работа",
            reply_markup=kb_cancel
        )
        return
    
    await state.update_data(job_type=job_type.value)
    await msg.answer(
        "✅ Тип вакансии сохранен!\n\n"
        "1️⃣ Опишите вакансию / вид работы",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.work_description)


@router.message(VacancyForm.work_description)
async def process_work_description(msg: Message, state: FSMContext):
    """Обработка описания работы"""
    if await check_cancel(msg, state):
        return
    
    work_description = msg.text.strip()
    if not work_description:
        await msg.answer("❌ Описание работы не может быть пустым. Пожалуйста, опишите работу:", reply_markup=kb_cancel)
        return
    
    await state.update_data(title=work_description)
    await msg.answer(
        "✅ Описание работы сохранено!\n\n"
        "2️⃣ Укажите адрес работы",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.address)


@router.message(VacancyForm.address)
async def process_address(msg: Message, state: FSMContext):
    """Обработка адреса вакансии"""
    if await check_cancel(msg, state):
        return
    
    address = msg.text.strip()
    if not address:
        await msg.answer("❌ Адрес не может быть пустым. Пожалуйста, введите адрес:", reply_markup=kb_cancel)
        return
    
    await state.update_data(address=address)
    await msg.answer(
        "✅ Адрес сохранен!\n\n"
        "3️⃣ Укажите требования\n"
        "(Например: мальчики/девочки, с опытом/без опыта)",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.requirements)


@router.message(VacancyForm.requirements)
async def process_requirements(msg: Message, state: FSMContext):
    """Обработка требований к работнику"""
    if await check_cancel(msg, state):
        return
    
    requirements = msg.text.strip()
    if not requirements:
        await msg.answer("❌ Требования не могут быть пустыми. Пожалуйста, укажите требования:", reply_markup=kb_cancel)
        return
    
    await state.update_data(requirements=requirements)
    await msg.answer(
        "✅ Требования сохранены!\n\n"
        "4️⃣ Укажите оплату в цифрах\n"
        "(Например: 500, 1000, 1500)",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.payment)


@router.message(VacancyForm.payment)
async def process_payment(msg: Message, state: FSMContext):
    """Обработка оплаты - проверка что только цифры"""
    if await check_cancel(msg, state):
        return
    
    payment = msg.text.strip()
    
    # Проверка: только цифры
    if not payment.isdigit():
        await msg.answer(
            "❌ Оплата должна содержать только цифры!\n"
            "Пожалуйста, введите оплату цифрами (например: 5000):",
            reply_markup=kb_cancel
        )
        return
    
    await state.update_data(payment=payment)
    await msg.answer(
        "✅ Оплата сохранена!\n\n"
        "5️⃣ Укажите график / время работы",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.schedule)


@router.message(VacancyForm.schedule)
async def process_schedule(msg: Message, state: FSMContext):
    """Обработка графика работы"""
    if await check_cancel(msg, state):
        return
    
    schedule = msg.text.strip()
    if not schedule:
        await msg.answer("❌ График работы не может быть пустым. Пожалуйста, укажите график:", reply_markup=kb_cancel)
        return
    
    await state.update_data(schedule=schedule)
    await msg.answer(
        "✅ График работы сохранен!\n\n"
        "6️⃣ Сколько человек требуется? (от 1 до 10)",
        reply_markup=kb_cancel
    )
    await state.set_state(VacancyForm.people_needed)


@router.message(VacancyForm.people_needed)
async def process_people_needed(msg: Message, state: FSMContext, bot: Bot):
    """Обработка количества требуемых людей и финальная публикация"""
    if await check_cancel(msg, state):
        return
    
    people_text = msg.text.strip()
    if not people_text.isdigit():
        await msg.answer(
            "❌ Количество должно быть числом от 1 до 10!\n"
            "Пожалуйста, введите количество еще раз:",
            reply_markup=kb_cancel
        )
        return
    
    people_needed = int(people_text)
    if people_needed < 1 or people_needed > 10:
        await msg.answer(
            "❌ Количество должно быть от 1 до 10!\n"
            "Пожалуйста, введите количество еще раз:",
            reply_markup=kb_cancel
        )
        return
    
    # Получаем все данные из состояния
    data = await state.get_data()
    
    uid = msg.from_user.id
    
    # Проверяем существование пользователя в базе
    try:
        insert_user(uid, msg.from_user.username or "")
    except Exception as e:
        logger.error(f"Ошибка при создании пользователя {uid}: {e}")
    
    # Формируем данные для сохранения
    vacancy_data = {
        "title": data.get("title", ""),
        "address": data.get("address", ""),
        "requirements": data.get("requirements", ""),
        "payment": data.get("payment", ""),
        "schedule": data.get("schedule", "")
    }
    
    job_type = JobType(data.get("job_type", JobType.ONE_TIME.value))
    
    try:
        # Публикация новой вакансии в канал
        vacancy_text = (
            f"📋 <b>{vacancy_data['title']}</b>\n\n"
            f"📍 Адрес: {vacancy_data['address']}\n"
            f"👤 Требования: {vacancy_data['requirements']}\n"
            f"💰 Оплата: {vacancy_data['payment']}\n"
            f"⏰ График: {vacancy_data['schedule']}\n"
            f"👥 Требуется: {people_needed} человек"
        )

        # Определяем канал и топик для публикации в зависимости от типа вакансии
        target_channel = CHANNEL_ID
        thread_id = get_vacancy_thread_id(job_type)  # 1195 = постоянные, 1 = подработки

        posted = await bot.send_message(
            chat_id=target_channel,
            message_thread_id=thread_id,
            text=vacancy_text,
            parse_mode=ParseMode.HTML
        )

        # Сохранение в базу
        job_id = None
        try:
            with SessionLocal() as session:
                from database.models import JobStatus
                job = Job(
                    user_id=uid,
                    message_id=posted.message_id,
                    all_info=vacancy_data,
                    job_type=job_type,
                    status=JobStatus.OPEN,
                    people_needed=people_needed,
                    people_confirmed=0
                )
                session.add(job)
                session.commit()
                job_id = job.id

            # Кнопка отклика
            with SessionLocal() as session:
                saved_job = session.query(Job).filter_by(id=job_id).first()
                response_button = create_response_buttons(job_id=job_id, job=saved_job)
            
            if response_button:
                await bot.edit_message_reply_markup(
                    chat_id=target_channel,
                    message_id=posted.message_id,
                    reply_markup=response_button
                )
        except Exception as e:
            # Отправляем ошибку админам
            for admin_id in ADMINS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"❌ Ошибка при сохранении вакансии:\n"
                        f"User ID: {uid}\n"
                        f"Message ID: {posted.message_id}\n"
                        f"Error: {str(e)}\n"
                        f"Data: {vacancy_data}"
                    )
                except Exception as admin_e:
                    logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
            
            # Удаляем сообщение из канала (message_thread_id не нужен для deleteMessage)
            try:
                await bot.delete_message(chat_id=CHANNEL_ID, message_id=posted.message_id)
            except Exception as delete_e:
                logger.error(f"Не удалось удалить сообщение из канала: {delete_e}")
            
            await msg.answer(
                "❌ Произошла ошибка при сохранении вакансии. Пожалуйста, попробуйте позже или обратитесь к администратору.",
                reply_markup=kb_menu
            )
            await state.clear()
            return

        await msg.answer(
            "✅ Ваша вакансия успешно опубликована!\n\n"
            f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}\n"
            "📋 Для управления вакансиями используйте 'Мои вакансии'",
            reply_markup=kb_menu
        )

    except Exception as e:
        logger.error(f"Ошибка при публикации вакансии: {e}")
        # Отправляем ошибку админам
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"❌ Ошибка при публикации вакансии:\n"
                    f"User ID: {uid}\n"
                    f"Error: {str(e)}\n"
                    f"Data: {vacancy_data}"
                )
            except Exception as admin_e:
                logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
        
        await msg.answer(
            "❌ Произошла ошибка при публикации вакансии. Пожалуйста, попробуйте позже или обратитесь к администратору.",
            reply_markup=kb_menu
        )

    await state.clear()


# ==================== ОБРАБОТЧИКИ ДЛЯ АНКЕТ ====================

async def prepare_resume_impl(msg: Message, state: FSMContext):
    """Общая логика подготовки анкеты - начинаем пошаговый опрос"""
    user_id = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id

    # Начинаем пошаговый опрос
    await msg.answer(
        "👋 Добро пожаловать!\n\n"
        "Для отклика на вакансии необходимо заполнить резюме.\n"
        "Ответьте на 6 вопросов (имя, возраст, пол, опыт, о себе, телефон):\n\n"
        "1️⃣ Как вас зовут?",
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.name)



@router.message(F.text == "📝 Моё резюме")
async def prepare_resume_button(msg: Message, state: FSMContext):
    """Обработчик кнопки Моё резюме"""
    user_id = msg.from_user.id

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()

        if user and user.name:
            rating_text = f"⭐ {user.average_rating:.1f} | {user.completed_jobs} работ | {user.refusals_count} отказ"
            if user.refusals_count != 1:
                rating_text = rating_text.replace("отказ", "отказов")

            edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1️⃣ Имя", callback_data="edit_resume_field_name_0")],
                [InlineKeyboardButton(text="2️⃣ Возраст", callback_data="edit_resume_field_age_0")],
                [InlineKeyboardButton(text="3️⃣ Пол", callback_data="edit_resume_field_gender_0")],
                [InlineKeyboardButton(text="4️⃣ Опыт", callback_data="edit_resume_field_experience_0")],
                [InlineKeyboardButton(text="5️⃣ О себе", callback_data="edit_resume_field_about_0")],
            ])

            await msg.answer(
                f"📋 <b>Моё резюме</b>\n\n"
                f"{rating_text}\n"
                f"Имя: {user.name or 'не указано'}\n"
                f"Возраст: {user.age or 'не указан'}\n"
                f"Пол: {user.gender or 'не указан'}\n"
                f"Опыт работы: {user.experience or 'не указан'}\n"
                f"О себе: {user.about or 'не указано'}\n\n"
                f"✏️ Выберите поле для редактирования:",
                parse_mode=ParseMode.HTML,
                reply_markup=edit_keyboard
            )
        else:
            await prepare_resume_impl(msg, state)


@router.callback_query(F.data == "create_new_resume")
async def create_new_resume_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик создания новой анкеты"""
    await callback.answer()
    await prepare_resume_impl(callback.message, state)


@router.callback_query(F.data == "edit_my_profile")
async def edit_my_profile_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования анкеты из команды /my_profile"""
    await callback.answer()
    user_id = callback.from_user.id
    
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user or not user.name:
            await callback.message.answer(
                "❌ У вас еще нет резюме. Создайте резюме сначала.",
                reply_markup=kb_menu
            )
            return
        
        # Показываем меню редактирования
        edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1️⃣ Имя", callback_data=f"edit_resume_field_name_0")],
            [InlineKeyboardButton(text="2️⃣ Возраст", callback_data=f"edit_resume_field_age_0")],
            [InlineKeyboardButton(text="3️⃣ Пол", callback_data=f"edit_resume_field_gender_0")],
            [InlineKeyboardButton(text="4️⃣ Опыт", callback_data=f"edit_resume_field_experience_0")],
            [InlineKeyboardButton(text="5️⃣ О себе", callback_data=f"edit_resume_field_about_0")],
        ])
        
        await callback.message.answer(
            "✏️ Выберите, что хотите отредактировать:",
            reply_markup=edit_keyboard
        )


@router.callback_query(F.data.regexp(r"^edit_resume_\d+$"))
async def edit_resume_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик редактирования анкеты"""
    try:
        resume_id = int(callback.data.rsplit("_", 1)[1])
        
        with SessionLocal() as session:
            resume = session.query(Resume).filter_by(id=resume_id, user_id=callback.from_user.id).first()
            if not resume:
                await callback.answer("❌ Резюме не найдено")
                return
            
            # Сохраняем ID анкеты в состоянии
            await state.update_data(editing_resume_id=resume_id)
            
            # Показываем меню выбора поля для редактирования
            edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1️⃣ Имя", callback_data=f"edit_resume_field_name_{resume_id}")],
                [InlineKeyboardButton(text="2️⃣ Возраст", callback_data=f"edit_resume_field_age_{resume_id}")],
                [InlineKeyboardButton(text="3️⃣ Пол", callback_data=f"edit_resume_field_gender_{resume_id}")],
                [InlineKeyboardButton(text="4️⃣ Опыт", callback_data=f"edit_resume_field_experience_{resume_id}")],
                [InlineKeyboardButton(text="5️⃣ О себе", callback_data=f"edit_resume_field_about_{resume_id}")],
            ])
            
            await callback.message.edit_text(
                "✏️ Выберите, что хотите отредактировать:",
                reply_markup=edit_keyboard
            )
            await callback.answer()
    
    except Exception as e:
        logger.error(f"Ошибка при редактировании анкеты: {e}")
        await callback.answer("❌ Произошла ошибка при редактировании")


@router.message(ResumeForm.name)
async def process_resume_name(msg: Message, state: FSMContext):
    """Обработка имени"""
    if await check_cancel(msg, state):
        return
    
    name = msg.text.strip()
    if not name:
        await msg.answer("❌ Имя не может быть пустым. Пожалуйста, введите ваше имя:", reply_markup=kb_cancel)
        return
    
    await state.update_data(name=name)
    await msg.answer(
        "✅ Имя сохранено!\n\n"
        "2️⃣ Сколько вам лет?",
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.age)


@router.message(ResumeForm.age)
async def process_resume_age(msg: Message, state: FSMContext):
    """Обработка возраста"""
    if await check_cancel(msg, state):
        return
    
    age_text = msg.text.strip()
    if not age_text or not age_text.isdigit():
        await msg.answer("❌ Возраст должен быть числом. Пожалуйста, введите ваш возраст:", reply_markup=kb_cancel)
        return
    
    age = int(age_text)
    if age < 14 or age > 100:
        await msg.answer("❌ Пожалуйста, введите корректный возраст (от 14 до 100):", reply_markup=kb_cancel)
        return
    
    await state.update_data(age=age)
    
    # Кнопки для выбора пола
    gender_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")],
            [KeyboardButton(text="❌ Отменить")],
        ],
        resize_keyboard=True
    )
    
    await msg.answer(
        "✅ Возраст сохранен!\n\n"
        "3️⃣ Укажите ваш пол",
        reply_markup=gender_keyboard
    )
    await state.set_state(ResumeForm.gender)


@router.message(ResumeForm.gender)
async def process_resume_gender(msg: Message, state: FSMContext):
    """Обработка пола — только выбор кнопками"""
    if await check_cancel(msg, state):
        return
    
    gender_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")],
            [KeyboardButton(text="❌ Отменить")],
        ],
        resize_keyboard=True
    )
    
    gender = msg.text.strip()
    if gender.lower() not in ["мужской", "женский", "муж", "жен"]:
        await msg.answer(
            "❌ Выберите пол кнопкой ниже:",
            reply_markup=gender_keyboard
        )
        return
    
    # Нормализуем пол
    if gender.lower() in ["мужской", "муж"]:
        gender = "Мужской"
    else:
        gender = "Женский"
    
    await state.update_data(gender=gender)
    await msg.answer(
        "✅ Пол сохранен!\n\n"
        "4️⃣ Опыт работы\n"
        "(Опишите предыдущие места работы)",
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.experience)


@router.message(ResumeForm.experience)
async def process_resume_experience(msg: Message, state: FSMContext):
    """Обработка опыта работы"""
    if await check_cancel(msg, state):
        return
    
    experience = msg.text.strip()
    if not experience:
        await msg.answer("❌ Опыт работы не может быть пустым. Пожалуйста, укажите опыт:", reply_markup=kb_cancel)
        return
    
    await state.update_data(experience=experience)
    await msg.answer(
        "✅ Опыт работы сохранен!\n\n"
        "5️⃣ Расскажите о себе\n"
        "(Дополнительная информация)",
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.about)


# Формат телефона: 0555123456 (0 и 9 цифр)
PHONE_PATTERN = re.compile(r"^0\d{9}$")


@router.message(ResumeForm.about)
async def process_resume_about(msg: Message, state: FSMContext):
    """Обработка информации о себе, затем запрос телефона"""
    if await check_cancel(msg, state):
        return
    
    about = msg.text.strip()
    if not about:
        await msg.answer("❌ Информация о себе не может быть пустой. Пожалуйста, расскажите о себе:", reply_markup=kb_cancel)
        return
    
    await state.update_data(about=about)
    await msg.answer(
        "✅ О себе сохранено!\n\n"
        "6️⃣ Введите номер телефона в формате:\n"
        "<b>0555123456</b>\n"
        "(ноль и 9 цифр, без пробелов и плюса)",
        parse_mode=ParseMode.HTML,
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.phone)


@router.message(ResumeForm.phone)
async def process_resume_phone(msg: Message, state: FSMContext, bot: Bot):
    """Обработка телефона и финальное сохранение анкеты"""
    if await check_cancel(msg, state):
        return
    
    raw = msg.text.strip().replace(" ", "").replace("-", "").replace("+", "")
    if not raw.startswith("0") and len(raw) == 9 and raw.isdigit():
        raw = "0" + raw
    if not PHONE_PATTERN.match(raw):
        await msg.answer(
            "❌ Неверный формат. Введите номер в формате <b>0555123456</b> (ноль и 9 цифр).",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_cancel
        )
        return
    
    phone = raw
    data = await state.get_data()
    data["phone"] = phone
    uid = msg.from_user.id
    
    about = data.get("about", "")
    
    try:
        with SessionLocal() as session:
            # Создаем или обновляем пользователя
            user = session.query(User).filter_by(telegram_id=uid).first()
            if not user:
                user = User(
                    telegram_id=uid,
                    username=msg.from_user.username or "",
                    phone=phone,
                    name=data.get("name", ""),
                    age=data.get("age"),
                    gender=data.get("gender", ""),
                    experience=data.get("experience", ""),
                    about=about,
                    average_rating=5.0,
                    completed_jobs=0,
                    refusals_count=0
                )
                session.add(user)
            else:
                # Обновляем данные пользователя
                user.name = data.get("name", "")
                user.age = data.get("age")
                user.gender = data.get("gender", "")
                user.experience = data.get("experience", "")
                user.about = about
                user.phone = phone
            
            session.commit()
            
            # Получаем рейтинг для отображения
            rating = user.average_rating
            completed_jobs = user.completed_jobs
            refusals_count = user.refusals_count
            
            # Удаляем старую анкету из канала, если она есть
            old_resume = session.query(Resume).filter_by(user_id=uid).order_by(Resume.created_at.desc()).first()
            if old_resume:
                try:
                    await bot.delete_message(
                        chat_id=RESUME_GROUP_ID,
                        message_id=old_resume.message_id
                    )
                    session.delete(old_resume)
                    session.commit()
                except Exception as e:
                    logger.error(f"Не удалось удалить старую анкету: {e}")
            
            # Формируем данные для сохранения в Resume (для совместимости)
            resume_data = {
                "name": data.get("name", ""),
                "age": data.get("age"),
                "gender": data.get("gender", ""),
                "experience": data.get("experience", ""),
                "about": about,
                "phone": phone
            }
        
        # Публикация анкеты в канал (если нужно)
        # Формат рейтинга: ⭐ 4.6 | 12 работ | 1 отказ
        rating_text = f"⭐ {rating:.1f} | {completed_jobs} работ | {refusals_count} отказ"
        if refusals_count != 1:
            rating_text = rating_text.replace("отказ", "отказов")
        
        resume_text = (
            f"<b>Резюме: {data.get('name', 'Не указано')}</b>\n\n"
            f"{rating_text}\n"
            f"📞 Телефон: {phone}\n"
            f"Возраст: {data.get('age', 'не указан')}\n"
            f"Пол: {data.get('gender', 'не указан')}\n"
            f"Опыт работы: {data.get('experience', 'не указан')}\n"
            f"О себе: {about}"
        )

        # Публикуем анкету в группу (опционально, если нужно)
        posted = None
        try:
            if RESUME_GROUP_ID:
                posted = await bot.send_message(
                    chat_id=RESUME_GROUP_ID,
                    message_thread_id=RESUME_THREAD_ID if RESUME_THREAD_ID else None,
                    text=resume_text,
                    parse_mode=ParseMode.HTML
                )
                
                # Сохранение в базу Resume (для совместимости)
                saved = await asyncio.to_thread(save_resume_db, uid, posted.message_id, resume_data)
                if not saved:
                    raise Exception("Не удалось сохранить анкету в базу данных")
        except Exception as e:
            # Отправляем ошибку админам
            for admin_id in ADMINS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"❌ Ошибка при сохранении анкеты:\n"
                        f"User ID: {uid}\n"
                        f"Message ID: {posted.message_id}\n"
                        f"Error: {str(e)}\n"
                        f"Data: {resume_data}"
                    )
                except Exception as admin_e:
                    logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
            
            # Удаляем сообщение из группы
            try:
                await bot.delete_message(chat_id=RESUME_GROUP_ID, message_id=posted.message_id)
            except Exception as delete_e:
                logger.error(f"Не удалось удалить сообщение из группы: {delete_e}")
            
            await msg.answer(
                "❌ Произошла ошибка при сохранении анкеты. Пожалуйста, попробуйте позже или обратитесь к администратору.",
                reply_markup=kb_menu
            )
            await state.clear()
            return

        # Проверяем, был ли это отклик на вакансию
        respond_to_job_id = data.get('respond_to_job_id')
        if respond_to_job_id:
            # Отправляем отклик работодателю и админу
            try:
                with SessionLocal() as session:
                    from database.models import JobResponse, ResponseStatus
                    job = session.query(Job).filter_by(id=respond_to_job_id).first()
                    if job:
                        # Получаем данные пользователя
                        user = session.query(User).filter_by(telegram_id=uid).first()
                        if not user:
                            user = session.query(User).filter_by(telegram_id=uid).first()
                        
                        rating = user.average_rating if user else 5.0
                        completed_jobs = user.completed_jobs if user else 0
                        refusals_count = user.refusals_count if user else 0
                        last_work_date = user.last_work_date.strftime('%d.%m.%Y') if user and user.last_work_date else 'нет'
                        
                        # Формат рейтинга: ⭐ 4.6 | 12 работ | 1 отказ
                        rating_text = f"⭐ {rating:.1f} | {completed_jobs} работ | {refusals_count} отказ"
                        if refusals_count != 1:
                            rating_text = rating_text.replace("отказ", "отказов")
                        
                        # Формируем текст отклика согласно новому ТЗ
                        response_text = (
                            f"📨 <b>НОВЫЙ ОТКЛИК</b>\n\n"
                            f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n\n"
                            f"👤 <b>Кандидат:</b>\n"
                            f"Имя: {data.get('name', 'не указано')}\n"
                            f"Возраст: {data.get('age', 'не указан')}\n"
                            f"Пол: {data.get('gender', 'не указан')}\n"
                            f"Опыт работы: {data.get('experience', 'не указан')}\n"
                            f"О себе: {about}\n"
                            f"📅 Последний выход на работу: {last_work_date}\n\n"
                            f"{rating_text}"
                        )
                        
                        # Кнопка для выбора кандидата
                        select_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(
                                text="✅ Выбрать этого кандидата",
                                callback_data=f"select_candidate_{respond_to_job_id}_{uid}"
                            )]
                        ])
                        
                        # Отправляем работодателю
                        await bot.send_message(
                            chat_id=job.user_id,
                            text=response_text,
                            parse_mode=ParseMode.HTML,
                            reply_markup=select_keyboard
                        )
                        
                        # Отправляем админу
                        for admin_id in ADMINS:
                            try:
                                await bot.send_message(
                                    chat_id=admin_id,
                                    text=response_text,
                                    parse_mode=ParseMode.HTML,
                                    reply_markup=select_keyboard
                                )
                            except Exception as admin_e:
                                logger.error(f"Не удалось отправить отклик админу {admin_id}: {admin_e}")
                        
                        # Сохраняем отклик в БД
                        response = JobResponse(
                            job_id=respond_to_job_id,
                            user_id=uid,
                            status=ResponseStatus.PENDING
                        )
                        session.add(response)
                        session.commit()
                        
                        await msg.answer(
                            "✅ Ваше резюме опубликована и отклик отправлен работодателю!\n\n"
                            f"📄 Ссылка на анкету: {CHANNEL_URL}/{posted.message_id}",
                            reply_markup=kb_menu
                        )
                    else:
                        await msg.answer(
                            "✅ Ваше резюме успешно опубликована!\n\n"
                            f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}",
                            reply_markup=kb_menu
                        )
            except Exception as e:
                logger.error(f"Ошибка при отправке отклика работодателю: {e}")
                await msg.answer(
                    "✅ Ваше резюме успешно опубликована!\n\n"
                    f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}\n\n"
                    "⚠️ Не удалось отправить отклик работодателю. Попробуйте связаться напрямую.",
                    reply_markup=kb_menu
                )
        else:
            await msg.answer(
                "✅ Ваше резюме успешно опубликована!\n\n"
                f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}",
                reply_markup=kb_menu
            )

    except Exception as e:
        logger.error(f"Ошибка при публикации анкеты: {e}")
        # Отправляем ошибку админам
        for admin_id in ADMINS:
            try:
                await bot.send_message(
                    admin_id,
                    f"❌ Ошибка при публикации анкеты:\n"
                    f"User ID: {uid}\n"
                    f"Error: {str(e)}\n"
                    f"Data: {resume_data}"
                )
            except Exception as admin_e:
                logger.error(f"Не удалось отправить сообщение админу {admin_id}: {admin_e}")
        
        await msg.answer(
            "❌ Произошла ошибка при публикации анкеты. Пожалуйста, попробуйте позже или обратитесь к администратору.",
            reply_markup=kb_menu
        )

    await state.clear()


# ЗАКОММЕНТИРОВАНО: Старый обработчик для формы в одну строку
# Этот код больше не используется, так как теперь используется пошаговый опрос
# @router.message(VacancyForm.all_info)
# async def process_vacancy_old(msg: Message, state: FSMContext, bot: Bot):
#     """Обработка заполненной формы вакансии"""
#     try:
#         # Весь старый код обработчика закомментирован, так как теперь используется пошаговый опрос
#         # См. обработчики: process_address, process_work_description, process_payment, 
#         # process_whatsapp, process_worker_requirements
#         pass


# ЗАКОММЕНТИРОВАНО: Функция проверки ограничений на публикацию
# Код перенесен в posting_restrictions.py
# Сейчас публикация разрешена всем пользователям
# 
# def can_post_more_extended(user_id: int) -> tuple[bool, str, int]:
#     """
#     Расширенная проверка возможности публикации вакансии
#     Возвращает: (может_публиковать, сообщение, количество_приглашений)
#     """
#     try:
#         with SessionLocal() as session:
#             user = session.query(User).filter_by(telegram_id=user_id).first()
# 
#             if not user:
#                 # Новый пользователь - первая публикация бесплатно
#                 return True, "Первая публикация бесплатно!", 0
# 
#             # Если у пользователя can_post = True - всегда можем публиковать
#             if user.can_post:
#                 return True, "У вас есть постоянное разрешение на публикацию", user.invites
# 
#             # Проверка месячной подписки
#             if user.can_post_until and user.can_post_until > datetime.now():
#                 return True, f"У вас есть месячная подписка до {user.can_post_until.strftime('%d.%m.%Y %H:%M')}", user.invites
# 
#             # Проверка разовых публикаций
#             if user.allowed_posts > 0:
#                 return True, f"Осталось публикаций: {user.allowed_posts}", user.invites
# 
#             # Проверка первой бесплатной публикации
#             job_count = session.query(func.count(Job.id)).filter_by(user_id=user_id).scalar()
#             if job_count == 0:
#                 return True, "Первая публикация бесплатно!", user.invites
# 
#             # Проверка приглашенных друзей (5+ друзей = 1 публикация)
#             if user.invites >= 5:
#                 # Даем одну публикацию и сбрасываем счетчик приглашений
#                 user.allowed_posts = 1
#                 user.invites = 0  # Сбрасываем счетчик
#                 session.commit()
#                 return True, "Получена публикация за приглашение друзей!", 0
# 
#             return False, "У вас нет доступных публикаций.", user.invites
# 
#     except Exception as e:
#         logger.error(f"Ошибка при can_post_more_extended для пользователя {user_id}: {e}")
#         return False, "Ошибка при проверке прав доступа.", 0


@router.message(Command("write"))
async def write_command_handler(message: Message, bot: Bot):
    """Команда для админов - отправка сообщения в канал от имени бота"""
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    
    try:
        # Получаем текст после команды /write
        command_text = message.text or ""
        if len(command_text.split()) < 2:
            await message.answer(
                "📝 <b>Использование команды:</b>\n\n"
                "/write текст сообщения\n\n"
                "Пример:\n"
                "/write Привет! Это сообщение от бота",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Извлекаем текст сообщения (все после /write)
        text_to_send = command_text.split("/write", 1)[1].strip()
        
        if not text_to_send:
            await message.answer("❌ Текст сообщения не может быть пустым.")
            return
        
        # Отправляем сообщение в канал
        sent_message = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=text_to_send,
            parse_mode=ParseMode.HTML
        )
        
        await message.answer(
            f"✅ Сообщение успешно отправлено в канал!\n\n"
            f"📄 Ссылка: {CHANNEL_URL}/{sent_message.message_id}",
            parse_mode=ParseMode.HTML
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения через /write: {e}")
        await message.answer(
            "❌ Произошла ошибка при отправке сообщения. Попробуйте позже."
        )


@router.message(Command("allow_posting"))
async def allow_posting_handler(message: Message):
    """Команда для админов - предоставление прав публикации"""
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.answer(
                "📝 Использование:\n"
                "/allow_posting @username - одна публикация\n"
                "/allow_posting month @username - месяц публикаций\n"
                "/allow_posting permanent @username - постоянное разрешение"
            )
            return

        is_month = (len(parts) == 3 and parts[1].lower() == "month")
        is_permanent = (len(parts) == 3 and parts[1].lower() == "permanent")
        username_or_id = parts[2] if (is_month or is_permanent) else parts[1]

        with SessionLocal() as session:
            user = None

            if username_or_id.startswith("@"):
                user = session.query(User).filter_by(username=username_or_id[1:]).first()
            elif username_or_id.isdigit():
                user = session.query(User).filter_by(telegram_id=int(username_or_id)).first()

            if not user:
                await message.answer("❌ Пользователь не найден в базе.")
                return

            # Сохраняем старые значения для логирования
            old_can_post = user.can_post
            old_can_post_until = user.can_post_until
            old_allowed_posts = user.allowed_posts

            try:
                if is_permanent:
                    # Постоянное разрешение - устанавливаем can_post = True
                    user.can_post = True
                    user.can_post_until = None
                    user.allowed_posts = 0
                    msg = f"✅ Пользователю {username_or_id} предоставлено постоянное разрешение на публикацию."
                    logger.info(
                        f"Админ {message.from_user.id} выдал постоянное разрешение пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )
                elif is_month:
                    # Месячная подписка - сбрасываем can_post
                    user.can_post = False
                    user.can_post_until = datetime.now() + timedelta(days=30)
                    user.allowed_posts = 0
                    msg = f"✅ Пользователю {username_or_id} предоставлен месяц публикаций до {user.can_post_until.strftime('%d.%m.%Y %H:%M')}"
                    logger.info(
                        f"Админ {message.from_user.id} выдал месячную подписку пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )
                else:
                    # Разовая публикация - сбрасываем can_post
                    user.can_post = False
                    user.can_post_until = None
                    user.allowed_posts += 1
                    msg = f"✅ Пользователю {username_or_id} добавлена 1 публикация. Всего: {user.allowed_posts}"
                    logger.info(
                        f"Админ {message.from_user.id} добавил публикацию пользователю {user.telegram_id} "
                        f"(было: can_post={old_can_post}, can_post_until={old_can_post_until}, allowed_posts={old_allowed_posts})"
                    )

                session.commit()
                
                # Проверяем, что изменения сохранились
                session.refresh(user)
                if is_permanent and not user.can_post:
                    raise Exception("Не удалось установить постоянное разрешение")
                
                await message.answer(msg)
                
                # Отправляем уведомление пользователю
                try:
                    await message.bot.send_message(
                        user.telegram_id,
                        f"🎉 {msg}\n\n"
                        "Теперь вы можете опубликовать вакансию через меню бота."
                    )
                except Exception as notify_e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user.telegram_id}: {notify_e}")
                
            except Exception as e:
                logger.error(f"Ошибка при обновлении прав пользователя {user.telegram_id}: {e}")
                session.rollback()
                await message.answer(
                    "❌ Произошла ошибка при обновлении прав. Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
                )
                return

    except Exception as e:
        logger.error(f"Ошибка в allow_posting_handler: {e}")
        await message.answer(
            "❌ Произошла ошибка при выполнении команды. Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )


@router.message(F.chat.type.in_([ChatType.GROUP, ChatType.SUPERGROUP]))
async def handle_group_messages(message: Message):
    """Обработка сообщений в группах"""
    try:
        # Отслеживание новых участников для системы приглашений
        if message.new_chat_members:
            for new_member in message.new_chat_members:
                if not new_member.is_bot and message.from_user:
                    try:
                        with SessionLocal() as session:
                            # Получаем пользователя-приглашающего
                            inviter = session.query(User).filter_by(telegram_id=message.from_user.id).first()
                            if not inviter:
                                continue
                            
                            # Увеличиваем счетчик приглашений
                            inviter.invites += 1
                            
                            # Если достигли 5 приглашений, даем публикацию
                            if inviter.invites >= 5 and inviter.invites % 5 == 0:
                                inviter.allowed_posts += 1
                            
                            session.commit()
                            logger.info(f"Пользователь {message.from_user.id} пригласил {new_member.id}")
                    except Exception as e:
                        logger.error(f"Ошибка при обновлении счетчика приглашений: {e}")
            return

        # Обработка выхода пользователей
        if message.left_chat_member:
            try:
                with SessionLocal() as session:
                    # Получаем пользователя, который пригласил ушедшего участника
                    # (это может быть любой пользователь, который приглашал участников)
                    inviter = session.query(User).filter(
                        User.invites > 0  # Берем пользователя, у которого есть приглашения
                    ).order_by(User.invites.desc()).first()
                    
                    if inviter:
                        # Уменьшаем счетчик приглашений
                        if inviter.invites > 0:
                            inviter.invites -= 1
                            
                            # Если количество приглашений стало меньше 5,
                            # отменяем бонусную публикацию
                            if inviter.invites < 5 and inviter.allowed_posts > 0:
                                inviter.allowed_posts -= 1
                            
                            session.commit()
                            logger.info(f"Пользователь {message.left_chat_member.id} покинул группу")
            except Exception as e:
                logger.error(f"Ошибка при обработке выхода пользователя: {e}")
            return

    except Exception as e:
        logger.error(f"Ошибка в handle_group_messages: {e}")


@router.message(Command("stats"))
async def stats_handler(message: Message):
    """Статистика для админов"""
    if message.from_user.id not in ADMINS:
        return

    try:
        with SessionLocal() as session:
            total_users = session.query(func.count(User.id)).scalar()
            total_jobs = session.query(func.count(Job.id)).scalar()
            active_subscriptions = session.query(func.count(User.id)).filter(
                User.can_post_until > datetime.now()
            ).scalar()
            permanent_users = session.query(func.count(User.id)).filter(
                User.can_post == True
            ).scalar()

        await message.answer(
            f"📊 <b>Статистика бота:</b>\n\n"
            f"👥 Всего пользователей: {total_users}\n"
            f"📄 Всего вакансий: {total_jobs}\n"
            f"💳 Активных подписок: {active_subscriptions}\n"
            f"🔐 Постоянных разрешений: {permanent_users}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка в stats_handler: {e}")
        await message.answer("❌ Ошибка при получении статистики.")


@router.message(Command("user_info"))
async def user_info_handler(message: Message):
    """Информация о пользователе для админов"""
    if message.from_user.id not in ADMINS:
        return

    try:
        parts = message.text.strip().split()
        if len(parts) < 2:
            await message.answer("Используй: /user_info @username или /user_info user_id")
            return

        identifier = parts[1]

        with SessionLocal() as session:
            user = None

            if identifier.startswith("@"):
                user = session.query(User).filter_by(username=identifier[1:]).first()
            elif identifier.isdigit():
                user = session.query(User).filter_by(telegram_id=int(identifier)).first()

            if not user:
                await message.answer("❌ Пользователь не найден.")
                return

            job_count = session.query(func.count(Job.id)).filter_by(user_id=user.telegram_id).scalar()

            info_text = (
                f"👤 <b>Информация о пользователе:</b>\n\n"
                f"🆔 ID: {user.telegram_id}\n"
                f"📝 Username: @{user.username or 'не указан'}\n"
                f"📅 Регистрация: {user.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📄 Всего вакансий: {job_count}\n"
                f"👥 Приглашений: {user.invites}\n"
                f"🎫 Разовых публикаций: {user.allowed_posts}\n"
                f"🔐 Постоянное разрешение: {'Да' if user.can_post else 'Нет'}\n"
            )

            if user.can_post_until:
                info_text += f"⏰ Подписка до: {user.can_post_until.strftime('%d.%m.%Y %H:%M')}\n"

            await message.answer(info_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Ошибка в user_info_handler: {e}")
        await message.answer("❌ Ошибка при получении информации о пользователе.")


@router.message(Command("post_all"))
async def post_all_handler(message: Message, state: FSMContext):
    """Команда для админов - автоматическая публикация всех сообщений"""
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У вас нет прав для этой команды.")
        return

    try:
        # Сохраняем состояние, что админ находится в режиме автоматической публикации
        await state.update_data(auto_posting=True)
        
        await message.answer(
            "✅ Режим автоматической публикации включен.\n\n"
            "📝 Отправляйте сообщения в формате вакансии, и они будут автоматически публиковаться.\n"
            "❌ Для отключения отправьте /stop_posting\n\n"
            "⚠️ Сообщения должны строго соответствовать формату:\n"
            "📍 Адрес: \n"
            "📝 Задача: \n"
            "💵 Оплата: \n"
            "☎️ Контакт: \n"
            "📌 Примечание: (необязательно)"
        )
    except Exception as e:
        logger.error(f"Ошибка при включении режима автоматической публикации: {e}")
        await message.answer("❌ Произошла ошибка при включении режима автоматической публикации.")


@router.message(Command("stop_posting"))
async def stop_posting_handler(message: Message, state: FSMContext):
    """Отключение режима автоматической публикации"""
    if message.from_user.id not in ADMINS:
        return

    try:
        await state.clear()
        await message.answer("✅ Режим автоматической публикации отключен.")
    except Exception as e:
        logger.error(f"Ошибка при отключении режима автоматической публикации: {e}")
        await message.answer("❌ Произошла ошибка при отключении режима автоматической публикации.")


@router.message(F.chat.type == ChatType.PRIVATE)
async def handle_private_messages(message: Message, state: FSMContext):
    """Обработчик всех сообщений в приватном чате"""
    try:
        # Проверяем, включен ли режим автоматической публикации
        state_data = await state.get_data()
        if state_data.get('auto_posting') and message.from_user.id in ADMINS:
            # Проверяем, соответствует ли сообщение формату вакансии
            lines = message.text.strip().splitlines()
            data = {}
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                for key, pat in TEMPLATE.items():
                    m = re.match(pat, line)
                    if m:
                        data[key] = m.group(1).strip()
                        break

            # Проверяем наличие всех обязательных полей
            required_fields = ["address", "title", "payment", "contact"]
            missing_fields = [field for field in required_fields if field not in data or not data[field]]

            if not missing_fields and PHONE_RE.match(data['contact']):
                # Если все поля на месте и телефон валидный, публикуем вакансию
                try:
                    # Публикация в канал
                    vacancy_text = (
                        f"<b>Вакансия {data['title']}</b>\n\n"
                        f"📍 <b>Адрес:</b> {data['address']}\n"
                        f"💵 <b>Оплата:</b> {data['payment']}\n"
                        f"☎️ <b>Контакт:</b> {data['contact']}"
                    )

                    if data.get('extra'):
                        vacancy_text += f"\n📌 <b>Примечание:</b> {data['extra']}"

                    posted = await message.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=vacancy_text,
                        parse_mode=ParseMode.HTML
                    )

                    # Кнопка отклика (временно без job_id, обновим после сохранения)
                    response_button = create_response_buttons(
                        data['contact'],
                        message.from_user.id,
                        message.from_user.username
                    )

                    await message.bot.edit_message_reply_markup(
                        chat_id=CHANNEL_ID,
                        message_id=posted.message_id,
                        reply_markup=response_button
                    )

                    # Сохраняем в базу
                    saved = await asyncio.to_thread(
                        save_job_db,
                        message.from_user.id,
                        posted.message_id,
                        data
                    )

                    if saved:
                        # Получаем ID сохраненной вакансии для кнопки отклика
                        job_id = None
                        with SessionLocal() as session:
                            saved_job = session.query(Job).filter_by(user_id=message.from_user.id, message_id=posted.message_id).first()
                            job_id = saved_job.id if saved_job else None
                        
                        # Обновляем кнопки с job_id
                        response_button = create_response_buttons(job_id=job_id, job=saved_job)
                        
                        if response_button:
                            await message.bot.edit_message_reply_markup(
                                chat_id=CHANNEL_ID,
                                message_id=posted.message_id,
                                reply_markup=response_button
                            )
                        
                        await message.answer(
                            f"✅ Вакансия опубликована!\n"
                            f"📄 Ссылка: {CHANNEL_URL}/{posted.message_id}"
                        )
                    else:
                        await message.answer("❌ Ошибка при сохранении вакансии в базу данных.")
                        # Удаляем сообщение из канала
                        try:
                            await message.bot.delete_message(chat_id=CHANNEL_ID, message_id=posted.message_id)
                        except Exception as delete_e:
                            logger.error(f"Не удалось удалить сообщение из канала: {delete_e}")

                except Exception as e:
                    logger.error(f"Ошибка при публикации вакансии в режиме auto_posting: {e}")
                    await message.answer("❌ Ошибка при публикации вакансии.")
            else:
                # Если формат не соответствует, отправляем сообщение об ошибке
                if missing_fields:
                    field_names = {
                        "address": "📍 Адрес",
                        "title": "📝 Задача",
                        "payment": "💵 Оплата",
                        "contact": "☎️ Контакт"
                    }
                    missing_names = [field_names[f] for f in missing_fields]
                    await message.answer(
                        f"❌ Не заполнены поля: {', '.join(missing_names)}\n"
                        "Сообщение не будет опубликовано."
                    )
                elif not PHONE_RE.match(data.get('contact', '')):
                    await message.answer(
                        "❌ Неверный формат телефона. Используйте формат: +996XXXXXXXXX\n"
                        "Сообщение не будет опубликовано."
                    )
        else:
            # Если не в режиме auto_posting, обрабатываем как обычное сообщение
            await unknown_message(message)

    except Exception as e:
        logger.error(f"Ошибка в handle_private_messages: {e}")
        await message.answer("❌ Произошла ошибка при обработке сообщения.")


@router.callback_query(F.data.startswith("confirm_attendance_"))
async def confirm_attendance(callback: CallbackQuery, bot: Bot):
    """Подтверждение участия в работе (за 4 часа или 45 минут)"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        worker_id = int(parts[3]) if len(parts) > 4 else callback.from_user.id
        confirm = parts[-1] == "yes"
        
        with SessionLocal() as session:
            from database.models import JobResponse, ResponseStatus, JobStatus
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=worker_id, status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не подтверждены на эту вакансию", show_alert=True)
                return
            
            if confirm:
                await callback.answer("✅ Вы подтвердили участие", show_alert=True)
                await callback.message.edit_text(
                    callback.message.text + "\n\n✅ <b>Участие подтверждено</b>",
                    parse_mode=ParseMode.HTML
                )
            else:
                # Отказ от работы
                await callback.answer("❌ Вы отказались от работы", show_alert=True)
                
                # Увеличиваем счетчик отказов
                user = session.query(User).filter_by(telegram_id=worker_id).first()
                if user:
                    user.refusals_count += 1
                    
                    # Проверяем черный список
                    if user.refusals_count >= 3 and not user.is_blacklisted:
                        user.is_blacklisted = True
                        user.blacklist_until = datetime.now() + timedelta(days=30)
                        
                        try:
                            await bot.send_message(
                                chat_id=worker_id,
                                text=(
                                    f"🚫 <b>Вы заблокированы на 30 дней</b>\n\n"
                                    f"Причина: 3 отказа после подтверждения выхода на работу.\n\n"
                                    f"Разблокировка: {user.blacklist_until.strftime('%d.%m.%Y')}"
                                ),
                                parse_mode=ParseMode.HTML
                            )
                        except Exception as e:
                            logger.error(f"Не удалось уведомить о блокировке: {e}")
                
                # Обновляем статус отклика
                response.status = ResponseStatus.REFUSED
                job.people_confirmed = max(0, job.people_confirmed - 1)
                
                # Если есть резервный кандидат, отправляем ему предложение
                reserve_response = session.query(JobResponse).filter_by(
                    job_id=job_id, is_reserve=True, status=ResponseStatus.ACCEPTED
                ).order_by(JobResponse.created_at).first()
                
                if reserve_response:
                    # Меняем резервного на основного
                    reserve_response.is_reserve = False
                    reserve_response.is_selected = True
                    job.people_confirmed += 1
                    
                    try:
                        confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✅ Подтвердить выход", callback_data=f"confirm_work_{job_id}")],
                            [InlineKeyboardButton(text="❌ Отказаться", callback_data=f"refuse_work_{job_id}")]
                        ])
                        
                        await bot.send_message(
                            chat_id=reserve_response.user_id,
                            text=(
                                f"🎉 <b>Вас выбрали на работу!</b>\n\n"
                                f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                                f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                                f"⏰ <b>Время:</b> {job.all_info.get('schedule', 'не указано')}\n"
                                f"💰 <b>Оплата:</b> {job.all_info.get('payment', 'не указана')}\n\n"
                                f"⚠️ Подтвердите свой выход на работу и укажите время:"
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=confirm_keyboard
                        )
                    except Exception as e:
                        logger.error(f"Не удалось уведомить резервного кандидата: {e}")
                
                # Уведомляем работодателя и админа
                user = session.query(User).filter_by(telegram_id=worker_id).first()
                notification_text = (
                    f"⚠️ <b>Работник отказался от выхода на работу</b>\n\n"
                    f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                    f"👤 <b>Работник:</b> {user.name if user else 'Не указано'}\n"
                    f"⏰ <b>Начало через 4 часа</b>\n\n"
                    f"Сделать вакансию активной?"
                )
                
                reactivate_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да", callback_data=f"reactivate_job_{job_id}")],
                    [InlineKeyboardButton(text="❌ Нет", callback_data=f"dont_reactivate_{job_id}")]
                ])
                
                try:
                    await bot.send_message(
                        chat_id=job.user_id,
                        text=notification_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reactivate_keyboard
                    )
                    
                    for admin_id in ADMINS:
                        try:
                            await bot.send_message(
                                chat_id=admin_id,
                                text=notification_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reactivate_keyboard
                            )
                        except Exception as admin_e:
                            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {admin_e}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке уведомления об отказе: {e}")
                
                session.commit()
    
    except Exception as e:
        logger.error(f"Ошибка при подтверждении участия: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("reactivate_job_"))
async def reactivate_job(callback: CallbackQuery, bot: Bot):
    """Активация вакансии после отказа кандидата"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            from database.models import JobStatus
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Проверяем, сколько еще нужно кандидатов
            if job.people_confirmed < job.people_needed:
                job.status = JobStatus.IN_PROGRESS
            else:
                job.status = JobStatus.OPEN
            
            session.commit()
            
            # Восстанавливаем кнопку отклика в канале, если вакансия открыта
            if job.status == JobStatus.OPEN or job.status == JobStatus.IN_PROGRESS:
                try:
                    response_button = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text="📝 Откликнуться",
                            callback_data=f"respond_job_{job_id}"
                        )]
                    ])
                    await bot.edit_message_reply_markup(
                        chat_id=CHANNEL_ID,
                        message_id=job.message_id,
                        reply_markup=response_button
                    )
                except Exception as e:
                    logger.error(f"Не удалось восстановить кнопку в канале: {e}")
            
            await callback.answer("✅ Вакансия активирована", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ <b>Вакансия активирована</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при активации вакансии: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("dont_reactivate_"))
async def dont_reactivate_job(callback: CallbackQuery):
    """Не активировать вакансию после отказа"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            from database.models import JobStatus
            job = session.query(Job).filter_by(id=job_id).first()
            if job:
                job.status = JobStatus.CANCELLED
                session.commit()
        
        await callback.answer("✅ Вакансия отменена", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ <b>Вакансия отменена</b>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка при отмене вакансии: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("cancel_job_"))
async def cancel_job(callback: CallbackQuery, bot: Bot):
    """Отмена вакансии"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            from database.models import JobStatus
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            job.status = JobStatus.CANCELLED
            session.commit()
            
            # Удаляем кнопку отклика в канале
            try:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID,
                    message_id=job.message_id,
                    reply_markup=None
                )
            except Exception as e:
                logger.error(f"Не удалось обновить кнопку в канале: {e}")
            
            await callback.answer("✅ Вакансия отменена", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ <b>Вакансия отменена</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при отмене вакансии: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("rate_worker_"))
async def rate_worker_start(callback: CallbackQuery, state: FSMContext):
    """Начало оценки работника"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        worker_id = int(parts[3]) if len(parts) > 3 else None
        
        with SessionLocal() as session:
            from database.models import ResponseStatus
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Если worker_id не указан, показываем список работников для оценки
            if not worker_id:
                confirmed_responses = session.query(JobResponse).filter_by(
                    job_id=job_id, status=ResponseStatus.CONFIRMED
                ).all()
                
                if not confirmed_responses:
                    await callback.answer("❌ Нет подтвержденных работников", show_alert=True)
                    return
                
                # Проверяем, кого еще не оценили
                rated_workers = session.query(Rating.rated_user_id).filter_by(
                    job_id=job_id, rater_user_id=callback.from_user.id
                ).all()
                rated_ids = [r[0] for r in rated_workers]
                
                buttons = []
                for response in confirmed_responses:
                    if response.user_id not in rated_ids:
                        user = session.query(User).filter_by(telegram_id=response.user_id).first()
                        if user:
                            buttons.append([InlineKeyboardButton(
                                text=f"👤 {user.name or 'Работник'}",
                                callback_data=f"rate_worker_{job_id}_{response.user_id}"
                            )])
                
                if not buttons:
                    await callback.answer("✅ Все работники уже оценены!", show_alert=True)
                    return
                
                await callback.answer()
                await callback.message.answer(
                    "👥 Выберите работника для оценки:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
                )
                return
            
            # Показываем кнопки оценки
            await callback.answer()
            rating_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⭐ 1", callback_data=f"set_rating_{job_id}_{worker_id}_1"),
                 InlineKeyboardButton(text="⭐⭐ 2", callback_data=f"set_rating_{job_id}_{worker_id}_2"),
                 InlineKeyboardButton(text="⭐⭐⭐ 3", callback_data=f"set_rating_{job_id}_{worker_id}_3")],
                [InlineKeyboardButton(text="⭐⭐⭐⭐ 4", callback_data=f"set_rating_{job_id}_{worker_id}_4"),
                 InlineKeyboardButton(text="⭐⭐⭐⭐⭐ 5", callback_data=f"set_rating_{job_id}_{worker_id}_5")]
            ])
            
            user = session.query(User).filter_by(telegram_id=worker_id).first()
            worker_name = user.name if user else "Работник"
            
            await callback.message.answer(
                f"⭐ Оцените работника <b>{worker_name}</b> по 5-балльной шкале:",
                parse_mode=ParseMode.HTML,
                reply_markup=rating_keyboard
            )
    
    except Exception as e:
        logger.error(f"Ошибка при начале оценки: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("set_rating_"))
async def set_rating(callback: CallbackQuery, bot: Bot):
    """Установка оценки работника"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        worker_id = int(parts[3])  # ID работника
        rating_value = int(parts[4])
        
        with SessionLocal() as session:
            from database.models import Rating, JobStatus, ResponseStatus
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Проверяем, что работник был подтвержден на эту вакансию
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=worker_id, status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Работник не найден", show_alert=True)
                return
            
            # Проверяем, не оценивали ли уже этого работника
            existing_rating = session.query(Rating).filter_by(
                job_id=job_id, rated_user_id=worker_id, rater_user_id=callback.from_user.id
            ).first()
            
            if existing_rating:
                await callback.answer("⚠️ Вы уже оценили этого работника", show_alert=True)
                return
            
            # Сохраняем оценку
            rating = Rating(
                job_id=job_id,
                rated_user_id=worker_id,
                rater_user_id=callback.from_user.id,
                rating=rating_value
            )
            session.add(rating)
            
            # Обновляем рейтинг пользователя
            rated_user = session.query(User).filter_by(telegram_id=worker_id).first()
            if rated_user:
                # Получаем все оценки пользователя
                all_ratings = session.query(Rating).filter_by(rated_user_id=worker_id).all()
                if all_ratings:
                    # Средняя оценка
                    avg_rating = sum(r.rating for r in all_ratings) / len(all_ratings)
                    # Учитываем отказы: каждый отказ снижает рейтинг на 0.3
                    final_rating = max(1.0, avg_rating - (rated_user.refusals_count * 0.3))
                    
                    rated_user.average_rating = final_rating
                    rated_user.completed_jobs += 1
                else:
                    rated_user.average_rating = rating_value
                    rated_user.completed_jobs = 1
            
            # Проверяем, все ли работники оценены
            confirmed_responses = session.query(JobResponse).filter_by(
                job_id=job_id, status=ResponseStatus.CONFIRMED
            ).all()
            
            rated_count = session.query(Rating).filter_by(
                job_id=job_id, rater_user_id=callback.from_user.id
            ).count()
            
            # Если все работники оценены, меняем статус вакансии
            if rated_count >= len(confirmed_responses):
                job.status = JobStatus.COMPLETED
            
            session.commit()
            
            await callback.answer(f"✅ Оценка {rating_value} сохранена!", show_alert=True)
            
            # Формируем текст рейтинга
            rating_text = f"⭐ {rated_user.average_rating:.1f} | {rated_user.completed_jobs} работ | {rated_user.refusals_count} отказ"
            if rated_user.refusals_count != 1:
                rating_text = rating_text.replace("отказ", "отказов")
            
            await callback.message.edit_text(
                f"✅ <b>Оценка сохранена</b>\n\n"
                f"Вы оценили работника на {rating_value} из 5",
                parse_mode=ParseMode.HTML
            )
            
            # Уведомляем работника
            try:
                await bot.send_message(
                    chat_id=worker_id,
                    text=(
                        f"🎉 <b>Работа выполнена!</b>\n\n"
                        f"Вас оценили на ⭐ {rating_value}/5\n\n"
                        f"Ваш новый рейтинг: {rating_text}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить работника об оценке: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка при установке оценки: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


async def send_work_reminders(bot: Bot):
    """Функция для отправки напоминаний о работе (вызывается по расписанию)"""
    try:
        with SessionLocal() as session:
            from database.models import JobStatus, ResponseStatus, User
            now = datetime.now()
            
            # Находим вакансии, которые начинаются через 4 часа
            four_hours_later = now + timedelta(hours=4)
            four_hours_jobs = session.query(Job).filter(
                Job.status == JobStatus.CONFIRMED,
                Job.work_start_time >= now,
                Job.work_start_time <= four_hours_later
            ).all()
            
            for job in four_hours_jobs:
                # Получаем всех подтвержденных работников
                confirmed_responses = session.query(JobResponse).filter_by(
                    job_id=job.id, status=ResponseStatus.CONFIRMED
                ).all()
                
                for response in confirmed_responses:
                    # Дублируем вакансию
                    vacancy_text = (
                        f"<b>Напоминание о вакансии</b>\n\n"
                        f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                        f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                        f"💵 <b>Оплата:</b> {job.all_info.get('payment', 'не указана')}\n"
                        f"⏰ <b>График:</b> {job.all_info.get('schedule', 'не указан')}\n"
                        f"📅 <b>Начало работы:</b> {job.work_start_time.strftime('%d.%m.%Y %H:%M')}"
                    )
                    
                    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Да, приду", callback_data=f"confirm_attendance_{job.id}_{response.user_id}_yes")],
                        [InlineKeyboardButton(text="❌ Нет, не смогу", callback_data=f"confirm_attendance_{job.id}_{response.user_id}_no")]
                    ])
                    
                    try:
                        await bot.send_message(
                            chat_id=response.user_id,
                            text=(
                                f"⏰ <b>Напоминание о работе через 4 часа</b>\n\n"
                                f"{vacancy_text}\n\n"
                                f"Вы сможете прийти?"
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=confirm_keyboard
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить напоминание за 4 часа для вакансии {job.id}: {e}")
            
            # Находим вакансии, которые начинаются через 45 минут
            forty_five_min_later = now + timedelta(minutes=45)
            forty_five_min_jobs = session.query(Job).filter(
                Job.status == JobStatus.CONFIRMED,
                Job.work_start_time >= now,
                Job.work_start_time <= forty_five_min_later
            ).all()
            
            for job in forty_five_min_jobs:
                confirmed_responses = session.query(JobResponse).filter_by(
                    job_id=job.id, status=ResponseStatus.CONFIRMED
                ).all()
                
                for response in confirmed_responses:
                    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Да, иду на работу", callback_data=f"confirm_attendance_{job.id}_{response.user_id}_yes")],
                        [InlineKeyboardButton(text="❌ Не смогу прийти", callback_data=f"confirm_attendance_{job.id}_{response.user_id}_no")]
                    ])
                    
                    try:
                        await bot.send_message(
                            chat_id=response.user_id,
                            text=(
                                f"🔔 <b>Работа начинается через 45 минут!</b>\n\n"
                                f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                                f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                                f"⏰ <b>Начало:</b> {job.work_start_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                                f"Подтверждаете выход?"
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=confirm_keyboard
                        )
                    except Exception as e:
                        logger.error(f"Не удалось отправить напоминание за 45 минут для вакансии {job.id}: {e}")
            
            # Находим завершенные вакансии для оценки
            completed_jobs = session.query(Job).filter(
                Job.status == JobStatus.CONFIRMED,
                Job.work_end_time <= now
            ).all()
            
            for job in completed_jobs:
                # Получаем всех подтвержденных работников
                confirmed_responses = session.query(JobResponse).filter_by(
                    job_id=job.id, status=ResponseStatus.CONFIRMED
                ).all()
                
                # Проверяем, кого еще не оценили
                rated_workers = session.query(Rating.rated_user_id).filter_by(
                    job_id=job.id, rater_user_id=job.user_id
                ).all()
                rated_ids = [r[0] for r in rated_workers]
                
                # Отправляем запрос на оценку для каждого неоцененного работника
                for response in confirmed_responses:
                    if response.user_id not in rated_ids:
                        try:
                            await bot.send_message(
                                chat_id=job.user_id,
                                text=(
                                    f"✅ <b>Время работы завершено</b>\n\n"
                                    f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                                    f"👤 <b>Работник:</b> {response.user.name if response.user else 'Не указано'}\n\n"
                                    f"Оцените работу исполнителя по 5-балльной шкале:"
                                ),
                                parse_mode=ParseMode.HTML,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(
                                        text="Оценить",
                                        callback_data=f"rate_worker_{job.id}_{response.user_id}"
                                    )]
                                ])
                            )
                        except Exception as e:
                            logger.error(f"Не удалось отправить запрос на оценку для вакансии {job.id}: {e}")
            
            # Авто-отмена вакансий за 2 часа до начала, если никто не подтвердил
            two_hours_later = now + timedelta(hours=2)
            unconfirmed_jobs = session.query(Job).filter(
                Job.status == JobStatus.CANDIDATES_SELECTED,
                Job.work_start_time >= now,
                Job.work_start_time <= two_hours_later,
                Job.people_confirmed == 0
            ).all()
            
            for job in unconfirmed_jobs:
                try:
                    reactivate_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Опубликовать снова", callback_data=f"reactivate_job_{job.id}")],
                        [InlineKeyboardButton(text="❌ Отменить вакансию", callback_data=f"cancel_job_{job.id}")]
                    ])
                    
                    await bot.send_message(
                        chat_id=job.user_id,
                        text=(
                            f"⚠️ <b>Внимание! Вакансия не подтверждена</b>\n\n"
                            f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                            f"⏰ <b>Начало через 2 часа</b>\n\n"
                            f"Ни один кандидат не подтвердил выход.\n\n"
                            f"Вакансия будет автоматически отменена."
                        ),
                        parse_mode=ParseMode.HTML,
                        reply_markup=reactivate_keyboard
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление об авто-отмене для вакансии {job.id}: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний: {e}")


async def unknown_message(message: Message):
    """Обработчик неизвестных сообщений"""
    await message.answer(
        "Не понимаю вас \n"
        "Используйте кнопки меню для навигации:",
        reply_markup=kb_menu
    )


async def on_shutdown(bot: Bot):
    """Корректное завершение работы бота"""
    logger.info("Shutting down...")
    await bot.session.close()

def handle_exit(signum, frame):
    """Обработчик сигналов завершения"""
    logger.info(f"Received exit signal {signum}")
    sys.exit(0)

# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)