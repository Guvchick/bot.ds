"""
Ког для системы логирования в боте Elix
"""
import discord
from discord.ext import commands
import asyncio
import datetime
import io
import json
from typing import Dict, Any, List, Optional, Union
import traceback

class LoggingCog(commands.Cog):
    """Ког для логирования событий сервера"""
    
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module
        
        # Используем кэш из модуля, если он доступен
        self.message_cache = {}
        self.deleted_messages = set()
        self.voice_time_cache = {}
        
        if self.module:
            self.message_cache = self.module.message_cache
            self.deleted_messages = self.module.deleted_messages
            self.voice_time_cache = self.module.voice_time_cache
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Обработчик новых сообщений"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем сообщения от ботов (опционально)
        if message.author.bot and message.author.id != self.bot.user.id:
            return
        
        # Игнорируем личные сообщения
        if not message.guild:
            return
        
        # Проверяем, включена ли категория логирования сообщений
        if self.module and not self.module.is_category_enabled("messages"):
            return
        
        # Кэшируем сообщение для отслеживания изменений
        if self.module:
            self.module.cache_message(message)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Обработчик удаленных сообщений"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем сообщения от ботов (опционально)
        if message.author.bot and message.author.id != self.bot.user.id:
            return
        
        # Игнорируем личные сообщения
        if not message.guild:
            return
        
        # Проверяем, включена ли категория логирования сообщений
        if self.module and not self.module.is_category_enabled("messages"):
            return
        
        # Проверяем, было ли сообщение удалено из-за фильтра
        was_filtered = False
        if self.module:
            was_filtered = self.module.was_deleted_by_filter(message.id)
        
        # Создаем эмбед для лога
        embed = discord.Embed(
            title="🗑️ Сообщение удалено",
            description=f"**Канал:** {message.channel.mention}\n**Автор:** {message.author.mention}",
            color=discord.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        
        # Добавляем контент сообщения, если он есть
        if message.content:
            if len(message.content) > 1024:
                embed.add_field(name="Содержимое", value=message.content[:1021] + "...", inline=False)
            else:
                embed.add_field(name="Содержимое", value=message.content, inline=False)
        
        # Добавляем информацию о вложениях
        if message.attachments:
            files_info = "\n".join([f"📎 `{attachment.filename}` ({attachment.size} байт)" for attachment in message.attachments])
            embed.add_field(name="Вложения", value=files_info, inline=False)
        
        # Добавляем информацию о причине удаления
        if was_filtered:
            embed.add_field(name="Причина удаления", value="Автоматическая фильтрация запрещенных слов", inline=False)
            embed.color = discord.Color.orange()
        
        # Устанавливаем автора эмбеда как автора сообщения
        embed.set_author(name=f"{message.author} ({message.author.id})", icon_url=message.author.display_avatar.url)
        
        # Отправляем лог
        if self.module:
            await self.module.log_to_channel(embed=embed)
    
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Обработчик измененных сообщений"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем сообщения от ботов (опционально)
        if before.author.bot and before.author.id != self.bot.user.id:
            return
        
        # Игнорируем личные сообщения
        if not before.guild:
            return
        
        # Проверяем, включена ли категория логирования сообщений
        if self.module and not self.module.is_category_enabled("messages"):
            return
        
        # Игнорируем, если содержимое не изменилось (например, встраивания загрузились)
        if before.content == after.content:
            return
        
        # Создаем эмбед для лога
        embed = discord.Embed(
            title="✏️ Сообщение изменено",
            description=f"**Канал:** {before.channel.mention}\n**Автор:** {before.author.mention}\n**[Перейти к сообщению]({after.jump_url})**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        
        # Добавляем старое содержимое
        if before.content:
            if len(before.content) > 1024:
                embed.add_field(name="До", value=before.content[:1021] + "...", inline=False)
            else:
                embed.add_field(name="До", value=before.content, inline=False)
        else:
            embed.add_field(name="До", value="*Нет содержимого*", inline=False)
        
        # Добавляем новое содержимое
        if after.content:
            if len(after.content) > 1024:
                embed.add_field(name="После", value=after.content[:1021] + "...", inline=False)
            else:
                embed.add_field(name="После", value=after.content, inline=False)
        else:
            embed.add_field(name="После", value="*Нет содержимого*", inline=False)
        
        # Устанавливаем автора эмбеда как автора сообщения
        embed.set_author(name=f"{before.author} ({before.author.id})", icon_url=before.author.display_avatar.url)
        
        # Отправляем лог
        if self.module:
            await self.module.log_to_channel(embed=embed)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Обработчик изменений состояния голосовых каналов"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            return
        
        # Игнорируем ботов (опционально)
        if member.bot:
            return
        
        # Проверяем, включена ли категория логирования голосовых каналов
        if self.module and not self.module.is_category_enabled("voice"):
            return
        
        # Пользователь присоединился к голосовому каналу
        if before.channel is None and after.channel is not None: