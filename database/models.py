"""
Модели базы данных для Telegram-бота вакансий
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()


class JobType(enum.Enum):
    """Типы вакансий"""
    LONG_TERM = "long_term"  # Долгосрочная вакансия
    ONE_TIME = "one_time"    # Разовая работа


class JobStatus(enum.Enum):
    """Статусы вакансий"""
    OPEN = "open"                           # Открыта
    IN_PROGRESS = "in_progress"             # Набрано X из N кандидатов
    CANDIDATES_SELECTED = "candidates_selected"  # Все кандидаты выбраны
    CONFIRMED = "confirmed"                 # Работники подтвердили выход
    COMPLETED = "completed"                 # Работа выполнена
    CANCELLED = "cancelled"                 # Отменена


class ResponseStatus(enum.Enum):
    """Статусы откликов"""
    PENDING = "pending"      # Ожидает рассмотрения
    ACCEPTED = "accepted"    # Принят (выбран)
    REJECTED = "rejected"    # Отклонен
    CONFIRMED = "confirmed"  # Подтвержден (работник подтвердил выход)
    REFUSED = "refused"      # Отказался (работник отказался)


class User(Base):
    """Пользователи системы"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255))
    phone = Column(String(20))
    
    # Данные анкеты
    name = Column(String(255))
    age = Column(Integer)
    gender = Column(String(20))
    experience = Column(Text)
    about = Column(Text)
    last_work_date = Column(DateTime)
    
    # Рейтинг и статистика
    average_rating = Column(Float, default=5.0)
    completed_jobs = Column(Integer, default=0)
    refusals_count = Column(Integer, default=0)
    
    # Черный список
    is_blacklisted = Column(Boolean, default=False)
    blacklist_until = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    jobs = relationship("Job", back_populates="employer")
    responses = relationship("JobResponse", back_populates="user")
    ratings_given = relationship("Rating", foreign_keys="Rating.employer_id", back_populates="employer")
    ratings_received = relationship("Rating", foreign_keys="Rating.worker_id", back_populates="worker")


class Job(Base):
    """Вакансии"""
    __tablename__ = 'jobs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    message_id = Column(Integer)  # ID сообщения в канале
    
    # Тип и статус
    job_type = Column(Enum(JobType), nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.OPEN)
    
    # Данные вакансии (JSON для гибкости)
    all_info = Column(JSON, nullable=False)  # Содержит: title, address, requirements, payment, schedule
    
    # Количество людей
    people_needed = Column(Integer, nullable=False)
    people_confirmed = Column(Integer, default=0)
    
    # Время работы
    work_start_time = Column(DateTime)
    work_end_time = Column(DateTime)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    employer = relationship("User", back_populates="jobs")
    responses = relationship("JobResponse", back_populates="job")
    ratings = relationship("Rating", back_populates="job")


class JobResponse(Base):
    """Отклики на вакансии"""
    __tablename__ = 'job_responses'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    
    # Статус отклика
    status = Column(Enum(ResponseStatus), default=ResponseStatus.PENDING)
    is_selected = Column(Boolean, default=False)  # Выбран как основной
    is_reserve = Column(Boolean, default=False)   # Выбран как резервный
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    job = relationship("Job", back_populates="responses")
    user = relationship("User", back_populates="responses")


class Rating(Base):
    """Оценки работников"""
    __tablename__ = 'ratings'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=False)
    worker_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    employer_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    
    rating = Column(Integer, nullable=False)  # 1-5
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связи
    job = relationship("Job", back_populates="ratings")
    worker = relationship("User", foreign_keys=[worker_id], back_populates="ratings_received")
    employer = relationship("User", foreign_keys=[employer_id], back_populates="ratings_given")


class Resume(Base):
    """Анкеты (для совместимости с существующим кодом)"""
    __tablename__ = 'resumes'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.telegram_id'), nullable=False)
    
    # Данные анкеты (дублируют User для совместимости)
    name = Column(String(255))
    age = Column(Integer)
    gender = Column(String(20))
    experience = Column(Text)
    about = Column(Text)
    phone = Column(String(20))
    
    # ID опубликованного сообщения в RESUME_THREAD_ID
    message_id = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class ActionLog(Base):
    """Логи действий"""
    __tablename__ = 'action_logs'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('jobs.id'))
    user_id = Column(Integer, ForeignKey('users.telegram_id'))
    
    action = Column(String(100), nullable=False)  # created, applied, selected, confirmed, etc.
    details = Column(JSON)  # Дополнительные данные
    
    timestamp = Column(DateTime, default=datetime.utcnow)