"""Shared fixtures: reset the client's cache + circuit breaker between tests so cached
responses or tripped breakers don't leak across cases."""

import pytest

from diamond_mcp import client, config


@pytest.fixture(autouse=True)
def _reset_client_state(monkeypatch):
    # Zero retry backoff so transient-failure tests don't actually sleep.
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_INITIAL", 0.0)
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_MAX", 0.0)
    client.reset_state()
    yield
    client.reset_state()
