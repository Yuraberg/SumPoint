from app.api.posts import _escape_like


def test_escape_like_passes_through_plain_text():
    assert _escape_like("hello world") == "hello world"


def test_escape_like_escapes_percent_and_underscore():
    assert _escape_like("100%_done") == "100\\%\\_done"


def test_escape_like_escapes_backslash_first():
    # Backslash must be escaped before % and _ are escaped, otherwise the
    # escaping backslashes themselves would be re-escaped.
    assert _escape_like("a\\b") == "a\\\\b"


def test_escape_like_neutralises_wildcard_injection():
    # A naive ILIKE search for "%" would match every row; escaped, it's literal.
    escaped = _escape_like("%")
    assert escaped == "\\%"
