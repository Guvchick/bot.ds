"""
Утилиты для работы с базой данных бота Elix
"""
import sqlite3
import aiosqlite
import os
import json
import logging
from typing import Any, Dict, List, Optional, Union

# Настройка логирования
logger = logging.getLogger('db_utils')

# Путь к базе данных
DB_PATH = os.path.join("data", "bot.db")

async def init_db():
    """Инициализирует базу данных и создает необходимые таблицы"""
    # Создаем директорию для БД, если её нет
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Создаем таблицу настроек
        await db.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            guild_id TEXT,
            key TEXT,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        )
        ''')
        
        # Создаем таблицу настроек модулей
        await db.execute('''
        CREATE TABLE IF NOT EXISTS module_settings (
            guild_id TEXT,
            module_name TEXT,
            setting_name TEXT,
            setting_value TEXT,
            PRIMARY KEY (guild_id, module_name, setting_name)
        )
        ''')
        
        # Создаем таблицу пользователей для системы рангов
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT,
            guild_id TEXT,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            voice_time INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        )
        ''')
        
        await db.commit()
    
    logger.info("База данных инициализирована")
    return True

async def get_setting(guild_id: str, key: str, default=None) -> Any:
    """Получает значение настройки из БД"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE guild_id = ? AND key = ?",
                (str(guild_id), key)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    # Пробуем преобразовать строку в нужный тип
                    try:
                        return json.loads(row[0])
                    except:
                        return row[0]
                return default
    except Exception as e:
        logger.error(f"Ошибка получения настройки {key}: {e}")
        return default

async def set_setting(guild_id: str, key: str, value: Any) -> bool:
    """Устанавливает значение настройки в БД"""
    try:
        # Преобразуем сложные объекты в JSON
        if not isinstance(value, str) and not isinstance(value, int) and not isinstance(value, float):
            value = json.dumps(value)
        else:
            value = str(value)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO settings (guild_id, key, value) VALUES (?, ?, ?)",
                (str(guild_id), key, value)
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка установки настройки {key}: {e}")
        return False

async def delete_setting(guild_id: str, key: str) -> bool:
    """Удаляет настройку из БД"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM settings WHERE guild_id = ? AND key = ?",
                (str(guild_id), key)
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления настройки {key}: {e}")
        return False

async def get_module_setting(guild_id: str, module_name: str, setting_name: str, default=None) -> Any:
    """Получает значение настройки модуля из БД"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT setting_value FROM module_settings WHERE guild_id = ? AND module_name = ? AND setting_name = ?",
                (str(guild_id), module_name, setting_name)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    # Пробуем преобразовать строку в нужный тип
                    try:
                        return json.loads(row[0])
                    except:
                        return row[0]
                return default
    except Exception as e:
        logger.error(f"Ошибка получения настройки модуля {module_name}.{setting_name}: {e}")
        return default

async def set_module_setting(guild_id: str, module_name: str, setting_name: str, value: Any) -> bool:
    """Устанавливает значение настройки модуля в БД"""
    try:
        # Преобразуем сложные объекты в JSON
        if not isinstance(value, str) and not isinstance(value, int) and not isinstance(value, float):
            value = json.dumps(value)
        else:
            value = str(value)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR REPLACE INTO module_settings (guild_id, module_name, setting_name, setting_value) VALUES (?, ?, ?, ?)",
                (str(guild_id), module_name, setting_name, value)
            )
            await db.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка установки настройки модуля {module_name}.{setting_name}: {e}")
        return False

async def get_all_module_settings(guild_id: str, module_name: str) -> Dict[str, Any]:
    """Получает все настройки модуля для гильдии"""
    result = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT setting_name, setting_value FROM module_settings WHERE guild_id = ? AND module_name = ?",
                (str(guild_id), module_name)
            ) as cursor:
                async for row in cursor:
                    try:
                        result[row[0]] = json.loads(row[1])
                    except:
                        result[row[0]] = row[1]
    except Exception as e:
        logger.error(f"Ошибка получения настроек модуля {module_name}: {e}")
    
    return result

async def get_all_settings(guild_id: str) -> Dict[str, Any]:
    """Получает все настройки гильдии из БД"""
    result = {}
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT key, value FROM settings WHERE guild_id = ?",
                (str(guild_id),)
            ) as cursor:
                async for row in cursor:
                    try:
                        result[row[0]] = json.loads(row[1])
                    except Exception:
                        result[row[0]] = row[1]
    except Exception as e:
        logger.error(f"Ошибка получения настроек гильдии {guild_id}: {e}")
    return result


async def migrate_data():
    """Мигрирует данные из JSON файлов в SQLite"""
    try:
        # Проверяем, есть ли маркер выполненной миграции
        if await get_setting("global", "migration_completed", False):
            logger.info("Миграция данных уже выполнена.")
            return

        # Миграция настроек сервера
        if os.path.exists("data/settings.json"):
            with open("data/settings.json", "r", encoding="utf-8") as f:
                try:
                    settings = json.load(f)
                    for guild_id, guild_settings in settings.items():
                        for key, value in guild_settings.items():
                            await set_setting(guild_id, key, value)
                    logger.info("Настройки мигрированы из settings.json")
                except Exception as e:
                    logger.error(f"Ошибка миграции настроек: {e}")

        # Миграция данных пользователей
        if os.path.exists("data/users.json"):
            with open("data/users.json", "r", encoding="utf-8") as f:
                try:
                    users = json.load(f)
                    async with aiosqlite.connect(DB_PATH) as db:
                        for guild_id, guild_users in users.items():
                            for user_id, user_data in guild_users.items():
                                await db.execute(
                                    """INSERT OR REPLACE INTO users 
                                    (user_id, guild_id, xp, level, messages, voice_time) 
                                    VALUES (?, ?, ?, ?, ?, ?)""",
                                    (user_id, guild_id, 
                                     user_data.get("xp", 0), 
                                     user_data.get("level", 0), 
                                     user_data.get("messages", 0), 
                                     user_data.get("voice_time", 0))
                                )
                        await db.commit()
                    logger.info("Данные пользователей мигрированы из users.json")
                except Exception as e:
                    logger.error(f"Ошибка миграции данных пользователей: {e}")

        # Устанавливаем маркер выполненной миграции
        await set_setting("global", "migration_completed", True)
        logger.info("Миграция данных завершена.")

    except Exception as e:
        logger.error(f"Ошибка во время миграции данных: {e}")