from sqlalchemy import (
    Column, Integer, BigInteger, ForeignKey,
    DateTime, Boolean, Text, JSON, Float, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db_base import Base
import enum

class JobType(enum.Enum):
    """Тип вакансии"""
    LONG_TERM = "long_term"  # Долгосрочная
    ONE_TIME = "one_time"    # Разовая

class JobStatus(enum.Enum):
    """Статус вакансии"""
    OPEN = "open"                      # Открыта, принимает отклики
    IN_PROGRESS = "in_progress"        # Набрано X из N кандидатов
    CANDIDATES_SELECTED = "candidates_selected"  # Все кандидаты выбраны, ожидается подтверждение
    CONFIRMED = "confirmed"            # Работники подтвердили выход
    COMPLETED = "completed"            # Завершена
    CANCELLED = "cancelled"            # Отменена

class ResponseStatus(enum.Enum):
    """Статус отклика"""
    PENDING = "pending"         # Ожидает рассмотрения
    ACCEPTED = "accepted"       # Принят (выбран как основной)
    REJECTED = "rejected"       # Отклонен
    CONFIRMED = "confirmed"     # Подтвердил выход
    REFUSED = "refused"         # Отказался после подтверждения

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(Text)
    phone = Column(Text, nullable=True)  # Номер телефона
    name = Column(Text, nullable=True)  # Имя
    age = Column(Integer, nullable=True)  # Возраст
    gender = Column(Text, nullable=True)  # Пол (Мужской/Женский)
    experience = Column(Text, nullable=True)  # Опыт работы
    about = Column(Text, nullable=True)  # О себе
    last_work_date = Column(DateTime, nullable=True)  # Последний выход на работу
    average_rating = Column(Float, default=5.0)  # Средний рейтинг
    completed_jobs = Column(Integer, default=0)  # Количество выполненных работ
    refusals_count = Column(Integer, default=0)  # Количество отказов после подтверждения
    is_blacklisted = Column(Boolean, default=False)  # В черном списке
    blacklist_until = Column(DateTime, nullable=True)  # Дата разблокировки
    # Старые поля для совместимости
    can_post = Column(Boolean, default=False)
    invites = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    can_post_until = Column(DateTime, nullable=True)
    allowed_posts = Column(Integer, default=0)
    rating = Column(Float, default=5.0)  # Для совместимости
    rating_count = Column(Integer, default=0)  # Для совместимости

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan", foreign_keys="Job.user_id")
    resumes = relationship("Resume", back_populates="user", cascade="all, delete-orphan")
    responses = relationship("JobResponse", back_populates="user", cascade="all, delete-orphan")
    ratings = relationship("Rating", back_populates="rated_user", foreign_keys="Rating.rated_user_id", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"
    id           = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    message_id   = Column(BigInteger, nullable=False)
    all_info     = Column(JSON, nullable=False)  # description, address, requirements, payment, schedule
    job_type = Column(SQLEnum(JobType), nullable=False, default=JobType.ONE_TIME)  # Тип вакансии
    status = Column(SQLEnum(JobStatus), nullable=False, default=JobStatus.OPEN)  # Статус вакансии
    people_needed = Column(Integer, default=1)  # Сколько человек требуется
    people_confirmed = Column(Integer, default=0)  # Сколько человек подтвердили
    work_start_time = Column(DateTime, nullable=True)  # Время начала работы
    work_end_time = Column(DateTime, nullable=True)  # Время окончания работы
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="jobs", foreign_keys=[user_id])
    responses = relationship("JobResponse", back_populates="job", cascade="all, delete-orphan")

class Resume(Base):
    __tablename__ = "resumes"
    id           = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    message_id   = Column(BigInteger, nullable=False)
    all_info     = Column(JSON, nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="resumes")

class JobResponse(Base):
    """Отклик на вакансию"""
    __tablename__ = "job_responses"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)
    status = Column(SQLEnum(ResponseStatus), nullable=False, default=ResponseStatus.PENDING)
    is_selected = Column(Boolean, default=False)  # Выбран как основной кандидат
    is_reserve = Column(Boolean, default=False)  # Выбран как резервный кандидат
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    job = relationship("Job", back_populates="responses")
    user = relationship("User", back_populates="responses")

class Rating(Base):
    """Оценка работника"""
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    rated_user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)  # Кого оценивают
    rater_user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"), nullable=False)  # Кто оценивает
    rating = Column(Integer, nullable=False)  # Оценка от 1 до 5
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    rated_user = relationship("User", foreign_keys=[rated_user_id], back_populates="ratings")


class Log(Base):
    """Логи действий"""
    __tablename__ = "logs"
    id = Column(Integer, primary_key=True)
    vacancy_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True)
    user_id = Column(BigInteger, ForeignKey("users.telegram_id", ondelete="SET NULL"), nullable=True)
    action = Column(Text, nullable=False)  # created/applied/selected/confirmed/refused/rated/etc
    details = Column(JSON, nullable=True)  # Дополнительные данные
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
