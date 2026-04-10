"""
Музыкальный ког для работы с модульной системой в боте Elix
"""
import discord
from discord.ext import commands
import asyncio
import datetime
import youtube_dl
import os
from async_timeout import timeout
from functools import partial
import itertools
from typing import Optional, List, Dict, Any

# Настройки youtube_dl
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    """Класс для работы с YouTube и другими источниками аудио"""
    
    def __init__(self, source, *, data, requester):
        super().__init__(source)
        self.requester = requester
        
        self.title = data.get('title')
        self.web_url = data.get('webpage_url')
        self.duration = data.get('duration')
        
        # Дополнительная информация
        self.thumbnail = data.get('thumbnail')
        self.channel = data.get('uploader')
        self.channel_url = data.get('uploader_url')
        
    def __getitem__(self, item: str):
        """Получить атрибут трека"""
        return self.__getattribute__(item)

    @classmethod
    async def create_source(cls, ctx, search: str, *, loop=None, download=False):
        """Создать источник аудио из поисковой строки"""
        loop = loop or asyncio.get_event_loop()
        
        to_run = partial(ytdl.extract_info, url=search, download=download)
        data = await loop.run_in_executor(None, to_run)
        
        if 'entries' in data:
            # Берем первый элемент из плейлиста
            data = data['entries'][0]
            
        return {'webpage_url': data['webpage_url'], 'requester': ctx.author, 'title': data['title']}

    @classmethod
    async def regather_stream(cls, data, *, loop=None):
        """Получить поток аудио для проигрывания"""
        loop = loop or asyncio.get_event_loop()
        requester = data['requester']
        
        to_run = partial(ytdl.extract_info, url=data['webpage_url'], download=False)
        data = await loop.run_in_executor(None, to_run)
        
        return cls(discord.FFmpegPCMAudio(data['url'], **ffmpeg_options), data=data, requester=requester)

class MusicPlayer:
    """Класс для работы с музыкальным плеером в гильдии"""
    
    def __init__(self, ctx):
        self.bot = ctx.bot
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.cog = ctx.cog
        
        self.queue = asyncio.Queue()
        self.next = asyncio.Event()
        
        self.np = None  # Текущий трек
        self.volume = 0.5  # Громкость (0-1)
        self.current = None  # Текущий источник
        
        # Дополнительные настройки из модуля
        self.auto_disconnect = True
        self.timeout = 180  # Время в секундах для автоотключения
        
        # Запускаем цикл проигрывания
        ctx.bot.loop.create_task(self.player_loop())
    
    async def player_loop(self):
        """Основной цикл проигрывания музыки"""
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            self.next.clear()
            
            # Проверяем, пуста ли очередь
            if self.queue.empty():
                # Если очередь пуста и включено автоотключение, запускаем таймер
                if self.auto_disconnect:
                    try:
                        # Ждем timeout секунд
                        async with timeout(self.timeout):
                            await self.next.wait()
                    except asyncio.TimeoutError:
                        # Время вышло, отключаемся
                        await self.disconnect()
                        return
                else:
                    # Просто ждем следующий трек
                    await self.next.wait()
            
            # Получаем трек из очереди
            source = await self.queue.get()
            
            self.current = await YTDLSource.regather_stream(source, loop=self.bot.loop)
            self.current.volume = self.volume
            self.guild.voice_client.play(
                self.current, 
                after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set)
            )
            
            # Отправляем сообщение о текущем треке
            self.np = await self.channel.send(
                f"🎵 **Сейчас играет:** `{self.current.title}` по запросу {self.current.requester.mention}"
            )
            
            # Ждем окончания трека
            await self.next.wait()
            
            # Очищаем текущий трек и удаляем сообщение
            try:
                await self.np.delete()
            except discord.HTTPException:
                pass
            
            self.current = None
    
    async def disconnect(self):
        """Отключение от голосового канала"""
        try:
            if self.guild.voice_client:
                await self.guild.voice_client.disconnect()
            
            # Очищаем очередь
            while not self.queue.empty():
                self.queue.get_nowait()
            
            # Сообщаем модулю о отключении
            if hasattr(self.cog, 'module') and self.cog.module:
                if self.guild.id in self.cog.module.players:
                    del self.cog.module.players[self.guild.id]
        except Exception as e:
            print(f"Ошибка при отключении: {e}")

