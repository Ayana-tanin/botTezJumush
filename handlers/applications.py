"""
Обработчики для откликов на вакансии и подтверждения работы
"""
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.context import FSMContext

from database.db_connection import SessionLocal
from database.models import Job, JobResponse, User, JobStatus, ResponseStatus
from vacancy_fsm import ConfirmWorkForm, RatingForm
from resume_fsm import ResumeForm
from config import CHANNEL_ID, ADMINS
from handlers.start import kb_menu, kb_cancel

logger = logging.getLogger(__name__)
router = Router()


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


def build_channel_response_buttons(job_id: int, selected_count: int, people_needed: int) -> InlineKeyboardMarkup | None:
    """
    Кнопки под постом вакансии в канале/супергруппе.

    По ТЗ кнопка "Откликнуться" должна исчезать, когда набрано нужное кол-во откликов.
    """
    if selected_count >= people_needed:
        return None

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Откликнуться", callback_data=f"respond_job_{job_id}")]
    ])


async def refresh_channel_response_button(bot: Bot, session, job: Job):
    """Обновляет кнопку отклика в супергруппе по числу откликов."""
    selected_count = session.query(JobResponse).filter_by(
        job_id=job.id,
        is_selected=True,
        is_reserve=False,
    ).count()

    if selected_count <= 0:
        job.status = JobStatus.OPEN
    elif selected_count < job.people_needed:
        job.status = JobStatus.IN_PROGRESS
    else:
        job.status = JobStatus.CANDIDATES_SELECTED

    markup = build_channel_response_buttons(job.id, selected_count, job.people_needed)
    try:
        await bot.edit_message_reply_markup(
            chat_id=CHANNEL_ID,
            message_id=job.message_id,
            reply_markup=markup
        )
    except Exception as e:
        logger.warning(f"Не удалось обновить кнопку отклика для вакансии {job.id}: {e}")


@router.callback_query(F.data.startswith("respond_job_"))
async def respond_to_job(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обработчик отклика на вакансию"""
    try:
        job_id = int(callback.data.split("_")[2])
        user_id = callback.from_user.id

        # Получаем информацию о вакансии (далее — только в личном чате)
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return

            selected_count = session.query(JobResponse).filter_by(
                job_id=job_id,
                is_selected=True,
                is_reserve=False,
            ).count()
            if selected_count >= job.people_needed:
                await refresh_channel_response_button(bot, session, job)
                session.commit()
                await callback.answer("❌ Набор уже завершен", show_alert=True)
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
            
            # Проверяем наличие анкеты у пользователя
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
                
                # Формируем текст отклика согласно ТЗ
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

                    # При отклике (PENDING) выбранные места не меняются,
                    # поэтому кнопку в супергруппе обновляем только при выборе/отклонении.
                    
                    await callback.answer("✅ Ваш отклик отправлен работодателю!", show_alert=True)
                except Exception as e:
                    logger.error(f"Ошибка при отправке отклика работодателю: {e}")
                    await callback.answer("❌ Не удалось отправить отклик. Попробуйте позже.", show_alert=True)
            else:
                # Если анкеты нет:
                # - в ЛС запускаем заполнение анкеты сразу;
                # - в группе отправляем пользователя в ЛС.
                if callback.message.chat.type == ChatType.PRIVATE:
                    await callback.answer()
                    await callback.message.answer(
                        "📝 Для отклика на вакансию нужно заполнить анкету.\n\n"
                        "Ответьте на 6 вопросов (в конце — номер телефона):",
                        reply_markup=kb_cancel
                    )

                    # Сохраняем job_id в состоянии для отправки отклика после заполнения
                    await state.update_data(respond_to_job_id=job_id)

                    # Начинаем заполнение анкеты
                    await callback.message.answer(
                        "1️⃣ Напишите ваше ФИО",
                        reply_markup=kb_cancel
                    )
                    await state.set_state(ResumeForm.name)
                else:
                    await callback.answer(
                        "📩 У вас нет резюме. Заполните анкету в личных сообщениях с ботом.",
                        show_alert=True
                    )
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=(
                                "📝 Для отклика на вакансию сначала заполните резюме.\n\n"
                                "Откройте личные сообщения с ботом, затем нажмите кнопку "
                                "«📝 Моё резюме» и заполните анкету.\n\n"
                                "После этого вернитесь к вакансии и нажмите «📝 Откликнуться»."
                            ),
                            parse_mode=ParseMode.HTML,
                            reply_markup=kb_menu,
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось отправить сообщение в ЛС пользователю {user_id}: {e}")
    
    except Exception as e:
        logger.error(f"Ошибка при обработке отклика на вакансию: {e}")
        await callback.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)


@router.callback_query(F.data.startswith("select_candidate_main_"))
async def select_candidate_main(callback: CallbackQuery, bot: Bot):
    """Выбрать кандидата в основной состав."""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[3])
        candidate_id = int(parts[4])

        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return

            if callback.from_user.id not in ADMINS and callback.from_user.id != job.user_id:
                await callback.answer("❌ Нет доступа", show_alert=True)
                return

            response = session.query(JobResponse).filter_by(job_id=job_id, user_id=candidate_id).first()
            if not response:
                await callback.answer("❌ Отклик не найден", show_alert=True)
                return

            selected_count = session.query(JobResponse).filter_by(
                job_id=job_id,
                is_selected=True,
                is_reserve=False
            ).count()
            if selected_count >= job.people_needed and not response.is_selected:
                await callback.answer("❌ Нужное количество уже набрано", show_alert=True)
                return

            response.status = ResponseStatus.ACCEPTED
            response.is_selected = True
            response.is_reserve = False

            await refresh_channel_response_button(bot, session, job)
            session.commit()

            try:
                await bot.send_message(
                    chat_id=candidate_id,
                    text=(
                        f"🎉 <b>Вас выбрали на работу!</b>\n\n"
                        f"📋 Вакансия: {job.all_info.get('title', 'не указано')}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Не удалось уведомить кандидата {candidate_id}: {e}")

            await callback.answer("✅ Кандидат выбран", show_alert=True)
            await callback.message.edit_reply_markup(reply_markup=None)

    except Exception as e:
        logger.error(f"Ошибка при выборе кандидата: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("reject_candidate_"))
async def reject_candidate(callback: CallbackQuery, bot: Bot):
    """Отклонить кандидата."""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        candidate_id = int(parts[3])

        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return

            if callback.from_user.id not in ADMINS and callback.from_user.id != job.user_id:
                await callback.answer("❌ Нет доступа", show_alert=True)
                return

            response = session.query(JobResponse).filter_by(job_id=job_id, user_id=candidate_id).first()
            if not response:
                await callback.answer("❌ Отклик не найден", show_alert=True)
                return

            response.status = ResponseStatus.REJECTED
            response.is_selected = False
            response.is_reserve = False

            await refresh_channel_response_button(bot, session, job)
            session.commit()

            try:
                await bot.send_message(
                    chat_id=candidate_id,
                    text=(
                        f"😔 <b>Ваш отклик отклонен</b>\n\n"
                        f"📋 Вакансия: {job.all_info.get('title', 'не указано')}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Не удалось уведомить кандидата {candidate_id} об отклонении: {e}")

            await callback.answer("❌ Кандидат отклонен", show_alert=True)
            await callback.message.edit_reply_markup(reply_markup=None)

    except Exception as e:
        logger.error(f"Ошибка при отклонении кандидата: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)