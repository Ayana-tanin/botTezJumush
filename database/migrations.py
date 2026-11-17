"""
Система миграций базы данных
Автоматически создает и обновляет структуру таблиц
"""
import logging
from sqlalchemy import inspect, text, Column, Integer, String, Float, Boolean, DateTime, Text, JSON, Enum
from sqlalchemy.exc import SQLAlchemyError
from database.db_base import engine, SessionLocal
from database.models import Base, JobType, JobStatus, ResponseStatus

logger = logging.getLogger(__name__)


def get_existing_tables():
    """Получает список существующих таблиц в БД"""
    inspector = inspect(engine)
    return inspector.get_table_names()


def get_existing_columns(table_name):
    """Получает список существующих колонок в таблице"""
    inspector = inspect(engine)
    return {col['name']: col for col in inspector.get_columns(table_name)}


def create_all_tables():
    """Создает все таблицы из моделей"""
    try:
        logger.info("📋 Создание таблиц базы данных...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Таблицы успешно созданы")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка при создании таблиц: {e}")
        return False


def migrate_users_table():
    """Миграция таблицы users - добавление недостающих колонок"""
    table_name = 'users'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    # Определяем необходимые колонки
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'telegram_id': 'BIGINT UNIQUE NOT NULL',
        'username': 'VARCHAR(255)',
        'phone': 'VARCHAR(20)',
        'name': 'VARCHAR(255)',
        'age': 'INTEGER',
        'gender': 'VARCHAR(20)',
        'experience': 'TEXT',
        'about': 'TEXT',
        'last_work_date': 'DATETIME',
        'average_rating': 'FLOAT DEFAULT 5.0',
        'completed_jobs': 'INTEGER DEFAULT 0',
        'refusals_count': 'INTEGER DEFAULT 0',
        'is_blacklisted': 'BOOLEAN DEFAULT FALSE',
        'blacklist_until': 'DATETIME',
        'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def migrate_jobs_table():
    """Миграция таблицы jobs - добавление недостающих колонок"""
    table_name = 'jobs'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    # Определяем необходимые колонки
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'user_id': 'BIGINT NOT NULL',
        'message_id': 'INTEGER',
        'job_type': "ENUM('long_term', 'one_time') NOT NULL",
        'status': "ENUM('open', 'in_progress', 'candidates_selected', 'confirmed', 'completed', 'cancelled') DEFAULT 'open'",
        'all_info': 'JSON NOT NULL',
        'people_needed': 'INTEGER NOT NULL',
        'people_confirmed': 'INTEGER DEFAULT 0',
        'work_start_time': 'DATETIME',
        'work_end_time': 'DATETIME',
        'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def migrate_job_responses_table():
    """Миграция таблицы job_responses"""
    table_name = 'job_responses'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'job_id': 'INTEGER NOT NULL',
        'user_id': 'BIGINT NOT NULL',
        'status': "ENUM('pending', 'accepted', 'rejected', 'confirmed', 'refused') DEFAULT 'pending'",
        'is_selected': 'BOOLEAN DEFAULT FALSE',
        'is_reserve': 'BOOLEAN DEFAULT FALSE',
        'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def migrate_ratings_table():
    """Миграция таблицы ratings"""
    table_name = 'ratings'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'job_id': 'INTEGER NOT NULL',
        'worker_id': 'BIGINT NOT NULL',
        'employer_id': 'BIGINT NOT NULL',
        'rating': 'INTEGER NOT NULL',
        'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def migrate_resumes_table():
    """Миграция таблицы resumes"""
    table_name = 'resumes'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'user_id': 'BIGINT NOT NULL',
        'name': 'VARCHAR(255)',
        'age': 'INTEGER',
        'gender': 'VARCHAR(20)',
        'experience': 'TEXT',
        'about': 'TEXT',
        'phone': 'VARCHAR(20)',
        'message_id': 'INTEGER',
        'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def migrate_action_logs_table():
    """Миграция таблицы action_logs"""
    table_name = 'action_logs'
    existing_tables = get_existing_tables()
    
    if table_name not in existing_tables:
        logger.info(f"⏭️ Таблица {table_name} не существует, будет создана автоматически")
        return True
    
    logger.info(f"🔍 Проверка таблицы {table_name}...")
    existing_columns = get_existing_columns(table_name)
    
    required_columns = {
        'id': 'INTEGER PRIMARY KEY AUTO_INCREMENT',
        'job_id': 'INTEGER',
        'user_id': 'BIGINT',
        'action': 'VARCHAR(100) NOT NULL',
        'details': 'JSON',
        'timestamp': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
    }
    
    added_count = 0
    with engine.connect() as conn:
        for col_name, col_definition in required_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_definition}"
                    conn.execute(text(sql))
                    conn.commit()
                    logger.info(f"✅ Добавлена колонка {table_name}.{col_name}")
                    added_count += 1
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось добавить колонку {table_name}.{col_name}: {e}")
    
    if added_count > 0:
        logger.info(f"✅ Миграция {table_name}: добавлено {added_count} колонок")
    else:
        logger.info(f"✅ Таблица {table_name} актуальна")
    
    return True


def run_all_migrations():
    """Запускает все миграции"""
    logger.info("=" * 60)
    logger.info("🔄 ЗАПУСК МИГРАЦИЙ БАЗЫ ДАННЫХ")
    logger.info("=" * 60)
    
    try:
        # Сначала создаем все таблицы, если их нет
        create_all_tables()
        
        # Затем запускаем миграции для каждой таблицы
        migrate_users_table()
        migrate_jobs_table()
        migrate_job_responses_table()
        migrate_ratings_table()
        migrate_resumes_table()
        migrate_action_logs_table()
        
        logger.info("=" * 60)
        logger.info("✅ ВСЕ МИГРАЦИИ УСПЕШНО ВЫПОЛНЕНЫ")
        logger.info("=" * 60)
        
        return True
    
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ ОШИБКА ПРИ ВЫПОЛНЕНИИ МИГРАЦИЙ: {e}")
        logger.error("=" * 60)
        return False


def check_database_connection():
    """Проверяет подключение к базе данных"""
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            logger.info("✅ Подключение к базе данных успешно")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к базе данных: {e}")
        return False


if __name__ == "__main__":
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Проверка подключения
    if check_database_connection():
        # Запуск миграций
        run_all_migrations()
    else:
        logger.error("Не удалось подключиться к базе данных. Миграции не выполнены.")