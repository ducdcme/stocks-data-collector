from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _test_ssi_rate_limit_defaults(monkeypatch):
    # Unit tests use fake HTTP clients and should not spend real time honoring
    # the production SSI quota. Individual tests opt back in when validating
    # the limiter itself.
    monkeypatch.setenv("SSI_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("SSI_QUOTA_RETRY_DELAY_SECONDS", "0")
    try:
        from app.providers.ssi_provider import SSIProvider
        SSIProvider._last_request_at.clear()
    except Exception:
        pass
    yield
