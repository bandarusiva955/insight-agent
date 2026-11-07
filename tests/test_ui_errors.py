from app.ui.errors import friendly_error

QUOTA = (
    "Gemini models are currently unavailable. gemini-3.6-flash: 429 RESOURCE_EXHAUSTED. "
    "{'message': 'You exceeded your current quota. Please retry in 4h38m24.02s.'}"
)


def test_quota_error_is_short_and_has_wait_time():
    message = friendly_error(RuntimeError(QUOTA))

    assert "quota" in message
    assert "4h 38m" in message
    assert "{" not in message and len(message) < 400


def test_busy_network_rejected_and_unknown():
    assert "busy" in friendly_error(RuntimeError("503 UNAVAILABLE high demand"))
    assert "internet" in friendly_error(RuntimeError("[Errno 11001] getaddrinfo failed"))
    assert "blocked by the safety checks" in friendly_error(ValueError("SQL rejected: no"))
    assert friendly_error(ValueError("boom")) == "Analysis failed: boom"
