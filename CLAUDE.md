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
- `GET /auth/me` — current user (`id`/`first_name`/`username`/`is_approved`/`is_owner`); the SPA calls it on load to decide login-vs-pending-vs-app since the JWT lives in an unreadable HttpOnly cookie
- `POST /auth/logout` — clears the session cookie (this device)
- `POST /auth/logout-all` — bumps the caller's `users.token_version`, invalidating every JWT already issued to them (logout-everywhere / revoke-on-compromise)
- `POST /auth/redeem-invite` — an authenticated-but-pending user unlocks their own account with an invite code, from the web pending screen
- `GET /admin/pending-users`, `POST /admin/pending-users/{id}/approve`, `GET|POST|DELETE /admin/invites` — owner-only (`Settings.owner_telegram_id_set`); manage the access-control queue and invite codes
- `GET|POST|DELETE /channels/` — list, add, remove channels
- `POST /channels/{id}/toggle` — enable/disable a channel; re-enabling clears the failure counter and last_error
- `POST /channels/import` — imports user's Telegram subscriptions via Celery worker
- `POST /channels/sync` — triggers background fetch (Celery), returns 202
- `GET /posts/` — paginated feed; query params: `category`, `channel_id`, `date_from`, `date_to` (ISO dates), `limit`, `offset`
- `GET /posts/search` — ILIKE text search over `posts.text`
- `GET /posts/export?format=csv|json` — download the filtered feed (same filters as `GET /posts/`), capped at 5000 rows
- `GET /posts/semantic-search` — pgvector cosine search (`embedding <=> query_vec`) over BGE-M3 embeddings
- `GET /posts/cluster/{cluster_id}` — sources (posts) making up a duplicate-cluster; powers the "также в N каналах" feed badge
- `GET /digest/` — builds and returns a markdown digest for the last N hours
- `GET /digest/events` — upcoming calendar events extracted from stored posts
- `GET /stats/overview?days=N` — analytics dashboard: totals, posts-per-day (zero-filled), per-category and top-channel breakdowns
- `GET /stats/channel-health` — per-channel post/unread counts, fetch freshness and last_error for the Channels health panel
- `POST /chat/ask` — RAG assistant: retrieves the user's most relevant posts (BGE-M3 semantic search, keyword fallback if Ollama is down) and asks DeepSeek to answer with `[N]` citations; returns `{answer, sources}`. Rate-limited (15/min) since it hits both the embedding model and DeepSeek.

### Post processing pipeline
New posts flow through the Celery worker only (never the API container):

