"""
Abuse protection: rate limits, telling visitors apart, and the admin token.

One uncached search makes 100+ requests to apple.com from this server, so an
unrestricted API can be used to hammer Apple (and get this server blocked)
or to fill the server's memory. Three limits apply to the price endpoints:

  1. requests per visitor            — any price request, cached or not
  2. Apple look-ups per visitor      — requests that need apple.com
  3. Apple look-ups for everyone     — the same, added up across all visitors

Limit 3 does not depend on telling visitors apart, so it holds even if
someone disguises their address. Each limit can be changed, or switched off
with 0, through an environment variable (see config.py). Counters live in
memory, like the caches, and are per process.

Refusals are returned as the payload to send: {"error", "rateLimited",
"retryAfterSeconds"}. The routes decide how to send it (HTTP 429, or an
error event in the stream). Each refusal is logged, without the visitor's
address.
"""
import hmac
import logging
import math
import threading
import time
from collections import deque
from typing import Optional

from . import config

log = logging.getLogger(__name__)


class SlidingWindowLimiter:
    """Allows at most `limit` events per `window` seconds for each key."""

    MAX_KEYS = 10_000             # most keys remembered at once

    def __init__(self, limit: int, window: int):
        self.limit   = limit
        self.window  = window
        self._events: dict[str, deque] = {}
        self._lock   = threading.Lock()
        self._last_sweep = 0.0

    def retry_after(self, key: str) -> int:
        """0 if `key` may act now, otherwise the seconds until it may."""
        if self.limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            return self._wait(key, now)

    def record(self, key: str) -> None:
        """Count one event for `key`."""
        if self.limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._sweep(now)
            self._events.setdefault(key, deque()).append(now)

    def hit(self, key: str) -> int:
        """Count one event if allowed and return 0; otherwise return the wait in
        seconds. A refused event is not counted, so retrying does not extend the wait."""
        if self.limit <= 0:
            return 0
        now = time.monotonic()
        with self._lock:
            wait = self._wait(key, now)
            if wait == 0:
                self._sweep(now)
                self._events.setdefault(key, deque()).append(now)
            return wait

    def count(self, key: str) -> int:
        """Events counted for `key` inside the current window."""
        now = time.monotonic()
        with self._lock:
            self._wait(key, now)                    # drops expired events
            return len(self._events.get(key, ()))

    def tracked(self) -> int:
        return len(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    # -- internals (call with the lock held) --
    def _wait(self, key: str, now: float) -> int:
        events = self._events.get(key)
        if not events:
            return 0
        while events and now - events[0] >= self.window:
            events.popleft()
        if len(events) < self.limit:
            return 0
        return max(1, math.ceil(self.window - (now - events[0])))

    def _sweep(self, now: float) -> None:
        """Forget keys with nothing recent, so memory does not grow with every visitor."""
        if now - self._last_sweep < 60 and len(self._events) < self.MAX_KEYS:
            return
        self._last_sweep = now
        for key in [k for k, ev in self._events.items()
                    if not ev or now - ev[-1] >= self.window]:
            del self._events[key]
        if len(self._events) >= self.MAX_KEYS:      # flood of distinct keys: drop the oldest half
            for key in list(self._events)[: self.MAX_KEYS // 2]:
                del self._events[key]


request_limiter      = SlidingWindowLimiter(config.RATE_REQUESTS_PER_MIN, 60)          # limit 1
fetch_limiter        = SlidingWindowLimiter(config.RATE_FETCHES_PER_10MIN, 600)        # limit 2
global_fetch_limiter = SlidingWindowLimiter(config.RATE_GLOBAL_FETCHES_PER_10MIN, 600) # limit 3


def human_wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    return f"{math.ceil(seconds / 60)} minutes"


def _refusal(message: str, wait: int) -> dict:
    return {"error": message, "rateLimited": True, "retryAfterSeconds": wait}


def check_request(client: str) -> Optional[dict]:
    """Limit 1. Call once per request: counts it and returns None, or returns the refusal."""
    wait = request_limiter.hit(client)
    if wait:
        log.info("Refused a visitor: over %d requests a minute", request_limiter.limit)
        return _refusal(f"Too many requests. Please try again in {human_wait(wait)}.", wait)
    return None


def charge_fetch(client: str) -> Optional[dict]:
    """
    Limits 2 and 3. Call once for a request that needs apple.com. Returns None
    and counts it if allowed; otherwise returns the refusal and counts nothing.
    """
    wait = fetch_limiter.retry_after(client)
    if wait:
        log.info("Refused a visitor: over %d look-ups in 10 minutes", fetch_limiter.limit)
        return _refusal("You have looked up a lot of products in a short time. "
                        f"Please try again in {human_wait(wait)}.", wait)
    wait = global_fetch_limiter.retry_after("all")
    if wait:
        log.warning("Refused a visitor: every visitor together is over %d look-ups in 10 minutes; "
                    "new products can be looked up again in %s", global_fetch_limiter.limit, human_wait(wait))
        return _refusal("The service is busy fetching prices for other visitors. "
                        f"Please try again in {human_wait(wait)}.", wait)
    fetch_limiter.record(client)
    global_fetch_limiter.record("all")
    return None


def client_id(request) -> tuple[str, str]:
    """
    (address, where it came from) for the visitor making `request`.
    Render serves web services through Cloudflare, which sets CF-Connecting-IP
    itself, so that header is preferred. X-Forwarded-For is a fallback: its
    first entry is the visitor on Render, but a visitor can send their own.
    """
    cf = request.headers.get("CF-Connecting-IP", "").strip()
    if cf:
        return cf[:64], "CF-Connecting-IP"
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64], "X-Forwarded-For"
    return (request.remote_addr or "unknown"), "connection"


def is_admin(request) -> bool:
    """True when `request` carries the configured ADMIN_TOKEN."""
    token = config.ADMIN_TOKEN
    if not token:
        return False
    supplied = request.headers.get("X-Admin-Token", "")
    auth = request.headers.get("Authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied.encode(), token.encode())
