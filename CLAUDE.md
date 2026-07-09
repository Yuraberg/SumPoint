# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Local development (without Docker)
```bash
# Start infrastructure only
docker compose up -d db redis

# Run database migrations
alembic upgrade head

# API server (http://localhost:8000)
uvicorn app.main:app --reload

# Celery worker (separate terminal)
celery -A app.tasks.celery_app worker --loglevel=info

# Celery beat scheduler (separate terminal)
celery -A app.tasks.celery_app beat --loglevel=info

# Telegram bot (separate terminal)
python -m bot.bot
```

### Full Docker deployment
```bash
# Development (hot-reload, published ports, DEBUG=true)
docker compose up -d

# Production (immutable images, restart: always, no exposed ports)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Pre-commit hooks (setup once per clone)
```bash
pip install pre-commit
pre-commit install
# Now every `git commit` will scan for secrets via detect-secrets.
# To manually scan: detect-secrets scan --all-files
# To update baseline after intentionally adding a secret-like string:
#   detect-secrets scan --update .secrets.baseline
```

### Database migrations
```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

### Generate Telethon session string (run once locally before Coolify deploy)
```bash
pip install telethon
python generate_session.py
# Outputs TELEGRAM_SESSION_STRING — paste it into Coolify env vars
```

## Architecture

### Request flow
`app/main.py` runs FastAPI, mounts the frontend SPA at `/`, registers all routers under `/api/v1/` via `app/api/router.py`. All routes except `POST /auth/telegram` require a Bearer JWT verified by `get_current_user()` in `app/api/auth.py`.

### API endpoints
- `GET|POST /auth/telegram` — Telegram Login Widget HMAC verification, returns 7-day JWT
- `GET|POST|DELETE /channels/` — list, add, remove channels
- `POST /channels/import` — imports user's Telegram subscriptions via Celery worker
- `POST /channels/sync` — triggers background fetch (Celery), returns 202
- `GET /posts/` — paginated feed; query params: `category`, `channel_id`, `date_from`, `date_to` (ISO dates), `limit`, `offset`
- `GET /posts/search` — ILIKE text search over `posts.text`
- `GET /posts/semantic-search` — pgvector cosine search (`embedding <=> query_vec`) over BGE-M3 embeddings
- `GET /digest/` — builds and returns a markdown digest for the last N hours
- `GET /digest/events` — upcoming calendar events extracted from stored posts

### Post processing pipeline
New posts flow through the Celery worker only (never the API container):

1. **Ingestion** (`app/services/telegram_ingestion.py`) — Telethon fetches raw messages, pre-filters ads by keyword heuristics, deduplicates in-memory by SHA-256 content hash within the run (the hash is also returned to the caller for cross-run dedup, see below).
2. **AI processing** (`app/services/ai_engine.py`, fully async via `AsyncOpenAI`/`httpx.AsyncClient`) — `process_post()` calls DeepSeek three times: `classify_post()` → `summarise_post()` → `extract_events()`. Uses `deepseek-chat` via the OpenAI SDK (`base_url="https://api.deepseek.com"`). `<thought>` blocks are stripped by regex before parsing. `generate_embedding()` calls Ollama BGE-M3 (`/api/embeddings`) for a 1024-dim vector, falling back to a zero-vector if Ollama is unreachable.
3. **Storage** — Processed posts written to the `posts` table with `category`, `summary`, `events` (JSON), and `embedding`.

`fetch_all_channels` Celery task runs continuously every `POSTS_FETCH_INTERVAL_MINUTES` (default 20), each tick processing only `POSTS_FETCH_BATCH_SIZE` channels (default 20) ordered by oldest `last_fetched_at` first — this spreads Telethon traffic out instead of bursting through every channel at once (flood-ban risk), while still cycling through all channels over time. A Redis `SET NX` lock (`sumpoint:fetch_lock`, 600s TTL) prevents an overlapping run (e.g. a manual `/channels/sync` firing mid-tick) from racing the scheduled one. Commits per channel inside a try/except so one failing channel doesn't block others; the error is also saved to `Channel.last_error` so it's visible via the API/frontend instead of only in worker logs. Users without `session_path` AND without `TELEGRAM_SESSION_STRING` are skipped.

**Duplicate prevention** has two layers: a DB unique constraint on `(channel_id, telegram_message_id)` catches re-fetches of the same Telegram message, and `Post.content_hash` (SHA-256 of the text, checked against the last 14 days for that channel) catches reposts of identical text under a different message id. Each post insert runs inside a `db.begin_nested()` savepoint, so a duplicate raced in by a concurrent writer only discards that one insert (`IntegrityError`) instead of rolling back every post already processed for the channel in that run.

### Telethon session: worker-only rule
**Telethon (User API) must only run inside the Celery worker.** Running it from the API container simultaneously causes `AuthKeyDuplicatedError` because Telegram detects two different IP addresses using the same session. The API container resolves this by dispatching all Telethon operations to the worker via Celery tasks (`import_channels_for_user`, `resolve_channel_username`, `fetch_all_channels`) using `run_in_threadpool` + `.apply_async().get(timeout=...)`.

### Telethon session management
Two modes, tried in order:
1. **Env var** (`TELEGRAM_SESSION_STRING`) — preferred for Coolify/Docker deploys. Generated once by `generate_session.py`. No file I/O.
2. **Encrypted file** — fallback. AES-256-GCM via `app/services/encryption.py` using `SESSION_ENCRYPTION_KEY`. Path stored in `User.session_path`. Stored in the `sessions/` volume. Never commit `.session` files.

### Scheduled digests
`send_scheduled_digests(slot)` runs twice daily. Queries users by `digest_morning`/`digest_evening` flags, builds digest via `app/services/digest_service.py`, sends via `python-telegram-bot` using `bot.send_message`.

### Telegram bot
`bot/bot.py` uses PTB (not Telethon). Handlers split into `bot/handlers/`: `start.py`, `digest.py`, `settings.py`. Handles `/start`, and callback queries: `digest_now`, `events`, `settings`, `toggle_morning`, `toggle_evening`, `filter_<category>`.

### Frontend
Vanilla JS SPA (`frontend/`). Layout: dark sidebar with page navigation + light main content. Pages: **Посты** (posts table with date/channel/category filters + expandable rows), **Сводки** (digest), **События** (events), **Каналы** (channel management). Auth via Telegram Login Widget → JWT stored as `sp_token` in localStorage.

### Prompts
All prompts live in `app/prompts/` (`classification.py`, `summarization.py`, `event_extraction.py`). When editing prompts, keep the parsing logic in `ai_engine.py` in sync with the expected output format.

## Key configuration
All settings loaded from `.env` via Pydantic `Settings` in `app/config.py` (cached with `lru_cache`). Copy `.env.example` to `.env` before first run.

Critical vars: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`, `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY`, `DATABASE_URL`, `SESSION_ENCRYPTION_KEY` (32-byte hex: `openssl rand -hex 32`), `SECRET_KEY`.

Digest schedule controlled by `DIGEST_MORNING_HOUR` and `DIGEST_EVENING_HOUR` (UTC integers, defaults 8 and 20). Continuous fetch/processing controlled by `POSTS_FETCH_INTERVAL_MINUTES` (default 20) and `POSTS_FETCH_BATCH_SIZE` (default 20).

`REDIS_URL` is also used directly as the Celery broker and result backend (`app/tasks/celery_app.py`) — there is no separate `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`. All four services (`api`, `bot`, `worker`, `beat`) must point `REDIS_URL` at the same Redis instance (e.g. `redis://redis:6379/0` in Docker), otherwise Celery can't dispatch or pick up any task.

Set `UPTIME_KUMA_PUSH_URL` to a Uptime Kuma push-monitor URL to get a heartbeat ping every 5 minutes from the worker (`uptime_kuma_heartbeat` task) — lets Uptime Kuma alert if the worker stops processing tasks.

## Monitoring (Uptime Kuma)

The following monitors should be configured in Uptime Kuma for full coverage:

### 1. Worker heartbeat (Push monitor)
- **Type:** Push
- **URL:** set `UPTIME_KUMA_PUSH_URL` in `.env` to the push URL from Uptime Kuma
- **Heartbeat interval:** 300s (5 min, matches the Celery beat schedule)
- **Alert after:** 600s (2 missed heartbeats)

### 2. API health check (HTTP monitor)
- **Type:** HTTP(s)
- **URL:** `https://<your-domain>/api/v1/health`
- **Interval:** 60s
- **Retries:** 3
- **Expected:** HTTP 200, JSON with `"status": "healthy"`
- This endpoint checks DB (`SELECT 1`) and Redis (`PING`) — alerts if either is down.

### 3. SSL certificate expiry
- **Type:** Certificate expiry (built into Uptime Kuma)
- **URL:** `https://<your-domain>`
- **Alert when:** < 14 days until expiry

### Notification channels
Configure at least one notification channel (Telegram bot is recommended):
- Uptime Kuma → Settings → Notifications → Telegram
- Set the bot token and chat ID

### Error tracking (Sentry)

SumPoint supports Sentry for automatic error tracking. It's **optional** — if
`SENTRY_DSN` is empty, Sentry is a no-op with zero overhead.

```bash
# 1. Create a project at https://sentry.io (FastAPI template)
# 2. Copy the DSN (Settings → Client Keys → DSN)
# 3. Add to .env:
SENTRY_DSN=https://abc123@sentry.io/12345
```

Once configured, all unhandled exceptions are automatically captured. The SDK
also captures FastAPI request data, stack traces, and 10% of transactions for
performance monitoring. PII is disabled by default.

## Database backups

Run `scripts/backup-db.sh` to create a gzipped pg_dump. The script auto-parses
`DATABASE_URL` from `.env`.

