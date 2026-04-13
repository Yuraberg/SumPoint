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
```

### Database migrations
```bash
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
```

## Architecture

### Request flow
The FastAPI app (`app/main.py`) mounts the frontend SPA at `/` and registers all routers under `/api/v1/` via `app/api/router.py`. All API routes except `POST /auth/telegram` require a Bearer JWT token verified by `get_current_user()` in `app/api/auth.py`.

### Post processing pipeline
New posts flow through three stages coordinated by the Celery worker:
1. **Ingestion** (`app/services/telegram_ingestion.py`) — Telethon fetches raw messages, pre-filters ads by keyword heuristics, deduplicates by SHA-256 content hash.
2. **AI processing** (`app/services/ai_engine.py`) — Each post goes through `process_post()` which calls Claude three times in sequence: classify → summarize → extract events. All three calls use `claude-opus-4-6` with adaptive thinking (think blocks stripped before parsing). Event extraction returns structured JSON parsed via regex.
3. **Storage** — Processed posts (with category, summary, events JSON, placeholder embedding) are written to the `posts` table.

The `fetch_all_channels` Celery task runs every 5 minutes and drives this entire pipeline for all active users.

### Scheduled digests
`send_scheduled_digests(slot)` runs twice daily (morning/evening UTC hours from env). It queries users by their `digest_morning`/`digest_evening` preference flags, builds a markdown digest via `app/services/digest_service.py`, then sends it via the Telegram bot directly using `bot.send_message`.

### Frontend auth
The frontend SPA (`frontend/`) authenticates via the Telegram Login Widget. On callback, `onTelegramAuth(user)` in `app.js` POSTs widget data to `/api/v1/auth/telegram`, which verifies the HMAC-SHA256 signature and auth_date freshness (< 24h), upserts the user, and returns a 7-day JWT stored in `localStorage` as `sp_token`.

### Semantic search
`GET /posts/search` currently uses a PostgreSQL `ILIKE` fallback. The `embedding` column (pgvector `Vector(1536)`) is populated with placeholder zeros — `generate_embedding()` in `ai_engine.py` is the stub to replace with a real embeddings model (e.g., OpenAI `text-embedding-3-small`).

### Telethon session security
Each user's Telethon session file is encrypted at rest with AES-256-GCM (`app/services/encryption.py`) using `SESSION_ENCRYPTION_KEY`. Sessions are stored in the `sessions/` volume. Never commit `.session` files.

## Key configuration
All settings are loaded from `.env` via Pydantic `Settings` in `app/config.py`. Copy `.env.example` to `.env` before first run. Critical vars: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `SESSION_ENCRYPTION_KEY` (32-byte hex: `openssl rand -hex 32`), `SECRET_KEY`.

## Prompts
All Claude prompts live in `app/prompts/`. They use role prompting, few-shot examples (classification), chain-of-thought (`<thought>` blocks stripped by regex before parsing), and delimiters (`###`, `"""`). When editing prompts, the parsing logic in `ai_engine.py` must stay in sync with the expected output format.
