from __future__ import annotations

import pytest

from app.services.encryption import decrypt_secret, encrypt_secret


@pytest.fixture
def key() -> str:
    return "test-encryption-key-32-bytes!!"


def test_encrypt_decrypt_roundtrip(key: str) -> None:
    plaintext = "snaptrade-user-secret-value"
    encrypted = encrypt_secret(plaintext, key)
    assert encrypted != plaintext
    assert decrypt_secret(encrypted, key) == plaintext


def test_encrypt_requires_key() -> None:
    with pytest.raises(ValueError):
        encrypt_secret("secret", "")
