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
    async def dashboard_settings(self, ctx, setting: str = None, value: str = None):
        """Команда для управления настройками панели управления"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Модуль панели управления отключен.")
            return
        
        if not setting:
            # Показываем текущие настройки панели управления
            if self.module:
                settings = self.module.get_settings()
                
                # Создаем эмбед с настройками
                embed = discord.Embed(
                    title="⚙️ Настройки панели управления",
                    color=discord.Color.blue()
                )
                
                # Добавляем информацию о настройках
                for key, val in settings.items():
                    if key not in ["enabled", "name", "description", "forbidden_words", "forbidden_words_count"]:
                        embed.add_field(name=key, value=str(val), inline=True)
                
                # Добавляем информацию о запрещенных словах
                embed.add_field(
                    name="Запрещенные слова",
                    value=f"Всего: {len(self.module.forbidden_words)}",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                return
        
        # Проверяем, существует ли настройка
        if self.module and setting not in self.module.settings:
            await ctx.send(f"❌ Настройка `{setting}` не найдена.")
            return
        
        # Изменяем настройку
        if not value:
            # Если значение не указано, показываем текущее значение
            await ctx.send(f"📝 Текущее значение `{setting}`: `{self.module.settings[setting]}`")
        else:
            # Преобразуем значение в нужный тип
            if isinstance(self.module.settings[setting], bool):
                value = value.lower() in ["true", "1", "yes", "y", "да"]
            elif isinstance(self.module.settings[setting], int):
                try:
                    value = int(value)
                except ValueError:
                    await ctx.send(f"❌ Значение `{value}` должно быть целым числом.")
                    return
            elif isinstance(self.module.settings[setting], float):
                try:
                    value = float(value)
                except ValueError:
                    await ctx.send(f"❌ Значение `{value}` должно быть числом.")
                    return
            
            # Обновляем настройку
            new_settings = {setting: value}
            await self.module.update_settings(new_settings)
            
            await ctx.send(f"✅ Настройка `{setting}` изменена на `{value}`.")
    
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