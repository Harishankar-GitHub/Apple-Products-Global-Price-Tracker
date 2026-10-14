"""
The API with apple.com replaced by the fake in tests/fakes/apple.py, as a WSGI app.
gunicorn runs it in tests/api/test_server.py and the browser end-to-end tests use it
(`python tests/servers/fake_api.py` serves it on port 5055).

Environment variables:
  FAKE_APPLE_SLOW     "prod901=1.5,prod902=0.2" — seconds each country-store request
                      for that product takes (slow searches on demand)
  FAKE_APPLE_JITTER   "1" — uneven response times, like a real network
  FETCH_SLOT_NOTICE   seconds between keep-alive lines while a search waits
  TEST_ROUTES         "1" — add /__test/... routes the browser tests use to set the scene
"""
import os
import pathlib
import random
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
for path in (ROOT / "api", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app import app  # noqa: E402
from fakes.apple import FakeApple, install, store_prefix  # noqa: E402
from flask import request  # noqa: E402
from tracker import config, exchange, limits, lookup, results_cache, search, web  # noqa: E402

slow = {k: float(v) for k, v in (p.split("=") for p in os.environ.get("FAKE_APPLE_SLOW", "").split(",") if p)}
jitter = os.environ.get("FAKE_APPLE_JITTER") == "1"


def delay(url: str) -> float:
    if "apple.com" not in url:
        return 0.0                                   # the exchange-rate service answers at once
    seconds = 0.0
    if store_prefix(url):
        seconds += next((s for slug, s in slow.items() if re.search(rf"/{slug}/?$", url)), 0.0)
    if jitter:
        seconds += random.uniform(0.02, 0.2) + random.random() ** 3 * 2
    return seconds


apple = install(FakeApple(delay=delay))
LIMITERS = (limits.request_limiter, limits.fetch_limiter, limits.global_fetch_limiter)
DEFAULT_LIMITS = [limiter.limit for limiter in LIMITERS]
if "FETCH_SLOT_NOTICE" in os.environ:
    config.FETCH_SLOT_NOTICE = float(os.environ["FETCH_SLOT_NOTICE"])

if os.environ.get("TEST_ROUTES") == "1":
    _offset = [0.0]
    _real_monotonic = time.monotonic
    time.monotonic = lambda: _real_monotonic() + _offset[0]

    @app.route("/__test/advance")
    def _advance():
        """Move the server's clock forward: /__test/advance?seconds=7500"""
        _offset[0] += float(request.args.get("seconds", 0))
        return {"offset": _offset[0]}

    @app.route("/__test/outage")
    def _outage():
        """apple.com stops answering (mode=timeout or a status code) or comes back (mode=off)."""
        mode = request.args.get("mode", "off")
        apple.outage = None if mode == "off" else (int(mode) if mode.isdigit() else mode)
        return {"outage": str(apple.outage)}

    @app.route("/__test/reset")
    def _reset():
        """A clean server: no fetch still running, empty caches, default limits, apple.com answering, real time."""
        global apple
        started = _real_monotonic()
        while search.fetch_slots._value < config.MAX_PARALLEL_FETCHES and _real_monotonic() - started < 60:
            time.sleep(0.1)                          # a closed page's fetch finishes in the background
        for cache in (results_cache, lookup, exchange):
            cache.clear()
        for limiter, limit in zip(LIMITERS, DEFAULT_LIMITS):
            limiter.clear()
            limiter.limit = limit
        apple = install(FakeApple(delay=delay))
        web.reset()                                  # new connections, to the new fake apple.com
        _offset[0] = 0.0
        return {"reset": True, "waited": round(_real_monotonic() - started, 1)}

    @app.route("/__test/limits")
    def _limits():
        """Change the rate limits: /__test/limits?requests=60&lookups=2&all=60"""
        for limiter, name in zip(LIMITERS, ("requests", "lookups", "all")):
            if name in request.args:
                limiter.limit = int(request.args[name])
        return {"limits": [limiter.limit for limiter in LIMITERS]}

    @app.route("/__test/rates")
    def _rates():
        """Leave a currency out of the exchange rates: /__test/rates?drop=INR"""
        apple.rates.pop(request.args.get("drop", ""), None)
        exchange.clear()
        return {"rates": sorted(apple.rates)}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5055)), threaded=True, use_reloader=False)
