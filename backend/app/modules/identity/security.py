"""Cryptographic primitives, with separate purposes for each authenticated value."""

import base64
import hashlib
import hmac
import secrets
import time
from threading import BoundedSemaphore
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.errors import AppError


def token_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


class Security:
    def __init__(self, key: str) -> None:
        self._key = base64.urlsafe_b64decode(key)
        self.passwords = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
        self._dummy = self.passwords.hash(new_token())
        self._hash_slots = BoundedSemaphore(4)

    def hash_password(self, password: str) -> str:
        if not self._hash_slots.acquire(timeout=1):
            raise AppError("auth_busy", "Please try again shortly.", 503)
        try:
            return self.passwords.hash(password)
        finally:
            self._hash_slots.release()

    def digest(self, purpose: str, value: str) -> bytes:
        return hmac.digest(self._key, f"{purpose}\0{value}".encode(), "sha256")

    def verify_password(self, encoded: str | None, password: str) -> bool:
        if not self._hash_slots.acquire(timeout=1):
            raise AppError("auth_busy", "Please try again shortly.", 503)
        try:
            valid = self.passwords.verify(encoded or self._dummy, password)
            return bool(encoded and valid)
        except (VerificationError, InvalidHashError):
            return False
        finally:
            self._hash_slots.release()

    def session_csrf(self, tenant: UUID, token: str) -> str:
        return self.digest("session-csrf", f"{tenant}:{token}").hex()

    def preauth_csrf(self, tenant: UUID) -> str:
        payload = f"{int(time.time())}.{new_token()}"
        return f"{payload}.{self.digest('preauth', f'{tenant}:{payload}').hex()}"

    def valid_preauth(self, tenant: UUID, cookie: str, header: str) -> bool:
        if (
            len(cookie) > 200
            or not cookie.isascii()
            or not header.isascii()
            or not hmac.compare_digest(cookie, header)
        ):
            return False
        try:
            timestamp, nonce, signature = cookie.split(".")
            age = time.time() - int(timestamp)
            expected = self.digest("preauth", f"{tenant}:{timestamp}.{nonce}").hex()
            return 0 <= age <= 600 and hmac.compare_digest(signature, expected)
        except ValueError:
            return False
