# Elix Bot

Discord-бот с модульной системой: логирование, ранги, музыка, автомодерация.  
Все команды — через слеш `/`.

## Требования

- Docker и Docker Compose
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))
- _(опционально)_ Токен Яндекс Музыки для воспроизведения треков с `music.yandex.ru`

Для запуска без Docker дополнительно нужны Python 3.11+, FFmpeg и PostgreSQL.

---

## Быстрый старт (Docker)

### 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd bot.ds
```

### 2. Создать файл окружения

```bash
cp .env.example .env
```

Открыть `.env` и заполнить переменные:

```env
# Discord
DISCORD_TOKEN=ваш_токен_бота

# PostgreSQL (пароль обязателен)
POSTGRES_DB=elixbot
POSTGRES_USER=elixbot
POSTGRES_PASSWORD=сильный_пароль
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Яндекс Музыка (необязательно)
# Как получить токен: https://github.com/MarshalX/yandex-music-api/discussions/513
YANDEX_MUSIC_TOKEN=ваш_токен
```

### 3. Запустить

```bash
docker compose up -d
```

или через Make:

```bash
make up
```

При первом запуске Docker соберёт образ и запустит два контейнера:
- **bot** — сам бот
- **db** — PostgreSQL в изолированной сети `ElixDsBot`

---

## Управление через Make

| Команда | Действие |
|---|---|
| `make up` | Запустить в фоне |
| `make down` | Остановить и удалить контейнеры |
| `make restart` | Перезапустить без пересборки |
| `make logs` | Логи в реальном времени |
| `make build` | Пересобрать образ без кэша |
| `make update` | Обновить (git pull → build → up) |
| `make shell` | Открыть bash внутри контейнера бота |

---

## Запуск без Docker

### 1. Установить PostgreSQL и зависимости

```bash
pip install -r requirement.txt
```

На Linux/macOS также нужен FFmpeg:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg libpq-dev
```

### 2. Запустить

```bash
python run.py
```

---

## Зависимости

| Пакет | Назначение |
|---|---|
| `discord.py[voice]>=2.3` | Discord API + голосовые каналы |
| `asyncpg>=0.29` | PostgreSQL клиент |
| `yt-dlp>=2024.1` | Загрузка аудио (YouTube, SoundCloud, VK и др.) |
| `PyNaCl>=1.4` | Шифрование голосового соединения |
| `yandex-music>=2.0` | Яндекс Музыка API |
| `pillow>=9.3` | Работа с изображениями |
| `aiohttp>=3.8` | HTTP-клиент |
| `python-dotenv` | Загрузка `.env` |

---

## Структура проекта

```
bot.ds/
├── bot/
│   ├── __init__.py
│   └── main.py          # Инициализация бота, синхронизация слеш-команд
├── logs/                # Логи (создаются автоматически)
├── dashboard.py         # /clear, /kick, /ban, /forbidden, /settings, /invite
├── db.py                # PostgreSQL-утилиты (asyncpg)
├── logging_cog.py       # Логирование: удаление/редактирование сообщений,
│                        #   вход/выход в войс, кики/баны/мьюты
├── music_cog.py         # /play, /stop, /skip, /queue, /np, /pause, /resume, /volume
├── rank_cog.py          # /rank, /leaderboard, /voicetime
├── run.py               # Скрипт запуска
├── Dockerfile
├── docker-compose.yml
└── requirement.txt
```

---

## Команды бота

### Музыка

| Команда | Описание |
|---|---|
| `/play <запрос>` | Трек по названию или ссылке (YouTube, Яндекс Музыка, Spotify, SoundCloud, VK) |
| `/stop` | Остановить и отключиться |
| `/skip` | Пропустить трек |
| `/pause` / `/resume` | Пауза / Возобновить |
| `/queue` | Очередь треков |
| `/nowplaying` | Текущий трек |
| `/volume <0-100>` | Громкость |

### Ранги

| Команда | Описание |
|---|---|
| `/rank [@user]` | Статистика и уровень |
| `/leaderboard [N]` | Таблица лидеров |
| `/voicetime [@user]` | Время в голосовых каналах |

### Модерация _(требует прав)_

| Команда | Описание |
|---|---|
| `/clear [N]` | Удалить N сообщений (макс. 100) |
| `/kick @user [причина]` | Кикнуть участника |
| `/ban @user [причина]` | Забанить участника |
| `/forbidden add <слово>` | Добавить слово в фильтр |
| `/forbidden remove <слово>` | Удалить слово из фильтра |
| `/forbidden list` | Список запрещённых слов |

### Настройки _(требует прав администратора)_

| Команда | Описание |
|---|---|
| `/settings` | Показать все настройки |
| `/settings <ключ>` | Текущее значение настройки |
| `/settings <ключ> <значение>` | Изменить настройку |
| `/invite` | Ссылка для добавления бота |

**Доступные ключи настроек:**

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `mod_log_channel` | int | — | ID канала для логов |
| `auto_moderation` | bool | true | Авто-удаление запрещённых слов |
| `xp_per_message` | int | 5 | XP за сообщение |
| `xp_per_minute_voice` | int | 1 | XP за минуту в войсе |
| `level_up_notification` | bool | true | Уведомление о новом уровне |
| `ignore_bot_channels` | bool | true | Не начислять XP в бот-каналах |
| `auto_disconnect` | bool | true | Авто-отключение музыки |
| `music_timeout` | int | 180 | Таймаут отключения (сек) |
| `volume` | int | 50 | Громкость музыки (0–100) |

---

## Логирование событий

Установите `mod_log_channel` — бот будет автоматически логировать:

- 🗑️ Удаление сообщений
- ✏️ Редактирование сообщений
- 🔊 Вход / 🔇 Выход / 🔄 Смена голосового канала
- 🔨 Баны и ✅ разбаны
- 👢 Кики участников
- 🔇 Тайм-ауты (мьюты) и их снятие
- 🤖 Срабатывание автомодерации

```
/settings mod_log_channel <ID канала>
```
