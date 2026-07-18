# 📡 SumPoint

**Intelligent Telegram content processing** — AI-powered digest, classification, semantic search and event extraction, with a web dashboard, a RAG assistant and a Telegram bot.

SumPoint connects to your Telegram channel subscriptions, filters out ads and duplicate reposts, and turns the noise into a structured feed: category labels, 1–3 sentence summaries, an upcoming-events calendar, keyword alerts, and scheduled digests — delivered via a web dashboard and a Telegram bot.

[![CI](https://github.com/Yuraberg/SumPoint/actions/workflows/deploy.yml/badge.svg)](https://github.com/Yuraberg/SumPoint/actions/workflows/deploy.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-Proprietary-red)

---

## Contents

- [Screenshots](#-screenshots)
- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Security](#-security)
- [Monitoring & Ops](#-monitoring--ops)
- [Prompt Engineering](#-prompt-engineering)
- [License](#-license)

---

## 📷 Screenshots

| Лента постов | События | Статистика |
|---|---|---|
| ![Посты](docs/screenshots/posts.png) | ![События](docs/screenshots/events.png) | ![Статистика](docs/screenshots/stats.png) |

Лента поддерживает фильтры по дате/каналу/теме, три уровня плотности, полнотекстовый и
семантический поиск, отметку прочитанного и выбор строк чекбоксами для CSV/JSON-экспорта.
Вкладка «События» умеет искать по названию/месту/спикерам и экспортировать выбранные
события в `.ics` для календаря.

---

## ✨ Features

| Feature | Description |
|---|---|
| **AI Classification** | Every post is tagged into a category (Рынок, Технологии, События…) by DeepSeek |
| **Smart Summarisation** | 1–3 sentence summaries that preserve key facts and numbers |
| **Event Extraction** | Dates, times, event names and links pulled out into a calendar view, with a text search over the extracted events and selective `.ics` export |
| **Semantic Search** | Find posts by meaning, not just keywords, via BGE-M3 embeddings + pgvector cosine search |
| **RAG Assistant** | Chat with your own feed — retrieves the most relevant posts and asks DeepSeek to answer with `[N]` citations back to the source |
| **Duplicate Clustering** | Reposts of the same story across channels are grouped ("также в N каналах") via pgvector nearest-neighbour search |
| **Keyword Alerts** | Get pinged the moment a channel posts something matching a word you're watching |
| **Custom Schedules** | Cron-based per-topic digests, not just the two default daily slots |
| **Analytics Dashboard** | Post volume over time, per-category and top-channel breakdowns, unread/event counts |
| **Selective Export** | Check just the rows you want on the Posts/Events tables and export only those — CSV/JSON for posts, `.ics` for events |
| **Telegram Bot** | Morning/evening digest delivery, category filters, one-tap channel management |
| **Web Dashboard** | Dark-mode SPA: post feed, digest view, events calendar, analytics, RAG chat, channel manager |
| **Ad & Dupe Filtering** | Keyword-based ad heuristics + content-hash dedup across reposts |
| **Access Control** | Invite-code / owner-approval gate on signup — new users land in a pending state until approved |

---

## 🏗 Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Telegram Channels  ──▶  Telethon (User API, worker-only)        │
│                                │                                  │
│                       Pre-filter (ads, dupes)                    │
│                                │                                  │
│                         Celery Worker                             │
│                                │                                  │
│              ┌─────────────────┼─────────────────┐               │
│         Classify           Summarise         Extract Events      │
│         (DeepSeek)          (DeepSeek)         (DeepSeek)         │
│                                │                                  │
│                      Embed (Ollama · BGE-M3)                      │
│                                │                                  │
│                     PostgreSQL + pgvector                         │
│                                │                                  │
│              ┌─────────────────┼─────────────────┐               │
│           FastAPI          Telegram Bot         Frontend SPA      │
│        (JWT + rate limit)  (python-telegram-bot)  (vanilla JS)   │
└──────────────────────────────────────────────────────────────────┘
```

Redis backs both the Celery broker/result store and a distributed lock that
paces the continuous fetch loop so it never bursts through every channel at
once (flood-ban avoidance) and never runs two overlapping fetch cycles.

**Why Telethon only runs in the worker:** Telegram's User API bans a session
that's used from two IPs at once, so all Telethon calls are dispatched from
the API container to the worker via Celery — the API process never touches
Telethon directly.

---

## 🚀 Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/Yuraberg/SumPoint.git
cd SumPoint
cp .env.example .env
# Fill in .env with your keys (see below)
```

### 2. Required credentials

| Variable | Where to get it |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org) → API development tools |
| `TELEGRAM_SESSION_STRING` | Run `python generate_session.py` once, locally |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` (same bot used for the Login Widget) |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) |
| `OLLAMA_BASE_URL` | URL of an Ollama instance serving `bge-m3` (for embeddings) |
| `SESSION_ENCRYPTION_KEY` | `openssl rand -hex 32` |
| `SECRET_KEY` | `openssl rand -hex 32` |

See `.env.example` for the full list, including optional ones (`SENTRY_DSN`, `UPTIME_KUMA_PUSH_URL`, digest schedule hours, fetch pacing).

### 3. Run with Docker Compose

```bash
docker compose up -d
```

- Web dashboard + API: `http://localhost:8001`
- API docs: `http://localhost:8001/docs`
- Health check: `http://localhost:8001/api/v1/health`

For production, layer the hardened overrides (no source mounts, resource limits, no published DB/Redis ports):

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 4. Run locally (development, without Docker)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

docker compose up -d db redis    # infrastructure only
alembic upgrade head

uvicorn app.main:app --reload                                # API
celery -A app.tasks.celery_app worker --loglevel=info         # separate terminal
celery -A app.tasks.celery_app beat --loglevel=info           # separate terminal
python -m bot.bot                                             # separate terminal
```

---

## 📁 Project Structure

```
SumPoint/
├── app/
│   ├── api/            # FastAPI routers (auth, admin, channels, posts, digest, chat, stats, schedule, health)
│   ├── models/          # SQLAlchemy models (User, Channel, Post, Schedule, KeywordAlert, MagicLink, InviteCode)
│   ├── repositories/     # Query layer, one module per aggregate
│   ├── schemas/           # Pydantic request/response models
│   ├── prompts/            # DeepSeek prompt templates (classification, summarisation, events)
│   ├── services/            # AI engine, Telegram ingestion, clustering, encryption, digest assembly, RAG
│   └── tasks/                # Celery tasks (fetch, digest scheduling, maintenance)
├── bot/                # Telegram bot (python-telegram-bot)
│   └── handlers/       # /start, digest, settings, search, alerts, access, recent-posts
├── frontend/           # Single-page web dashboard (vanilla JS, no build step)
├── alembic/            # Database migrations (schema is Alembic-owned, not app-managed)
├── scripts/            # backup-db.sh / restore-db.sh
├── tests/              # unit + integration (real Postgres/pgvector) suites
├── docker-compose.yml         # development
├── docker-compose.prod.yml    # production overrides
└── .env.example
```

---

## 🔐 Security

- Telegram session strings encrypted at rest with **AES-256-GCM**
- Auth via **Telegram Login Widget** (HMAC-verified, timing-safe compare) or bot-issued magic links, both exchanged for a **JWT** delivered as an HttpOnly, `SameSite=Lax`, `Secure` cookie — never touched by frontend JS, so XSS can't exfiltrate it
- **Access control**: new signups land in a pending state until an owner approves them or redeems a single-use invite code; every business endpoint is gated on `is_approved`
- Per-endpoint **rate limiting** (`slowapi`), Redis-backed, keyed off the real client IP behind the Caddy reverse proxy (last `X-Forwarded-For` hop, not the first — the first is client-spoofable)
- Security headers on every response: CSP (no `unsafe-inline`), `X-Frame-Options`, HSTS, `Referrer-Policy`, `Permissions-Policy`
- Dependencies scanned with `pip-audit` on every CI run
- Optional **Sentry** integration for error tracking (no-op unless `SENTRY_DSN` is set)

## 📊 Monitoring & Ops

- `GET /api/v1/health` — deep health check (DB `SELECT 1` + Redis `PING`), meant for Uptime Kuma
- `GET /api/v1/health/fetch` — fetch-pipeline freshness check, catches a wedged worker/beat even when the API and worker heartbeat both still look green
- Celery worker heartbeat pushed to Uptime Kuma every 5 minutes when `UPTIME_KUMA_PUSH_URL` is set
- Every request gets a `request_id`, echoed in the `X-Request-ID` response header and stitched into JSON logs, so a bug report can be traced back to exact log lines
- `scripts/backup-db.sh` / `scripts/restore-db.sh` for pg_dump-based backup and restore; deploy pipeline keeps the nightly backup cron installed on the host
- CI (`.github/workflows/deploy.yml`) runs lint + `pip-audit` + unit tests on every PR, runs integration tests against a real Postgres/pgvector service container, and deploys via SSH on merge to `main` — with an automatic rollback to the previous commit if the post-deploy health check fails

---

## 🤖 Prompt Engineering

All DeepSeek prompts (`app/prompts/`) follow a consistent structure:

- **Role Prompting** — a defined persona per task (classifier, summariser, event extractor)
- **Delimiters** — `###` and `"""` separate instructions from post content
- **Chain-of-Thought** — a `<thought>` block for pre-analysis, stripped before the result is stored or shown
- **Few-Shot** — annotated examples in the classification prompt

---

## 📄 License

**© 2026 Yuraberg. All rights reserved.**

This software is proprietary. No use, copying, modification, or distribution
is permitted without prior written authorization from the copyright holder —
see [LICENSE](LICENSE) for the full terms.