class MusicCog(commands.Cog):
    """Музыкальный ког для проигрывания аудио в голосовых каналах"""
    
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module  # Ссылка на модуль
        self.players = {}  # guild_id -> MusicPlayer
        
        # Если передан модуль, используем его для хранения плееров
        if self.module:
            self.players = self.module.players
    
    def get_player(self, ctx):
        """Получить или создать музыкальный плеер для сервера"""
        try:
            # Если есть модуль, используем его метод
            if self.module:
                player = self.module.get_player(ctx.guild.id)
                if player:
                    return player
                
                # Создаем новый плеер через модуль
                player = MusicPlayer(ctx)
                self.module.players[ctx.guild.id] = player
                return player
            
            # Если нет модуля, используем старую логику
            if ctx.guild.id in self.players:
                return self.players[ctx.guild.id]
            
            player = MusicPlayer(ctx)
            self.players[ctx.guild.id] = player
            return player
        except Exception as e:
            print(f"Ошибка при получении плеера: {e}")
            return None
    
    @commands.command(name='play', aliases=['p'])
    async def play(self, ctx, *, search: str):
        """Добавляет трек в очередь"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, подключен ли автор к голосовому каналу
        if not ctx.author.voice:
            await ctx.send("❌ Вы должны быть подключены к голосовому каналу.")
            return
        
        channel = ctx.author.voice.channel
        
        # Подключаемся к голосовому каналу, если еще не подключены
        if not ctx.voice_client:
            await channel.connect()
        
        # Создаем/получаем плеер
        player = self.get_player(ctx)
        
        # Обновляем настройки плеера из модуля
        if self.module:
            player.auto_disconnect = self.module.settings.get("auto_disconnect", True)
            player.timeout = self.module.settings.get("timeout", 180)
            player.volume = self.module.settings.get("volume", 50) / 100.0
        
        # Ищем трек
        try:
            async with ctx.typing():
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
                await player.queue.put(source)
                
                # Отправляем сообщение о добавлении трека
                await ctx.send(
                    f"🎵 **Добавлено в очередь:** `{source['title']}` по запросу {ctx.author.mention}"
                )
        except Exception as e:
            await ctx.send(f"❌ Ошибка при поиске трека: {str(e)}")
    
    @commands.command(name='stop')
    async def stop(self, ctx):
        """Останавливает воспроизведение и очищает очередь"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client:
            await ctx.send("❌ Бот не подключен к голосовому каналу.")
            return
        
        # Получаем плеер
        player = self.get_player(ctx)
        
        # Останавливаем воспроизведение и отключаемся
        await player.disconnect()
        await ctx.send("⏹️ Воспроизведение остановлено, очередь очищена.")
    
    @commands.command(name='skip')
    async def skip(self, ctx):
        """Пропускает текущий трек"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("❌ Нечего пропускать.")
            return
        
        # Пропускаем трек
        ctx.voice_client.stop()
        await ctx.send("⏭️ Трек пропущен.")
    
    @commands.command(name='queue', aliases=['q'])
    async def queue_info(self, ctx):
        """Показывает очередь"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Получаем плеер
        player = self.get_player(ctx)
        
        # Проверяем, есть ли треки в очереди
        if player.queue.empty():
            await ctx.send("📂 Очередь пуста.")
            return
        
        # Получаем первые 5 треков из очереди
        upcoming = list(itertools.islice(player.queue._queue, 0, 5))
        
        # Форматируем очередь
        fmt = '\n'.join(f"**{i+1}.** `{source['title']}`" for i, source in enumerate(upcoming))
        embed = discord.Embed(
            title="📋 Очередь треков",
            description=fmt,
            color=discord.Color.green()
        )
        
        # Добавляем информацию о количестве треков
        queue_length = len(player.queue._queue)
        if queue_length > 5:
            embed.set_footer(text=f"И еще {queue_length - 5} треков")
            
        await ctx.send(embed=embed)
    
    @commands.command(name='volume', aliases=['vol'])
    async def change_volume(self, ctx, *, vol: int):
        """Изменяет громкость воспроизведения"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("❌ В данный момент ничего не воспроизводится.")
            return
        
        # Ограничиваем громкость от 0 до 100
        if not 0 <= vol <= 100:
            await ctx.send("❌ Громкость должна быть от 0 до 100.")
            return
        
        # Получаем плеер
        player = self.get_player(ctx)
        
        # Устанавливаем новую громкость
        player.volume = vol / 100
        if player.current:
            player.current.volume = vol / 100
        
        # Если есть модуль, обновляем его настройки
        if self.module:
            await self.module.update_settings({"volume": vol})
        
        await ctx.send(f"🔊 Громкость установлена на {vol}%")
    
    @commands.command(name='nowplaying', aliases=['np'])
    async def now_playing(self, ctx):
        """Показывает информацию о текущем треке"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("❌ В данный момент ничего не воспроизводится.")
            return
        
        # Получаем плеер
        player = self.get_player(ctx)
        
        # Создаем эмбед с информацией о треке
        embed = discord.Embed(
            title="🎵 Сейчас играет",
            description=f"`{player.current.title}`",
            color=discord.Color.blue()
        )
        
        # Добавляем thumbnail, если есть
        if player.current.thumbnail:
            embed.set_thumbnail(url=player.current.thumbnail)
        
        # Добавляем информацию о канале
        if player.current.channel:
            embed.add_field(name="Канал", value=player.current.channel, inline=True)
        
        # Добавляем информацию о запросившем
        embed.add_field(name="Запросил", value=player.current.requester.mention, inline=True)
        
        # Добавляем ссылку на источник
        embed.add_field(name="Ссылка", value=f"[Нажмите здесь]({player.current.web_url})", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.command(name='pause')
    async def pause(self, ctx):
        """Приостанавливает воспроизведение"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            await ctx.send("❌ В данный момент ничего не воспроизводится.")
            return
        
        # Приостанавливаем воспроизведение
        if ctx.voice_client.is_paused():
            await ctx.send("❌ Воспроизведение уже приостановлено.")
            return
        
        ctx.voice_client.pause()
        await ctx.send("⏸️ Воспроизведение приостановлено.")
    
    @commands.command(name='resume')
    async def resume(self, ctx):
        """Возобновляет воспроизведение"""
        # Проверяем, включен ли модуль
        if self.module and not self.module.enabled:
            await ctx.send("❌ Музыкальный модуль отключен.")
            return
        
        # Проверяем, есть ли активное соединение
        if not ctx.voice_client:
            await ctx.send("❌ Бот не подключен к голосовому каналу.")
            return
        
        # Возобновляем воспроизведение
        if not ctx.voice_client.is_paused():
            await ctx.send("❌ Воспроизведение не приостановлено.")
            return
        
        ctx.voice_client.resume()
        await ctx.send("▶️ Воспроизведение возобновлено.")
    
    # Обработчики событий Discord
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Обработчик изменения голосового состояния"""
        # Если бот вышел из канала, удаляем плеер
        if member.id == self.bot.user.id and before.channel and not after.channel:
            if before.channel.guild.id in self.players:
                del self