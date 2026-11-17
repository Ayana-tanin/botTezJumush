import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from database.db_connection import init_db

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_environment():
    """Проверяет критически важные переменные окружения"""
    import os

    required_vars = ["BOT_TOKEN", "DATABASE_URL"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        logger.critical(f"Отсутствуют следующие переменные окружения: {', '.join(missing)}")
        return False
    return True


async def main():
    """Основная функция, инициализирует бота и запускает его"""
    # Проверяем переменные окружения
    if not check_environment():
        logger.critical("Критические переменные окружения отсутствуют. Бот не может быть запущен.")
        return

    try:
        # Инициализация базы данных
        logger.info("🔧 Инициализация базы данных...")
        
        try:
            db_status = init_db()
            if db_status:
                logger.info("✅ База данных успешно подключена")
            else:
                logger.error("❌ Не удалось подключиться к базе данных")
                return
        except Exception as db_error:
            logger.error(f"❌ Критическая ошибка при инициализации БД: {db_error}")
            raise

        # Создание экземпляра бота
        logger.info("Создание экземпляра бота...")
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

        # Создание диспетчера
        dp = Dispatcher(storage=MemoryStorage())

        # Импортируем роутеры
        from handlers.start import router as start_router
        from handlers.profile import router as profile_router
        from handlers.employer import router as employer_router
        from handlers.applications import router as applications_router
        from handlers.reminders import router as reminders_router
        from handlers.admin import router as admin_router
        
        # Подключаем роутеры
        dp.include_router(start_router)
        dp.include_router(profile_router)
        dp.include_router(employer_router)
        dp.include_router(applications_router)
        dp.include_router(reminders_router)
        dp.include_router(admin_router)

        # Запуск планировщика уведомлений
        async def reminder_scheduler():
            """Планировщик для отправки уведомлений о работе"""
            from services.notification_service import send_work_reminders, check_unconfirmed_jobs
            
            while True:
                try:
                    await send_work_reminders(bot)
                    await check_unconfirmed_jobs(bot)
                    # Проверяем каждые 5 минут
                    await asyncio.sleep(300)
                except Exception as e:
                    logger.error(f"Ошибка в планировщике уведомлений: {e}")
                    await asyncio.sleep(60)  # При ошибке ждем минуту
        
        # Запускаем планировщик в фоне
        asyncio.create_task(reminder_scheduler())
        logger.info("Планировщик уведомлений запущен")

        # Запуск бота
        logger.info("🚀 Запуск бота...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске бота: {str(e)}", exc_info=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.critical(f"Непредвиденная ошибка: {str(e)}", exc_info=True)