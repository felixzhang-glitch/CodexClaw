import time

from channel.feishu.security import compute_signature, verify_request_signature


def test_verify_request_signature_success() -> None:
    raw_body = b'{"type":"url_verification","challenge":"abc"}'
    encrypt_key = "test_encrypt_key"
    timestamp = str(int(time.time()))
    nonce = "nonce_1"
    signature = compute_signature(timestamp=timestamp, nonce=nonce, encrypt_key=encrypt_key, raw_body=raw_body)

    headers = {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": signature,
    }

    assert verify_request_signature(headers=headers, raw_body=raw_body, encrypt_key=encrypt_key)


def test_verify_request_signature_failure() -> None:
    raw_body = b'{"type":"url_verification","challenge":"abc"}'
    headers = {
        "X-Lark-Request-Timestamp": str(int(time.time())),
        "X-Lark-Request-Nonce": "nonce_1",
        "X-Lark-Signature": "bad_signature",
    }

    assert not verify_request_signature(headers=headers, raw_body=raw_body, encrypt_key="test_encrypt_key")
