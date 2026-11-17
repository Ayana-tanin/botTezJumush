"""
Обработчики для работы с резюме соискателей
"""
import re
import logging
from sqlalchemy.exc import OperationalError
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext
from datetime import datetime

from database.db_connection import SessionLocal
from database.models import User, Resume
from resume_fsm import ResumeForm, EditResumeForm
from handlers.start import kb_menu, kb_cancel
from config import CHANNEL_ID, RESUME_THREAD_ID

logger = logging.getLogger(__name__)
router = Router()

# Формат телефона: 0555123456 (0 и 9 цифр)
PHONE_PATTERN = re.compile(r"^0\d{9}$")


async def check_cancel(msg: Message, state: FSMContext) -> bool:
    """
    Проверяет, была ли нажата кнопка отмены. 
    Возвращает True, если была отменена (и уже обработана).
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


def get_user_last_resume(user_id: int):
    """Получить последнюю анкету пользователя"""
    with SessionLocal() as session:
        return session.query(Resume).filter_by(user_id=user_id).order_by(Resume.created_at.desc()).first()


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


@router.message(F.text.in_({"📝 Выложить/Редактировать анкету", "📝 Моё резюме"}))
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
            # Резюме нет — начинаем создание
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


def build_resume_text(user: User) -> str:
    """Формирует текст анкеты для публикации (без контактов)"""
    rating_text = f"⭐ {user.average_rating:.1f} | {user.completed_jobs} работ | {user.refusals_count} отказ"
    if user.refusals_count != 1:
        rating_text = rating_text.replace("отказ", "отказов")
    return (
        f"👤 <b>РЕЗЮМЕ СОИСКАТЕЛЯ</b>\n\n"
        f"{rating_text}\n"
        f"Имя: {user.name or 'не указано'}\n"
        f"Возраст: {user.age or 'не указан'}\n"
        f"Пол: {user.gender or 'не указан'}\n"
        f"Опыт работы: {user.experience or 'не указан'}\n"
        f"О себе: {user.about or 'не указано'}"
    )


async def publish_resume(bot: Bot, user: User, resume: Resume) -> int | None:
    """Публикует или обновляет анкету в RESUME_THREAD_ID. Возвращает message_id."""
    text = build_resume_text(user)
    contact_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📞 Связаться", callback_data=f"contact_resume_{user.telegram_id}")]
    ])
    try:
        if resume.message_id:
            # Обновляем существующее сообщение
            await bot.edit_message_text(
                chat_id=CHANNEL_ID,
                message_id=resume.message_id,
                message_thread_id=RESUME_THREAD_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=contact_kb
            )
            return resume.message_id
        else:
            posted = await bot.send_message(
                chat_id=CHANNEL_ID,
                message_thread_id=RESUME_THREAD_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=contact_kb
            )
            return posted.message_id
    except Exception as e:
        logger.error(f"Ошибка при публикации анкеты: {e}")
        return None


async def prepare_resume_impl(msg: Message, state: FSMContext):
    """Общая логика подготовки анкеты"""
    await msg.answer(
        "👋 Добро пожаловать!\n\n"
        "Для отклика на вакансии необходимо заполнить резюме.\n"
        "Это важно, смотря на ваше резюме, Наниматель будет выбирать вас\n"
        "Ответьте на 6 вопросов (имя, возраст, пол, опыт, о себе, телефон):\n\n"
        "1️⃣ Как вас зовут?",
        reply_markup=kb_cancel
    )
    await state.set_state(ResumeForm.name)


# ==================== ОБРАБОТЧИКИ СОЗДАНИЯ АНКЕТЫ ====================

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
                user.name = data.get("name", "")
                user.age = data.get("age")
                user.gender = data.get("gender", "")
                user.experience = data.get("experience", "")
                user.about = about
                user.phone = phone
            
            session.commit()
            session.refresh(user)
            
            # Получаем или создаём запись Resume
            resume = session.query(Resume).filter_by(user_id=uid).order_by(Resume.created_at.desc()).first()
            if not resume:
                resume = Resume(
                    user_id=uid,
                    name=user.name,
                    age=user.age,
                    gender=user.gender,
                    experience=user.experience,
                    about=user.about,
                    phone=phone
                )
                session.add(resume)
                session.commit()
                session.refresh(resume)
            else:
                resume.name = user.name
                resume.age = user.age
                resume.gender = user.gender
                resume.experience = user.experience
                resume.about = user.about
                resume.phone = phone
                session.commit()
                session.refresh(resume)
            
            # Публикуем анкету в RESUME_THREAD_ID (без контактов)
            message_id = await publish_resume(bot, user, resume)
            if message_id:
                resume.message_id = message_id
                session.commit()
            
            await msg.answer(
                "✅ Резюме успешно сохранена и опубликована!\n\n"
                "Теперь вы можете откликаться на вакансии.",
                reply_markup=kb_menu
            )
    
    except Exception as e:
        logger.error(f"Ошибка при сохранении анкеты: {e}")
        await msg.answer(
            "❌ Произошла ошибка при сохранении резюме. Попробуйте позже.",
            reply_markup=kb_menu
        )
    
    await state.clear()


# ==================== ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ АНКЕТЫ ====================

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


@router.callback_query(F.data.startswith("edit_resume_field_name_"))
async def edit_resume_field_name(callback: CallbackQuery, state: FSMContext):
    """Редактирование имени в анкете"""
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
            
            setattr(user, field_name, new_value)
            session.commit()
            session.refresh(user)
            
            # Обновляем публикацию анкеты.
            # На старой схеме БД может отсутствовать resumes.message_id.
            try:
                resume = session.query(Resume).filter_by(user_id=user_id).order_by(Resume.created_at.desc()).first()
                if resume:
                    setattr(resume, field_name, new_value)
                    session.commit()
                    session.refresh(resume)
                    bot = msg.bot
                    message_id = await publish_resume(bot, user, resume)
                    if message_id and not resume.message_id:
                        resume.message_id = message_id
                        session.commit()
            except OperationalError as db_e:
                if "no such column: resumes.message_id" in str(db_e):
                    logger.warning(
                        "Пропущено обновление публикации резюме: в БД отсутствует колонка resumes.message_id"
                    )
                    session.rollback()
                else:
                    raise
            
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


# ==================== ОБРАБОТЧИК КНОПКИ "СВЯЗАТЬСЯ" ====================

@router.callback_query(F.data.startswith("contact_resume_"))
async def contact_resume_callback(callback: CallbackQuery, bot: Bot):
    """Обработчик кнопки 'Связаться' — отправляет контакты владельца анкеты нажавшему"""
    owner_telegram_id = int(callback.data.split("_")[2])
    requester_id = callback.from_user.id

    # Нельзя связаться с самим собой
    if requester_id == owner_telegram_id:
        await callback.answer("Это ваше собственное резюме.", show_alert=True)
        return

    with SessionLocal() as session:
        owner = session.query(User).filter_by(telegram_id=owner_telegram_id).first()
        requester = session.query(User).filter_by(telegram_id=requester_id).first()

        if not owner:
            await callback.answer("❌ Пользователь не найден.", show_alert=True)
            return

        owner_name = owner.name or "Соискатель"
        owner_phone = owner.phone or "не указан"
        owner_username = f"@{owner.username}" if owner.username else "нет"

        # Отправляем контакты владельцу анкеты (кто хочет связаться)
        requester_name = requester.name if requester else callback.from_user.full_name
        requester_username = f"@{callback.from_user.username}" if callback.from_user.username else "нет"

        try:
            # Уведомляем владельца анкеты
            await bot.send_message(
                chat_id=owner_telegram_id,
                text=(
                    f"📩 <b>Кто-то хочет с вами связаться!</b>\n\n"
                    f"Имя: {requester_name or 'не указано'}\n"
                    f"Username: {requester_username}\n"
                    f"Telegram ID: <code>{requester_id}</code>"
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить владельца анкеты {owner_telegram_id}: {e}")

        # Отправляем контакты владельца тому, кто нажал
        try:
            await bot.send_message(
                chat_id=requester_id,
                text=(
                    f"📞 <b>Контакты соискателя</b>\n\n"
                    f"Имя: {owner_name}\n"
                    f"Телефон: <code>{owner_phone}</code>\n"
                    f"Username: {owner_username}"
                ),
                parse_mode=ParseMode.HTML
            )
            await callback.answer("✅ Контакты отправлены вам в личные сообщения!", show_alert=True)
        except Exception as e:
            logger.error(f"Не удалось отправить контакты пользователю {requester_id}: {e}")
            await callback.answer(
                "❌ Не удалось отправить контакты. Сначала напишите боту в личные сообщения.",
                show_alert=True
            )
