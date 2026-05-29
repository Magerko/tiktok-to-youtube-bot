# TikTok → YouTube bot

Мост из TikTok в YouTube, который управляется Telegram-ботом. Следит за указанными TikTok-аккаунтами, при появлении новых видео скачивает их через `yt-dlp` и заливает на выбранный YouTube-канал.

Поддерживается многие-ко-многим: один TikTok → несколько YouTube, и наоборот. Для каждой пары можно выбрать режим:

- 📝 **Review** — карточка с превью прилетает в личку, заливка только после ✅;
- ⚡ **Auto** — скачали → залили без подтверждения.

## Возможности

- Polling TikTok через `yt-dlp` (`extract_flat`), без сторонних API.
- Per-account cookies для случаев, когда TikTok отдаёт пустой плейлист (загрузка прямо в боте, гайд там же).
- Resumable upload на YouTube Data API v3, ретраи на 5xx, авто-`#Shorts`.
- Per-channel OAuth и квота: подключаешь `client_secrets.json` отдельно на каждый канал — у каждого свой потолок 10 000 ед./сутки. Можно использовать общий fallback.
- Очередь в SQLite (WAL), идемпотентная по `(pair_id, tiktok_video_id)`.
- Каскадное удаление: убрал TikTok-аккаунт или YouTube-канал — пары с ним пропадают сами.
- Inline-админка с пагинацией, retry упавших шагов из бота.
- Admin-only middleware с whitelist по Telegram user-id.

## Требования

- Python **3.11+** (тестировалось на 3.11 и 3.12)
- `ffmpeg` в PATH — нужен `yt-dlp` для слияния потоков (в Docker ставится автоматически)
- Telegram Bot Token
- Один или несколько OAuth-клиентов Google (Desktop / installed app) с включённым YouTube Data API v3 — подключаются через бота

## Структура

```
.
├── main.py                       # точка входа — бот + monitor + pipeline в одном loop
├── config.py                     # .env через python-dotenv
├── keyboards.py                  # inline-клавиатуры
├── middlewares.py                # AdminOnly
├── states.py                     # FSM-стейты
├── handlers/
│   ├── common.py                 # /start, /menu, /cancel
│   ├── tiktok.py                 # CRUD TikTok-аккаунтов + cookies
│   ├── youtube.py                # CRUD YouTube-каналов + OAuth-флоу
│   ├── pairs.py                  # CRUD пар
│   ├── review.py                 # карточка с ✅ / ✏️ / ❌
│   └── info.py                   # /status, очередь, retry
├── services/
│   ├── storage.py                # JSON
│   ├── db.py                     # SQLite
│   ├── tiktok_monitor.py
│   ├── downloader.py
│   ├── cookies.py
│   ├── youtube_auth.py
│   ├── youtube_upload.py
│   ├── quota.py
│   └── pipeline.py
├── pydata/                       # JSON-конфиги + state.sqlite + quota_<channel>.json
├── downloads/                    # временные mp4
├── secrets/
│   ├── client_secrets.json       # (опционально) общий fallback
│   ├── client_secrets/<ch>.json  # per-channel OAuth-клиенты
│   ├── cookies/<acc>.txt         # per-account TikTok cookies
│   └── tokens/<keyring_user>.json # refresh-токены
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml            # bot + redis (FSM)
```

## Установка

```powershell
git clone https://github.com/<you>/tiktok-to-youtube-bot.git
cd tiktok-to-youtube-bot

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

copy .env.example .env
# отредактируйте .env: пропишите TELEGRAM_BOT_TOKEN и ADMIN_USERS

python main.py
```

В первый запуск бот создаст `pydata/`, `downloads/` и `secrets/tokens/` сам.

### Что положить в `.env`

```env
TELEGRAM_BOT_TOKEN=123456789:ABC-DEF...
ADMIN_USERS=123456789

CHECK_INTERVAL=600         # как часто опрашиваем TikTok, сек
# YOUTUBE_CLIENT_SECRETS=secrets/client_secrets.json   # опциональный fallback

YT_PRIVACY=public
YT_CATEGORY_ID=22
YT_DEFAULT_LANGUAGE=ru
YT_MADE_FOR_KIDS=false

# REDIS_URL=redis://localhost:6379/0    # для FSM, переживает рестарт
```

## Где взять ключи

### Telegram Bot Token

[@BotFather](https://t.me/BotFather) → `/newbot` → следуйте инструкции. Полученная строка `123456789:ABC...` идёт в `TELEGRAM_BOT_TOKEN`.

### Telegram user-id для ADMIN_USERS

Напишите [@userinfobot](https://t.me/userinfobot) — он пришлёт ваш `id`. Несколько админов — через запятую.

### `client_secrets.json` для YouTube-канала

На каждый подключаемый YouTube-канал заведите **отдельный** Google Cloud-проект — тогда у каждого будет своя суточная квота 10 000 единиц (≈6 аплоадов/сутки). Иначе каналы делят один лимит.

1. [Google Cloud Console](https://console.cloud.google.com/) → **New Project**.
2. **APIs & Services → Library** → найдите **YouTube Data API v3** → **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User Type: **External**;
   - заполните App name + Support email;
   - в **Test users** добавьте Google-аккаунт, к которому привязан ваш YouTube-канал — без этого Google форсит `privacyStatus=private`.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app**.
5. Нажмите **Download JSON** на созданной записи.
6. Этот файл вы пришлёте в бота на шаге подключения канала.

Этот же гайд продублирован прямо в боте — кнопка **«ℹ️ Гайд: как получить»** на шаге подключения.

### Опциональный общий вариант

Если у вас уже есть один `client_secrets.json` на несколько каналов — положите его в `secrets/client_secrets.json` и пропишите `YOUTUBE_CLIENT_SECRETS=secrets/client_secrets.json` в `.env`. При подключении нового канала появится кнопка **«🔁 Использовать общий»**. Квота тогда — одна на всех каналах, идущих через этот файл.

## Первый запуск

1. В Telegram → бот → `/start`.
2. **🎵 TikTok аккаунты → ➕ Добавить** → пришлите `@username` или ссылку. Первый цикл мониторинга только зафиксирует последний свежий video_id — историю заливать не будем.
3. **📺 YouTube каналы → ➕ Подключить** → пришлите имя канала → пришлите `client_secrets.json` как документ (📎 → Файл) → бот откроет браузер на хосте для входа в Google-аккаунт.
4. **🔗 Пары → ➕ Создать пару** → выберите TikTok → выберите YouTube → выберите режим (по умолчанию Review).
5. Готово. Через `CHECK_INTERVAL` секунд монитор увидит новые публикации.

## Команды

| Команда   | Что делает                |
|-----------|---------------------------|
| `/start`  | Главное меню              |
| `/menu`   | То же                     |
| `/status` | Сводка по очереди + квоты |
| `/cancel` | Выход из текущего FSM     |

Всё остальное — кнопками.

## Cookies (на случай регионов / login-wall)

Если для какого-то TikTok-аккаунта yt-dlp стабильно возвращает пустой список или капчу — подключите для него cookies из браузера, где вы залогинены в TikTok.

🎵 TikTok → 🍪 Cookies → выберите аккаунт → 📤 Загрузить. Гайд (Chrome / Edge / Brave / Firefox) — там же кнопкой. Cookies хранятся per-аккаунт в `secrets/cookies/<id>.txt`, монитор и downloader подцепят автоматически.

## Docker

```powershell
docker compose up -d --build
docker compose logs -f bot
```

В compose поднимается **bot + redis**. Папки `pydata/`, `downloads/`, `secrets/` маунтятся с хоста.

**Caveat:** OAuth-флоу через `flow.run_local_server` открывает браузер на хосте контейнера — в Docker не сработает. Workaround: пройдите подключение каналов локально (`python main.py` на хосте), потом смонтируйте `secrets/` в контейнер — refresh-токены продолжат работать.

## Подводные камни

- **YouTube квота** — 10 000 ед./сутки **на GCP-проект**. Один аплоад = 1 600 ⇒ ~6 видео/сутки на проект. С отдельным `client_secrets` на канал квоты независимые. При `QuotaExceeded` pipeline сам подождёт минуту и попробует снова.
- **Watermark TikTok** — yt-dlp обычно вытаскивает чистую версию, но не всегда. YouTube понижает в выдаче Shorts с чужими watermark.
- **Shorts auto-detect** — YouTube видит 9:16 + ≤3 мин + `#Shorts`. Хэштег дописывается автоматически.
- **Telegram 50 MB лимит** — review-карточка падает на `send_document`, потом на текстовое сообщение.
- **Регион/captcha** — подключите cookies (см. раздел выше).
- **Copyright** — задумано для собственного контента, который вы переливаете на свой же канал. Лить чужие TikTok-видео на YouTube — нарушение TOS обеих платформ, можно поймать страйки.

## Лицензия

MIT.
