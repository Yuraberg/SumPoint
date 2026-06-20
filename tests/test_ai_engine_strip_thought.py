from app.services.ai_engine import _strip_thought


def test_strip_closed_thought_block():
    raw = "<thought>reasoning here</thought>Краткое резюме."
    assert _strip_thought(raw) == "Краткое резюме."


def test_strip_unterminated_thought_block():
    # Simulates DeepSeek output truncated by max_tokens before the closing tag.
    raw = "Some preamble<thought>reasoning that never closes because tokens ran out"
    assert _strip_thought(raw) == "Some preamble"


def test_strip_thought_no_block_present():
    raw = "Просто текст без thought-блока."
    assert _strip_thought(raw) == raw


def test_strip_thought_multiple_blocks():
    raw = "<thought>a</thought>Result<thought>b</thought>"
    assert _strip_thought(raw) == "Result"
