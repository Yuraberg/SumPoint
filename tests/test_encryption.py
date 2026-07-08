import pytest
from cryptography.exceptions import InvalidTag

from app.services import encryption


def test_encrypt_decrypt_roundtrip():
    plaintext = b"telethon session bytes \x00\x01\x02"
    ciphertext = encryption.encrypt_file(plaintext)
    assert ciphertext != plaintext
    assert encryption.decrypt_file(ciphertext) == plaintext


def test_decrypt_rejects_tampered_ciphertext():
    ciphertext = bytearray(encryption.encrypt_file(b"some session data"))
    ciphertext[-1] ^= 0xFF  # flip last byte of the GCM tag
    with pytest.raises(InvalidTag):
        encryption.decrypt_file(bytes(ciphertext))


def test_get_key_rejects_wrong_length(monkeypatch):
    monkeypatch.setattr(encryption._settings, "session_encryption_key", "00" * 16)
    with pytest.raises(RuntimeError, match="32 bytes"):
        encryption._get_key()


def test_get_key_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(encryption._settings, "session_encryption_key", "")
    with pytest.raises(RuntimeError, match="not set"):
        encryption._get_key()
