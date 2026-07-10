"""Access-control unit tests: owner-id parsing, approval decision, and
invite-code validity — all pure, no DB required."""
from datetime import timedelta

from app.config import Settings
from app.models.invite_code import InviteCode
from app.models.user import User
from app.repositories.invite_repository import is_valid
from app.utils.time import utcnow


def _settings(**overrides):
    base = dict(secret_key="t", session_encryption_key="00" * 32,
                telegram_bot_token="1:t", database_url="postgresql+asyncpg://t:t@localhost/t",
                deepseek_api_key="t")
    base.update(overrides)
    return Settings(**base)


def test_owner_telegram_id_set_parses_csv():
    s = _settings(owner_telegram_ids="123, 456,789")
    assert s.owner_telegram_id_set == {123, 456, 789}


def test_owner_telegram_id_set_empty_by_default():
    assert _settings().owner_telegram_id_set == set()


def test_owner_telegram_id_set_ignores_blank_entries():
    s = _settings(owner_telegram_ids="123,,  ,456")
    assert s.owner_telegram_id_set == {123, 456}


def test_is_effectively_approved_owner_bypasses_db_flag(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps, "get_settings", lambda: _settings(owner_telegram_ids="42"))
    user = User(id=42, first_name="Owner")
    user.is_approved = False  # DB row not approved — allowlist still grants access
    assert deps.is_effectively_approved(user) is True


def test_is_effectively_approved_respects_db_flag_for_non_owner(monkeypatch):
    from app.api import deps

    monkeypatch.setattr(deps, "get_settings", lambda: _settings(owner_telegram_ids="42"))
    pending = User(id=99, first_name="Pending")
    pending.is_approved = False
    approved = User(id=100, first_name="Approved")
    approved.is_approved = True
    assert deps.is_effectively_approved(pending) is False
    assert deps.is_effectively_approved(approved) is True


def test_invite_is_valid_within_uses_and_not_expired():
    inv = InviteCode(code="AAAAAAAA", max_uses=2, uses=1, expires_at=None)
    assert is_valid(inv) is True


def test_invite_is_valid_false_when_exhausted():
    inv = InviteCode(code="AAAAAAAA", max_uses=1, uses=1, expires_at=None)
    assert is_valid(inv) is False


def test_invite_is_valid_false_when_expired():
    inv = InviteCode(code="AAAAAAAA", max_uses=5, uses=0, expires_at=utcnow() - timedelta(minutes=1))
    assert is_valid(inv) is False


def test_invite_is_valid_true_when_expires_in_future():
    inv = InviteCode(code="AAAAAAAA", max_uses=5, uses=0, expires_at=utcnow() + timedelta(minutes=1))
    assert is_valid(inv) is True
