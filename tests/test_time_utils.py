from datetime import datetime, timezone

from app.utils.time import utcnow


def test_utcnow_is_naive():
    now = utcnow()
    assert now.tzinfo is None


def test_utcnow_close_to_real_utc():
    # Within a few seconds of the true UTC wall clock.
    delta = abs((datetime.now(timezone.utc).replace(tzinfo=None) - utcnow()).total_seconds())
    assert delta < 5
