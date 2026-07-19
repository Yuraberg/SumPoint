"""Unit tests for the pure helpers behind the bot's ⭐/✖ toggle buttons."""
from bot.handlers.favorites import _chunk, favorite_toggle_row


def test_favorite_toggle_row_labels_by_state():
    buttons = favorite_toggle_row([(10, True), (20, False), (30, False)])
    assert [b.text for b in buttons] == ["⭐1", "☆2", "☆3"]
    assert [b.callback_data for b in buttons] == ["favtoggle:10", "favtoggle:20", "favtoggle:30"]


def test_favorite_toggle_row_empty():
    assert favorite_toggle_row([]) == []


def test_chunk_splits_into_fixed_size_groups():
    assert _chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_empty_list():
    assert _chunk([], 5) == []
