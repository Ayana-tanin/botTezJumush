"""
Файл с закомментированными проверками ограничений на публикацию вакансий.
Эти проверки были отключены, чтобы разрешить публикацию всем пользователям.

Чтобы включить ограничения обратно:
1. Раскомментируйте код в этом файле
2. Раскомментируйте соответствующие проверки в handlers.py
3. Импортируйте функции из этого файла в handlers.py
"""

# import re
# import asyncio
# import logging
# from datetime import datetime, timedelta
# from sqlalchemy import func
# from db_connection import SessionLocal
# from models import User, Job
# from config import ADMINS, ADMIN_USERNAME, CHANNEL_URL
# 
# logger = logging.getLogger(__name__)


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


# Пример использования в prepare_vacancy_impl:
# 
# async def prepare_vacancy_impl(msg: Message, state: FSMContext):
#     """Общая логика подготовки вакансии"""
#     user_id = msg.from_user.id if hasattr(msg, 'from_user') else msg.chat.id
# 
#     # Проверяем возможность публикации
#     can_post, message, invites_count = can_post_more_extended(user_id)
# 
#     if not can_post:
#         if user_id not in ADMINS:
#             await msg.answer(
#                 f"🔒 {message}\n"
#                 f"👥 Вы добавили: {invites_count}/5 друзей\n\n"
#                 f"💰 Оплатить: https://t.me/{ADMIN_USERNAME}\n"
#                 f"👥 Или добавьте ещё {5 - invites_count} друзей в группу",
#                 reply_markup=InlineKeyboardMarkup(inline_keyboard=[
#                     [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")],
#                     [InlineKeyboardButton(text="👥 Группа", url=CHANNEL_URL)]
#                 ])
#             )
#             return
# 
#     await msg.answer(...)


# Пример использования в process_vacancy:
# 
# # Повторная проверка возможности публикации
# can_post, message, invites_count = can_post_more_extended(uid)
# if not can_post and uid not in ADMINS:
#     await msg.answer(
#         f"🔒 {message}\n"
#         f"👥 Вы добавили: {invites_count}/5 друзей\n\n"
#         f"💰 Оплатить: https://t.me/{ADMIN_USERNAME}",
#         reply_markup=InlineKeyboardMarkup(inline_keyboard=[
#             [InlineKeyboardButton(text="👤 Админ", url=f"https://t.me/{ADMIN_USERNAME}")]
#         ])
#     )
#     await state.clear()
#     return


# Пример уменьшения счетчика публикаций:
# 
# # Уменьшение счетчика публикаций (только если это не админ, не can_post=True и не первая публикация)
# try:
#     with SessionLocal() as session:
#         user = session.query(User).filter_by(telegram_id=uid).first()
#         if user:
#             # Проверяем, первая ли это публикация
#             job_count = session.query(func.count(Job.id)).filter_by(user_id=uid).scalar()
#             
#             # Уменьшаем счетчик только если:
#             # 1. Это не первая публикация
#             # 2. У пользователя нет постоянного разрешения (can_post=False)
#             # 3. Есть доступные публикации
#             if job_count > 1 and not user.can_post and user.allowed_posts > 0:
#                 user.allowed_posts -= 1
#                 session.commit()
#                 logger.info(f"Уменьшен счетчик публикаций для пользователя {uid}")
# except Exception as e:
#     logger.error(f"Ошибка при обновлении счетчика публикаций: {e}")

