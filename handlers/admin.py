"""
Обработчики для администраторов
"""
import logging
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.enums import ChatType, ParseMode

from database.db_connection import SessionLocal
from database.models import User, Job, JobResponse, Rating, ActionLog
from config import ADMINS

logger = logging.getLogger(__name__)
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором"""
    return user_id in ADMINS


@router.message(Command("logs"), F.chat.type == ChatType.PRIVATE)
async def cmd_logs(msg: Message):
    """Просмотр логов вакансии (только для админов)"""
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        # Парсим ID вакансии из команды
        args = msg.text.split()
        if len(args) < 2:
            await msg.answer("❌ Укажите ID вакансии: /logs 123")
            return
        
        job_id = int(args[1])
        
        with SessionLocal() as session:
            job = session.query(Job).filter_by(id=job_id).first()
            if not job:
                await msg.answer(f"❌ Вакансия с ID {job_id} не найдена.")
                return
            
            # Получаем логи для этой вакансии
            logs = session.query(ActionLog).filter_by(job_id=job_id).order_by(ActionLog.timestamp).all()
            
            log_text = f"📋 <b>Логи вакансии #{job_id}</b>\n\n"
            log_text += f"<b>Название:</b> {job.all_info.get('title', 'не указано')}\n"
            log_text += f"<b>Работодатель:</b> {job.user_id}\n"
            log_text += f"<b>Статус:</b> {job.status.value}\n\n"
            
            if logs:
                log_text += "<b>История действий:</b>\n"
                for log in logs:
                    timestamp = log.timestamp.strftime('%d.%m.%Y %H:%M')
                    log_text += f"• {timestamp} - {log.action}\n"
            else:
                log_text += "Логи отсутствуют."
            
            await msg.answer(log_text, parse_mode=ParseMode.HTML)
    
    except ValueError:
        await msg.answer("❌ Неверный формат ID вакансии.")
    except Exception as e:
        logger.error(f"Ошибка при получении логов: {e}")
        await msg.answer("❌ Произошла ошибка при получении логов.")


@router.message(Command("user_info"), F.chat.type == ChatType.PRIVATE)
async def cmd_user_info(msg: Message):
    """Информация о пользователе (только для админов)"""
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        # Парсим ID пользователя из команды
        args = msg.text.split()
        if len(args) < 2:
            await msg.answer("❌ Укажите ID пользователя: /user_info 123456789")
            return
        
        user_id = int(args[1])
        
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await msg.answer(f"❌ Пользователь с ID {user_id} не найден.")
                return
            
            # Формируем информацию о пользователе
            user_info = f"👤 <b>Информация о пользователе</b>\n\n"
            user_info += f"<b>ID:</b> {user.telegram_id}\n"
            user_info += f"<b>Username:</b> @{user.username or 'не указан'}\n"
            user_info += f"<b>Имя:</b> {user.name or 'не указано'}\n"
            user_info += f"<b>Возраст:</b> {user.age or 'не указан'}\n"
            user_info += f"<b>Пол:</b> {user.gender or 'не указан'}\n"
            user_info += f"<b>Телефон:</b> {user.phone or 'не указан'}\n\n"
            
            user_info += f"📊 <b>Статистика:</b>\n"
            user_info += f"⭐ Рейтинг: {user.average_rating:.1f}\n"
            user_info += f"✅ Выполнено работ: {user.completed_jobs}\n"
            user_info += f"❌ Отказов: {user.refusals_count}\n"
            user_info += f"📅 Последний выход: {user.last_work_date.strftime('%d.%m.%Y') if user.last_work_date else 'нет'}\n"
            user_info += f"📅 Регистрация: {user.created_at.strftime('%d.%m.%Y') if user.created_at else 'неизвестно'}\n\n"
            
            if user.is_blacklisted:
                user_info += f"🚫 <b>Заблокирован до:</b> {user.blacklist_until.strftime('%d.%m.%Y') if user.blacklist_until else 'неизвестно'}\n\n"
            
            # Статистика вакансий
            jobs_count = session.query(Job).filter_by(user_id=user_id).count()
            responses_count = session.query(JobResponse).filter_by(user_id=user_id).count()
            
            user_info += f"📋 <b>Активность:</b>\n"
            user_info += f"Опубликовано вакансий: {jobs_count}\n"
            user_info += f"Откликов на вакансии: {responses_count}"
            
            await msg.answer(user_info, parse_mode=ParseMode.HTML)
    
    except ValueError:
        await msg.answer("❌ Неверный формат ID пользователя.")
    except Exception as e:
        logger.error(f"Ошибка при получении информации о пользователе: {e}")
        await msg.answer("❌ Произошла ошибка при получении информации.")


@router.message(Command("blacklist"), F.chat.type == ChatType.PRIVATE)
async def cmd_blacklist(msg: Message):
    """Список заблокированных пользователей (только для админов)"""
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        with SessionLocal() as session:
            blacklisted_users = session.query(User).filter_by(is_blacklisted=True).all()
            
            if not blacklisted_users:
                await msg.answer("✅ Заблокированных пользователей нет.")
                return
            
            blacklist_text = "🚫 <b>Заблокированные пользователи:</b>\n\n"
            
            for user in blacklisted_users:
                blacklist_text += f"👤 <b>{user.name or 'Без имени'}</b>\n"
                blacklist_text += f"ID: {user.telegram_id}\n"
                blacklist_text += f"Username: @{user.username or 'не указан'}\n"
                blacklist_text += f"Отказов: {user.refusals_count}\n"
                blacklist_text += f"До: {user.blacklist_until.strftime('%d.%m.%Y') if user.blacklist_until else 'неизвестно'}\n\n"
            
            await msg.answer(blacklist_text, parse_mode=ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Ошибка при получении черного списка: {e}")
        await msg.answer("❌ Произошла ошибка при получении списка.")


@router.message(Command("unblock"), F.chat.type == ChatType.PRIVATE)
async def cmd_unblock(msg: Message):
    """Разблокировать пользователя (только для админов)"""
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        # Парсим ID пользователя из команды
        args = msg.text.split()
        if len(args) < 2:
            await msg.answer("❌ Укажите ID пользователя: /unblock 123456789")
            return
        
        user_id = int(args[1])
        
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                await msg.answer(f"❌ Пользователь с ID {user_id} не найден.")
                return
            
            if not user.is_blacklisted:
                await msg.answer(f"✅ Пользователь {user.name or user_id} не заблокирован.")
                return
            
            # Разблокируем пользователя
            user.is_blacklisted = False
            user.blacklist_until = None
            session.commit()
            
            await msg.answer(f"✅ Пользователь {user.name or user_id} разблокирован.")
    
    except ValueError:
        await msg.answer("❌ Неверный формат ID пользователя.")
    except Exception as e:
        logger.error(f"Ошибка при разблокировке пользователя: {e}")
        await msg.answer("❌ Произошла ошибка при разблокировке.")


@router.message(Command("stats"), F.chat.type == ChatType.PRIVATE)
async def cmd_stats(msg: Message):
    """Общая статистика системы (только для админов)"""
    if not is_admin(msg.from_user.id):
        await msg.answer("❌ У вас нет прав для выполнения этой команды.")
        return
    
    try:
        with SessionLocal() as session:
            # Общая статистика
            total_users = session.query(User).count()
            total_jobs = session.query(Job).count()
            total_responses = session.query(JobResponse).count()
            total_ratings = session.query(Rating).count()
            blacklisted_users = session.query(User).filter_by(is_blacklisted=True).count()
            
            # Статистика за сегодня
            today = datetime.now().date()
            today_jobs = session.query(Job).filter(Job.created_at >= today).count()
            today_users = session.query(User).filter(User.created_at >= today).count()
            
            stats_text = f"📊 <b>Статистика системы</b>\n\n"
            stats_text += f"👥 <b>Пользователи:</b>\n"
            stats_text += f"Всего: {total_users}\n"
            stats_text += f"Новых сегодня: {today_users}\n"
            stats_text += f"Заблокированных: {blacklisted_users}\n\n"
            
            stats_text += f"📋 <b>Вакансии:</b>\n"
            stats_text += f"Всего: {total_jobs}\n"
            stats_text += f"Сегодня: {today_jobs}\n\n"
            
            stats_text += f"📨 <b>Отклики:</b> {total_responses}\n"
            stats_text += f"⭐ <b>Оценки:</b> {total_ratings}\n\n"
            
            stats_text += f"📅 <b>Дата:</b> {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            
            await msg.answer(stats_text, parse_mode=ParseMode.HTML)
    
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        await msg.answer("❌ Произошла ошибка при получении статистики.")