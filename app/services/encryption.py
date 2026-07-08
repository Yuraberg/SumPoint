"""AES-256-GCM encryption for Telegram session files."""
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_settings = get_settings()


def _get_key() -> bytes:
    raw = _settings.session_encryption_key
    if not raw:
        raise RuntimeError("SESSION_ENCRYPTION_KEY is not set")
    key = bytes.fromhex(raw)
    if len(key) != 32:
        raise RuntimeError(
            f"SESSION_ENCRYPTION_KEY must be 32 bytes (64 hex chars) for AES-256, got {len(key)} bytes"
        )
    return key


def encrypt_file(plaintext: bytes) -> bytes:
    """Encrypt bytes with AES-256-GCM. Returns nonce + ciphertext."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_file(data: bytes) -> bytes:
    """Decrypt bytes produced by encrypt_file."""
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None)


def save_encrypted(path: str, plaintext: bytes) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(encrypt_file(plaintext))


def load_decrypted(path: str) -> bytes:
    with open(path, "rb") as f:
        return decrypt_file(f.read())
