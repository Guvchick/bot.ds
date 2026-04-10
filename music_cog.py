"""
Музыкальный ког для бота Elix (слеш-команды, yt-dlp, Яндекс Музыка)
"""
import asyncio
import os
import re
import itertools
from functools import partial
from typing import Optional, Dict

import discord
from discord import app_commands
from discord.ext import commands

# ── yt-dlp ─────────────────────────────────────────────────────────────────────
import yt_dlp as youtube_dl

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "options": "-vn",
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
}

ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

# ── Яндекс Музыка ──────────────────────────────────────────────────────────────
_ym_client = None

def _init_yandex_music():
    global _ym_client
    token = os.getenv("YANDEX_MUSIC_TOKEN")
    if not token:
        return
    try:
        from yandex_music import Client
        _ym_client = Client(token).init()
    except Exception as e:
        print(f"[music] Яндекс Музыка недоступна: {e}")

_init_yandex_music()


def _is_yandex_url(url: str) -> bool:
    return "music.yandex" in url


def _fetch_yandex(url: str) -> dict:
    """Синхронно получает прямую ссылку на трек через yandex-music API."""
    if _ym_client is None:
        raise ValueError(
            "Токен Яндекс Музыки не настроен. Добавьте YANDEX_MUSIC_TOKEN в .env"
        )

    track_match = re.search(r"/track/(\d+)", url)
    if not track_match:
        raise ValueError("Не удалось распознать ID трека из ссылки Яндекс Музыки")

    album_match = re.search(r"/album/(\d+)", url)
    track_id = track_match.group(1)
    album_id = album_match.group(1) if album_match else None
    track_key = f"{track_id}:{album_id}" if album_id else track_id

    tracks = _ym_client.tracks([track_key])
    if not tracks:
        raise ValueError("Трек не найден")

    track = tracks[0]
    download_info = track.get_download_info(get_direct_links=True)
    if not download_info:
        raise ValueError("Не удалось получить ссылку на трек")

    best = max(download_info, key=lambda x: x.bitrate_in_kbps)
    artists = ", ".join(a.name for a in track.artists) if track.artists else "Unknown"
    thumbnail = (
        f"https://{track.cover_uri.replace('%%', '200x200')}"
        if track.cover_uri
        else None
    )
    return {
        "title": f"{artists} — {track.title}",
        "url": best.direct_link,
        "webpage_url": url,
        "thumbnail": thumbnail,
        "is_yandex": True,
    }


# ── Источник аудио ─────────────────────────────────────────────────────────────

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data: dict, requester: discord.User):
        super().__init__(source)
        self.requester = requester
        self.title = data.get("title")
        self.web_url = data.get("webpage_url")
        self.thumbnail = data.get("thumbnail")
        self.channel = data.get("uploader")

    @classmethod
    async def create_source(
        cls,
        requester: discord.User,
        search: str,
        *,
        loop: asyncio.AbstractEventLoop = None,
    ) -> dict:
        """Возвращает dict-очередь для последующего regather_stream."""
        loop = loop or asyncio.get_event_loop()

        if _is_yandex_url(search):
            data = await loop.run_in_executor(None, partial(_fetch_yandex, search))
            data["requester"] = requester
            return data

        to_run = partial(ytdl.extract_info, url=search, download=False)
        data = await loop.run_in_executor(None, to_run)
        if "entries" in data:
            data = data["entries"][0]

        return {
            "webpage_url": data["webpage_url"],
            "title": data["title"],
            "thumbnail": data.get("thumbnail"),
            "requester": requester,
            "is_yandex": False,
        }

    @classmethod
    async def regather_stream(
        cls, data: dict, *, loop: asyncio.AbstractEventLoop = None
    ) -> "YTDLSource":
        loop = loop or asyncio.get_event_loop()
        requester = data["requester"]

        if data.get("is_yandex"):
            # Прямая ссылка уже есть в data["url"]
            return cls(
                discord.FFmpegPCMAudio(data["url"], **FFMPEG_OPTIONS),
                data=data,
                requester=requester,
            )

        to_run = partial(ytdl.extract_info, url=data["webpage_url"], download=False)
        raw = await loop.run_in_executor(None, to_run)
        return cls(
            discord.FFmpegPCMAudio(raw["url"], **FFMPEG_OPTIONS),
            data=raw,
            requester=requester,
        )


# ── Плеер гильдии ──────────────────────────────────────────────────────────────

class MusicPlayer:
    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        channel: discord.TextChannel,
    ):
        self.bot = bot
        self.guild = guild
        self.channel = channel

        self.queue: asyncio.Queue = asyncio.Queue()
        self.next = asyncio.Event()
        self.current: Optional[YTDLSource] = None
        self.np_message: Optional[discord.Message] = None
        self.volume: float = 0.5
        self.auto_disconnect: bool = True
        self.timeout: int = 180

        bot.loop.create_task(self._player_loop())

    async def _player_loop(self):
        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            self.next.clear()

            if self.queue.empty() and self.auto_disconnect:
                try:
                    async with discord.utils.asyncio_timeout(self.timeout):
                        source = await self.queue.get()
                except (asyncio.TimeoutError, Exception):
                    await self._disconnect()
                    return
            else:
                source = await self.queue.get()

            self.current = await YTDLSource.regather_stream(source, loop=self.bot.loop)
            self.current.volume = self.volume

            vc = self.guild.voice_client
            if not vc:
                return

            vc.play(self.current, after=lambda _: self.bot.loop.call_soon_threadsafe(self.next.set))

            self.np_message = await self.channel.send(
                f"🎵 **Сейчас играет:** `{self.current.title}`"
                f" по запросу {self.current.requester.mention}"
            )
            await self.next.wait()

            try:
                await self.np_message.delete()
            except discord.HTTPException:
                pass
            self.current = None

    async def _disconnect(self):
        vc = self.guild.voice_client
        if vc:
            await vc.disconnect()
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break


