"""
Утилиты для работы с базой данных (PostgreSQL) бота Elix
"""
import asyncpg
import os
import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger('db_utils')

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "db"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "elixbot"),
            user=os.getenv("POSTGRES_USER", "elixbot"),
            password=os.getenv("POSTGRES_PASSWORD", "changeme"),
            min_size=2,
            max_size=10,
        )
    return _pool


async def init_db() -> bool:
    """Создаёт таблицы если не существуют"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                guild_id TEXT NOT NULL,
                key      TEXT NOT NULL,
                value    TEXT,
                PRIMARY KEY (guild_id, key)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS module_settings (
                guild_id      TEXT NOT NULL,
                module_name   TEXT NOT NULL,
                setting_name  TEXT NOT NULL,
                setting_value TEXT,
                PRIMARY KEY (guild_id, module_name, setting_name)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id    TEXT   NOT NULL,
                guild_id   TEXT   NOT NULL,
                xp         BIGINT DEFAULT 0,
                level      INT    DEFAULT 0,
                messages   INT    DEFAULT 0,
                voice_time BIGINT DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
    logger.info("База данных инициализирована")
    return True


def _encode(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def _decode(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


async def get_setting(guild_id: str, key: str, default=None) -> Any:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM settings WHERE guild_id = $1 AND key = $2",
                str(guild_id), key,
            )
            if row:
                return _decode(row["value"])
            return default
    except Exception as e:
        logger.error(f"Ошибка получения настройки {key}: {e}")
        return default


async def set_setting(guild_id: str, key: str, value: Any) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO settings (guild_id, key, value)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id, key) DO UPDATE SET value = EXCLUDED.value""",
                str(guild_id), key, _encode(value),
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка установки настройки {key}: {e}")
        return False


async def delete_setting(guild_id: str, key: str) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM settings WHERE guild_id = $1 AND key = $2",
                str(guild_id), key,
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка удаления настройки {key}: {e}")
        return False


async def get_all_settings(guild_id: str) -> Dict[str, Any]:
    result = {}
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value FROM settings WHERE guild_id = $1",
                str(guild_id),
            )
            for row in rows:
                result[row["key"]] = _decode(row["value"])
    except Exception as e:
        logger.error(f"Ошибка получения всех настроек гильдии {guild_id}: {e}")
    return result


async def get_module_setting(
    guild_id: str, module_name: str, setting_name: str, default=None
) -> Any:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT setting_value FROM module_settings
                   WHERE guild_id = $1 AND module_name = $2 AND setting_name = $3""",
                str(guild_id), module_name, setting_name,
            )
            if row:
                return _decode(row["setting_value"])
            return default
    except Exception as e:
        logger.error(f"Ошибка получения настройки модуля {module_name}.{setting_name}: {e}")
        return default


async def set_module_setting(
    guild_id: str, module_name: str, setting_name: str, value: Any
) -> bool:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO module_settings (guild_id, module_name, setting_name, setting_value)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (guild_id, module_name, setting_name)
                   DO UPDATE SET setting_value = EXCLUDED.setting_value""",
                str(guild_id), module_name, setting_name, _encode(value),
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка установки настройки модуля {module_name}.{setting_name}: {e}")
        return False


async def get_all_module_settings(guild_id: str, module_name: str) -> Dict[str, Any]:
    result = {}
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT setting_name, setting_value FROM module_settings
                   WHERE guild_id = $1 AND module_name = $2""",
                str(guild_id), module_name,
            )
            for row in rows:
                result[row["setting_name"]] = _decode(row["setting_value"])
    except Exception as e:
        logger.error(f"Ошибка получения настроек модуля {module_name}: {e}")
    return result


async def migrate_data():
    """Нет данных для миграции — БД на PostgreSQL с нуля."""
    pass
