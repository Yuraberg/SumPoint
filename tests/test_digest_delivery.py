from app.services.digest_delivery import format_events_message


def test_empty_events_message():
    assert "Нет предстоящих событий" in format_events_message([])


def test_formats_event_with_link():
    events = [{"name": "Конференция", "date": "2026-08-01", "time": "10:00", "link": "https://x"}]
    msg = format_events_message(events)
    assert "*Конференция*" in msg
    assert "2026-08-01" in msg
    assert "[→](https://x)" in msg


def test_event_without_link_has_no_arrow():
    events = [{"name": "Митап", "date": "2026-08-01"}]
    msg = format_events_message(events)
    assert "→" not in msg


def test_limit_caps_number_of_events():
    events = [{"name": f"E{i}", "date": "2026-08-01"} for i in range(20)]
    msg = format_events_message(events, limit=3)
    # header + 3 bullets
    assert msg.count("•") == 3


def test_missing_name_falls_back():
    msg = format_events_message([{"date": "2026-08-01"}])
    assert "Событие" in msg
