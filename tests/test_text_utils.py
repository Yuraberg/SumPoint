from app.utils.text import truncate
from app.constants import DIGEST_TEXT_LIMIT


def test_truncate_short_text_unchanged():
    assert truncate("hello") == "hello"


def test_truncate_exactly_at_limit_unchanged():
    text = "x" * DIGEST_TEXT_LIMIT
    assert truncate(text) == text


def test_truncate_over_limit_adds_ellipsis():
    text = "x" * (DIGEST_TEXT_LIMIT + 100)
    out = truncate(text)
    assert out.endswith("\n…")
    assert len(out) == DIGEST_TEXT_LIMIT + len("\n…")


def test_truncate_custom_limit():
    assert truncate("abcdef", limit=3) == "abc\n…"
