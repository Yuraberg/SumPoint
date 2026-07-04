"""Project-wide constants shared across the API, worker, and bot.

Single source of truth for values that were previously duplicated across
several modules (model names, Telegram limits, digest defaults, anti-flood
pacing, ad heuristics, cron presets).
"""

# ── DeepSeek models ───────────────────────────────────────────────────────────
DEFAULT_MODEL = "deepseek-v4-flash"
AVAILABLE_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]
MODEL_LABELS = {"deepseek-v4-flash": "Flash", "deepseek-v4-pro": "Pro"}

# ── Telegram message limits ───────────────────────────────────────────────────
# Telegram hard-caps a message at 4096 chars; we truncate a little below that
# to leave room for the trailing ellipsis marker.
TELEGRAM_MSG_LIMIT = 4096
DIGEST_TEXT_LIMIT = 4000

# ── Digest defaults ───────────────────────────────────────────────────────────
DEFAULT_DIGEST_HOURS = 24
VALID_DIGEST_HOURS = [24, 72, 168]
DIGEST_HOURS_LABELS = {24: "24 ч", 72: "72 ч", 168: "7 дней"}
DIGEST_SLOT_LABELS = {
    "morning": "🌅 Утренний (09:00)",
    "evening": "🌆 Вечерний (21:00)",
}

# ── Post fetch / dedup pacing ─────────────────────────────────────────────────
# Reposted/identical text is deduped against posts published within this window,
# so a channel re-posting old content doesn't get flagged forever.
CONTENT_DEDUP_WINDOW_DAYS = 14

# Anti-flood: pause between individual channel fetches and, less often, a longer
# pause between batches — keeps Telethon traffic spread out to avoid flood bans.
CHANNEL_FETCH_DELAY = 1.5   # seconds between individual channel fetches
CHANNEL_BATCH_SIZE = 5      # channels per batch before a longer pause
CHANNEL_BATCH_DELAY = 8.0   # seconds between batches

# Redis lock guarding overlapping fetch_all_channels runs.
FETCH_LOCK_KEY = "sumpoint:fetch_lock"
FETCH_LOCK_TTL = 600        # safety net if a worker dies mid-run, in seconds

# Per-channel history window pulled from Telethon on each fetch tick.
FETCH_HISTORY_HOURS = 24
# Max messages pulled per channel per tick (Telethon iter_messages limit).
FETCH_MESSAGE_LIMIT = 500

# ── Embeddings ────────────────────────────────────────────────────────────────
EMBEDDING_DIM = 1024  # BGE-M3

# ── Ad detection heuristics ───────────────────────────────────────────────────
AD_KEYWORDS = frozenset({
    "реклама", "спонсор", "промокод", "скидка",
    "#реклама", "#ad", "#sponsor", "партнёрский",
})

# ── Schedules (v2, cron-based) ────────────────────────────────────────────────
SCHEDULE_TYPES = ["topics", "events", "collect"]
SCHEDULE_STATUSES = ["active", "paused", "disabled"]
SCHEDULE_TYPE_LABELS = {"topics": "Темы", "events": "События", "collect": "Сбор"}

CRON_PRESETS = {
    "0 9 * * *":    "Каждый день в 09:00",
    "0 12 * * *":   "Каждый день в 12:00",
    "0 21 * * *":   "Каждый день в 21:00",
    "0 */6 * * *":  "Каждые 6 часов",
    "0 * * * *":    "Каждый час",
    "*/30 * * * *": "Каждые 30 минут",
}

# ── Auth ──────────────────────────────────────────────────────────────────────
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 60 * 60 * 24 * 7   # 7 days
AUTH_FRESHNESS_SECONDS = 86400            # Telegram auth_date must be within 24h
MAGIC_LINK_TTL_MINUTES = 10
