"""Verifies NTRIP credentials with scrypt."""

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Self


def is_anonymous(authorization: str) -> bool:
    scheme, separator, encoded = authorization.partition(" ")
    return bool(separator) and scheme.lower() == "basic" and encoded == "Og=="


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if not 16 <= len(password.encode("utf-8")) <= 256:
        raise ValueError("passwords need 16..256 UTF-8 bytes")
    salt = secrets.token_bytes(16) if salt is None else salt
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


class Credentials:
    def __init__(self, users: Mapping[str, str]) -> None:
        if len(users) > 10000:
            raise ValueError("credentials file exceeds 10000 accounts")
        for username, encoded in users.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username):
                raise ValueError("invalid credential username")
            if not isinstance(encoded, str) or not re.fullmatch(
                r"scrypt\$[0-9a-f]{32}\$[0-9a-f]{64}", encoded
            ):
                raise ValueError("credentials need fixed-cost scrypt hashes")
        self._users = dict(users)
        self._dummy = f"scrypt${secrets.token_hex(16)}${secrets.token_hex(32)}"

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read a credentials file with no group or other access permissions."""
        with path.open("rb") as stream:
            mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
            if mode & 0o077:
                raise ValueError(
                    "credentials file permissions must be 0600 or stricter"
                )
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("credentials file is too large")
        users = json.loads(raw)
        if not isinstance(users, dict):
            raise ValueError("credentials must be a JSON object")
        return cls(users)

    def verify(self, authorization: str) -> str | None:
        try:
            scheme, encoded = authorization.split(" ", 1)
            if scheme.lower() != "basic" or len(encoded) > 1024:
                return None
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
            if not 16 <= len(password.encode("utf-8")) <= 256:
                return None
        except (ValueError, UnicodeError, binascii.Error):
            return None
        stored = self._users.get(username, self._dummy)
        salt = bytes.fromhex(stored.split("$")[1])
        actual = hash_password(password, salt=salt)
        valid = hmac.compare_digest(actual, stored)
        return username if valid and username in self._users else None
