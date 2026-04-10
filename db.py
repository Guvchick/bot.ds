"""
HTTP-клиент для Go DB-сервиса бота Elix.
Все операции с БД выполняются через REST API Go-микросервиса.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("db_client")

_BASE = os.getenv("DB_SERVICE_URL", "http://db-service:8080")
_session: Optional[aiohttp.ClientSession] = None


async def _sess() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


def _encode(value: Any) -> str:
    """Кодирует Python-значение в строку для хранения."""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _decode(raw: str) -> Any:
    """Декодирует строку из БД обратно в Python-тип."""
    try:
        return json.loads(raw)
    except Exception:
        return raw


# ── settings ──────────────────────────────────────────────────────────────────

async def get_setting(guild_id, key: str, default=None) -> Any:
    try:
        s = await _sess()
        async with s.get(f"{_BASE}/settings/{guild_id}/{key}") as r:
            if r.status == 404:
                return default
            if r.status != 200:
                return default
            data = await r.json()
            return _decode(data["value"])
    except Exception as e:
        logger.error(f"get_setting [{key}]: {e}")
        return default


async def set_setting(guild_id, key: str, value: Any) -> bool:
    try:
        s = await _sess()
        async with s.put(
            f"{_BASE}/settings/{guild_id}/{key}",
            json={"value": _encode(value)},
        ) as r:
            return r.status == 200
    except Exception as e:
        logger.error(f"set_setting [{key}]: {e}")
        return False


async def delete_setting(guild_id, key: str) -> bool:
    try:
        s = await _sess()
        async with s.delete(f"{_BASE}/settings/{guild_id}/{key}") as r:
            return r.status == 200
    except Exception as e:
        logger.error(f"delete_setting [{key}]: {e}")
        return False


async def get_all_settings(guild_id) -> Dict[str, Any]:
    try:
        s = await _sess()
        async with s.get(f"{_BASE}/settings/{guild_id}") as r:
            if r.status != 200:
                return {}
            raw: dict = await r.json()
            return {k: _decode(v) for k, v in raw.items()}
    except Exception as e:
        logger.error(f"get_all_settings: {e}")
        return {}


# ── users ─────────────────────────────────────────────────────────────────────

async def get_user(user_id, guild_id) -> Optional[Dict[str, Any]]:
    try:
        s = await _sess()
        async with s.get(f"{_BASE}/users/{guild_id}/{user_id}") as r:
            if r.status != 200:
                return None
            data = await r.json()
            data["next_level_xp"] = 300 * (data["level"] + 1)
            return data
    except Exception as e:
        logger.error(f"get_user: {e}")
        return None


async def add_xp(user_id, guild_id, amount: int) -> Dict[str, Any]:
    """Добавляет XP. Возвращает {"level": N, "level_up": bool}."""
    try:
        s = await _sess()
        async with s.post(
            f"{_BASE}/users/{guild_id}/{user_id}/xp",
            json={"amount": amount},
        ) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.error(f"add_xp: {e}")
    return {"level": 0, "level_up": False}


async def incr_messages(user_id, guild_id) -> None:
    try:
        s = await _sess()
        async with s.post(f"{_BASE}/users/{guild_id}/{user_id}/messages"):
            pass
    except Exception as e:
        logger.error(f"incr_messages: {e}")


async def add_voice_time(user_id, guild_id, seconds: int) -> None:
    try:
        s = await _sess()
        async with s.post(
            f"{_BASE}/users/{guild_id}/{user_id}/voice",
            json={"seconds": seconds},
        ):
            pass
    except Exception as e:
        logger.error(f"add_voice_time: {e}")


async def get_leaderboard(guild_id, limit: int = 10) -> List[Dict[str, Any]]:
    try:
        s = await _sess()
        async with s.get(
            f"{_BASE}/leaderboard/{guild_id}",
            params={"limit": limit},
        ) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.error(f"get_leaderboard: {e}")
    return []


async def trigger_backup() -> bool:
    try:
        s = await _sess()
        async with s.post(f"{_BASE}/backup") as r:
            return r.status in (200, 202)
    except Exception as e:
        logger.error(f"trigger_backup: {e}")
    return False


# ── lifecycle ─────────────────────────────────────────────────────────────────

async def init_db() -> bool:
    """Ожидает доступности Go DB-сервиса."""
    timeout = aiohttp.ClientTimeout(total=3)
    for attempt in range(15):
        try:
            s = await _sess()
            async with s.get(f"{_BASE}/health", timeout=timeout) as r:
                if r.status == 200:
                    logger.info("Go DB-сервис доступен")
                    return True
        except Exception:
            pass
        logger.warning(f"Go DB-сервис недоступен, попытка {attempt + 1}/15...")
        await asyncio.sleep(3)
    raise RuntimeError("Go DB-сервис не ответил после 15 попыток")


async def migrate_data():
    """Заглушка для совместимости — таблицы создаёт Go-сервис."""
    pass