1. **Ingestion** (`app/services/telegram_ingestion.py`) — Telethon fetches raw messages, pre-filters ads by keyword heuristics, deduplicates in-memory by SHA-256 content hash within the run (the hash is also returned to the caller for cross-run dedup, see below).
2. **AI processing** (`app/services/ai_engine.py`, fully async via `AsyncOpenAI`/`httpx.AsyncClient`) — `process_post()` calls DeepSeek three times: `classify_post()` → `summarise_post()` → `extract_events()`. Uses `deepseek-chat` via the OpenAI SDK (`base_url="https://api.deepseek.com"`). `<thought>` blocks are stripped by regex before parsing. `generate_embedding()` calls Ollama BGE-M3 (`/api/embeddings`) for a 1024-dim vector, falling back to a zero-vector if Ollama is unreachable.
3. **Storage** — Processed posts written to the `posts` table with `category`, `summary`, `events` (JSON), and `embedding`.
4. **Duplicate clustering** (`app/services/clustering.py`) — after the insert flushes, `assign_cluster()` runs one pgvector nearest-neighbour query (scoped to the same user's channels, within `CLUSTER_WINDOW_DAYS`) and adopts the neighbour's `cluster_id` if cosine similarity ≥ `CLUSTER_SIMILARITY_THRESHOLD` (default 0.86); otherwise the post starts its own cluster (`cluster_id = own id`). The feed then shows "также в N каналах" (distinct channels sharing the cluster). **Graceful degradation:** two zero-vectors have cosine distance 0, so an unavailable BGE-M3 (zero-vector fallback) would falsely merge everything — `is_usable_embedding()` guards against this, leaving embedding-less posts unclustered (`cluster_id` stays NULL / singleton) instead of merging. Clustering runs in its own savepoint so a hiccup never discards the stored post. Set `CLUSTERING_ENABLED=false` to skip it entirely. New posts are clustered at ingestion; to group **historical** posts once after deploy, run the `backfill_clusters` Celery task (`celery -A app.tasks.celery_app call app.tasks.maintenance_tasks.backfill_clusters`; pass `--args='[true]'` to reset & recompute after changing the threshold).

`fetch_all_channels` Celery task runs continuously every `POSTS_FETCH_INTERVAL_MINUTES` (default 20), each tick processing only `POSTS_FETCH_BATCH_SIZE` channels (default 20) ordered by oldest `last_fetched_at` first — this spreads Telethon traffic out instead of bursting through every channel at once (flood-ban risk), while still cycling through all channels over time. A Redis `SET NX` lock (`sumpoint:fetch_lock`, 600s TTL) prevents an overlapping run (e.g. a manual `/channels/sync` firing mid-tick) from racing the scheduled one. Commits per channel inside a try/except so one failing channel doesn't block others; the error is also saved to `Channel.last_error` so it's visible via the API/frontend instead of only in worker logs. `Channel.error_count` tracks consecutive real failures (flood waits don't count) — after `AUTO_DEACTIVATE_AFTER_FAILURES` (default 10) the channel is auto-deactivated (`is_active=False`) so the worker stops wasting Telethon calls on a permanently-broken source, and the owner is notified once; re-enabling via `POST /channels/{id}/toggle` resets the counter. Users without `session_path` AND without `TELEGRAM_SESSION_STRING` are skipped.

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
Vanilla JS SPA (`frontend/`). Layout: dark sidebar with page navigation + light main content. Pages: **Posts** (posts table with date/channel/category filters + expandable rows; per-row checkboxes with a header select-all — the CSV/JSON export button exports just the checked posts client-side when any are selected, otherwise the whole filtered feed via server-side `/posts/export`), **Digests**, **Events** (client-side text search over name/location/channel/topics/speakers/partners, since `/digest/events` has no server-side search like `/posts/search`; per-row checkboxes — `.ics` calendar export is scoped to the checked events when any are selected, otherwise everything currently shown), **Statistics** (analytics dashboard), **Assistant** (RAG chat over your posts), **Channels** (channel management + health panel). Auth via Telegram Login Widget → the JWT arrives as an HttpOnly `sp_session` cookie (see Security posture below); frontend JS never stores or reads it directly.

**i18n:** Russian is the default UI language; a fixed top-right toggle switches to English, persisted in `localStorage` (`sp_lang`) — no server round-trip or account field. All static markup carries `data-i18n`/`data-i18n-placeholder`/`data-i18n-title`/`data-i18n-html` attributes resolved by `frontend/i18n.js`'s `applyI18n()`; every dynamically-rendered string in `app.js` (toasts, table rows, relative-time labels, locale-aware dates) goes through the same file's `t()` helper. Post `category` and event `type` values are written in Russian by the AI (`app/prompts/classification.py`, `app/prompts/event_extraction.py`) and used as literal filter values — `categoryLabel()`/`eventTypeLabel()` translate only the on-screen label, never the underlying value, so filters keep working against the API regardless of UI language. Switching language just persists the choice and reloads the page — simpler than re-rendering every open view in place.

### Prompts
All prompts live in `app/prompts/` (`classification.py`, `summarization.py`, `event_extraction.py`). When editing prompts, keep the parsing logic in `ai_engine.py` in sync with the expected output format.

## Key configuration
All settings loaded from `.env` via Pydantic `Settings` in `app/config.py` (cached with `lru_cache`). Copy `.env.example` to `.env` before first run.

Critical vars: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`, `TELEGRAM_BOT_TOKEN`, `DEEPSEEK_API_KEY`, `DATABASE_URL`, `SESSION_ENCRYPTION_KEY` (32-byte hex: `openssl rand -hex 32`), `SECRET_KEY`, `APP_BASE_URL` (public `https://` domain — left at its `localhost` default, the magic-link message the bot sends still arrives but its login link is unreachable, which reads as "there's no link"; `app/main.py` logs a warning at startup if this looks misconfigured in production).

### Security posture
- **Auth:** all four Telegram flows (Login Widget, Mini App, Magic Link) verify an HMAC-SHA256 with `hmac.compare_digest` and a 24h `auth_date` freshness window, then mint a JWT (HS256, `SECRET_KEY`, claims `sub`/`tv`/`iat`/`exp`, 7-day expiry). The JWT is delivered as an **HttpOnly, `SameSite=Lax`, `Secure` (off only in `DEBUG`) cookie** (`sp_session`) — JavaScript can't read it, so an XSS payload can't exfiltrate it, and `SameSite=Lax` blocks the cookie on cross-site POST/DELETE (CSRF) without a separate token. `get_current_user` reads the cookie (Bearer header as a fallback for API clients) and rejects a token whose `tv` != the user's `token_version`, so `POST /auth/logout-all` (bumps `token_version`) instantly revokes every issued token; `POST /auth/logout` just clears the cookie. Magic-link verify is an atomic `UPDATE ... WHERE used=false RETURNING` (no double-spend).
- **Rate limiting:** slowapi keyed on the real client IP (last `X-Forwarded-For` entry, un-spoofable behind Caddy), **Redis-backed** (`REDIS_URL`) so limits are shared across workers and survive restarts, with `swallow_errors` (fail-open on a Redis blip) and a global `240/min` default (`SlowAPIMiddleware`); `/health` and static serving are exempt.
- **Headers:** every response carries CSP, `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and HSTS (set in `app/main.py`). The CSP `script-src` omits `'unsafe-inline'` — the frontend uses external files + delegated listeners (no inline `on*`/`<script>`), so an injected script can't run and steal the session cookie's JWT; Telegram's widget host + iframe are whitelisted.
- **Data isolation:** every query is scoped by `channels.user_id` / `user_id`; Telethon sessions are AES-256-GCM encrypted at rest.
- **Access control (who can even sign up):** Telegram auth alone only proves *which* Telegram account is logging in, not that they're welcome — any real account can pass the HMAC check. `users.is_approved` (default `false`) gates every business endpoint via `app/api/deps.py`'s `CurrentUser` (`/auth/me`, `/auth/logout*` intentionally use `get_current_user` directly instead, so a pending user can still check their status and sign out). A brand-new signup is auto-approved only if their Telegram id is in the live `Settings.owner_telegram_id_set` (`OWNER_TELEGRAM_IDS` env, no DB write needed to grant/revoke) or they supply a valid invite code (`app/models/invite_code.py`, single-use by default, redeemed atomically via `invite_repository.try_consume`); otherwise they land pending and the configured owner(s) get a bot DM with an inline "✅ Одобрить" button. The owner generates codes with the bot's `/invite` command or the "Доступ" page (`/admin/invites`, owner-only via `app/api/admin.py`). Bot commands are gated the same way — `bot/bot.py`'s `require_approved()` wraps every data-touching handler so approval can't be bypassed by going through the bot instead of the web app. The migration that introduced this backfilled every pre-existing user to `is_approved=true`, so shipping it never locks out someone already using the app.

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

### 4. Fetch pipeline freshness (HTTP monitor)
- **Type:** HTTP(s)
- **URL:** `https://<your-domain>/api/v1/health/fetch`
- **Interval:** 300s (5 min)
- **Retries:** 2
- **Expected:** HTTP 200, JSON with `"status": "healthy"`
- Checks the newest `Channel.last_fetched_at` across all channels — `fetch_all_channels` touches it every tick, on both success and failure, so a stale value (> 2x `POSTS_FETCH_INTERVAL_MINUTES`) means beat stopped scheduling ticks or the worker stopped picking them up, even though the worker heartbeat and API health check still look green. Added after a Docker restart on 2026-07-04 wedged the worker with no posts ingested for four days and nothing caught it.

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