# ── Ког ────────────────────────────────────────────────────────────────────────

class MusicCog(commands.Cog):
    def __init__(self, bot, module=None):
        self.bot = bot
        self.module = module
        self._players: Dict[int, MusicPlayer] = {}

    def _get_player(self, interaction: discord.Interaction) -> MusicPlayer:
        gid = interaction.guild_id
        if gid not in self._players:
            self._players[gid] = MusicPlayer(self.bot, interaction.guild, interaction.channel)
        return self._players[gid]

    # ── /play ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="play", description="Воспроизвести трек или добавить в очередь")
    @app_commands.describe(search="Название, ссылка YouTube / Spotify / SoundCloud / VK / Яндекс Музыки")
    async def play(self, interaction: discord.Interaction, search: str = None):
        if not search:
            embed = discord.Embed(
                title="🎵 Как использовать /play",
                description="Укажите название или ссылку в параметре `search`",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Поддерживаемые платформы",
                value=(
                    "**YouTube** — ссылка или название\n"
                    "**Яндекс Музыка** — ссылка на трек\n"
                    "**Spotify** — ссылка на трек/плейлист\n"
                    "**SoundCloud** — ссылка на трек\n"
                    "**VK** — ссылка на аудио"
                ),
                inline=False,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if not interaction.user.voice:
            await interaction.response.send_message(
                "❌ Сначала зайдите в голосовой канал.", ephemeral=True
            )
            return

        await interaction.response.defer()

        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()

        player = self._get_player(interaction)

        try:
            source = await YTDLSource.create_source(interaction.user, search, loop=self.bot.loop)
            await player.queue.put(source)
            await interaction.followup.send(
                f"🎵 **Добавлено в очередь:** `{source['title']}` по запросу {interaction.user.mention}"
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}")

    # ── /stop ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="stop", description="Остановить воспроизведение и отключиться")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Бот не в голосовом канале.", ephemeral=True)
            return
        player = self._players.pop(interaction.guild_id, None)
        if player:
            await player._disconnect()
        else:
            await vc.disconnect()
        await interaction.response.send_message("⏹️ Воспроизведение остановлено.")

    # ── /skip ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="skip", description="Пропустить текущий трек")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ Нечего пропускать.", ephemeral=True)
            return
        vc.stop()
        await interaction.response.send_message("⏭️ Трек пропущен.")

    # ── /queue ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="queue", description="Показать очередь треков")
    async def queue_info(self, interaction: discord.Interaction):
        player = self._players.get(interaction.guild_id)
        if not player or player.queue.empty():
            await interaction.response.send_message("📂 Очередь пуста.", ephemeral=True)
            return
        upcoming = list(itertools.islice(player.queue._queue, 0, 10))
        fmt = "\n".join(f"**{i+1}.** `{s['title']}`" for i, s in enumerate(upcoming))
        embed = discord.Embed(title="📋 Очередь", description=fmt, color=discord.Color.green())
        total = len(player.queue._queue)
        if total > 10:
            embed.set_footer(text=f"И ещё {total - 10} треков")
        await interaction.response.send_message(embed=embed)

    # ── /nowplaying ────────────────────────────────────────────────────────────

    @app_commands.command(name="nowplaying", description="Текущий трек")
    async def now_playing(self, interaction: discord.Interaction):
        player = self._players.get(interaction.guild_id)
        if not player or not player.current:
            await interaction.response.send_message("❌ Ничего не играет.", ephemeral=True)
            return
        cur = player.current
        embed = discord.Embed(
            title="🎵 Сейчас играет",
            description=f"`{cur.title}`",
            color=discord.Color.blue(),
        )
        if cur.thumbnail:
            embed.set_thumbnail(url=cur.thumbnail)
        if cur.channel:
            embed.add_field(name="Канал", value=cur.channel, inline=True)
        embed.add_field(name="Запросил", value=cur.requester.mention, inline=True)
        if cur.web_url:
            embed.add_field(name="Ссылка", value=f"[Открыть]({cur.web_url})", inline=True)
        await interaction.response.send_message(embed=embed)

    # ── /pause & /resume ───────────────────────────────────────────────────────

    @app_commands.command(name="pause", description="Поставить на паузу")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ Ничего не играет.", ephemeral=True)
            return
        if vc.is_paused():
            await interaction.response.send_message("❌ Уже на паузе.", ephemeral=True)
            return
        vc.pause()
        await interaction.response.send_message("⏸️ Пауза.")

    @app_commands.command(name="resume", description="Возобновить воспроизведение")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            await interaction.response.send_message("❌ Воспроизведение не на паузе.", ephemeral=True)
            return
        vc.resume()
        await interaction.response.send_message("▶️ Воспроизведение возобновлено.")

    # ── /volume ────────────────────────────────────────────────────────────────

    @app_commands.command(name="volume", description="Изменить громкость (0–100)")
    @app_commands.describe(level="Уровень громкости от 0 до 100")
    async def change_volume(self, interaction: discord.Interaction, level: int):
        if not 0 <= level <= 100:
            await interaction.response.send_message("❌ Укажите значение от 0 до 100.", ephemeral=True)
            return
        player = self._players.get(interaction.guild_id)
        if not player:
            await interaction.response.send_message("❌ Плеер не активен.", ephemeral=True)
            return
        player.volume = level / 100
        if player.current:
            player.current.volume = level / 100
        await interaction.response.send_message(f"🔊 Громкость: **{level}%**")

    # ── голосовые события ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.id != self.bot.user.id:
            return
        if before.channel and not after.channel:
            self._players.pop(member.guild.id, None)
