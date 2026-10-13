"""
Fixtures shared by the API tests.

Every test gets the API module (api/app.py) with empty caches, rate limits
switched off and no admin token, and talks to the fake apple.com in
tests/fakes/apple.py, never to the real one. Tests switch on what they need.
"""
from __future__ import annotations

import threading

import pytest

import app as api
from fakes.apple import FakeApple, install
from support.client import LIMITERS, Api, Clock


@pytest.fixture(autouse=True)
def apple(monkeypatch) -> FakeApple:
    """The fake apple.com (and exchange-rate service) every request goes to."""
    return install(FakeApple(), monkeypatch.setattr)


@pytest.fixture(autouse=True)
def fresh_api(monkeypatch):
    """Empty caches, limits off, no admin token, every fetch slot free."""
    api._results_cache.clear()
    api._slug_cache.clear()
    monkeypatch.setattr(api, "_rates_cache", {})
    monkeypatch.setattr(api, "_rates_fetched_at", 0.0)
    for limiter in LIMITERS:
        limiter.clear()
        monkeypatch.setattr(limiter, "limit", 0)
    monkeypatch.setattr(api, "ADMIN_TOKEN", "")
    monkeypatch.setattr(api, "_fetch_slots", threading.BoundedSemaphore(api.MAX_PARALLEL_FETCHES))
    yield
    api._results_cache.clear()
    api._slug_cache.clear()



@pytest.fixture
def limits(monkeypatch):
    """Switch the rate limits on: limits(requests=60, lookups=20, all_lookups=60)."""
    def set_limits(requests: int = 60, lookups: int = 20, all_lookups: int = 60):
        for limiter, value in zip(LIMITERS, (requests, lookups, all_lookups)):
            monkeypatch.setattr(limiter, "limit", value)
    return set_limits


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


@pytest.fixture
def client():
    return api.app.test_client()


@pytest.fixture
def server(client) -> Api:
    return Api(client)


@pytest.fixture(params=["json", "stream"])
def via(request) -> str:
    """Run the test against both /api/prices and /api/prices/stream."""
    return request.param
