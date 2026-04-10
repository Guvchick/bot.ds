"""
Ког системы рангов и XP для бота Elix (слеш-команды)
"""
import time
from typing import Dict, Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from db import get_setting, get_user, add_xp, incr_messages, add_voice_time, get_leaderboard


class RankSystemCog(commands.Cog):
    def __init__(self, bot, module=None):
        self.bot = bot
        self._cooldowns: Dict[int, float] = {}
        self._voice_sessions: Dict[int, float] = {}

    # ── кулдаун XP ────────────────────────────────────────────────────────────

    def _is_on_cooldown(self, user_id: int, cooldown: int = 60) -> bool:
        now = time.time()
        if now - self._cooldowns.get(user_id, 0) < cooldown:
            return True
        self._cooldowns[user_id] = now
        return False

    # ── уведомление о новом уровне ────────────────────────────────────────────

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

    # ── слушатели ─────────────────────────────────────────────────────────────

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
        result = await add_xp(message.author.id, message.guild.id, int(xp_amount))
        await incr_messages(message.author.id, message.guild.id)

        if result.get("level_up"):
            notify = await get_setting(str(message.guild.id), "level_up_notification", True)
            if notify:
                await self._notify_level_up(message.author.id, message.guild.id, result["level"])

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
            duration = int(time.time() - start)
            xp_per_min = await get_setting(str(member.guild.id), "xp_per_minute_voice", 1)
            xp_amount = int(duration / 60 * int(xp_per_min))
            if xp_amount > 0:
                result = await add_xp(member.id, member.guild.id, xp_amount)
                if result.get("level_up"):
                    notify = await get_setting(str(member.guild.id), "level_up_notification", True)
                    if notify:
                        await self._notify_level_up(member.id, member.guild.id, result["level"])
            if duration > 0:
                await add_voice_time(member.id, member.guild.id, duration)

    # ── слеш-команды ──────────────────────────────────────────────────────────

    @app_commands.command(name="rank", description="Показать ранг пользователя")
    @app_commands.describe(member="Пользователь (по умолчанию вы)")
    async def rank_command(
        self,
        interaction: discord.Interaction,
        member: discord.Member = None,
    ):
        target = member or interaction.user
        stats = await get_user(target.id, interaction.guild_id)
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
        board = await get_leaderboard(interaction.guild_id, limit)
        if not board:
            await interaction.response.send_message("❌ Таблица лидеров пуста.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🏆 Таблица лидеров {interaction.guild.name}",
            color=discord.Color.gold(),
        )
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        for i, e in enumerate(board, 1):
            icon = medals.get(i, f"{i}.")
            user = self.bot.get_user(int(e["user_id"]))
            name = user.name if user else f"#{e['user_id']}"
            embed.add_field(
                name=f"{icon} {name}",
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
        stats = await get_user(target.id, interaction.guild_id)
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
