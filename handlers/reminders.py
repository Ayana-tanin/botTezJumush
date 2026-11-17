"""
Обработчики для системы напоминаний и уведомлений
"""
import logging
from datetime import datetime, timedelta
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from database.db_connection import SessionLocal
from database.models import Job, JobResponse, User, Rating, JobStatus, ResponseStatus
from services.notification_service import notify_employer_about_refusal

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("confirm_4h_"))
async def confirm_4_hour_reminder(callback: CallbackQuery):
    """Подтверждение выхода на работу за 4 часа"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=callback.from_user.id,
                status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не подтверждены на эту работу", show_alert=True)
                return
            
            await callback.answer("✅ Отлично! Ждем вас на работе", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ <b>Подтверждено: приду на работу</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при подтверждении 4-часового напоминания: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("refuse_4h_"))
async def refuse_4_hour_reminder(callback: CallbackQuery, bot: Bot):
    """Отказ от работы за 4 часа"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=callback.from_user.id,
                status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не подтверждены на эту работу", show_alert=True)
                return
            
            job = session.query(Job).filter_by(id=job_id).first()
            user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
            
            if not job or not user:
                await callback.answer("❌ Данные не найдены", show_alert=True)
                return
            
            # Обновляем статус отклика
            response.status = ResponseStatus.REFUSED
            
            # Увеличиваем счетчик отказов
            user.refusals_count += 1
            
            # Проверяем черный список
            if user.refusals_count >= 3 and not user.is_blacklisted:
                user.is_blacklisted = True
                user.blacklist_until = datetime.now() + timedelta(days=30)
                
                await bot.send_message(
                    chat_id=callback.from_user.id,
                    text=(
                        f"🚫 <b>Вы заблокированы на 30 дней</b>\n\n"
                        f"Причина: 3 отказа после подтверждения выхода на работу.\n\n"
                        f"Разблокировка: {user.blacklist_until.strftime('%d.%m.%Y')}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            
            # Уменьшаем счетчик подтвержденных
            job.people_confirmed = max(0, job.people_confirmed - 1)
            if job.people_confirmed < job.people_needed:
                job.status = JobStatus.CANDIDATES_SELECTED
            
            session.commit()
            
            # Уведомляем работодателя
            await notify_employer_about_refusal(bot, job, user, 4)
            
            # Проверяем резервных кандидатов
            reserve_response = session.query(JobResponse).filter_by(
                job_id=job_id, is_reserve=True, status=ResponseStatus.ACCEPTED
            ).order_by(JobResponse.created_at).first()
            
            if reserve_response:
                # Отправляем предложение резервному кандидату
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
                
                # Меняем статус резервного на основной
                reserve_response.is_reserve = False
                reserve_response.is_selected = True
                session.commit()
            
            await callback.answer("❌ Отказ зарегистрирован", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ <b>Отказ зарегистрирован</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при отказе от 4-часового напоминания: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("confirm_45m_"))
async def confirm_45_minute_reminder(callback: CallbackQuery):
    """Подтверждение выхода на работу за 45 минут"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=callback.from_user.id,
                status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не подтверждены на эту работу", show_alert=True)
                return
            
            await callback.answer("✅ Отлично! Удачной работы!", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ <b>Финальное подтверждение получено</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при подтверждении 45-минутного напоминания: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("refuse_45m_"))
async def refuse_45_minute_reminder(callback: CallbackQuery, bot: Bot):
    """Отказ от работы за 45 минут"""
    try:
        job_id = int(callback.data.split("_")[2])
        
        with SessionLocal() as session:
            response = session.query(JobResponse).filter_by(
                job_id=job_id, user_id=callback.from_user.id,
                status=ResponseStatus.CONFIRMED
            ).first()
            
            if not response:
                await callback.answer("❌ Вы не подтверждены на эту работу", show_alert=True)
                return
            
            job = session.query(Job).filter_by(id=job_id).first()
            user = session.query(User).filter_by(telegram_id=callback.from_user.id).first()
            
            if not job or not user:
                await callback.answer("❌ Данные не найдены", show_alert=True)
                return
            
            # Обновляем статус отклика
            response.status = ResponseStatus.REFUSED
            
            # Увеличиваем счетчик отказов
            user.refusals_count += 1
            
            # Проверяем черный список
            if user.refusals_count >= 3 and not user.is_blacklisted:
                user.is_blacklisted = True
                user.blacklist_until = datetime.now() + timedelta(days=30)
                
                await bot.send_message(
                    chat_id=callback.from_user.id,
                    text=(
                        f"🚫 <b>Вы заблокированы на 30 дней</b>\n\n"
                        f"Причина: 3 отказа после подтверждения выхода на работу.\n\n"
                        f"Разблокировка: {user.blacklist_until.strftime('%d.%m.%Y')}"
                    ),
                    parse_mode=ParseMode.HTML
                )
            
            # Уменьшаем счетчик подтвержденных
            job.people_confirmed = max(0, job.people_confirmed - 1)
            if job.people_confirmed < job.people_needed:
                job.status = JobStatus.CANDIDATES_SELECTED
            
            session.commit()
            
            # Уведомляем работодателя (без дублирования вакансии)
            await notify_employer_about_refusal(bot, job, user, 1)  # 45 минут ≈ 1 час
            
            await callback.answer("❌ Отказ зарегистрирован", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + "\n\n❌ <b>Отказ зарегистрирован</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при отказе от 45-минутного напоминания: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("rate_worker_"))
async def rate_worker(callback: CallbackQuery, bot: Bot):
    """Оценка работника работодателем"""
    try:
        parts = callback.data.split("_")
        job_id = int(parts[2])
        worker_id = int(parts[3])
        rating = int(parts[4])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id, user_id=callback.from_user.id).first()
            if not job:
                await callback.answer("❌ Вакансия не найдена", show_alert=True)
                return
            
            # Проверяем, не была ли уже поставлена оценка
            existing_rating = session.query(Rating).filter_by(
                job_id=job_id, worker_id=worker_id, employer_id=callback.from_user.id
            ).first()
            
            if existing_rating:
                await callback.answer("❌ Вы уже оценили этого работника", show_alert=True)
                return
            
            # Создаем новую оценку
            new_rating = Rating(
                job_id=job_id,
                worker_id=worker_id,
                employer_id=callback.from_user.id,
                rating=rating
            )
            session.add(new_rating)
            
            # Обновляем статистику работника
            worker = session.query(User).filter_by(telegram_id=worker_id).first()
            if worker:
                # Пересчитываем средний рейтинг
                all_ratings = session.query(Rating).filter_by(worker_id=worker_id).all()
                if all_ratings:
                    total_rating = sum(r.rating for r in all_ratings)
                    worker.average_rating = total_rating / len(all_ratings)
                
                # Увеличиваем счетчик выполненных работ
                worker.completed_jobs += 1
                
                # Применяем штраф за отказы (каждый отказ -0.3)
                penalty = worker.refusals_count * 0.3
                worker.average_rating = max(1.0, worker.average_rating - penalty)
            
            session.commit()
            
            # Уведомляем работника
            try:
                await bot.send_message(
                    chat_id=worker_id,
                    text=(
                        f"🎉 <b>Работа выполнена!</b>\n\n"
                        f"Вас оценили на ⭐ {rating}/5\n\n"
                        f"Ваш новый рейтинг: ⭐ {worker.average_rating:.1f} | {worker.completed_jobs} работ"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить работника о оценке: {e}")
            
            await callback.answer(f"✅ Оценка {rating}/5 поставлена!", show_alert=True)
            await callback.message.edit_text(
                callback.message.text + f"\n\n✅ <b>Оценка поставлена: {rating}/5</b>",
                parse_mode=ParseMode.HTML
            )
    
    except Exception as e:
        logger.error(f"Ошибка при оценке работника: {e}")
        await callback.answer("❌ Произошла ошибка", show_alert=True)