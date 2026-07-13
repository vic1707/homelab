from __future__ import annotations

import base64
import hashlib

import bcrypt
from ansible.errors import AnsibleFilterError

_BCRYPT_BASE64 = bytes.maketrans(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
    b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
)


def bcrypt_hash(password: str, salt_seed: str, rounds: int = 12) -> str:
    password_bytes = password.encode()
    if len(password_bytes) > 72:
        raise AnsibleFilterError("bcrypt passwords cannot exceed 72 bytes")
    if not 4 <= rounds <= 31:
        raise AnsibleFilterError("bcrypt rounds must be between 4 and 31")

    salt_bytes = hashlib.sha256(salt_seed.encode()).digest()[:16]
    salt = base64.b64encode(salt_bytes).rstrip(b"=").translate(_BCRYPT_BASE64)
    bcrypt_salt = f"$2b${rounds:02d}$".encode() + salt
    return bcrypt.hashpw(password_bytes, bcrypt_salt).decode()


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {"bcrypt_hash": bcrypt_hash}


if __name__ == "__main__":
    result = bcrypt_hash("test", "fedex", 4)
    assert bcrypt.checkpw(b"test", result.encode())
    assert result == bcrypt_hash("test", "fedex", 4)
