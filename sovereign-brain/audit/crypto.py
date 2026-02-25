"""
Sovereign Brain — Field Encryption
====================================
AES-128-CBC + HMAC-SHA256 via Python cryptography.fernet.
MultiFernet supports key rotation: first key encrypts, all keys decrypt.

Key generation:
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotation (prepend new key, keep old key):
    FIELD_ENCRYPTION_KEY=<new_key>,<old_key>
"""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class AuditCrypto:
    """Thin wrapper around MultiFernet for audit field encryption/decryption."""

    def __init__(self, key_string: str):
        self._fernet: MultiFernet | None = None
        if key_string:
            keys = [
                Fernet(k.strip().encode())
                for k in key_string.split(",")
                if k.strip()
            ]
            if keys:
                self._fernet = MultiFernet(keys)

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, text: str) -> str:
        """Encrypt text. Returns plaintext unchanged if encryption is disabled."""
        if not self._fernet or not text:
            return text
        return self._fernet.encrypt(text.encode()).decode()

    def decrypt(self, text: str) -> str:
        """Decrypt text. Returns original value on failure (legacy plaintext rows)."""
        if not self._fernet or not text:
            return text
        try:
            return self._fernet.decrypt(text.encode()).decode()
        except (InvalidToken, Exception):
            return text  # pre-encryption row — return as-is
