"""
Файл запуска бота Elix с модульной системой
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PYTHONPATH
current_dir = Path(__file__).resolve().parent
root_dir = current_dir
sys.path.append(str(root_dir))

# Настраиваем логирование
log_dir = root_dir / 'logs'
if not log_dir.exists():
    log_dir.mkdir(parents=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_dir / 'bot.txt')
    ]
)
logger = logging.getLogger('elix_bot')

# Импортируем функцию запуска бота
try:
    from bot.main import start_bot
    logger.info("Импорт функции запуска успешен")
except ImportError as e:
    logger.error(f"Ошибка импорта: {e}")
    sys.exit(1)

if __name__ == "__main__":
    try:
        logger.info("Запуск бота Elix...")
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}")
        import traceback
        logger.error(traceback.format_exc())