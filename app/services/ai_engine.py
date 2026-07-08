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


async def _call(prompt: str, max_tokens: int = MAX_TOKENS, model: str | None = None) -> str:
    """Send a prompt to DeepSeek and return the text response."""
    response = await _get_client().chat.completions.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


async def generate_digest_text(summaries: list[dict], model: str | None = None) -> str:
    """Public entry point for digest assembly — keeps callers out of ``_call``."""
    from app.prompts.summarization import build_digest_prompt

    return await _call(build_digest_prompt(summaries), max_tokens=4096, model=model)


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
