# Elix Bot

Discord-бот с модульной системой: логирование событий, ранги и XP, музыка, автомодерация.  
Все команды работают через слеш `/`. Хранение данных — Go-микросервис + PostgreSQL.

---

## Архитектура

```
Discord API
    │
    ▼
[bot]  Python 3.11 · discord.py
    │  HTTP REST (aiohttp)
    ▼
[db-service]  Go 1.22 · net/http
    │  · REST API для всех операций с БД
    │  · Cron-планировщик резервных копий
    │  · pg_dump → ZIP → Discord-канал
    │  SQL (pgx v5)
    ▼
[db]  PostgreSQL 16

Docker-сеть: ElixDsBot
```

---

## Требования

- **Docker** и **Docker Compose** — для запуска через контейнеры
- **Discord Bot Token** — [Discord Developer Portal](https://discord.com/developers/applications)
- **ID Discord-канала** — для получения резервных копий БД
- _(опционально)_ **Токен Яндекс Музыки** — для воспроизведения треков с `music.yandex.ru`

---

## Быстрый старт

### 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd bot.ds
```

### 2. Создать файл окружения

```bash
cp .env.example .env
```

Обязательные поля в `.env`:

```env
DISCORD_TOKEN=ваш_токен_бота
POSTGRES_PASSWORD=сильный_пароль
BACKUP_CHANNEL_ID=123456789012345678
```

### 3. Запустить

```bash
docker compose up -d
```

Docker автоматически:
1. Соберёт Go-бинарник `db-service` (multi-stage build)
2. Поднимет PostgreSQL и дождётся его готовности
3. Поднимет `db-service` и дождётся его готовности
4. Запустит Python-бота

---

## Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `DISCORD_TOKEN` | ✅ | — | Токен Discord-бота |
| `POSTGRES_PASSWORD` | ✅ | — | Пароль PostgreSQL |
| `BACKUP_CHANNEL_ID` | ✅ | — | ID Discord-канала для бэкапов |
| `POSTGRES_DB` | | `elixbot` | Имя базы данных |
| `POSTGRES_USER` | | `elixbot` | Пользователь PostgreSQL |
| `POSTGRES_HOST` | | `db` | Хост PostgreSQL |
| `POSTGRES_PORT` | | `5432` | Порт PostgreSQL |
| `DB_SERVICE_URL` | | `http://db-service:8080` | Адрес Go DB-сервиса |
| `DB_SERVICE_PORT` | | `8080` | Порт Go DB-сервиса |
| `BACKUP_CRON` | | `0 3 * * *` | Расписание бэкапов (cron) |
| `YANDEX_MUSIC_TOKEN` | | — | Токен Яндекс Музыки |

---

## Управление

### Docker Compose

```bash
docker compose up -d          # запустить в фоне
docker compose down           # остановить и удалить контейнеры
docker compose up -d --build  # пересобрать образы и запустить
docker compose logs -f        # логи всех контейнеров в реальном времени
docker compose logs -f bot    # логи только бота
```

### Make

| Команда | Действие |
|---|---|
| `make up` | Запустить в фоне |
| `make down` | Остановить контейнеры |
| `make restart` | Перезапустить без пересборки |
| `make logs` | Логи всех контейнеров |
| `make build` | Пересобрать все образы без кэша |
| `make update` | `git pull` → `build` → `up` |
| `make shell` | `bash` внутри контейнера `bot` |

---

## Резервные копии БД

Бэкапы выполняет Go-сервис автоматически по расписанию.

**Процесс:**
1. `pg_dump` создаёт дамп PostgreSQL
2. Дамп упаковывается в ZIP-архив (сжатие в памяти, без записи на диск)
3. Архив отправляется в Discord-канал `BACKUP_CHANNEL_ID` через Discord API

**Настройка расписания** (cron-выражение в `BACKUP_CRON`):

```
0 3 * * *    — каждый день в 03:00 (по умолчанию)
0 */6 * * *  — каждые 6 часов
0 3 * * 1   — каждый понедельник в 03:00
0 */12 * * * — дважды в день
```

**Ручной запуск:**

```bash
curl -X POST http://localhost:8080/backup
```

---

## Логи

Все логи пишутся **одновременно** в stdout и в файл.

| Контейнер | Файл |
|---|---|
| `bot` | `logs/bot.txt` |
| `db-service` | `logs/db-service.txt` |

Тома Docker монтируются в именованные volumes (`bot_logs`, `db_service_logs`) — логи **не теряются** при перезапуске.

---

## Запуск без Docker

### Go DB-сервис

Требуется: Go 1.22+, работающий PostgreSQL

```bash
cd db-service
go mod tidy
go run .
```

### Python-бот

Требуется: Python 3.11+, FFmpeg, libsodium

```bash
# macOS
brew install ffmpeg libsodium

# Ubuntu/Debian
sudo apt install ffmpeg libsodium-dev

pip install -r requirement.txt
python run.py
```

---

## Зависимости

### Python — `requirement.txt`

| Пакет | Версия | Назначение |
|---|---|---|
| `discord.py[voice]` | ≥ 2.3.0 | Discord API, слеш-команды, голосовые каналы |
| `aiohttp` | ≥ 3.9.0 | HTTP-клиент для Go DB-сервиса |
| `yt-dlp` | ≥ 2024.1.1 | Загрузка аудио (YouTube, SoundCloud, VK и др.) |
| `PyNaCl` | ≥ 1.4.0 | Шифрование голосового соединения Discord |
| `yandex-music` | ≥ 2.0.0 | API Яндекс Музыки |
| `pillow` | ≥ 9.3.0 | Работа с изображениями |
| `async-timeout` | 4.0.2 | Таймауты для async-операций |
| `python-dotenv` | 1.0.0 | Загрузка `.env` |

### Go — `db-service/go.mod`

| Пакет | Назначение |
|---|---|
| `github.com/jackc/pgx/v5` | PostgreSQL-драйвер (stdlib-совместимый) |
| `github.com/robfig/cron/v3` | Cron-планировщик автоматических бэкапов |

---

## Структура проекта

```
bot.ds/
├── bot/
│   ├── __init__.py
│   └── main.py           # Инициализация бота, sync слеш-команд
│
├── db-service/
│   ├── main.go           # Go: REST API, БД, бэкапы, логи
│   ├── go.mod
│   └── Dockerfile        # Multi-stage: builder (Go) + runtime (Alpine)
│
├── logs/                 # Создаётся автоматически
│   ├── bot.txt
│   └── (db-service.txt в отдельном volume)
│
├── dashboard.py          # /clear /kick /ban /forbidden /settings /invite
├── db.py                 # aiohttp-клиент для Go DB-сервиса
├── logging_cog.py        # Логирование всех событий сервера
├── music_cog.py          # /play /stop /skip /queue /nowplaying /pause /resume /volume
├── rank_cog.py           # /rank /leaderboard /voicetime
├── run.py                # Точка входа, настройка логирования
│
├── .env.example          # Шаблон переменных окружения
├── Dockerfile            # Python-бот (slim + FFmpeg + libsodium)
├── docker-compose.yml    # db → db-service → bot, сеть ElixDsBot
├── Makefile
└── requirement.txt
```

---

## Команды бота

### Музыка

| Команда | Описание |
|---|---|
| `/play <запрос>` | Воспроизвести трек по названию или ссылке |
| `/stop` | Остановить воспроизведение и отключиться |
| `/skip` | Пропустить текущий трек |
| `/pause` | Поставить на паузу |
| `/resume` | Возобновить воспроизведение |
| `/queue` | Показать очередь треков |
| `/nowplaying` | Информация о текущем треке |
| `/volume <0–100>` | Изменить громкость |

**Поддерживаемые источники:** YouTube, Яндекс Музыка, Spotify, SoundCloud, VK и любые другие, поддерживаемые `yt-dlp`.

Для Яндекс Музыки укажите токен в `YANDEX_MUSIC_TOKEN`.  
Как получить токен: [MarshalX/yandex-music-api#513](https://github.com/MarshalX/yandex-music-api/discussions/513)

### Ранги и активность

| Команда | Описание |
|---|---|
| `/rank [@user]` | Уровень, XP и прогресс-бар |
| `/leaderboard [N]` | Топ-N участников сервера |
| `/voicetime [@user]` | Время в голосовых каналах |

XP начисляется автоматически за сообщения и время в войсе. Настраивается через `/settings`.

### Модерация

| Команда | Права | Описание |
|---|---|---|
| `/clear [N]` | Manage Messages | Удалить до 100 сообщений |
| `/kick @user [причина]` | Kick Members | Кикнуть участника |
| `/ban @user [причина]` | Ban Members | Забанить участника |
| `/forbidden add <слово>` | Manage Messages | Добавить слово в фильтр |
| `/forbidden remove <слово>` | Manage Messages | Удалить слово из фильтра |
| `/forbidden list` | Manage Messages | Список запрещённых слов |

### Настройки и утилиты

| Команда | Права | Описание |
|---|---|---|
| `/settings` | Administrator | Показать все настройки сервера |
| `/settings <ключ> <значение>` | Administrator | Изменить настройку |
| `/invite` | — | Ссылка для добавления бота на сервер |

**Все доступные ключи `/settings`:**

| Ключ | Тип | По умолчанию | Описание |
|---|---|---|---|
| `mod_log_channel` | int | — | ID канала для логов модерации |
| `auto_moderation` | bool | `true` | Автоудаление запрещённых слов |
| `xp_per_message` | int | `5` | XP за одно сообщение |
| `xp_per_minute_voice` | int | `1` | XP за минуту в голосовом канале |
| `level_up_notification` | bool | `true` | Уведомление о повышении уровня |
| `ignore_bot_channels` | bool | `true` | Не начислять XP в бот-каналах |
| `auto_disconnect` | bool | `true` | Авто-отключение при пустой очереди |
| `music_timeout` | int | `180` | Таймаут авто-отключения (секунды) |
| `volume` | int | `50` | Громкость музыки (0–100) |

---

## Логирование событий

Все события логируются в канал, заданный в `mod_log_channel`.

```
/settings mod_log_channel <ID канала>
```

| Событие | Embed |
|---|---|
| Удаление сообщения | 🗑️ красный — автор, канал, текст, вложения |
| Редактирование сообщения | ✏️ синий — до / после, ссылка на сообщение |
| Вход в голосовой канал | 🔊 зелёный |
| Выход из голосового канала | 🔇 красный |
| Смена голосового канала | 🔄 синий — из какого в какой |
| Бан участника | 🔨 красный — модератор, причина (из audit log) |
| Снятие бана | ✅ зелёный |
| Кик участника | 👢 оранжевый — модератор, причина (из audit log) |
| Тайм-аут (мьют) | 🔇 оранжевый — до какого времени |
| Снятие мьюта | 🔊 зелёный |
| Автомодерация | 🤖 оранжевый — сработавшее слово, содержимое |

> Для чтения audit log боту нужно право **View Audit Log**.

---

## Go DB-сервис — API

Внутренний REST API (доступен только внутри Docker-сети `ElixDsBot`):

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/health` | Статус сервиса |
| `GET` | `/settings/{guildID}` | Все настройки сервера |
| `GET` | `/settings/{guildID}/{key}` | Значение одной настройки |
| `PUT` | `/settings/{guildID}/{key}` | Установить настройку |
| `DELETE` | `/settings/{guildID}/{key}` | Удалить настройку |
| `GET` | `/users/{guildID}/{userID}` | Статистика пользователя |
| `POST` | `/users/{guildID}/{userID}/xp` | Добавить XP `{"amount": N}` |
| `POST` | `/users/{guildID}/{userID}/messages` | +1 к счётчику сообщений |
| `POST` | `/users/{guildID}/{userID}/voice` | Добавить время в войсе `{"seconds": N}` |
| `GET` | `/leaderboard/{guildID}?limit=N` | Таблица лидеров |
| `POST` | `/backup` | Запустить бэкап вручную |
