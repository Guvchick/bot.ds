"""
Ког системы рангов и XP для бота Elix (слеш-команды)
"""
import time
import datetime
from typing import Dict, Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from db import get_pool, get_setting


class RankSystemCog(commands.Cog):
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module
        self._cooldowns: Dict[int, float] = {}  # user_id → timestamp

    # ── вспомогательные ────────────────────────────────────────────────────────

    def _xp_for_next_level(self, level: int) -> int:
        return 300 * (level + 1)

    def _is_on_cooldown(self, user_id: int, cooldown: int = 60) -> bool:
        now = time.time()
        last = self._cooldowns.get(user_id, 0)
        if now - last < cooldown:
            return True
        self._cooldowns[user_id] = now
        return False

    # ── XP ─────────────────────────────────────────────────────────────────────

    async def _add_xp(self, user_id: int, guild_id: int, amount: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT xp, level FROM users WHERE user_id = $1 AND guild_id = $2",
                str(user_id), str(guild_id),
            )
            if row:
                new_xp = row["xp"] + amount
                new_level = row["level"]
                if new_xp >= self._xp_for_next_level(new_level):
                    new_level += 1
                    notify = await get_setting(str(guild_id), "level_up_notification", True)
                    if notify:
                        await self._notify_level_up(user_id, guild_id, new_level)
                await conn.execute(
                    "UPDATE users SET xp = $1, level = $2 WHERE user_id = $3 AND guild_id = $4",
                    new_xp, new_level, str(user_id), str(guild_id),
                )
            else:
                await conn.execute(
                    """INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time)
                       VALUES ($1, $2, $3, 0, 0, 0)
                       ON CONFLICT (user_id, guild_id) DO NOTHING""",
                    str(user_id), str(guild_id), amount,
                )

    async def _inc_messages(self, user_id: int, guild_id: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time)
                   VALUES ($1, $2, 0, 0, 1, 0)
                   ON CONFLICT (user_id, guild_id) DO UPDATE SET messages = users.messages + 1""",
                str(user_id), str(guild_id),
            )

    async def _inc_voice_time(self, user_id: int, guild_id: int, seconds: int) -> None:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time)
                   VALUES ($1, $2, 0, 0, 0, $3)
                   ON CONFLICT (user_id, guild_id) DO UPDATE SET voice_time = users.voice_time + $3""",
                str(user_id), str(guild_id), seconds,
            )

    async def _get_stats(self, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT xp, level, messages, voice_time FROM users WHERE user_id = $1 AND guild_id = $2",
                str(user_id), str(guild_id),
            )
            if row:
                return {
                    "xp": row["xp"],
                    "level": row["level"],
                    "messages": row["messages"],
                    "voice_time": row["voice_time"],
                    "next_level_xp": self._xp_for_next_level(row["level"]),
                }
            # Создаём запись
            await conn.execute(
                """INSERT INTO users (user_id, guild_id, xp, level, messages, voice_time)
                   VALUES ($1, $2, 0, 0, 0, 0) ON CONFLICT DO NOTHING""",
                str(user_id), str(guild_id),
            )
            return {"xp": 0, "level": 0, "messages": 0, "voice_time": 0, "next_level_xp": 300}

    async def _get_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT user_id, xp, level, messages, voice_time
                   FROM users WHERE guild_id = $1
                   ORDER BY level DESC, xp DESC
                   LIMIT $2""",
                str(guild_id), limit,
            )
        result = []
        for i, row in enumerate(rows, 1):
            user = self.bot.get_user(int(row["user_id"]))
            if not user:
                try:
                    user = await self.bot.fetch_user(int(row["user_id"]))
                except Exception:
                    user = None
            result.append({
                "rank": i,
                "user_name": user.name if user else f"#{row['user_id']}",
                "xp": row["xp"],
                "level": row["level"],
                "messages": row["messages"],
            })
        return result

    async def _notify_level_up(self, user_id: int, guild_id: int, new_level: int) -> None:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        member = guild.get_member(user_id)
        if not member:
            return
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                embed = discord.Embed(
                    title="🎉 Повышение уровня!",
                    description=f"{member.mention} достиг уровня **{new_level}**!",
                    color=discord.Color.green(),
                )
                await ch.send(embed=embed)
                return

    # ── слушатели ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        ignore_bot_ch = await get_setting(str(message.guild.id), "ignore_bot_channels", True)
        if ignore_bot_ch and message.channel.name.lower() in ("bot", "bots", "команды", "commands"):
            return

        if self._is_on_cooldown(message.author.id):
            return

        xp_amount = await get_setting(str(message.guild.id), "xp_per_message", 5)
        await self._add_xp(message.author.id, message.guild.id, int(xp_amount))
        await self._inc_messages(message.author.id, message.guild.id)

    _voice_sessions: Dict[int, float] = {}

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        if before.channel is None and after.channel is not None:
            self._voice_sessions[member.id] = time.time()
        elif before.channel is not None and after.channel is None:
            start = self._voice_sessions.pop(member.id, None)
            if start is None:
                return
            duration = time.time() - start
            xp_per_min = await get_setting(str(member.guild.id), "xp_per_minute_voice", 1)
            xp_amount = int(duration / 60 * int(xp_per_min))
            if xp_amount > 0:
                await self._add_xp(member.id, member.guild.id, xp_amount)
                await self._inc_voice_time(member.id, member.guild.id, int(duration))

    # ── слеш-команды ───────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="Показать ранг пользователя")
    @app_commands.describe(member="Пользователь (по умолчанию вы)")
    async def rank_command(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
    ):
        target = member or interaction.user
        stats = await self._get_stats(target.id, interaction.guild_id)
        if not stats:
            await interaction.response.send_message("❌ Не удалось получить статистику.", ephemeral=True)
            return

        vt = stats["voice_time"]
        h, r = divmod(vt, 3600)
        m, s = divmod(r, 60)

        progress = min(stats["xp"] / max(stats["next_level_xp"], 1), 1.0)
        bar = "█" * int(progress * 10) + "░" * (10 - int(progress * 10))

        embed = discord.Embed(
            title=f"Статистика {target.display_name}",
            color=target.color or discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(
            name="Уровень",
            value=f"**{stats['level']}** ({stats['xp']}/{stats['next_level_xp']} XP)",
            inline=False,
        )
        embed.add_field(name="Прогресс", value=f"`{bar}` {int(progress * 100)}%", inline=False)
        embed.add_field(name="Сообщений", value=str(stats["messages"]), inline=True)
        embed.add_field(name="Войс", value=f"{h}ч {m}м {s}с", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Таблица лидеров сервера")
    @app_commands.describe(limit="Количество позиций (1–25)")
    async def leaderboard_command(self, interaction: discord.Interaction, limit: int = 10):
        limit = max(1, min(limit, 25))
        board = await self._get_leaderboard(interaction.guild_id, limit)
        if not board:
            await interaction.response.send_message("❌ Таблица лидеров пуста.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"🏆 Таблица лидеров {interaction.guild.name}",
            color=discord.Color.gold(),
        )
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for e in board:
            icon = medals.get(e["rank"], f"{e['rank']}.")
            embed.add_field(
                name=f"{icon} {e['user_name']}",
                value=f"Уровень: **{e['level']}** | XP: **{e['xp']}** | Сообщений: **{e['messages']}**",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="voicetime", description="Время в голосовых каналах")
    @app_commands.describe(member="Пользователь (по умолчанию вы)")
    async def voice_time_command(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
    ):
        target = member or interaction.user
        stats = await self._get_stats(target.id, interaction.guild_id)
        if not stats:
            await interaction.response.send_message("❌ Не удалось получить статистику.", ephemeral=True)
            return

        vt = stats["voice_time"]
        days, r = divmod(vt, 86400)
        hours, r = divmod(r, 3600)
        minutes, secs = divmod(r, 60)

        parts = []
        if days:    parts.append(f"{days} дн.")
        if hours:   parts.append(f"{hours} ч.")
        if minutes: parts.append(f"{minutes} мин.")
        parts.append(f"{secs} сек.")

        embed = discord.Embed(
            title="Время в голосовых каналах",
            description=f"{target.mention} провёл(а):\n**{' '.join(parts)}**",
            color=target.color or discord.Color.blue(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)
