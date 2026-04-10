"""
Точка входа бота Elix — инициализация и запуск
"""
import os
import logging
import discord
from discord.ext import commands

from db import init_db, migrate_data
from rank_cog import RankSystemCog
from logging_cog import LoggingCog
from dashboard import DashboardCog

logger = logging.getLogger('elix_bot')


async def start_bot():
    """Инициализирует и запускает бота"""
    # Инициализируем базу данных
    await init_db()
    await migrate_data()

    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения DISCORD_TOKEN не задана")

    prefix = os.getenv("PREFIX", "!")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True

    bot = commands.Bot(command_prefix=prefix, intents=intents)

    @bot.event
    async def on_ready():
        logger.info(f"Бот запущен как {bot.user} (ID: {bot.user.id})")

    await bot.add_cog(RankSystemCog(bot))
    await bot.add_cog(LoggingCog(bot))
    await bot.add_cog(DashboardCog(bot))

    # Музыкальный ког требует youtube_dl / yt-dlp — добавляем если доступен
    try:
        from music_cog import MusicCog
        await bot.add_cog(MusicCog(bot))
        logger.info("Музыкальный модуль загружен")
    except Exception as e:
        logger.warning(f"Музыкальный модуль не загружен: {e}")

    await bot.start(token)
