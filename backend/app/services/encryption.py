from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _derive_key(encryption_key: str) -> bytes:
    raw = encryption_key.strip()
    if not raw:
        raise ValueError("ENCRYPTION_KEY is not configured")
    try:
        decoded = base64.urlsafe_b64decode(raw + "==")
        if len(decoded) == 32:
            return decoded
    except Exception:  # noqa: BLE001
        pass
    if len(raw.encode("utf-8")) == 32:
        return raw.encode("utf-8")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def encrypt_secret(plaintext: str, encryption_key: str) -> str:
    key = _derive_key(encryption_key)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(ciphertext: str, encryption_key: str) -> str:
    key = _derive_key(encryption_key)
    blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    nonce, encrypted = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, encrypted, None).decode("utf-8")
