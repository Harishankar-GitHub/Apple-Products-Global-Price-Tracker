"""
Fixtures shared by the API tests.

Every test gets the API (api/tracker) with empty caches, rate limits
switched off and no admin token, and talks to the fake apple.com in
tests/fakes/apple.py, never to the real one. Tests switch on what they need.
"""
from __future__ import annotations

import threading

import pytest

from app import app as flask_app
from fakes.apple import FakeApple, install
from support.client import LIMITERS, Api, Clock
from tracker import config, exchange, lookup, results_cache, search, web


@pytest.fixture(autouse=True)
def apple(monkeypatch) -> FakeApple:
    """The fake apple.com (and exchange-rate service) every request goes to."""
    return install(FakeApple(), monkeypatch.setattr)


@pytest.fixture(autouse=True)
def fresh_api(monkeypatch, apple):
    """Empty caches, limits off, no admin token, every fetch slot free, a new connection pool."""
    web.reset()                     # the next request opens a session to this test's fake apple.com
    for cache in (results_cache, lookup, exchange):
        cache.clear()
    for limiter in LIMITERS:
        limiter.clear()
        monkeypatch.setattr(limiter, "limit", 0)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "")
    monkeypatch.setattr(search, "fetch_slots", threading.BoundedSemaphore(config.MAX_PARALLEL_FETCHES))
    yield
    web.reset()
    for cache in (results_cache, lookup, exchange):
        cache.clear()



@pytest.fixture
def limits_on(monkeypatch):
    """Switch the rate limits on: limits_on(requests=60, lookups=20, all_lookups=60)."""
    def set_limits(requests: int = 60, lookups: int = 20, all_lookups: int = 60):
        for limiter, value in zip(LIMITERS, (requests, lookups, all_lookups)):
            monkeypatch.setattr(limiter, "limit", value)
    return set_limits


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


@pytest.fixture
def client():
    return flask_app.test_client()


@pytest.fixture
def server(client) -> Api:
    return Api(client)


@pytest.fixture(params=["json", "stream"])
def via(request) -> str:
    """Run the test against both /api/prices and /api/prices/stream."""
    return request.param
