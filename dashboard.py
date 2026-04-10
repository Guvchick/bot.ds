"""
Ког для панели управления и модерации в боте Elix
"""
import discord
from discord.ext import commands
import asyncio
import datetime
import re
import os
import json
from typing import Dict, Any, List, Optional, Union
import traceback

from db import get_setting, set_setting, get_all_settings

# Описание всех настраиваемых параметров бота
SETTINGS_META: Dict[str, Dict[str, Any]] = {
    "mod_log_channel":        {"type": "int",  "default": None,  "desc": "ID канала для логов модерации"},
    "auto_moderation":        {"type": "bool", "default": True,  "desc": "Автоматическая фильтрация сообщений"},
    "xp_per_message":         {"type": "int",  "default": 5,     "desc": "XP за одно сообщение"},
    "xp_per_minute_voice":    {"type": "int",  "default": 1,     "desc": "XP за минуту в голосовом канале"},
    "level_up_notification":  {"type": "bool", "default": True,  "desc": "Уведомление о повышении уровня"},
    "ignore_bot_channels":    {"type": "bool", "default": True,  "desc": "Не начислять XP в бот-каналах"},
    "auto_disconnect":        {"type": "bool", "default": True,  "desc": "Авто-отключение музыки при пустой очереди"},
    "music_timeout":          {"type": "int",  "default": 180,   "desc": "Таймаут авто-отключения музыки (секунды)"},
    "volume":                 {"type": "int",  "default": 50,    "desc": "Громкость музыки (0–100)"},
}


