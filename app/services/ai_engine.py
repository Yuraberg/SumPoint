"""
AI Engine — DeepSeek-powered classification, summarisation, and event extraction.

All prompts follow the spec:
  - Role Prompting
  - Chain-of-Thought (<thought> block)
  - Few-Shot examples (in classification prompt)
  - Delimiters (### and \"\"\")
"""
import asyncio
import json
import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.constants import EMBEDDING_DIM
from app.prompts import (
    build_classification_prompt,
    build_event_extraction_prompt,
    build_summarization_prompt,
)
from app.prompts.classification import CATEGORIES

logger = logging.getLogger(__name__)
settings = get_settings()

MODEL = settings.deepseek_model
MAX_TOKENS = 512

# The DeepSeek client wraps an httpx session bound to the event loop it is first
# used on. Celery runs each task in a fresh loop (asyncio.run), so a single
# module-level client would raise "Event loop is closed" on the second task.
# Cache the client per running loop and rebuild it when the loop changes.
_client: AsyncOpenAI | None = None
_client_loop: asyncio.AbstractEventLoop | None = None

# Same per-loop caching for the Ollama embedding client — avoids opening a
# fresh TCP connection for every single post in a fetch batch.
_embed_client: httpx.AsyncClient | None = None
_embed_client_loop: asyncio.AbstractEventLoop | None = None


def _get_client() -> AsyncOpenAI:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key or None,
            base_url=settings.deepseek_base_url,
            max_retries=3,
            # Without this the SDK falls back to httpx's 600s default — a
            # hung DeepSeek call would stall the Celery task (and, via the
            # asyncio.gather in process_post, the whole post) for 10 minutes
            # before failing.
            timeout=90.0,
        )
        _client_loop = loop
    return _client


def _get_embed_client() -> httpx.AsyncClient:
    global _embed_client, _embed_client_loop
    loop = asyncio.get_running_loop()
    if _embed_client is None or _embed_client_loop is not loop:
        _embed_client = httpx.AsyncClient(timeout=60)
        _embed_client_loop = loop
    return _embed_client


def _strip_thought(raw: str) -> str:
    """Remove <thought>...</thought> blocks. Also strips an unterminated
    trailing <thought> (e.g. truncated by max_tokens) so it never leaks
    into a summary/category shown to the user."""
    clean = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL)
    clean = re.sub(r"<thought>.*$", "", clean, flags=re.DOTALL)
    return clean.strip()


async def _call_raw(prompt: str, max_tokens: int = MAX_TOKENS, model: str | None = None):
    """Send a prompt to DeepSeek and return the raw completion object — lets
    callers that care (e.g. the digest) inspect ``finish_reason`` instead of
    just the text, to tell a genuine answer from one cut off by max_tokens."""
    return await _get_client().chat.completions.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )


async def _call(prompt: str, max_tokens: int = MAX_TOKENS, model: str | None = None) -> str:
    """Send a prompt to DeepSeek and return the text response."""
    response = await _call_raw(prompt, max_tokens=max_tokens, model=model)
    return response.choices[0].message.content.strip()


