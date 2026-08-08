"""Safe Telegram send/edit/reply — Markdown parse-error fallback.

Telegram rejects a whole message if its Markdown entities are unbalanced —
common in text we don't control (post excerpts, channel/event titles, search
queries, AI-generated digests). Without a fallback, `reply_text(...,
parse_mode="Markdown")` raises `BadRequest`, the bot's global error handler
(`bot.py:on_error`) only logs it, and the user gets silence instead of a
reply. These wrappers retry once as plain text, the same pattern already
proven in `app.services.digest_delivery.send_digest_for_user`.
"""
import logging

from telegram.error import BadRequest

logger = logging.getLogger(__name__)


async def safe_reply(message, text, parse_mode="Markdown", **kwargs):
    """``message.reply_text`` with Markdown, falling back to plain text."""
    try:
        return await message.reply_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        logger.warning("Markdown rejected on reply (%s); resending as plain text", e)
        return await message.reply_text(text, parse_mode=None, **kwargs)


async def safe_edit(query_or_message, text, parse_mode="Markdown", **kwargs):
    """``edit_message_text`` with Markdown, falling back to plain text.

    "Message is not modified" isn't a parse error — the plain-text retry
    would just reformat the message for no reason, so it's swallowed
    instead of retried.
    """
    try:
        return await query_or_message.edit_message_text(text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            return None
        logger.warning("Markdown rejected on edit (%s); resending as plain text", e)
        return await query_or_message.edit_message_text(text, parse_mode=None, **kwargs)


async def safe_send(bot, chat_id, text, parse_mode="Markdown", **kwargs):
    """``bot.send_message`` with Markdown, falling back to plain text."""
    try:
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, **kwargs)
    except BadRequest as e:
        logger.warning("Markdown rejected on send to %s (%s); resending as plain text", chat_id, e)
        return await bot.send_message(chat_id=chat_id, text=text, parse_mode=None, **kwargs)
