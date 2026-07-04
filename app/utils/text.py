"""Text helpers shared by the bot and worker."""
from app.constants import DIGEST_TEXT_LIMIT


def truncate(text: str, limit: int = DIGEST_TEXT_LIMIT) -> str:
    """Trim ``text`` to ``limit`` chars, appending an ellipsis marker if cut.

    Telegram rejects messages longer than 4096 chars; callers pass digests and
    search results through here so a long body degrades gracefully instead of
    raising ``BadRequest: message is too long``.
    """
    if len(text) > limit:
        return text[:limit] + "\n…"
    return text