async def answer_from_context(question: str, context: str, model: str | None = None) -> str:
    """RAG answer: reply to ``question`` grounded strictly in ``context`` (the
    retrieved posts, each prefixed with a [N] marker). Used by the assistant
    chat — kept here so all DeepSeek calls share one client/timeout config."""
    system = (
        "Ты — ассистент по личной ленте Telegram-каналов пользователя. "
        "Отвечай на вопрос ТОЛЬКО на основе приведённых ниже постов. "
        "Ссылайся на источники в квадратных скобках в формате [N], где N — номер поста. "
        "Если информации в постах недостаточно для ответа, честно скажи об этом и не выдумывай. "
        "Отвечай на русском языке, кратко и по существу."
    )
    user = f"Вопрос: {question}\n\n### Посты\n{context}"
    response = await _get_client().chat.completions.create(
        model=model or MODEL,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _strip_thought(response.choices[0].message.content.strip())


DIGEST_MAX_TOKENS = 8192


def _trim_incomplete_tail(text: str) -> str:
    """Drop the last line of a completion that was cut off by max_tokens — it's
    reliably mid-sentence (or mid-Markdown-entity, e.g. a bare "- Channel: <"),
    never a bullet worth keeping."""
    idx = text.rstrip().rfind("\n")
    return text[:idx].rstrip() if idx != -1 else ""


async def generate_digest_text(summaries: list[dict], model: str | None = None) -> str:
    """Public entry point for digest assembly — keeps callers out of ``_call``.

    DeepSeek occasionally returns a 200 with empty content for large digest
    prompts (no exception, so ``_call``'s retries never kick in) — retry once
    before giving up, since callers otherwise mistake this for "no posts".
    """
    from app.prompts.summarization import build_digest_prompt

    # A post with no summary contributes nothing but bulk to the prompt, and
    # DeepSeek just parrots it back as a bare "- Channel: " bullet with no
    # content — drop it rather than pad the digest with empty lines. If every
    # summary is empty (shouldn't normally happen), fall back to the original
    # list so the digest call still has something to work with.
    usable = [s for s in summaries if (s.get("summary") or "").strip()]
    prompt = build_digest_prompt(usable or summaries)

    response = await _call_raw(prompt, max_tokens=DIGEST_MAX_TOKENS, model=model)
    text = response.choices[0].message.content.strip()
    truncated = response.choices[0].finish_reason == "length"

    if not text.strip():
        logger.warning("DeepSeek returned an empty digest (%d posts); retrying once", len(usable))
        response = await _call_raw(prompt, max_tokens=DIGEST_MAX_TOKENS, model=model)
        text = response.choices[0].message.content.strip()
        truncated = response.choices[0].finish_reason == "length"

    if truncated:
        # The model ran out of output tokens mid-generation — the tail is
        # reliably a broken bullet (empty, or cut off mid-word/mid-markdown,
        # e.g. "- Channel: <"). Drop it and say so, instead of silently
        # shipping a digest that just stops mid-sentence.
        logger.warning(
            "Digest generation hit the token limit (%d posts) — trimming the incomplete tail",
            len(usable),
        )
        text = _trim_incomplete_tail(text)
        text += (
            "\n\n_…дайджест обрезан — слишком много постов за этот период. "
            "Попробуйте сузить временное окно или темы в настройках расписания._"
        )
    return text


async def classify_post(text: str) -> str:
    """Return one of the predefined category strings for the given post text."""
    prompt = build_classification_prompt(text)
    raw = await _call(prompt)
    clean = _strip_thought(raw)
    last_line = [line.strip() for line in clean.splitlines() if line.strip()][-1] if clean else ""
    for cat in CATEGORIES:
        if cat.lower() in last_line.lower():
            return cat
    logger.warning("Could not parse category from: %r", raw)
    return "Прочее"


async def summarise_post(text: str, channel_title: str) -> str:
    """Return a 1-3 sentence summary of the post."""
    prompt = build_summarization_prompt(text, channel_title)
    raw = await _call(prompt, max_tokens=256)
    return _strip_thought(raw)


async def extract_events(text: str) -> list[dict[str, Any]]:
    """Return a list of event dicts extracted from the post."""
    prompt = build_event_extraction_prompt(text)
    raw = await _call(prompt, max_tokens=512)
    clean = _strip_thought(raw)
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        logger.warning("Failed to parse events JSON: %r", clean)
        return []


async def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector using BGE-M3 via Ollama."""
    url = f"{settings.ollama_base_url}/api/embeddings"
    body = {"model": "bge-m3", "prompt": text[:8000]}
    try:
        resp = await _get_embed_client().post(url, json=body)
        resp.raise_for_status()
        data = resp.json()
        vec = data["embedding"]
        logger.info("Embedding generated (%d dims) via Ollama BGE-M3", len(vec))
        return vec
    except Exception as e:
        logger.warning("Ollama BGE-M3 embedding failed: %s — using zero-vector fallback", e)
        return [0.0] * EMBEDDING_DIM


async def process_post(text: str, channel_title: str) -> dict[str, Any] | None:
    """Full AI pipeline for one post. Returns enriched fields, or None if
    DeepSeek is unavailable — callers should skip the post and continue
    with the rest of the batch rather than aborting the whole fetch.

    classify/summarise/extract/embed don't depend on each other's output, so
    they run concurrently instead of as four sequential round-trips."""
    try:
        category, summary, events, embedding = await asyncio.gather(
            classify_post(text),
            summarise_post(text, channel_title),
            extract_events(text),
            generate_embedding(text),
        )
        return {
            "category": category,
            "summary": summary,
            "events": events,
            "embedding": embedding,
        }
    except Exception:
        logger.exception("process_post failed; skipping this post")
        return None
