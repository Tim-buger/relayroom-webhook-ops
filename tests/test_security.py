import json
import time

import pytest

from app.security import InvalidSignature, create_demo_signature, verify_stripe_signature


def test_valid_signature():
    payload = json.dumps({"id": "evt_123"}, separators=(",", ":")).encode()
    signature = create_demo_signature(payload, "secret", timestamp=1_000)

    verify_stripe_signature(payload, signature, "secret", 300, now=1_100)


def test_rejects_tampered_payload():
    payload = b'{"id":"evt_123"}'
    signature = create_demo_signature(payload, "secret", timestamp=1_000)

    with pytest.raises(InvalidSignature, match="does not match"):
        verify_stripe_signature(b'{"id":"evt_changed"}', signature, "secret", 300, now=1_100)


def test_rejects_stale_signature():
    payload = b'{"id":"evt_123"}'
    signature = create_demo_signature(payload, "secret", timestamp=int(time.time()) - 400)

    with pytest.raises(InvalidSignature, match="tolerance"):
        verify_stripe_signature(payload, signature, "secret", 300)
