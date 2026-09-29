import hashlib
import hmac
import time


class InvalidSignature(ValueError):
    pass


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int,
    now: int | None = None,
) -> None:
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(","):
        key, separator, value = item.partition("=")
        if separator:
            parts.setdefault(key.strip(), []).append(value.strip())

    try:
        timestamp = int(parts["t"][0])
        signatures = parts["v1"]
    except (KeyError, ValueError, IndexError) as exc:
        raise InvalidSignature("Malformed Stripe-Signature header") from exc

    current_time = int(time.time()) if now is None else now
    if abs(current_time - timestamp) > tolerance_seconds:
        raise InvalidSignature("Signature timestamp is outside the allowed tolerance")

    signed_payload = str(timestamp).encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidSignature("Signature does not match the payload")


def create_demo_signature(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    signed_at = int(time.time()) if timestamp is None else timestamp
    signed_payload = str(signed_at).encode() + b"." + payload
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={signed_at},v1={digest}"