```bash
cd /root/vps-new
source .env
./scripts/backup-db.sh          # single backup
./scripts/backup-db.sh --cron   # backup + rotate (keeps 7 days)
```

To automate, add a cron job on the VPS host:

```
0 3 * * * cd /root/vps-new && source .env && ./scripts/backup-db.sh --cron
```

Backups are stored in `./backups/` by default (override with `BACKUP_DIR`).

## Database schema notes
- `users.id` is the Telegram user ID (BigInteger), not a serial PK.
- `posts.published_at` is `TIMESTAMP WITHOUT TIME ZONE` — always strip `tzinfo` before inserting (`pub_at.replace(tzinfo=None)`).
- `posts.embedding` is `pgvector Vector(1024)` (BGE-M3 dimension), populated by `generate_embedding()` during AI processing.
- Schema is owned exclusively by Alembic — the app does **not** create or migrate tables at startup. Always run `alembic upgrade head` before starting the API/worker/bot (see `docker-compose.yml`'s `api` command).

## Production Readiness Backlog

### Первая волна («Да»)

| # | Этап | Статус | Файлы |
|---|------|--------|-------|
| 1A | `.env.example` — все переменные с подсказками | ✅ | `.env.example` |
| 2A | HEALTHCHECK + `/api/v1/health` (DB + Redis) | ✅ | `Dockerfile`, `app/api/health.py`, `app/api/router.py` |
| 3A | `ruff` + `pip-audit` в CI | ⚠️→✅ | `.github/workflows/deploy.yml`, `pyproject.toml`. Гейт был добавлен, но не проходил: 71 ошибка ruff (в основном ложные F821 на forward-ref в SQLAlchemy-моделях) и 20 CVE в зависимостях. Исправлено отдельным коммитом (`6248597`) — заменён `python-jose`→`PyJWT`, обновлены `fastapi`/`starlette`/`cryptography`/`pytest`. `pip-audit` теперь 0 уязвимостей |
| 4A | CORS — warning о localhost в проде | ✅ | `app/main.py` |
| 4Б | Rate limit на `/auth/*` (slowapi) | ⚠️→✅ | Был и раньше, но брал первый IP из `X-Forwarded-For` — Caddy добавляет свой IP в конец, а не заменяет заголовок, так что первый элемент подконтролен атакующему (обход лимита ротацией фейкового IP). Исправлено на последний элемент (`874ed8d`) |
| 5A | Uptime Kuma — 3 монитора + алерты | ✅ | `CLAUDE.md` (документация) |
| 6В | `LOG_LEVEL` + глушение шумных библиотек | ⚠️→✅ | `app/config.py`, `app/main.py`. Закрывало утечку токена бота в логи только в `api`-процессе; `worker`/`beat` (Celery, где реально шлются все дайджесты/алерты через httpx) остались незащищены. Добавлено то же подавление в `app/tasks/celery_app.py` (`6248597`) |
| 7А | `pg_dump` бэкап + cron (7 дней) | ✅ | `scripts/backup-db.sh`, `CLAUDE.md` |

### Вторая волна («Позже»)

| # | Этап | Статус | Файлы |
|---|------|--------|-------|
| 1Б | Pre-commit `detect-secrets` | ✅ | `.pre-commit-config.yaml`, `.secrets.baseline` |
| 2Б | `docker-compose.yml` (dev) + `.prod.yml` | ⚠️→✅ | `docker-compose.yml`, `docker-compose.prod.yml`, CI. `docker compose config` фатально падал — сервис `bot` отсутствовал в базовом файле, на который ссылался prod-оверлей; dev-режим (`docker compose up -d`) был сломан ссылкой на необъявленную сеть `coolify`; `deploy.yml` вызывал несуществующие имена сервисов (`sumpoint-api` вместо `api`). Исправлено (`63e8623`) |
| 3Б | Интеграционные тесты с pgvector в CI | ⚠️→✅ | `tests/integration/`, CI job. Все 4 теста падали с `ScopeMismatch` при каждом запуске (session-scoped фикстура зависела от function-scoped event loop). Исправлено (`6248597`), заодно найден и исправлен реальный баг: `get_or_create` не обновлял `first_name` у существующих пользователей |
| 5Б | Sentry (опционально по `SENTRY_DSN`) | ✅ | `requirements.txt`, `app/config.py`, `app/main.py` |
| 6А | JSON-логи в проде | ✅ | `app/logging.py`, `app/main.py` |

**Итого: 13/13 этапов добавлено, из них 5 не проходили проверку и были доисправлены отдельными коммитами на `main` — см. таблицу.**

CI теперь также гейтит сами PR (`pull_request`-триггер добавлен в `deploy.yml`, `54f6c38`) — раньше ruff/pip-audit/pytest запускались только после мержа в `main`, так что PR мог влиться с падающими проверками без единого красного крестика.
