"""
Сервис уведомлений для системы напоминаний о работе
"""
import logging
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from database.db_connection import SessionLocal
from database.models import Job, JobResponse, User, JobStatus, ResponseStatus
from config import ADMINS

logger = logging.getLogger(__name__)


async def send_work_reminders(bot: Bot):
    """
    Отправляет уведомления работникам за 4 часа и за 45 минут до начала работы
    """
    try:
        with SessionLocal() as session:
            now = datetime.now()
            
            # Находим все подтвержденные работы
            confirmed_responses = session.query(JobResponse).join(Job).filter(
                JobResponse.status == ResponseStatus.CONFIRMED,
                Job.work_start_time.isnot(None),
                Job.status == JobStatus.CONFIRMED
            ).all()
            
            for response in confirmed_responses:
                job = response.job
                user_id = response.user_id
                
                if not job.work_start_time:
                    continue
                
                time_until_work = job.work_start_time - now
                
                # Уведомление за 4 часа
                if timedelta(hours=3, minutes=50) <= time_until_work <= timedelta(hours=4, minutes=10):
                    await send_4_hour_reminder(bot, user_id, job)
                
                # Уведомление за 45 минут
                elif timedelta(minutes=35) <= time_until_work <= timedelta(minutes=55):
                    await send_45_minute_reminder(bot, user_id, job)
                
                # Проверка на завершение работы
                elif job.work_end_time and now >= job.work_end_time and job.status == JobStatus.CONFIRMED:
                    await send_work_completion_request(bot, job)
    
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомлений: {e}")


async def send_4_hour_reminder(bot: Bot, user_id: int, job: Job):
    """Уведомление за 4 часа до начала работы"""
    try:
        reminder_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, приду", callback_data=f"confirm_4h_{job.id}")],
            [InlineKeyboardButton(text="❌ Нет, не смогу", callback_data=f"refuse_4h_{job.id}")]
        ])
        
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"⏰ <b>Напоминание о работе через 4 часа</b>\n\n"
                f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                f"⏰ <b>Начало работы:</b> {job.work_start_time.strftime('%H:%M')}\n\n"
                f"Вы сможете прийти?"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=reminder_keyboard
        )
        
        logger.info(f"Отправлено 4-часовое напоминание пользователю {user_id} для работы {job.id}")
    
    except Exception as e:
        logger.error(f"Ошибка при отправке 4-часового напоминания: {e}")


async def send_45_minute_reminder(bot: Bot, user_id: int, job: Job):
    """Уведомление за 45 минут до начала работы"""
    try:
        reminder_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, иду на работу", callback_data=f"confirm_45m_{job.id}")],
            [InlineKeyboardButton(text="❌ Не смогу прийти", callback_data=f"refuse_45m_{job.id}")]
        ])
        
        await bot.send_message(
            chat_id=user_id,
            text=(
                f"🔔 <b>Работа начинается через 45 минут!</b>\n\n"
                f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                f"📍 <b>Адрес:</b> {job.all_info.get('address', 'не указан')}\n"
                f"⏰ <b>Начало:</b> {job.work_start_time.strftime('%H:%M')}\n\n"
                f"Подтверждаете выход?"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=reminder_keyboard
        )
        
        logger.info(f"Отправлено 45-минутное напоминание пользователю {user_id} для работы {job.id}")
    
    except Exception as e:
        logger.error(f"Ошибка при отправке 45-минутного напоминания: {e}")


async def send_work_completion_request(bot: Bot, job: Job):
    """Запрос оценки работы у работодателя после завершения"""
    try:
        # Находим всех подтвержденных работников для этой вакансии
        with SessionLocal() as session:
            confirmed_responses = session.query(JobResponse).filter_by(
                job_id=job.id,
                status=ResponseStatus.CONFIRMED
            ).all()
            
            for response in confirmed_responses:
                user = session.query(User).filter_by(telegram_id=response.user_id).first()
                
                rating_keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(text="⭐ 1", callback_data=f"rate_worker_{job.id}_{response.user_id}_1"),
                        InlineKeyboardButton(text="⭐ 2", callback_data=f"rate_worker_{job.id}_{response.user_id}_2"),
                        InlineKeyboardButton(text="⭐ 3", callback_data=f"rate_worker_{job.id}_{response.user_id}_3"),
                        InlineKeyboardButton(text="⭐ 4", callback_data=f"rate_worker_{job.id}_{response.user_id}_4"),
                        InlineKeyboardButton(text="⭐ 5", callback_data=f"rate_worker_{job.id}_{response.user_id}_5")
                    ]
                ])
                
                await bot.send_message(
                    chat_id=job.user_id,
                    text=(
                        f"✅ <b>Время работы завершено</b>\n\n"
                        f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
                        f"👤 <b>Работник:</b> {user.name if user else 'Не указано'}\n\n"
                        f"Оцените работу исполнителя по 5-балльной шкале:"
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=rating_keyboard
                )
            
            # Обновляем статус работы
            job.status = JobStatus.COMPLETED
            session.commit()
        
        logger.info(f"Отправлен запрос оценки для работы {job.id}")
    
    except Exception as e:
        logger.error(f"Ошибка при отправке запроса оценки: {e}")


async def notify_employer_about_refusal(bot: Bot, job: Job, user: User, hours_before: int):
    """Уведомляет работодателя об отказе работника"""
    try:
        reactivate_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data=f"reactivate_job_{job.id}")],
            [InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel_job_{job.id}")]
        ])
        
        notification_text = (
            f"⚠️ <b>Работник {user.name if user else 'Не указано'} отказался от выхода на работу</b>\n\n"
            f"📋 <b>Вакансия:</b> {job.all_info.get('title', 'не указано')}\n"
            f"⏰ <b>Начало через {hours_before} {'час' if hours_before == 1 else 'часа' if hours_before < 5 else 'часов'}</b>\n\n"
            f"Сделать вакансию активной?"
        )
        
        # Отправляем работодателю
        await bot.send_message(
            chat_id=job.user_id,
            text=notification_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reactivate_keyboard
        )
        
        # Отправляем админам
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
        logger.error(f"Ошибка при уведомлении работодателя об отказе: {e}")


async def check_unconfirmed_jobs(bot: Bot):
    """Проверяет вакансии без подтверждения за 2 часа до начала"""
    try:
        with SessionLocal() as session:
            now = datetime.now()
            
            # Находим вакансии, которые начинаются через 2 часа, но не подтверждены
            jobs_in_2_hours = session.query(Job).filter(
                Job.work_start_time.between(
                    now + timedelta(hours=1, minutes=50),
                    now + timedelta(hours=2, minutes=10)
                ),
                Job.status == JobStatus.CANDIDATES_SELECTED,
                Job.people_confirmed == 0
            ).all()
            
            for job in jobs_in_2_hours:
                cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
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
                    reply_markup=cancel_keyboard
                )
    
    except Exception as e:
        logger.error(f"Ошибка при проверке неподтвержденных вакансий: {e}")