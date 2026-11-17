"""
Сервис для работы с рейтингами пользователей
"""
import logging
from database.db_connection import SessionLocal
from database.models import User, Rating

logger = logging.getLogger(__name__)


def calculate_user_rating(user_id: int) -> float:
    """
    Рассчитывает средний рейтинг пользователя с учетом штрафов за отказы
    """
    try:
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                return 5.0  # Начальный рейтинг для новых пользователей
            
            # Получаем все оценки пользователя
            ratings = session.query(Rating).filter_by(worker_id=user_id).all()
            
            if not ratings:
                base_rating = 5.0  # Начальный рейтинг
            else:
                # Рассчитываем средний рейтинг
                total_rating = sum(r.rating for r in ratings)
                base_rating = total_rating / len(ratings)
            
            # Применяем штраф за отказы (каждый отказ -0.3)
            penalty = user.refusals_count * 0.3
            final_rating = max(1.0, base_rating - penalty)
            
            return round(final_rating, 1)
    
    except Exception as e:
        logger.error(f"Ошибка при расчете рейтинга пользователя {user_id}: {e}")
        return 5.0


def update_user_rating(user_id: int, new_rating: int) -> bool:
    """
    Обновляет рейтинг пользователя после получения новой оценки
    """
    try:
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                return False
            
            # Пересчитываем средний рейтинг
            user.average_rating = calculate_user_rating(user_id)
            session.commit()
            
            return True
    
    except Exception as e:
        logger.error(f"Ошибка при обновлении рейтинга пользователя {user_id}: {e}")
        return False


def get_user_stats(user_id: int) -> dict:
    """
    Получает статистику пользователя
    """
    try:
        with SessionLocal() as session:
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if not user:
                return {
                    'rating': 5.0,
                    'completed_jobs': 0,
                    'refusals_count': 0,
                    'last_work_date': None
                }
            
            return {
                'rating': user.average_rating,
                'completed_jobs': user.completed_jobs,
                'refusals_count': user.refusals_count,
                'last_work_date': user.last_work_date
            }
    
    except Exception as e:
        logger.error(f"Ошибка при получении статистики пользователя {user_id}: {e}")
        return {
            'rating': 5.0,
            'completed_jobs': 0,
            'refusals_count': 0,
            'last_work_date': None
        }


def format_rating_text(user_id: int) -> str:
    """
    Форматирует текст рейтинга для отображения
    """
    stats = get_user_stats(user_id)
    
    rating_text = f"⭐ {stats['rating']:.1f} | {stats['completed_jobs']} работ | {stats['refusals_count']} отказ"
    
    if stats['refusals_count'] != 1:
        rating_text = rating_text.replace("отказ", "отказов")
    
    return rating_text