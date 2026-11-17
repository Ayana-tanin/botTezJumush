import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from config import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

# Используем переменную окружения для подключения к базе данных
try:
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не установлен")

    # Создаем движок SQLAlchemy с настройками для MySQL
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,  # Проверка соединения перед использованием
        pool_recycle=3600,   # Переподключение каждый час
        pool_size=10,        # Размер пула соединений
        max_overflow=20,     # Максимальное количество дополнительных соединений
        connect_args={
            "connect_timeout": 10,  # Таймаут подключения
        }
    )

    # Проверяем соединение
    with engine.connect() as conn:
        logger.info("✅ Соединение с базой данных успешно установлено")
        logger.info(f"📊 Используется: {DATABASE_URL.split('@')[1].split('/')[0] if '@' in DATABASE_URL else 'локальная БД'}")

except (SQLAlchemyError, ValueError) as e:
    logger.error(f"❌ Ошибка при подключении к базе данных: {str(e)}")
    # Создаем резервный SQLite движок для локальной разработки
    logger.warning("⚠️ Использую SQLite локально как резервный вариант")
    import os
    db_path = os.path.join(os.path.dirname(__file__), "bot_database.db")
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    logger.info(f"📁 SQLite база данных будет создана в: {db_path}")

# Создаем фабрику сессий
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


# Функция для получения сессии базы данных
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()