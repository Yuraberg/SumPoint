"""
AI Engine — DeepSeek-powered classification, summarisation, and event extraction.

All prompts follow the spec:
  - Role Prompting
  - Chain-of-Thought (<thought> block)
  - Few-Shot examples (in classification prompt)
  - Delimiters (### and \"\"\")
"""
import json
import logging
import re
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import get_settings
from app.prompts import (
    build_classification_prompt,
    build_summarization_prompt,
    build_event_extraction_prompt,
)
from app.prompts.classification import CATEGORIES

logger = logging.getLogger(__name__)
settings = get_settings()

_client = AsyncOpenAI(api_key=settings.deepseek_api_key or None, base_url="https://api.deepseek.com")

MODEL = "deepseek-chat"
MAX_TOKENS = 512


def _strip_thought(raw: str) -> str:
    """Remove <thought>...</thought> blocks. Also strips an unterminated
    trailing <thought> (e.g. truncated by max_tokens) so it never leaks
    into a summary/category shown to the user."""
    clean = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL)
    clean = re.sub(r"<thought>.*$", "", clean, flags=re.DOTALL)
    return clean.strip()


async def _call(prompt: str, max_tokens: int = MAX_TOKENS, model: str | None = None) -> str:
    """Send a prompt to DeepSeek and return the text response."""
    response = await _client.chat.completions.create(
        model=model or MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


async def classify_post(text: str) -> str:
    """Return one of the predefined category strings for the given post text."""
    prompt = build_classification_prompt(text)
    raw = await _call(prompt)
    clean = _strip_thought(raw)
    last_line = [l.strip() for l in clean.splitlines() if l.strip()][-1] if clean else ""
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
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        vec = data["embedding"]
        logger.info("Embedding generated (%d dims) via Ollama BGE-M3", len(vec))
        return vec
    except Exception as e:
        logger.warning("Ollama BGE-M3 embedding failed: %s — using zero-vector fallback", e)
        return [0.0] * 1024


async def process_post(text: str, channel_title: str) -> dict[str, Any] | None:
    """Full AI pipeline for one post. Returns enriched fields, or None if
    DeepSeek is unavailable — callers should skip the post and continue
    with the rest of the batch rather than aborting the whole fetch."""
    try:
        return {
            "category": await classify_post(text),
            "summary": await summarise_post(text, channel_title),
            "events": await extract_events(text),
            "embedding": await generate_embedding(text),
        }
    except Exception:
        logger.exception("process_post failed; skipping this post")
        return None
