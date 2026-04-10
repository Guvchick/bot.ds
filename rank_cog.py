"""
Ког для системы рангов в боте Elix
"""
import discord
from discord.ext import commands
import asyncio
import time
import datetime
import math
from typing import Dict, Any, List, Optional
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import aiosqlite
import os

class RankSystemCog(commands.Cog):
    """Система рангов и уровней для участников сервера"""
    
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module
        self.db_path = os.path.join("data", "bot.db")
        
        # Кэш для отслеживания сообщений пользователей
        self.message_cooldowns = {}
        if self.module:
            self.message_cooldowns = self.module.cooldowns
        
        # Кэш для отслеживания голосовых каналов
        self.voice_sessions = {}
        if self.module:
            self.voice_sessions = self.module.voice_sessions
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Обработчик сообщений для начисления XP"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем ботов
        if message.author.bot:
            return
        
        # Игнорируем личные сообщения
        if not message.guild:
            return
        
        # Проверяем, находится ли канал в списке игнорируемых
        if self.module and self.module.settings.get("ignore_bot_channels", True):
            # Проверка по имени или правам канала
            if message.channel.name.lower() in ["bot", "bots", "команды", "commands"]:
                return
        
        # Проверяем кулдаун
        if self.is_on_cooldown(message.author.id):
            return
        
        # Начисляем XP
        xp_amount = self.module.settings.get("xp_per_message", 5) if self.module else 5
        await self.add_xp(message.author.id, message.guild.id, xp_amount)
        
        # Увеличиваем счетчик сообщений
        await self.increment_message_count(message.author.id, message.guild.id)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Обработчик голосовых каналов для начисления XP"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем ботов
        if member.bot:
            return
        
        # Пользователь присоединился к голосовому каналу
        if before.channel is None and after.channel is not None:
            # Начинаем отслеживание сессии
            if self.module:
                self.module.start_voice_session(member.id)
            else:
                self.voice_sessions[member.id] = time.time()
        
        # Пользователь вышел из голосового канала
        elif before.channel is not None and after.channel is None:
            # Завершаем отслеживание сессии и начисляем XP
            duration = 0
            if self.module:
                duration = self.module.end_voice_session(member.id)
            elif member.id in self.voice_sessions:
                duration = time.time() - self.voice_sessions.pop(member.id)
            
            if duration > 0:
                # Начисляем XP за каждую минуту в голосовом канале
                minutes = duration / 60
                xp_per_minute = self.module.settings.get("xp_per_minute_voice", 1) if self.module else 1
                xp_amount = int(minutes * xp_per_minute)
                
                if xp_amount > 0:
                    await self.add_xp(member.id, member.guild.id, xp_amount)
                    await self.increment_voice_time(member.id, member.guild.id, int(duration))
    
    async def add_xp(self, user_id: int, guild_id: int, amount: int) -> bool:
        """Добавляет XP пользователю и проверяет повышение уровня"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Проверяем, существует ли запись для этого пользователя
                async with db.execute(
                    "SELECT xp, level FROM users WHERE user_id = ? AND guild_id = ?", 
                    (str(user_id), str(guild_id))
                ) as cursor:
                    row = await cursor.fetchone()
                    
                    if row:
                        # Обновляем существующую запись
                        current_xp, current_level = row
                        new_xp = current_xp + amount
                        
                        # Проверяем, повысился ли уровень
                        new_level = current_level
                        xp_needed = self.calculate_xp_for_next_level(current_level)
                        
                        if new_xp >= xp_needed:
                            new_level += 1
                            
                            # Отправляем уведомление о повышении уровня
                            if self.module and self.module.settings.get("level_up_notification", True):
                                await self.send_level_up_notification(user_id, guild_id, new_level)
                        
                        # Обновляем запись в БД
                        await db.execute(
                            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
                            (new_xp, new_level, str(user_id), str(guild_id))
                        )
                    else:
                        # Создаем новую запись
                        await db.execute(
                            "INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(user_id), str(guild_id), amount, 0, 0, 0)
                        )
                
                await db.commit()
                return True
        except Exception as e:
            print(f"Ошибка при добавлении XP: {e}")
            return False
    
    async def increment_message_count(self, user_id: int, guild_id: int) -> bool:
        """Увеличивает счетчик сообщений пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET messages = messages + 1 WHERE user_id = ? AND guild_id = ?",
                    (str(user_id), str(guild_id))
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Ошибка при обновлении счетчика сообщений: {e}")
            return False
    
    async def increment_voice_time(self, user_id: int, guild_id: int, seconds: int) -> bool:
        """Увеличивает время в голосовых каналах для пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET voice_time = voice_time + ? WHERE user_id = ? AND guild_id = ?",
                    (seconds, str(user_id), str(guild_id))
                )
                await db.commit()
                return True
        except Exception as e:
            print(f"Ошибка при обновлении времени в голосовых каналах: {e}")
            return False
    
    async def get_user_stats(self, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        """Получает статистику пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT xp, level, messages, voice_time FROM users WHERE user_id = ? AND guild_id = ?",
                    (str(user_id), str(guild_id))
                ) as cursor:
                    row = await cursor.fetchone()
                    
                    if row:
                        xp, level, messages, voice_time = row
                        next_level_xp = self.calculate_xp_for_next_level(level)
                        
                        return {
                            "xp": xp,
                            "level": level,
                            "messages": messages,
                            "voice_time": voice_time,
                            "next_level_xp": next_level_xp
                        }
                    else:
                        # Создаем запись для пользователя, если её нет
                        await db.execute(
                            "INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time) VALUES (?, ?, ?, ?, ?, ?)",
                            (str(user_id), str(guild_id), 0, 0, 0, 0)
                        )
                        await db.commit()
                        
                        return {
                            "xp": 0,
                            "level": 0,
                            "messages": 0,
                            "voice_time": 0,
                            "next_level_xp": self.calculate_xp_for_next_level(0)
                        }
        except Exception as e:
            print(f"Ошибка при получении статистики пользователя: {e}")
            return None
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Получает лидеров сервера по XP"""
        leaderboard = []
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    """SELECT user_id, xp, level, messages, voice_time 
                       FROM users 
                       WHERE guild_id = ? 
                       ORDER BY level DESC, xp DESC 
                       LIMIT ?""",
                    (str(guild_id), limit)
                ) as cursor:
                    rank = 1
                    async for row in cursor:
                        user_id, xp, level, messages, voice_time = row
                        
                        # Получаем объект пользователя
                        user = self.bot.get_user(int(user_id))
                        if not user:
                            try:
                                user = await self.bot.fetch_user(int(user_id))
                            except:
                                user_name = f"Пользователь #{user_id}"
                        
                        user_name = user.name if user else f"Пользователь #{user_id}"
                        
                        leaderboard.append({
                            "rank": rank,
                            "user_id": user_id,
                            "user_name": user_name,
                            "xp": xp,
                            "level": level,
                            "messages": messages,
                            "voice_time": voice_time
                        })
                        
                        rank += 1
        
        except Exception as e:
            print(f"Ошибка при получении таблицы лидеров: {e}")
        
        return leaderboard
    
    def calculate_xp_for_next_level(self, level: int) -> int:
        """Расчет необходимого количества XP для следующего уровня"""
        if self.module:
            return self.module.calculate_xp_for_next_level(level)
        else:
            # Формула по умолчанию
            return 300 * (level + 1)
    
    def is_on_cooldown(self, user_id: int) -> bool:
        """Проверяет, находится ли пользователь на кулдауне для получения XP"""
        if self.module:
            return self.module.is_on_cooldown(user_id)
        else:
            # Логика кулдауна по умолчанию (60 секунд)
            current_time = time.time()
            if user_id in self.message_cooldowns:
                last_time = self.message_cooldowns[user_id]
                if current_time - last_time < 60:
                    return True
            
            # Обновляем время последнего получения XP
            self.message_cooldowns[user_id] = current_time
            return False
    
    async def send_level_up_notification(self, user_id: int, guild_id: int, new_level: int) -> None:
        """Отправляет уведомление о повышении уровня"""
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            user = guild.get_member(user_id)
            if not user:
                return
            
            # Ищем канал для уведомлений
            channel = None
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
            
            if not channel:
                return
            
            # Создаем эмбед с поздравлением
            embed = discord.Embed(
                title="🎉 Повышение уровня!",
                description=f"{user.mention} достиг уровня **{new_level}**!",
                color=discord.Color.green()
            )
            
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Ошибка при отправке уведомления о повышении уровня: {e}")
    
    @commands.command(name="rank", aliases=["level"])
    async def rank_command(self, ctx, member: discord.Member = None):
        """Показывает ранг и статистику пользователя"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль рангов отключен.")
            return
        
        # Если не указан участник, используем автора сообщения
        if not member:
            member = ctx.author
        
        # Получаем статистику пользователя
        stats = await self.get_user_stats(member.id, ctx.guild.id)
        if not stats:
            await ctx.send("❌ Не удалось получить статистику пользователя.")
            return
        
        # Форматируем время в голосовых каналах
        voice_time = stats["voice_time"]
        hours, remainder = divmod(voice_time, 3600)
        minutes, seconds = divmod(remainder, 60)
        voice_time_formatted = f"{hours}ч {minutes}м {seconds}с"
        
        # Создаем эмбед со статистикой
        embed = discord.Embed(
            title=f"Статистика {member.display_name}",
            color=member.color or discord.Color.blue()
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        
        # Добавляем информацию об уровне и XP
        embed.add_field(
            name="Уровень",
            value=f"**{stats['level']}** ({stats['xp']}/{stats['next_level_xp']} XP)",
            inline=False
        )
        
        # Визуализация прогресса XP
        progress = min(stats['xp'] / max(stats['next_level_xp'], 1), 1)
        progress_bar = '█' * int(round(progress * 10)) + '░' * (10 - int(round(progress * 10)))
        embed.add_field(
            name="Прогресс",
            value=f"`{progress_bar}` {int(progress * 100)}%",
            inline=False
        )
        
        # Добавляем статистику сообщений и времени в голосовых каналах
        embed.add_field(name="Сообщений", value=f"{stats['messages']}", inline=True)
        embed.add_field(name="Время в голосовых каналах", value=voice_time_formatted, inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name="leaderboard", aliases=["top", "leaders"])
    async def leaderboard_command(self, ctx, limit: int = 10):
        """Показывает таблицу лидеров сервера"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль рангов отключен.")
            return
        
        # Ограничиваем размер таблицы
        if limit < 1:
            limit = 10
        elif limit > 25:
            limit = 25
        
        # Получаем таблицу лидеров
        leaderboard = await self.get_leaderboard(ctx.guild.id, limit)
        
        if not leaderboard:
            await ctx.send("❌ Таблица лидеров пуста.")
            return
        
        # Создаем эмбед с таблицей лидеров
        embed = discord.Embed(
            title=f"🏆 Таблица лидеров {ctx.guild.name}",
            description="Самые активные участники сервера:",
            color=discord.Color.gold()
        )
        
        # Форматируем строки с лидерами
        for entry in leaderboard:
            rank_emoji = "🥇" if entry["rank"] == 1 else "🥈" if entry["rank"] == 2 else "🥉" if entry["rank"] == 3 else f"{entry['rank']}."
            embed.add_field(
                name=f"{rank_emoji} {entry['user_name']}",
                value=f"Уровень: **{entry['level']}**\nXP: **{entry['xp']}**\nСообщений: **{entry['messages']}**",
                inline=False
            )
        
        await ctx.send(embed=embed)
    
    @commands.command(name="voicetime", aliases=["vt"])
    async def voice_time_command(self, ctx, member: discord.Member = None):
        """Показывает время, проведенное в голосовых каналах"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль рангов отключен.")
            return
        
        # Если не указан участник, используем автора сообщения
        if not member:
            member = ctx.author
        
        # Получаем статистику пользователя
        stats = await self.get_user_stats(member.id, ctx.guild.id)
        if not stats:
            await ctx.send("❌ Не удалось получить статистику пользователя.")
            return
        
        # Форматируем время в голосовых каналах
        voice_time = stats["voice_time"]
        days, remainder = divmod(voice_time, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Создаем красивое форматирование
        parts = []
        if days > 0:
            parts.append(f"{days} дн.")
        if hours > 0 or days > 0:
            parts.append(f"{hours} ч.")
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(f"{minutes} мин.")
        parts.append(f"{seconds} сек.")
        
        voice_time_formatted = " ".join(parts)
        
        # Создаем эмбед с информацией
        embed = discord.Embed(
            title=f"Время в голосовых каналах",
            description=f"{member.mention} провел(а) в голосовых каналах:\n**{voice_time_formatted}**",
            color=member.color or discord.Color.blue()
        )
        
        embed.set_thumbnail(url=member.display_avatar.url)
        
        await ctx.send(embed=embed)