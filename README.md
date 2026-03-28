# 📡 SumPoint

**Intelligent Telegram content processing** — AI-powered digest, classification & event extraction.

SumPoint connects to your Telegram subscriptions, automatically filters out ads and noise, and delivers a structured daily digest with category labels, concise summaries, and an upcoming-events calendar — all powered by Claude.

---

## ✨ Features

| Feature | Description |
|---|---|
| **AI Classification** | Each post is tagged: Market, Technology, Shopping, Events, Politics… |
| **Smart Summarisation** | 1-3 sentence summaries preserving key facts and numbers |
| **Event Extraction** | Dates, times, event names and links pulled into a calendar |
| **Semantic Search** | Find posts by meaning, not just keywords (pgvector) |
| **Telegram Bot** | Morning/evening digest delivery + quick category filters |
| **Web Dashboard** | Clean dark-mode UI with feed, calendar widget, and prompt editor |

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Telegram Channels  →  Telethon (User API)              │
│                              │                           │
│                       Pre-filter (ads, dupes)           │
│                              │                           │
│                       Celery Worker                     │
│                              │                           │
│                    Claude (Opus 4.6)                    │
│              ┌───────────────┼──────────────┐           │
│         Classify        Summarise      Extract Events   │
│              └───────────────┼──────────────┘           │
│                       PostgreSQL + pgvector             │
│                              │                           │
│              ┌───────────────┼──────────────┐           │
│         FastAPI            Telegram Bot    Frontend     │
└─────────────────────────────────────────────────────────┘
```

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
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → /newbot |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `SESSION_ENCRYPTION_KEY` | `openssl rand -hex 32` |
| `SECRET_KEY` | `openssl rand -hex 32` |

### 3. Run with Docker Compose

```bash
docker compose up -d
```

The API will be available at `http://localhost:8000`
The web dashboard at `http://localhost:8000/`
API docs at `http://localhost:8000/docs`

### 4. Run locally (development)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start DB + Redis
docker compose up -d db redis

# Apply migrations
alembic upgrade head

# API
uvicorn app.main:app --reload

# Celery worker (separate terminal)
celery -A app.tasks.celery_app worker --loglevel=info

# Celery beat scheduler (separate terminal)
celery -A app.tasks.celery_app beat --loglevel=info

# Telegram bot (separate terminal)
python -m bot.bot
```

---

## 📁 Project Structure

```
SumPoint/
├── app/
│   ├── api/            # FastAPI routers (auth, channels, posts, digest)
│   ├── models/         # SQLAlchemy models (User, Channel, Post)
│   ├── prompts/        # Prompt templates (classification, summarisation, events)
│   ├── services/       # Business logic (AI engine, Telegram ingestion, encryption)
│   └── tasks/          # Celery tasks (fetch, digest scheduling)
├── bot/                # Telegram bot (python-telegram-bot)
│   └── handlers/       # Command & callback handlers
├── frontend/           # Single-page web dashboard
│   ├── index.html
│   ├── style.css
│   └── app.js
├── alembic/            # Database migrations
├── docker-compose.yml
└── .env.example
```

---

## 🔐 Security

- Telegram session files are encrypted at rest with **AES-256-GCM**
- Web panel authentication via **Telegram Login Widget** + JWT
- **Row-Level Security** can be enabled in PostgreSQL for per-user data isolation

---

## 🤖 Prompt Engineering

All Claude prompts follow the spec:

- **Role Prompting** — "Professional Business Assistant with data analytics skills"
- **Delimiters** — `###` and `"""` separate instructions from content
- **Chain-of-Thought** — `<thought>` block for pre-analysis
- **Few-Shot** — 3 annotated examples in the classification prompt

---

## 📄 License

MIT