class DashboardCog(commands.Cog):
    """Ког для панели управления и модерации"""
    
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module
        self.forbidden_words = []
        
        if self.module:
            self.forbidden_words = self.module.forbidden_words
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Обработчик сообщений для автомодерации"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем сообщения от ботов и в ЛС
        if message.author.bot or not message.guild:
            return
        
        # Проверяем, включена ли автомодерация
        if self.module and self.module.settings.get("auto_moderation", True):
            # Проверяем сообщение на нарушения
            check_result = self.module.check_message(message)
            
            if not check_result["valid"]:
                # Удаляем сообщение
                try:
                    await message.delete()
                    
                    # Помечаем сообщение как удаленное автомодерацией
                    if hasattr(self.module, "mark_deleted_by_filter"):
                        self.module.mark_deleted_by_filter(message.id)
                    
                    # Отправляем предупреждение пользователю
                    await message.channel.send(
                        f"{message.author.mention}, ваше сообщение было удалено. "
                        f"Причина: {check_result.get('description', 'нарушение правил сервера')}.",
                        delete_after=10
                    )
                    
                    # Логируем действие в канал модерации
                    log_channel_id = self.module.settings.get("mod_log_channel")
                    if log_channel_id:
                        log_channel = message.guild.get_channel(int(log_channel_id))
                        if log_channel:
                            embed = discord.Embed(
                                title="🔨 Автомодерация: сообщение удалено",
                                description=f"**Автор:** {message.author.mention}\n**Канал:** {message.channel.mention}",
                                color=discord.Color.orange(),
                                timestamp=datetime.datetime.utcnow()
                            )
                            
                            # Добавляем содержимое сообщения
                            if message.content:
                                if len(message.content) > 1024:
                                    embed.add_field(name="Содержимое", value=message.content[:1021] + "...", inline=False)
                                else:
                                    embed.add_field(name="Содержимое", value=message.content, inline=False)
                            
                            # Добавляем причину удаления
                            embed.add_field(name="Причина", value=check_result.get('description', 'нарушение правил сервера'), inline=False)
                            
                            # Устанавливаем автора эмбеда
                            embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
                            
                            await log_channel.send(embed=embed)
                
                except Exception as e:
                    print(f"Ошибка автомодерации: {e}")
    
    @commands.group(name="forbidden", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def forbidden(self, ctx):
        """Команды для управления запрещенными словами"""
        if ctx.invoked_subcommand is None:
            await ctx.send(
                "**Доступные команды:**\n"
                "`!forbidden add <слово>` - добавить запрещенное слово\n"
                "`!forbidden remove <слово>` - удалить запрещенное слово\n"
                "`!forbidden list` - показать список запрещенных слов"
            )
    
    @forbidden.command(name="add")
    @commands.has_permissions(manage_messages=True)
    async def add_forbidden(self, ctx, *, word: str):
        """Добавляет слово в список запрещенных"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем, указано ли слово
        if not word:
            await ctx.send("❌ Укажите слово для добавления в список запрещенных.")
            return
        
        # Добавляем слово в список запрещенных
        if self.module:
            result = self.module.add_forbidden_word(word)
            if result:
                await ctx.send(f"✅ Слово `{word}` добавлено в список запрещенных.")
            else:
                await ctx.send(f"❌ Слово `{word}` уже находится в списке запрещенных.")
        else:
            await ctx.send("❌ Модуль панели управления не инициализирован.")
    
    @forbidden.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def remove_forbidden(self, ctx, *, word: str):
        """Удаляет слово из списка запрещенных"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем, указано ли слово
        if not word:
            await ctx.send("❌ Укажите слово для удаления из списка запрещенных.")
            return
        
        # Удаляем слово из списка запрещенных
        if self.module:
            result = self.module.remove_forbidden_word(word)
            if result:
                await ctx.send(f"✅ Слово `{word}` удалено из списка запрещенных.")
            else:
                await ctx.send(f"❌ Слово `{word}` не найдено в списке запрещенных.")
        else:
            await ctx.send("❌ Модуль панели управления не инициализирован.")
    
    @forbidden.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def list_forbidden(self, ctx):
        """Показывает список запрещенных слов"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем, есть ли запрещенные слова
        if not self.module or not self.module.forbidden_words:
            await ctx.send("📋 Список запрещенных слов пуст.")
            return
        
        # Создаем эмбед со списком запрещенных слов
        embed = discord.Embed(
            title="📋 Список запрещенных слов",
            description="Слова, автоматически фильтруемые ботом:",
            color=discord.Color.blue()
        )
        
        # Форматируем список слов
        words_list = "`" + "`, `".join(self.module.forbidden_words) + "`"
        
        # Если список слишком длинный, разбиваем его на части
        if len(words_list) > 1024:
            chunks = []
            current_chunk = ""
            
            for word in self.module.forbidden_words:
                if len(current_chunk + f"`{word}`, ") > 1000:
                    chunks.append(current_chunk)
                    current_chunk = f"`{word}`, "
                else:
                    current_chunk += f"`{word}`, "
            
            if current_chunk:
                chunks.append(current_chunk[:-2])  # Удаляем последнюю запятую и пробел
            
            for i, chunk in enumerate(chunks):
                embed.add_field(name=f"Часть {i+1}", value=chunk, inline=False)
        else:
            embed.description += f"\n\n{words_list}"
        
        await ctx.send(embed=embed)
    
    @commands.command(name="clear", aliases=["purge"])
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 5):
        """Очищает указанное количество сообщений"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем количество сообщений
        if amount < 1:
            await ctx.send("❌ Укажите положительное количество сообщений для удаления.")
            return
        
        if amount > 100:
            await ctx.send("❌ За один раз можно удалить не более 100 сообщений.")
            return
        
        # Удаляем сообщения
        try:
            deleted = await ctx.channel.purge(limit=amount + 1)  # +1 для команды
            
            # Отправляем уведомление
            message = await ctx.send(f"✅ Удалено {len(deleted) - 1} сообщений.")
            await asyncio.sleep(5)
            await message.delete()
            
            # Логируем действие в канал модерации
            if self.module:
                log_channel_id = self.module.settings.get("mod_log_channel")
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        embed = discord.Embed(
                            title="🧹 Модерация: сообщения удалены",
                            description=f"**Модератор:** {ctx.author.mention}\n**Канал:** {ctx.channel.mention}\n**Количество:** {len(deleted) - 1}",
                            color=discord.Color.blue(),
                            timestamp=datetime.datetime.utcnow()
                        )
                        
                        await log_channel.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ У бота нет прав для удаления сообщений.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Произошла ошибка при удалении сообщений: {e}")
    
    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = None):
        """Выгоняет участника с сервера"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем, может ли бот выгнать этого участника
        if not ctx.guild.me.guild_permissions.kick_members:
            await ctx.send("❌ У бота нет прав для выгона участников.")
            return
        
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send("❌ Бот не может выгнать участника с такой же или более высокой ролью.")
            return
        
        # Проверяем, может ли пользователь выгнать этого участника
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("❌ Вы не можете выгнать участника с такой же или более высокой ролью, чем у вас.")
            return
        
        # Формируем причину
        reason = reason or "Причина не указана"
        full_reason = f"{ctx.author} ({ctx.author.id}): {reason}"
        
        # Выгоняем участника
        try:
            await member.kick(reason=full_reason)
            
            # Отправляем уведомление
            await ctx.send(f"✅ Участник {member.mention} выгнан с сервера.\nПричина: {reason}")
            
            # Логируем действие в канал модерации
            if self.module:
                log_channel_id = self.module.settings.get("mod_log_channel")
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        embed = discord.Embed(
                            title="👢 Модерация: участник выгнан",
                            description=f"**Модератор:** {ctx.author.mention}\n**Участник:** {member.mention} ({member})\n**Причина:** {reason}",
                            color=discord.Color.orange(),
                            timestamp=datetime.datetime.utcnow()
                        )
                        
                        embed.set_thumbnail(url=member.display_avatar.url)
                        
                        await log_channel.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ У бота нет прав для выгона этого участника.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Произошла ошибка при выгоне участника: {e}")
    
    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = None):
        """Банит участника на сервере"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        # Проверяем, может ли бот забанить этого участника
        if not ctx.guild.me.guild_permissions.ban_members:
            await ctx.send("❌ У бота нет прав для бана участников.")
            return
        
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send("❌ Бот не может забанить участника с такой же или более высокой ролью.")
            return
        
        # Проверяем, может ли пользователь забанить этого участника
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            await ctx.send("❌ Вы не можете забанить участника с такой же или более высокой ролью, чем у вас.")
            return
        
        # Формируем причину
        reason = reason or "Причина не указана"
        full_reason = f"{ctx.author} ({ctx.author.id}): {reason}"
        
        # Баним участника
        try:
            await member.ban(reason=full_reason, delete_message_days=1)
            
            # Отправляем уведомление
            await ctx.send(f"✅ Участник {member.mention} забанен на сервере.\nПричина: {reason}")
            
            # Логируем действие в канал модерации
            if self.module:
                log_channel_id = self.module.settings.get("mod_log_channel")
                if log_channel_id:
                    log_channel = ctx.guild.get_channel(int(log_channel_id))
                    if log_channel:
                        embed = discord.Embed(
                            title="🔨 Модерация: участник забанен",
                            description=f"**Модератор:** {ctx.author.mention}\n**Участник:** {member.mention} ({member})\n**Причина:** {reason}",
                            color=discord.Color.red(),
                            timestamp=datetime.datetime.utcnow()
                        )
                        
                        embed.set_thumbnail(url=member.display_avatar.url)
                        
                        await log_channel.send(embed=embed)
            
        except discord.Forbidden:
            await ctx.send("❌ У бота нет прав для бана этого участника.")
        except discord.HTTPException as e:
            await ctx.send(f"❌ Произошла ошибка при бане участника: {e}")
    
    @commands.command(name="settings")
    @commands.has_permissions(administrator=True)
    async def dashboard_settings(self, ctx, setting: str = None, *, value: str = None):
        """Управление настройками бота на этом сервере"""
        guild_id = str(ctx.guild.id)

        if setting is None:
            # Показываем все настройки с текущими значениями из БД
            db_settings = await get_all_settings(guild_id)

            embed = discord.Embed(
                title="⚙️ Настройки сервера",
                description=(
                    "Просмотр: `!settings <ключ>`\n"
                    "Изменение: `!settings <ключ> <значение>`"
                ),
                color=discord.Color.blue(),
            )

            for key, meta in SETTINGS_META.items():
                current = db_settings.get(key, meta["default"])
                embed.add_field(
                    name=f"`{key}`",
                    value=f"{meta['desc']}\nЗначение: **{current}**",
                    inline=False,
                )

            await ctx.send(embed=embed)
            return

        # Проверяем, является ли ключ известным
        if setting not in SETTINGS_META:
            known = ", ".join(f"`{k}`" for k in SETTINGS_META)
            await ctx.send(
                f"❌ Неизвестная настройка `{setting}`.\n**Доступные ключи:** {known}"
            )
            return

        meta = SETTINGS_META[setting]

        if value is None:
            # Показываем текущее значение конкретной настройки
            current = await get_setting(guild_id, setting, meta["default"])
            embed = discord.Embed(
                title=f"⚙️ `{setting}`",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Описание", value=meta["desc"], inline=False)
            embed.add_field(name="Текущее значение", value=str(current), inline=True)
            embed.add_field(name="Тип", value=meta["type"], inline=True)
            embed.set_footer(text=f"Изменить: !settings {setting} <значение>")
            await ctx.send(embed=embed)
            return

        # Преобразуем строку в нужный тип
        try:
            if meta["type"] == "bool":
                parsed = value.lower() in ("true", "1", "yes", "да", "вкл", "on")
            elif meta["type"] == "int":
                parsed = int(value)
            else:
                parsed = value
        except ValueError:
            await ctx.send(f"❌ Неверный тип значения. Ожидается `{meta['type']}`.")
            return

        await set_setting(guild_id, setting, parsed)
        await ctx.send(f"✅ Настройка `{setting}` установлена на **{parsed}**.")
    
    @commands.command(name="invite")
    async def invite(self, ctx):
        """Отправляет ссылку для добавления бота на сервер"""
        permissions = discord.Permissions(
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
        )

        invite_url = discord.utils.oauth_url(
            ctx.bot.user.id,
            permissions=permissions,
            scopes=("bot", "applications.commands"),
        )

        embed = discord.Embed(
            title="Добавить бота на сервер",
            description=f"[Нажмите здесь, чтобы пригласить бота]({invite_url})",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Для добавления бота требуются права администратора на целевом сервере.")

        await ctx.send(embed=embed)

    @kick.error
    @ban.error
    @clear.error
    @dashboard_settings.error
    async def mod_command_error(self, ctx, error):
        """Обработчик ошибок модерационных команд"""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ У вас нет прав для выполнения этой команды.")
        elif isinstance(error, commands.MemberNotFound):
            await ctx.send("❌ Участник не найден.")
        else:
            await ctx.send(f"❌ Произошла ошибка: {str(error)}")