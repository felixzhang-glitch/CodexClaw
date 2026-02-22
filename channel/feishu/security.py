from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class FeishuSecurityError(ValueError):
    pass


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return ""


def compute_signature(timestamp: str, nonce: str, encrypt_key: str, raw_body: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(timestamp.encode("utf-8"))
    digest.update(nonce.encode("utf-8"))
    digest.update(encrypt_key.encode("utf-8"))
    digest.update(raw_body)
    return digest.hexdigest()


def verify_request_signature(
    headers: Mapping[str, str],
    raw_body: bytes,
    encrypt_key: str,
    max_skew_seconds: int = 3600,
) -> bool:
    timestamp = _header(headers, "X-Lark-Request-Timestamp")
    nonce = _header(headers, "X-Lark-Request-Nonce")
    signature = _header(headers, "X-Lark-Signature")

    if not timestamp or not nonce or not signature:
        return False

    try:
        ts = int(timestamp)
    except ValueError:
        return False

    now = int(time.time())
    if abs(now - ts) > max_skew_seconds:
        return False

    expected = compute_signature(timestamp=timestamp, nonce=nonce, encrypt_key=encrypt_key, raw_body=raw_body)

    if signature.startswith("sha256="):
        signature = signature.split("=", 1)[1]

    return hmac.compare_digest(expected, signature)


def decrypt_event_payload(encrypt_value: str, encrypt_key: str) -> dict[str, Any]:
    try:
        encrypted = base64.b64decode(encrypt_value)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise FeishuSecurityError("invalid encrypt payload encoding") from exc

    if len(encrypted) <= 16:
        raise FeishuSecurityError("invalid encrypt payload length")

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = encrypted[:16]
    ciphertext = encrypted[16:]

    try:
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()
        return json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise FeishuSecurityError("failed to decrypt callback payload") from exc
