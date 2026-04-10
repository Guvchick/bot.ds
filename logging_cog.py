"""
Ког для логирования событий сервера в боте Elix
"""
import asyncio
import datetime
from typing import Optional

import discord
from discord.ext import commands

from db import get_setting


class LoggingCog(commands.Cog):
    def __init__(self, bot, module=None):
        self.bot = bot
        # Отслеживаем недавно забаненных, чтобы on_member_remove не логировал их как кик
        self._recent_bans: set = set()

    # ── вспомогательные ────────────────────────────────────────────────────────

    async def _log_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        channel_id = await get_setting(str(guild.id), "mod_log_channel")
        if not channel_id:
            return None
        try:
            return guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            return None

    async def _send(self, guild: discord.Guild, embed: discord.Embed) -> None:
        ch = await self._log_channel(guild)
        if ch:
            try:
                await ch.send(embed=embed)
            except discord.Forbidden:
                pass

    # ── сообщения ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        embed = discord.Embed(
            title="🗑️ Сообщение удалено",
            description=f"**Канал:** {message.channel.mention}\n**Автор:** {message.author.mention}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        if message.content:
            embed.add_field(
                name="Содержимое",
                value=message.content[:1024],
                inline=False,
            )
        if message.attachments:
            embed.add_field(
                name="Вложения",
                value="\n".join(f"📎 `{a.filename}` ({a.size} байт)" for a in message.attachments),
                inline=False,
            )
        embed.set_author(
            name=f"{message.author} ({message.author.id})",
            icon_url=message.author.display_avatar.url,
        )
        await self._send(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild:
            return
        if before.content == after.content:
            return

        embed = discord.Embed(
            title="✏️ Сообщение изменено",
            description=(
                f"**Канал:** {before.channel.mention}\n"
                f"**Автор:** {before.author.mention}\n"
                f"**[Перейти к сообщению]({after.jump_url})**"
            ),
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="До",    value=before.content[:1024] or "*пусто*", inline=False)
        embed.add_field(name="После", value=after.content[:1024]  or "*пусто*", inline=False)
        embed.set_author(
            name=f"{before.author} ({before.author.id})",
            icon_url=before.author.display_avatar.url,
        )
        await self._send(before.guild, embed)

    # ── голосовые каналы ───────────────────────────────────────────────────────

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
            embed = discord.Embed(
                title="🔊 Вход в голосовой канал",
                description=f"{member.mention} подключился к **{after.channel.name}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )
        elif before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title="🔇 Выход из голосового канала",
                description=f"{member.mention} отключился от **{before.channel.name}**",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
        elif before.channel != after.channel:
            embed = discord.Embed(
                title="🔄 Смена голосового канала",
                description=(
                    f"{member.mention} перешёл из **{before.channel.name}** → **{after.channel.name}**"
                ),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow(),
            )
        else:
            return  # Мьют/анмьют в войсе — не логируем

        embed.set_author(name=f"{member} ({member.id})", icon_url=member.display_avatar.url)
        await self._send(member.guild, embed)

    # ── бан ────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        self._recent_bans.add(user.id)

        embed = discord.Embed(
            title="🔨 Участник забанен",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)

        if guild.me.guild_permissions.view_audit_log:
            try:
                await asyncio.sleep(0.5)
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                    if entry.target.id == user.id:
                        embed.add_field(name="Модератор", value=entry.user.mention, inline=True)
                        if entry.reason:
                            embed.add_field(name="Причина", value=entry.reason, inline=False)
                        break
            except discord.Forbidden:
                pass

        await self._send(guild, embed)

        await asyncio.sleep(5)
        self._recent_bans.discard(user.id)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        embed = discord.Embed(
            title="✅ Бан снят",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)

        if guild.me.guild_permissions.view_audit_log:
            try:
                await asyncio.sleep(0.5)
                async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                    if entry.target.id == user.id:
                        embed.add_field(name="Модератор", value=entry.user.mention, inline=True)
                        break
            except discord.Forbidden:
                pass

        await self._send(guild, embed)

    # ── кик ────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Ждём, пока аудит-лог обновится, и пока on_member_ban пометит бан
        await asyncio.sleep(1)

        if member.id in self._recent_bans:
            return  # Это бан, уже залогировали выше

        if not member.guild.me.guild_permissions.view_audit_log:
            return

        try:
            async for entry in member.guild.audit_logs(
                limit=5,
                action=discord.AuditLogAction.kick,
                after=datetime.datetime.utcnow() - datetime.timedelta(seconds=10),
            ):
                if entry.target.id == member.id:
                    embed = discord.Embed(
                        title="👢 Участник кикнут",
                        color=discord.Color.orange(),
                        timestamp=discord.utils.utcnow(),
                    )
                    embed.set_author(
                        name=f"{member} ({member.id})",
                        icon_url=member.display_avatar.url,
                    )
                    embed.add_field(name="Модератор", value=entry.user.mention, inline=True)
                    if entry.reason:
                        embed.add_field(name="Причина", value=entry.reason, inline=False)
                    await self._send(member.guild, embed)
                    return
        except discord.Forbidden:
            pass

    # ── мьют (тайм-аут) ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.timed_out_until == after.timed_out_until:
            return

        if after.timed_out_until is not None:
            until_ts = int(after.timed_out_until.timestamp())
            embed = discord.Embed(
                title="🔇 Участник замьючен",
                description=f"{after.mention} получил тайм-аут до <t:{until_ts}:F>",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
        else:
            embed = discord.Embed(
                title="🔊 Мьют снят",
                description=f"С {after.mention} снят тайм-аут",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow(),
            )

        embed.set_author(name=f"{after} ({after.id})", icon_url=after.display_avatar.url)

        if after.guild.me.guild_permissions.view_audit_log:
            try:
                await asyncio.sleep(0.5)
                async for entry in after.guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.member_update
                ):
                    if entry.target.id == after.id:
                        embed.add_field(name="Модератор", value=entry.user.mention, inline=True)
                        if entry.reason:
                            embed.add_field(name="Причина", value=entry.reason, inline=False)
                        break
            except discord.Forbidden:
                pass

        await self._send(after.guild, embed)
