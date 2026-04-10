"""
Ког модерации и настроек бота Elix (слеш-команды)
"""
import asyncio
import datetime
from typing import Dict, Any

import discord
from discord import app_commands
from discord.ext import commands

from db import get_setting, set_setting, get_all_settings

# ── метаданные всех настраиваемых параметров ───────────────────────────────────
SETTINGS_META: Dict[str, Dict[str, Any]] = {
    "mod_log_channel":       {"type": "int",  "default": None,  "desc": "ID канала для логов модерации"},
    "auto_moderation":       {"type": "bool", "default": True,  "desc": "Автоматическая фильтрация сообщений"},
    "xp_per_message":        {"type": "int",  "default": 5,     "desc": "XP за одно сообщение"},
    "xp_per_minute_voice":   {"type": "int",  "default": 1,     "desc": "XP за минуту в голосовом канале"},
    "level_up_notification": {"type": "bool", "default": True,  "desc": "Уведомление о повышении уровня"},
    "ignore_bot_channels":   {"type": "bool", "default": True,  "desc": "Не начислять XP в бот-каналах"},
    "auto_disconnect":       {"type": "bool", "default": True,  "desc": "Авто-отключение музыки при пустой очереди"},
    "music_timeout":         {"type": "int",  "default": 180,   "desc": "Таймаут авто-отключения музыки (сек)"},
    "volume":                {"type": "int",  "default": 50,    "desc": "Громкость музыки (0–100)"},
}


