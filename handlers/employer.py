"""
Обработчики для работодателей - создание и управление вакансиями
"""
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext

from database.db_connection import SessionLocal, insert_user
from database.models import Job, JobType, JobStatus, User
from vacancy_fsm import VacancyForm, EditVacancyForm
from config import CHANNEL_ID, CHANNEL_URL, ADMINS, REGULAR_THREAD_ID, PART_JOB_THREAD_ID
from handlers.start import kb_menu, kb_cancel

logger = logging.getLogger(__name__)
router = Router()


def get_vacancy_thread_id(job_type: JobType):
    """Возвращает ID топика для публикации вакансии по типу"""
    if job_type == JobType.LONG_TERM:
        return REGULAR_THREAD_ID if REGULAR_THREAD_ID and REGULAR_THREAD_ID > 1 else None
    else:
        return None  # разовые вакансии публикуются в General


async def check_cancel(msg: Message, state: FSMContext) -> bool:
    """Проверяет, была ли нажата кнопка отмены"""
    if msg.text and msg.text.strip() == "❌ Отменить":
        await state.clear()
        await msg.answer(
            "❌ Заполнение отменено.\n\n"
            "Вы вернулись в главное меню.",
            reply_markup=kb_menu
        )
        return True
    return False


def create_response_buttons(job_id: int = None, job: Job = None) -> InlineKeyboardMarkup:
    """Создает кнопки для отклика на вакансию"""
    buttons = []
    
    if job_id is not None:
        if job is None:
            with SessionLocal() as session:
                job = session.query(Job).filter_by(id=job_id).first()
        
        if job:
            from database.models import JobResponse, ResponseStatus
            with SessionLocal() as session:
                selected_count = session.query(JobResponse).filter_by(
                    job_id=job.id,
                    is_selected=True,
                    is_reserve=False,
                ).count()
            
            # Кнопка отклика активна только при статусах open и in_progress
            if job.status in [JobStatus.OPEN, JobStatus.IN_PROGRESS] and selected_count < job.people_needed:
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


@router.message(Command("my_vacancies"), F.chat.type == ChatType.PRIVATE)
async def cmd_my_vacancies(msg: Message):
    """Список моих вакансий"""
    await my_vacancies(msg)


# ==================== ОБРАБОТЧИКИ СОЗДАНИЯ ВАКАНСИИ ====================

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
        thread_id = get_vacancy_thread_id(job_type)

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
            
            # Удаляем сообщение из канала
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

# ==================== ОБРАБОТЧИКИ РЕДАКТИРОВАНИЯ ВАКАНСИЙ ====================

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
                current_requirements=job.all_info.get('requirements', ''),
                current_schedule=job.all_info.get('schedule', '')
            )
            
            # Показываем меню выбора поля для редактирования
            edit_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="1️⃣ Адрес", callback_data=f"edit_field_address_{job_id}")],
                [InlineKeyboardButton(text="2️⃣ Вакансия", callback_data=f"edit_field_title_{job_id}")],
                [InlineKeyboardButton(text="3️⃣ Оплата", callback_data=f"edit_field_payment_{job_id}")],
                [InlineKeyboardButton(text="4️⃣ Требования", callback_data=f"edit_field_requirements_{job_id}")],
                [InlineKeyboardButton(text="5️⃣ График", callback_data=f"edit_field_schedule_{job_id}")],
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
    data = await state.get_data()
    current_payment = data.get('current_payment', 'не указана')
    
    await callback.message.edit_text(
        f"✏️ Редактирование оплаты\n\n"
        f"💵 Текущая оплата: {current_payment}\n\n"
        "Введите новую оплату (только цифры):"
    )
    await state.set_state(EditVacancyForm.edit_payment)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_requirements_"))
async def edit_field_requirements_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования требований"""
    data = await state.get_data()
    current_requirements = data.get('current_requirements', 'не указаны')
    
    await callback.message.edit_text(
        f"✏️ Редактирование требований\n\n"
        f"👤 Текущие требования: {current_requirements}\n\n"
        "Введите новые требования:"
    )
    await state.set_state(EditVacancyForm.edit_requirements)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_field_schedule_"))
async def edit_field_schedule_callback(callback: CallbackQuery, state: FSMContext):
    """Выбор редактирования графика"""
    data = await state.get_data()
    current_schedule = data.get('current_schedule', 'не указан')
    
    await callback.message.edit_text(
        f"✏️ Редактирование графика\n\n"
        f"⏰ Текущий график: {current_schedule}\n\n"
        "Введите новый график работы:"
    )
    await state.set_state(EditVacancyForm.edit_schedule)
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


@router.message(EditVacancyForm.edit_requirements)
async def process_edit_requirements(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования требований"""
    new_requirements = msg.text.strip()
    if not new_requirements:
        await msg.answer("❌ Требования не могут быть пустыми. Введите требования:")
        return
    
    await update_vacancy_field(msg, state, bot, 'requirements', new_requirements)


@router.message(EditVacancyForm.edit_schedule)
async def process_edit_schedule(msg: Message, state: FSMContext, bot: Bot):
    """Обработка редактирования графика"""
    new_schedule = msg.text.strip()
    if not new_schedule:
        await msg.answer("❌ График не может быть пустым. Введите график:")
        return
    
    await update_vacancy_field(msg, state, bot, 'schedule', new_schedule)


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
                f"📋 <b>{job.all_info['title']}</b>\n\n"
                f"📍 Адрес: {job.all_info['address']}\n"
                f"👤 Требования: {job.all_info.get('requirements', 'не указаны')}\n"
                f"💰 Оплата: {job.all_info['payment']}\n"
                f"⏰ График: {job.all_info.get('schedule', 'не указан')}\n"
                f"👥 Требуется: {job.people_needed} человек"
            )
            
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
                'requirements': 'Требования',
                'schedule': 'График'
            }
            
            await msg.answer(
                f"✅ {field_names.get(field_name, 'Поле')} успешно обновлено!\n\n"
                f"📄 Ссылка: {CHANNEL_URL}",
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
            
            # Удаляем сообщение из канала
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