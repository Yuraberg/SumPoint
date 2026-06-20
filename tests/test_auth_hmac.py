import hashlib
import hmac
import json
import time

from app.api.auth import TelegramAuthData, _verify_telegram_hash, _verify_webapp_init_data, settings


def _signed_login_widget_data(**overrides) -> TelegramAuthData:
    fields = {
        "id": 12345,
        "first_name": "Test",
        "auth_date": int(time.time()),
        **overrides,
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return TelegramAuthData(**fields)


def test_telegram_hash_accepts_valid_signature():
    data = _signed_login_widget_data()
    assert _verify_telegram_hash(data) is True


def test_telegram_hash_rejects_tampered_field():
    data = _signed_login_widget_data()
    data.first_name = "Attacker"
    assert _verify_telegram_hash(data) is False


def test_telegram_hash_rejects_wrong_hash():
    data = _signed_login_widget_data()
    data.hash = "0" * 64
    assert _verify_telegram_hash(data) is False


def test_telegram_hash_rejects_stale_auth_date():
    data = _signed_login_widget_data(auth_date=int(time.time()) - 100000)
    assert _verify_telegram_hash(data) is False


def _signed_init_data(user: dict, auth_date: int | None = None) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAAtest",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    from urllib.parse import urlencode
    return urlencode(fields)


def test_webapp_init_data_accepts_valid_signature():
    init_data = _signed_init_data({"id": 999, "first_name": "Mini"})
    result = _verify_webapp_init_data(init_data)
    assert result == {"id": 999, "first_name": "Mini"}


def test_webapp_init_data_rejects_tampered_payload():
    init_data = _signed_init_data({"id": 999, "first_name": "Mini"})
    tampered = init_data.replace("Mini", "Evil")
    assert _verify_webapp_init_data(tampered) is None


def test_webapp_init_data_rejects_missing_hash():
    assert _verify_webapp_init_data("auth_date=123&user=%7B%7D") is None


def test_webapp_init_data_rejects_empty_string():
    assert _verify_webapp_init_data("") is None