class DashboardCog(commands.Cog):
    """Ког модерации и настроек"""

    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module

    # ── автомодерация (слушатель) ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        auto_mod = await get_setting(str(message.guild.id), "auto_moderation", True)
        if not auto_mod:
            return

        forbidden: list = await get_setting(str(message.guild.id), "forbidden_words", [])
        if not isinstance(forbidden, list) or not forbidden:
            return

        content_lower = message.content.lower()
        for word in forbidden:
            if str(word).lower() in content_lower:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, ваше сообщение удалено: содержит запрещённое слово.",
                        delete_after=10,
                    )
                    log_channel_id = await get_setting(str(message.guild.id), "mod_log_channel")
                    if log_channel_id:
                        log_ch = message.guild.get_channel(int(log_channel_id))
                        if log_ch:
                            embed = discord.Embed(
                                title="🤖 Автомодерация: сообщение удалено",
                                description=(
                                    f"**Автор:** {message.author.mention}\n"
                                    f"**Канал:** {message.channel.mention}"
                                ),
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow(),
                            )
                            embed.add_field(name="Содержимое", value=message.content[:1024], inline=False)
                            embed.add_field(name="Причина", value=f"Запрещённое слово: `{word}`", inline=False)
                            embed.set_author(
                                name=f"{message.author} ({message.author.id})",
                                icon_url=message.author.display_avatar.url,
                            )
                            await log_ch.send(embed=embed)
                except discord.Forbidden:
                    pass
                return

    # ── /clear ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="clear", description="Удалить сообщения в канале")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="Количество сообщений (1–100)")
    async def clear(self, interaction: discord.Interaction, amount: int = 5):
        if amount < 1 or amount > 100:
            await interaction.response.send_message("❌ Укажите число от 1 до 100.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений.", ephemeral=True)

    # ── /kick ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Кикнуть участника сервера")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.describe(member="Участник для кика", reason="Причина")
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = None,
    ):
        me = interaction.guild.me
        if not me.guild_permissions.kick_members:
            await interaction.response.send_message("❌ У бота нет прав для кика.", ephemeral=True)
            return
        if member.top_role >= me.top_role:
            await interaction.response.send_message(
                "❌ Нельзя кикнуть участника с ролью выше или равной роли бота.", ephemeral=True
            )
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                "❌ Нельзя кикнуть участника с ролью выше или равной вашей.", ephemeral=True
            )
            return

        reason = reason or "Причина не указана"
        await member.kick(reason=f"{interaction.user} ({interaction.user.id}): {reason}")
        await interaction.response.send_message(
            f"✅ Участник {member.mention} кикнут.\nПричина: {reason}"
        )

    # ── /ban ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Забанить участника сервера")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.describe(member="Участник для бана", reason="Причина")
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = None,
    ):
        me = interaction.guild.me
        if not me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ У бота нет прав для бана.", ephemeral=True)
            return
        if member.top_role >= me.top_role:
            await interaction.response.send_message(
                "❌ Нельзя забанить участника с ролью выше или равной роли бота.", ephemeral=True
            )
            return
        if member.top_role >= interaction.user.top_role and interaction.user != interaction.guild.owner:
            await interaction.response.send_message(
                "❌ Нельзя забанить участника с ролью выше или равной вашей.", ephemeral=True
            )
            return

        reason = reason or "Причина не указана"
        await member.ban(
            reason=f"{interaction.user} ({interaction.user.id}): {reason}",
            delete_message_days=1,
        )
        await interaction.response.send_message(
            f"✅ Участник {member.mention} забанен.\nПричина: {reason}"
        )

    # ── /forbidden ─────────────────────────────────────────────────────────────

    forbidden = app_commands.Group(
        name="forbidden",
        description="Управление фильтром запрещённых слов",
        default_permissions=discord.Permissions(manage_messages=True),
    )

    @forbidden.command(name="add", description="Добавить слово в фильтр")
    @app_commands.describe(word="Слово для добавления")
    async def forbidden_add(self, interaction: discord.Interaction, word: str):
        gid = str(interaction.guild_id)
        words: list = await get_setting(gid, "forbidden_words", [])
        if not isinstance(words, list):
            words = []
        word = word.lower().strip()
        if word in words:
            await interaction.response.send_message(
                f"❌ Слово `{word}` уже в списке.", ephemeral=True
            )
            return
        words.append(word)
        await set_setting(gid, "forbidden_words", words)
        await interaction.response.send_message(f"✅ Слово `{word}` добавлено в фильтр.")

    @forbidden.command(name="remove", description="Удалить слово из фильтра")
    @app_commands.describe(word="Слово для удаления")
    async def forbidden_remove(self, interaction: discord.Interaction, word: str):
        gid = str(interaction.guild_id)
        words: list = await get_setting(gid, "forbidden_words", [])
        if not isinstance(words, list):
            words = []
        word = word.lower().strip()
        if word not in words:
            await interaction.response.send_message(
                f"❌ Слово `{word}` не найдено в списке.", ephemeral=True
            )
            return
        words.remove(word)
        await set_setting(gid, "forbidden_words", words)
        await interaction.response.send_message(f"✅ Слово `{word}` удалено из фильтра.")

    @forbidden.command(name="list", description="Показать все запрещённые слова")
    async def forbidden_list(self, interaction: discord.Interaction):
        words: list = await get_setting(str(interaction.guild_id), "forbidden_words", [])
        if not isinstance(words, list) or not words:
            await interaction.response.send_message("📋 Список запрещённых слов пуст.", ephemeral=True)
            return
        embed = discord.Embed(
            title="📋 Запрещённые слова",
            description=", ".join(f"`{w}`" for w in words),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /settings ──────────────────────────────────────────────────────────────

    @app_commands.command(name="settings", description="Просмотр и изменение настроек бота")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(setting="Ключ настройки", value="Новое значение")
    async def settings_cmd(
        self,
        interaction: discord.Interaction,
        setting: str = None,
        value: str = None,
    ):
        gid = str(interaction.guild_id)

        if setting is None:
            db_vals = await get_all_settings(gid)
            embed = discord.Embed(
                title="⚙️ Настройки сервера",
                description="Изменить: `/settings <ключ> <значение>`",
                color=discord.Color.blue(),
            )
            for key, meta in SETTINGS_META.items():
                current = db_vals.get(key, meta["default"])
                embed.add_field(
                    name=f"`{key}`",
                    value=f"{meta['desc']}\nЗначение: **{current}**",
                    inline=False,
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if setting not in SETTINGS_META:
            known = ", ".join(f"`{k}`" for k in SETTINGS_META)
            await interaction.response.send_message(
                f"❌ Неизвестная настройка `{setting}`.\n**Доступные:** {known}",
                ephemeral=True,
            )
            return

        meta = SETTINGS_META[setting]

        if value is None:
            current = await get_setting(gid, setting, meta["default"])
            embed = discord.Embed(title=f"⚙️ `{setting}`", color=discord.Color.blue())
            embed.add_field(name="Описание", value=meta["desc"], inline=False)
            embed.add_field(name="Значение", value=str(current), inline=True)
            embed.add_field(name="Тип", value=meta["type"], inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            if meta["type"] == "bool":
                parsed: Any = value.lower() in ("true", "1", "yes", "да", "вкл", "on")
            elif meta["type"] == "int":
                parsed = int(value)
            else:
                parsed = value
        except ValueError:
            await interaction.response.send_message(
                f"❌ Неверный тип. Ожидается `{meta['type']}`.", ephemeral=True
            )
            return

        await set_setting(gid, setting, parsed)
        await interaction.response.send_message(
            f"✅ Настройка `{setting}` установлена на **{parsed}**."
        )

    # ── /invite ────────────────────────────────────────────────────────────────

    @app_commands.command(name="invite", description="Получить ссылку для добавления бота")
    async def invite(self, interaction: discord.Interaction):
        perms = discord.Permissions(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            add_reactions=True,
            manage_messages=True,
            kick_members=True,
            ban_members=True,
            connect=True,
            speak=True,
            manage_roles=True,
            moderate_members=True,
            view_audit_log=True,
        )
        url = discord.utils.oauth_url(
            self.bot.user.id,
            permissions=perms,
            scopes=("bot", "applications.commands"),
        )
        embed = discord.Embed(
            title="Добавить бота на сервер",
            description=f"[Нажмите здесь, чтобы пригласить бота]({url})",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Требуются права администратора на целевом сервере.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
