from app.worker import is_retryable_status


def test_retries_transient_http_statuses():
    assert is_retryable_status(408)
    assert is_retryable_status(429)
    assert is_retryable_status(503)


def test_does_not_retry_permanent_http_statuses():
    assert not is_retryable_status(400)
    assert not is_retryable_status(401)
    assert not is_retryable_status(422)
