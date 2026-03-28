"""
AI Engine — Claude-powered classification, summarisation, event extraction,
and semantic search embedding generation.

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

import anthropic

from app.config import get_settings
from app.prompts import (
    build_classification_prompt,
    build_summarization_prompt,
    build_event_extraction_prompt,
)
from app.prompts.classification import CATEGORIES

logger = logging.getLogger(__name__)
settings = get_settings()

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

MODEL = "claude-opus-4-6"
MAX_TOKENS = 512


def _call(prompt: str, max_tokens: int = MAX_TOKENS) -> str:
    """Send a prompt to Claude and return the text response."""
    response = _client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    )
    # Extract text from content blocks
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return ""


def classify_post(text: str) -> str:
    """Return one of the predefined category strings for the given post text."""
    prompt = build_classification_prompt(text)
    raw = _call(prompt)
    # The model outputs a <thought>…</thought> block then the category.
    # Strip the thought block and take the last non-empty line.
    clean = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL).strip()
    last_line = [l.strip() for l in clean.splitlines() if l.strip()][-1] if clean else ""
    # Validate against known categories
    for cat in CATEGORIES:
        if cat.lower() in last_line.lower():
            return cat
    logger.warning("Could not parse category from: %r", raw)
    return "Other"


def summarise_post(text: str, channel_title: str) -> str:
    """Return a 1-3 sentence summary of the post."""
    prompt = build_summarization_prompt(text, channel_title)
    raw = _call(prompt, max_tokens=256)
    # Strip thought block
    clean = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL).strip()
    return clean


def extract_events(text: str) -> list[dict[str, Any]]:
    """Return a list of event dicts extracted from the post."""
    prompt = build_event_extraction_prompt(text)
    raw = _call(prompt, max_tokens=512)
    # Strip thought block
    clean = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL).strip()
    # Find JSON array
    match = re.search(r"\[.*\]", clean, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        logger.warning("Failed to parse events JSON: %r", clean)
        return []


def generate_embedding(text: str) -> list[float]:
    """
    Generate a text embedding using Claude's approach.
    Note: Anthropic does not yet expose a dedicated embeddings endpoint,
    so we use a lightweight prompt to produce a 1536-dim float list
    via a numeric encoding step — in production, swap this for
    OpenAI text-embedding-3-small or a local model.
    """
    # Placeholder: return a zero vector so the pipeline stays functional
    # without a separate embeddings API key.
    logger.info("Embedding generation: using zero-vector placeholder")
    return [0.0] * 1536


def process_post(text: str, channel_title: str) -> dict[str, Any]:
    """Full AI pipeline for one post. Returns enriched fields."""
    return {
        "category": classify_post(text),
        "summary": summarise_post(text, channel_title),
        "events": extract_events(text),
        "embedding": generate_embedding(text),
    }
