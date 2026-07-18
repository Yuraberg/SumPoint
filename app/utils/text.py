"""Text helpers shared by the bot and worker."""
from app.constants import DIGEST_TEXT_LIMIT


def truncate(text: str, limit: int = DIGEST_TEXT_LIMIT) -> str:
    """Trim ``text`` to ``limit`` chars, appending an ellipsis marker if cut.

    Telegram rejects messages longer than 4096 chars; callers pass digests and
    search results through here so a long body degrades gracefully instead of
    raising ``BadRequest: message is too long``.

    Cuts on the nearest preceding blank line (or single newline) rather than a
    raw character offset — a mid-character cut has previously landed inside an
    open Markdown entity (e.g. an unclosed ``**`` or ``[text](url``), which
    made Telegram reject the whole message with "can't parse entities" instead
    of just looking truncated.
    """
    if len(text) <= limit:
        return text
    cut = text.rfind("\n\n", 0, limit)
    if cut == -1:
        cut = text.rfind("\n", 0, limit)
    if cut == -1:
        cut = limit
    return text[:cut] + "\n…"
