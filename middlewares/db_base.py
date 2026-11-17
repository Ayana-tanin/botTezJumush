import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Используем переменную окружения для подключения к базе данных
try:
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не установлен")

    # Создаем движок SQLAlchemy
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True  # Добавляем проверку соединения перед использованием
    )

    # Проверяем соединение
    with engine.connect() as conn:
        logger.info("Соединение с базой данных успешно установлено")

except (SQLAlchemyError, ValueError) as e:
    logger.error(f"Ошибка при подключении к базе данных: {str(e)}")
    # Создаем резервный SQLite движок для локальной разработки
    logger.warning("Использую SQLite локально как резервный вариант")
    import os
    db_path = os.path.join(os.path.dirname(__file__), "bot_database.db")
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    logger.info(f"SQLite база данных будет создана в: {db_path}")

# Создаем фабрику сессий
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
)

# Базовый класс для объявления моделей
Base = declarative_base()


# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()