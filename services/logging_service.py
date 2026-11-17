"""
Сервис для логирования действий пользователей
"""
import logging
from datetime import datetime
from database.db_connection import SessionLocal
from database.models import ActionLog

logger = logging.getLogger(__name__)


def log_action(job_id: int = None, user_id: int = None, action: str = "", details: dict = None):
    """
    Логирует действие пользователя
    
    Args:
        job_id: ID вакансии (опционально)
        user_id: ID пользователя (опционально)
        action: Тип действия (created, applied, selected, confirmed, etc.)
        details: Дополнительные данные в формате JSON
    """
    try:
        with SessionLocal() as session:
            log_entry = ActionLog(
                job_id=job_id,
                user_id=user_id,
                action=action,
                details=details or {},
                timestamp=datetime.now()
            )
            session.add(log_entry)
            session.commit()
            
            logger.info(f"Действие залогировано: {action} для пользователя {user_id}, вакансия {job_id}")
    
    except Exception as e:
        logger.error(f"Ошибка при логировании действия: {e}")


def log_vacancy_created(job_id: int, user_id: int, job_data: dict):
    """Логирует создание вакансии"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="vacancy_created",
        details={
            "title": job_data.get("title", ""),
            "payment": job_data.get("payment", ""),
            "people_needed": job_data.get("people_needed", 1)
        }
    )


def log_application_sent(job_id: int, user_id: int):
    """Логирует отправку отклика"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="application_sent"
    )


def log_candidate_selected(job_id: int, user_id: int, employer_id: int, is_reserve: bool = False):
    """Логирует выбор кандидата"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="candidate_selected",
        details={
            "employer_id": employer_id,
            "is_reserve": is_reserve
        }
    )


def log_work_confirmed(job_id: int, user_id: int, start_time: str, end_time: str):
    """Логирует подтверждение выхода на работу"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="work_confirmed",
        details={
            "start_time": start_time,
            "end_time": end_time
        }
    )


def log_work_refused(job_id: int, user_id: int, reason: str = ""):
    """Логирует отказ от работы"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="work_refused",
        details={
            "reason": reason
        }
    )


def log_rating_given(job_id: int, worker_id: int, employer_id: int, rating: int):
    """Логирует выставление оценки"""
    log_action(
        job_id=job_id,
        user_id=worker_id,
        action="rating_given",
        details={
            "employer_id": employer_id,
            "rating": rating
        }
    )


def log_user_blacklisted(user_id: int, reason: str = ""):
    """Логирует блокировку пользователя"""
    log_action(
        user_id=user_id,
        action="user_blacklisted",
        details={
            "reason": reason
        }
    )


def log_vacancy_edited(job_id: int, user_id: int, field: str, old_value: str, new_value: str):
    """Логирует редактирование вакансии"""
    log_action(
        job_id=job_id,
        user_id=user_id,
        action="vacancy_edited",
        details={
            "field": field,
            "old_value": old_value,
            "new_value": new_value
        }
    )