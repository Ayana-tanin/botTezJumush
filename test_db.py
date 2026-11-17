"""
Скрипт для тестирования инициализации базы данных
"""
import logging
from db_connection import init_db, SessionLocal
from models import User, Job, Resume, JobResponse, Rating, Log

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_db_connection():
    """Тестирование подключения к БД"""
    try:
        logger.info("=" * 50)
        logger.info("ТЕСТИРОВАНИЕ БАЗЫ ДАННЫХ")
        logger.info("=" * 50)
        
        # Инициализация БД
        logger.info("\n1. Инициализация базы данных...")
        init_db()
        
        # Проверка подключения
        logger.info("\n2. Проверка подключения...")
        with SessionLocal() as session:
            # Пробуем выполнить простой запрос
            user_count = session.query(User).count()
            logger.info(f"✅ Подключение успешно. Пользователей в БД: {user_count}")
        
        # Проверка таблиц
        logger.info("\n3. Проверка структуры таблиц...")
        with SessionLocal() as session:
            from sqlalchemy import inspect, text
            inspector = inspect(session.bind)
            tables = inspector.get_table_names()
            
            logger.info(f"Найдено таблиц: {len(tables)}")
            for table in tables:
                columns = [col['name'] for col in inspector.get_columns(table)]
                logger.info(f"  - {table}: {len(columns)} колонок")
        
        logger.info("\n" + "=" * 50)
        logger.info("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"\n❌ ОШИБКА: {str(e)}", exc_info=True)
        return False
    
    return True

if __name__ == "__main__":
    success = test_db_connection()
    exit(0 if success else 1)
