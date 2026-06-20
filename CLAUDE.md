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
docker compose up -d
# App is exposed on port 8001 (mapped to container's 8000)
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

1. **Ingestion** (`app/services/telegram_ingestion.py`) — Telethon fetches raw messages, pre-filters ads by keyword heuristics, deduplicates by SHA-256 content hash.
2. **AI processing** (`app/services/ai_engine.py`) — `process_post()` calls DeepSeek three times: `classify_post()` → `summarise_post()` → `extract_events()`. Uses `deepseek-chat` via the OpenAI SDK (`base_url="https://api.deepseek.com"`). `<thought>` blocks are stripped by regex before parsing. `generate_embedding()` calls Ollama BGE-M3 (`/api/embeddings`) for a 1024-dim vector, falling back to a zero-vector if Ollama is unreachable.
3. **Storage** — Processed posts written to the `posts` table with `category`, `summary`, `events` (JSON), and `embedding`.

`fetch_all_channels` Celery task runs once nightly (`POSTS_FETCH_HOUR`, UTC, default 3) so Telethon polling and the DeepSeek/embedding calls it triggers stay off the hot path. Commits per channel inside a try/except so one failing channel doesn't block others. Users without `session_path` AND without `TELEGRAM_SESSION_STRING` are skipped.

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

Digest schedule controlled by `DIGEST_MORNING_HOUR` and `DIGEST_EVENING_HOUR` (UTC integers, defaults 8 and 20). Nightly fetch/processing controlled by `POSTS_FETCH_HOUR` (UTC, default 3).

## Database schema notes
- `users.id` is the Telegram user ID (BigInteger), not a serial PK.
- `posts.published_at` is `TIMESTAMP WITHOUT TIME ZONE` — always strip `tzinfo` before inserting (`pub_at.replace(tzinfo=None)`).
- `posts.embedding` is `pgvector Vector(1024)` (BGE-M3 dimension), populated by `generate_embedding()` during AI processing.
- Schema is owned exclusively by Alembic — the app does **not** create or migrate tables at startup. Always run `alembic upgrade head` before starting the API/worker/bot (see `docker-compose.yml`'s `api` command).
