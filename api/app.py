"""
Apple Products Global Price Tracker — Flask API
All outbound HTTP calls use aiohttp + asyncio so all 50 country requests
fire simultaneously in a single thread (no ThreadPoolExecutor). Each store
needs one page download when its buy page has the price, two otherwise.
"""

import re
import os
import hmac
import json
import math
import time
import asyncio
import queue
import threading
from collections import deque
from typing import NamedTuple, Optional
from urllib.parse import urlparse

import aiohttp
from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

# Requests are served by several threads at once (see gunicorn.conf.py), so
# reads and writes of the slug and results caches go through this lock.
# (Exchange rates are swapped in as a whole new dict, so they need none.)
_cache_lock = threading.RLock()

# Cache 1 — Exchange rates  (TTL: 30 min)
_rates_cache: dict[str, float] = {}
_rates_fetched_at: float = 0.0
RATES_TTL = 30 * 60

# Cache 2 — Slug resolution
#   Keyed by whatever was typed, so it is capped: the oldest entries are
#   dropped once it holds SLUG_CACHE_MAX names.
#   Each entry: {"result": (slug, category) or None, "expires": monotonic time
#   or None, "failed": bool}. How long an answer is kept depends on how sure
#   it is, so that one Apple timeout cannot make a product "not found" (or
#   pin it to the wrong page) until the server restarts:
#     found, every check answered      → kept for the life of the process
#     found a fallback while a check failed → SLUG_TTL_UNSURE, then looked up again
#     not found, every check answered  → SLUG_TTL_NOT_FOUND (Apple adds products)
#     could not tell (Apple did not answer) → SLUG_TTL_FAILED, and reported as
#                                         "try again", never as "not found"
_slug_cache: dict[str, dict] = {}
SLUG_CACHE_MAX     = 500
SLUG_TTL_NOT_FOUND = 60 * 60      # 1 hour
SLUG_TTL_UNSURE    = 5 * 60       # 5 minutes
SLUG_TTL_FAILED    = 60           # 1 minute — only long enough to stop retry storms

# Cache 3 — Price results per slug
#   Apple changes prices rarely, so a complete result set is kept for hours.
#   A set where any country failed to load (timeout, rate limit, server error),
#   or where no country returned a price, is kept only briefly so that a bad
#   fetch is retried soon instead of being served for hours.
#   Each entry: {"ts": monotonic time stored, "ttl": seconds, "payload": {...}}
_results_cache: dict[str, dict] = {}
RESULTS_TTL       = 6 * 60 * 60   # complete result set  (6 hours)
RESULTS_TTL_SHORT = 5 * 60        # incomplete result set (5 minutes)
RESULTS_CACHE_MAX = 200           # most result sets held at once; oldest dropped first

# ---------------------------------------------------------------------------
# Abuse protection
# ---------------------------------------------------------------------------
# One uncached search makes 100+ requests to apple.com from this server, so an
# unrestricted API can be used to hammer Apple (and get this server blocked)
# or to fill the server's memory. Three limits apply to the price endpoints:
#
#   1. requests per visitor            — any price request, cached or not
#   2. Apple look-ups per visitor      — requests that need apple.com
#   3. Apple look-ups for everyone     — the same, added up across all visitors
#
# Limit 3 does not depend on telling visitors apart, so it holds even if
# someone disguises their address. Each limit can be changed, or switched off
# with 0, through an environment variable. Counters live in memory, like the
# caches, and are per process.

def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


MAX_PRODUCT_LENGTH = 80           # characters accepted in ?product=

RATE_REQUESTS_PER_MIN        = _env_int("RATE_LIMIT_REQUESTS_PER_MIN", 60)
RATE_FETCHES_PER_10MIN       = _env_int("RATE_LIMIT_FETCHES_PER_10MIN", 20)
RATE_GLOBAL_FETCHES_PER_10MIN = _env_int("RATE_LIMIT_GLOBAL_FETCHES_PER_10MIN", 60)

# Secret that unlocks the detailed view of /api/cache/status (search terms and
# product slugs). Unset → the detailed view is never available.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


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


_request_limiter      = SlidingWindowLimiter(RATE_REQUESTS_PER_MIN, 60)
_fetch_limiter        = SlidingWindowLimiter(RATE_FETCHES_PER_10MIN, 600)
_global_fetch_limiter = SlidingWindowLimiter(RATE_GLOBAL_FETCHES_PER_10MIN, 600)


def _client_id() -> tuple[str, str]:
    """
    (address, where it came from) for the visitor making this request.
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


def _human_wait(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    return f"{math.ceil(seconds / 60)} minutes"


def _charge_fetch(client: str) -> Optional[tuple[str, int]]:
    """
    Call once for a request that needs apple.com. Returns None and counts it if
    allowed; otherwise returns (message, seconds to wait) and counts nothing.
    """
    wait = _fetch_limiter.retry_after(client)
    if wait:
        return ("You have looked up a lot of products in a short time. "
                f"Please try again in {_human_wait(wait)}.", wait)
    wait = _global_fetch_limiter.retry_after("all")
    if wait:
        return ("The service is busy fetching prices for other visitors. "
                f"Please try again in {_human_wait(wait)}.", wait)
    _fetch_limiter.record(client)
    _global_fetch_limiter.record("all")
    return None


def _too_fast(wait: int) -> tuple[str, int]:
    return (f"Too many requests. Please try again in {_human_wait(wait)}.", wait)


def _limit_payload(message: str, wait: int) -> dict:
    return {"error": message, "rateLimited": True, "retryAfterSeconds": wait}


def _limit_response(message: str, wait: int):
    """HTTP 429 for the JSON endpoints."""
    resp = jsonify(_limit_payload(message, wait))
    resp.status_code = 429
    resp.headers["Retry-After"] = str(wait)
    return resp


def _sse_error(payload: dict) -> Response:
    """A stream that reports one error. EventSource cannot read the body of a
    non-200 reply, so stream errors are sent as an event the page can show."""
    def _gen():
        yield f"event: error\ndata: {json.dumps(payload)}\n\n"
    return Response(stream_with_context(_gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _is_admin() -> bool:
    """True when the request carries the configured ADMIN_TOKEN."""
    if not ADMIN_TOKEN:
        return False
    supplied = request.headers.get("X-Admin-Token", "")
    auth = request.headers.get("Authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied.encode(), ADMIN_TOKEN.encode())

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCHANGE_API = "https://open.er-api.com/v6/latest/USD"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

COUNTRIES: dict[str, tuple[str, str, str]] = {
    "United States":        ("",    "USD", "$"),
    "Japan":                ("jp",  "JPY", "¥"),
    "Canada":               ("ca",  "CAD", "CA$"),
    "South Korea":          ("kr",  "KRW", "₩"),
    "Hong Kong":            ("hk",  "HKD", "HK$"),
    "Taiwan":               ("tw",  "TWD", "NT$"),
    "United Arab Emirates": ("ae",  "AED", "AED"),
    "China":                ("cn",  "CNY", "¥"),
    "Philippines":          ("ph",  "PHP", "₱"),
    "Thailand":             ("th",  "THB", "฿"),
    "India":                ("in",  "INR", "₹"),
    "Singapore":            ("sg",  "SGD", "S$"),
    "Malaysia":             ("my",  "MYR", "RM"),
    "Australia":            ("au",  "AUD", "A$"),
    "New Zealand":          ("nz",  "NZD", "NZ$"),
    "United Kingdom":       ("uk",  "GBP", "£"),
    "Germany":              ("de",  "EUR", "€"),
    "France":               ("fr",  "EUR", "€"),
    "Netherlands":          ("nl",  "EUR", "€"),
    "Spain":                ("es",  "EUR", "€"),
    "Italy":                ("it",  "EUR", "€"),
    "Austria":              ("at",  "EUR", "€"),
    "Ireland":              ("ie",  "EUR", "€"),
    "Portugal":             ("pt",  "EUR", "€"),
    "Sweden":               ("se",  "SEK", "kr"),
    "Norway":               ("no",  "NOK", "kr"),
    "Denmark":              ("dk",  "DKK", "kr"),
    "Poland":               ("pl",  "PLN", "zł"),
    "Turkey":               ("tr",  "TRY", "₺"),
    "Mexico":               ("mx",  "MXN", "MX$"),
    "Brazil":               ("br",  "BRL", "R$"),
    "Saudi Arabia":         ("sa",  "SAR", "SAR"),
    "Vietnam":              ("vn",  "VND", "₫"),
    "Indonesia":            ("id",  "IDR", "Rp"),
    "Israel":               ("il",  "ILS", "₪"),
    "South Africa":         ("za",  "ZAR", "R"),
    "Czech Republic":       ("cz",  "CZK", "Kč"),
    "Hungary":              ("hu",  "HUF", "Ft"),
    "Romania":              ("ro",  "RON", "lei"),
    "Finland":              ("fi",  "EUR", "€"),
    "Belgium":              ("be",  "EUR", "€"),
    "Luxembourg":           ("lu",  "EUR", "€"),
    "Greece":               ("gr",  "EUR", "€"),
    "Switzerland":          ("ch",  "CHF", "CHF"),
    "Chile":                ("cl",  "CLP", "CLP"),
    "Colombia":             ("co",  "COP", "COP"),
    "Kuwait":               ("kw",  "KWD", "KWD"),
    "Qatar":                ("qa",  "QAR", "QAR"),
    "Bahrain":              ("bh",  "BHD", "BHD"),
    "Oman":                 ("om",  "OMR", "OMR"),
}

COUNTRY_FLAGS: dict[str, str] = {
    "United States": "🇺🇸", "Japan": "🇯🇵", "Canada": "🇨🇦", "South Korea": "🇰🇷",
    "Hong Kong": "🇭🇰", "Taiwan": "🇹🇼", "United Arab Emirates": "🇦🇪", "China": "🇨🇳",
    "Philippines": "🇵🇭", "Thailand": "🇹🇭", "India": "🇮🇳", "Singapore": "🇸🇬",
    "Malaysia": "🇲🇾", "Australia": "🇦🇺", "New Zealand": "🇳🇿", "United Kingdom": "🇬🇧",
    "Germany": "🇩🇪", "France": "🇫🇷", "Netherlands": "🇳🇱", "Spain": "🇪🇸",
    "Italy": "🇮🇹", "Austria": "🇦🇹", "Ireland": "🇮🇪", "Portugal": "🇵🇹",
    "Sweden": "🇸🇪", "Norway": "🇳🇴", "Denmark": "🇩🇰", "Poland": "🇵🇱",
    "Turkey": "🇹🇷", "Mexico": "🇲🇽", "Brazil": "🇧🇷", "Saudi Arabia": "🇸🇦",
    "Vietnam": "🇻🇳", "Indonesia": "🇮🇩", "Israel": "🇮🇱", "South Africa": "🇿🇦",
    "Czech Republic": "🇨🇿", "Hungary": "🇭🇺", "Romania": "🇷🇴", "Finland": "🇫🇮",
    "Belgium": "🇧🇪", "Luxembourg": "🇱🇺", "Greece": "🇬🇷", "Switzerland": "🇨🇭",
    "Chile": "🇨🇱", "Colombia": "🇨🇴", "Kuwait": "🇰🇼", "Qatar": "🇶🇦",
    "Bahrain": "🇧🇭", "Oman": "🇴🇲",
}

# Names that plain name → slug conversion gets wrong, including older models
# that should lead to the one Apple sells now. Each entry is a hint, not a
# fact: it is used only while Apple still serves a page for that slug (see
# _override_is_live), so an entry that goes stale falls back to normal
# discovery instead of pointing at a retired page. When the slug differs from
# what was typed, the response says so (see match_info).
SLUG_OVERRIDES: dict[str, tuple[str, str]] = {
    "iphone 16 pro":       ("iphone-16-pro",      "iphone"),
    "iphone 16":           ("iphone-16",           "iphone"),
    "iphone 17":           ("iphone-17",           "iphone"),
    "apple watch ultra":   ("apple-watch-ultra-4", "watch"),
    "apple watch ultra 3": ("apple-watch-ultra-4", "watch"),
    "apple watch ultra 2": ("apple-watch-ultra-4", "watch"),
}


# ---------------------------------------------------------------------------
# Async HTTP helpers
# ---------------------------------------------------------------------------

# Connections open to apple.com at the same time. Every request goes to the
# one host (www.apple.com), so this is what decides how many stores are
# actually fetched at once: 50 gives each of the 50 stores its own connection.
# It was 10, which made a search queue through five rounds. Lower it with the
# APPLE_MAX_CONNECTIONS environment variable if Apple starts refusing requests.
APPLE_MAX_CONNECTIONS = max(1, _env_int("APPLE_MAX_CONNECTIONS", 50))

# Searches that fetch from apple.com at the same time. Visitors are served in
# parallel, but each such search opens up to APPLE_MAX_CONNECTIONS connections
# and holds those pages in memory, so a burst of visitors searching for new
# products is let through a couple at a time instead of multiplying both.
# Cached results, health checks and everything else are not limited by this.
# A search waits up to FETCH_SLOT_WAIT seconds for a free slot, then is told to
# try again.
MAX_PARALLEL_FETCHES = max(1, _env_int("MAX_PARALLEL_FETCHES", 2))
FETCH_SLOT_WAIT   = 45      # seconds a search may wait for a slot
FETCH_SLOT_NOTICE = 5       # while a stream waits, it sends a line this often (seconds)
_fetch_slots = threading.BoundedSemaphore(MAX_PARALLEL_FETCHES)


def _busy_payload() -> dict:
    return {"error": "The service is busy fetching prices for other visitors. "
                     "Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


def _wait_for_fetch_slot():
    """
    For the stream route (use with `yield from`): waits up to FETCH_SLOT_WAIT
    seconds for a fetch slot and returns True once it holds one, False if none
    came free. While waiting it tells the page (a `queued` event, then a comment
    line every few seconds). Writing to the connection also notices a visitor
    who has closed the page, which ends the wait instead of taking a slot that
    nobody needs any more.
    """
    if _fetch_slots.acquire(blocking=False):
        return True
    queued = {"message": "Waiting for other searches to finish", "maxWaitSeconds": FETCH_SLOT_WAIT}
    yield f"event: queued\ndata: {json.dumps(queued)}\n\n"
    deadline = time.monotonic() + FETCH_SLOT_WAIT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _fetch_slots.acquire(timeout=min(FETCH_SLOT_NOTICE, remaining)):
            return True
        yield ": still waiting for a free fetch slot\n\n"


def _make_connector() -> aiohttp.TCPConnector:
    """Connector that lets every store be fetched at once (see APPLE_MAX_CONNECTIONS)."""
    return aiohttp.TCPConnector(
        limit=APPLE_MAX_CONNECTIONS,           # total concurrent connections
        limit_per_host=APPLE_MAX_CONNECTIONS,  # all of them go to www.apple.com
        ttl_dns_cache=300,  # cache DNS for 5 min
        enable_cleanup_closed=True,
    )


async def _async_fetch_rates() -> dict[str, float]:
    """Fetch exchange rates (called only when Cache 1 is stale)."""
    global _rates_cache, _rates_fetched_at
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        try:
            async with session.get(EXCHANGE_API, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    _rates_cache = data.get("rates", {})
                    _rates_fetched_at = time.monotonic()
        except Exception:
            pass  # fall through — returns stale or empty below
    return _rates_cache or {}


def fetch_exchange_rates() -> dict[str, float]:
    """Sync wrapper — uses cache, goes async only when TTL expired."""
    global _rates_cache, _rates_fetched_at
    now = time.monotonic()
    if _rates_cache and (now - _rates_fetched_at) < RATES_TTL:
        return _rates_cache                          # Cache 1 hit
    return asyncio.run(_async_fetch_rates())


def rates_for_client(rates: dict[str, float]) -> dict[str, float]:
    """Subset of exchange rates (units per 1 USD) for the currencies we list.
    Sent to the browser so it can show prices in the visitor's own currency."""
    wanted = {currency for (_prefix, currency, _symbol) in COUNTRIES.values()}
    return {c: rates[c] for c in sorted(wanted) if rates.get(c)}


# ---------------------------------------------------------------------------
# Slug discovery (async probing)
# ---------------------------------------------------------------------------

def name_to_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def infer_category(slug: str) -> str:
    s = slug.lower()
    if "iphone"      in s: return "iphone"
    if "ipad"        in s: return "ipad"
    if "macbook"     in s: return "mac"
    if "mac"         in s: return "mac"
    if "airpods"     in s: return "airpods"
    if "apple-watch" in s: return "watch"
    if "watch"       in s: return "watch"
    if "apple-tv"    in s: return "appletv"
    if "homepod"     in s: return "homepod"
    if "airtag"      in s: return "airtag"
    return s.split("-")[0]


# How Apple writes the words that are not simply capitalised.
_NAME_WORDS = {
    "iphone": "iPhone", "ipad": "iPad", "imac": "iMac", "macbook": "MacBook",
    "airpods": "AirPods", "airtag": "AirTag", "homepod": "HomePod",
    "tv": "TV", "4k": "4K", "se": "SE", "xdr": "XDR", "mini": "mini",
    "generation": "generation", "hermes": "Hermès",
}


def display_name(slug: str) -> str:
    """'apple-watch-ultra-4' → 'Apple Watch Ultra 4', 'ipad-mini' → 'iPad mini'."""
    words = []
    for word in slug.lower().split("-"):
        if not word:
            continue
        if word in _NAME_WORDS:
            words.append(_NAME_WORDS[word])
        elif word[0].isdigit():
            words.append(word)                       # 17e, 2nd, 4
        else:
            words.append(word.capitalize())
    return " ".join(words)


def _name_key(text: str) -> str:
    """Letters and digits only, without a leading 'apple', for comparing names."""
    key = re.sub(r"[^a-z0-9]", "", text.lower())
    return key[5:] if key.startswith("apple") and len(key) > 5 else key


def match_info(product_name: str, slug: str) -> dict:
    """
    What was actually priced, for the response. `substituted` is True when the
    product found is not the one typed — an older model mapped to the current
    one, a longer name cut down to a page that exists, a number added — so the
    page can say so instead of presenting it as an exact answer. Differences
    in case, spacing, hyphens or a leading "Apple" do not count.
    """
    return {"matchedName": display_name(slug),
            "substituted": _name_key(product_name) != _name_key(slug)}


# A page check that ends in one of these told us something definite ("the page
# exists" / "there is no such page"). Anything else — a timeout, a network
# error, 403, 429, 5xx — means Apple could not be asked, and is noted in the
# `failures` list the checks are given so the caller knows its answer is unsure.
_DEFINITE_STATUSES = (200, 404, 410)


async def _async_probe(session: aiohttp.ClientSession, url: str,
                       failures: Optional[list] = None) -> bool:
    """
    Returns True only if the final URL's first path segment matches the
    probed slug — rejects silent homepage redirects.
    """
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                               allow_redirects=True) as r:
            if r.status == 200:
                probed_slug = urlparse(url).path.strip("/").split("/")[0]
                final_slug  = urlparse(str(r.url)).path.strip("/").split("/")[0]
                return bool(probed_slug and probed_slug == final_slug)
            if r.status not in _DEFINITE_STATUSES and failures is not None:
                failures.append(url)
    except Exception:
        if failures is not None:
            failures.append(url)
    return False


async def _async_page_is_for(session: aiohttp.ClientSession, url: str, slug: str,
                             failures: Optional[list] = None) -> bool:
    """True if `url` answers 200 and, after redirects, is still a page for `slug`."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=12),
                               allow_redirects=True) as r:
            if r.status not in _DEFINITE_STATUSES and failures is not None:
                failures.append(url)
            return r.status == 200 and slug in urlparse(str(r.url)).path
    except Exception:
        if failures is not None:
            failures.append(url)
        return False


async def _override_is_live(session: aiohttp.ClientSession, slug: str, category: str,
                            failures: Optional[list] = None) -> bool:
    """
    An override is used only while Apple still has a page for its slug: the
    product page, or the US buy page for products that have no product page.
    Apple redirects retired product pages to the line-up page, which fails both.
    """
    product_ok, shop_ok = await asyncio.gather(
        _async_probe(session, f"https://www.apple.com/{slug}/", failures),
        _async_page_is_for(session, build_shop_url("", category, slug), slug, failures),
    )
    return product_ok or shop_ok


async def _async_resolve_slug(product_name: str) -> tuple[Optional[tuple[str, str]], bool]:
    """
    All apple.com probing runs concurrently inside one aiohttp session.
    Returns (result, unsure). `unsure` is True when a page check failed for a
    temporary reason before the answer was reached, so the answer — a fallback
    page, or "not found" — might be different once Apple responds again. An
    exact match is never unsure. Failures of the suggestions service alone do
    not count: it is only a hint, and the page checks decide.
    """
    override  = SLUG_OVERRIDES.get(product_name.strip().lower())
    candidate = name_to_slug(product_name)
    category  = infer_category(candidate)
    failures: list = []

    async with aiohttp.ClientSession(headers=HEADERS,
                                     connector=_make_connector()) as session:
        # 0. Known name: use its slug while Apple still serves it, else carry on below
        if override and await _override_is_live(session, *override, failures):
            return override, False

        # 1. Direct probe + suggestions API call in parallel
        async def suggestions() -> Optional[tuple[str, str]]:
            try:
                params = {"q": product_name, "locale": "en_US", "client": "global-search"}
                async with session.get(
                    "https://www.apple.com/search-services/suggestions/",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        for s in data.get("suggestions", []):
                            url_hint = s.get("url", "")
                            if "apple.com" in url_hint:
                                path = url_hint.rstrip("/").split("apple.com/")[-1].strip("/")
                                slug = path.split("/")[0]
                                if slug and slug not in ("shop", "store", "search"):
                                    if await _async_probe(session, f"https://www.apple.com/{slug}/", failures):
                                        return (slug, infer_category(slug))
            except Exception:
                pass
            return None

        direct_ok, suggestion_result = await asyncio.gather(
            _async_probe(session, f"https://www.apple.com/{candidate}/", failures),
            suggestions(),
        )

        if direct_ok:
            return (candidate, category), False     # exact page exists: certain
        if suggestion_result:
            return suggestion_result, bool(failures)

        # 2. Try common variations concurrently
        words = candidate.split("-")
        variations = list(dict.fromkeys(filter(None, [
            "apple-" + candidate,
            "-".join(words[:3]),
            "-".join(words[:2]),
            *[f"{candidate}-{s}"       for s in ("2", "3", "4", "10", "11")],
            *[f"apple-{candidate}-{s}" for s in ("2", "3", "4", "10", "11")],
        ])))
        variations = [v for v in variations if v != candidate]

        probe_tasks = [
            _async_probe(session, f"https://www.apple.com/{v}/", failures)
            for v in variations
        ]
        results = await asyncio.gather(*probe_tasks)
        for var, ok in zip(variations, results):
            if ok:
                return (var, infer_category(var)), bool(failures)

    return None, bool(failures)


class SlugLookup(NamedTuple):
    """Outcome of resolving a product name."""
    result: Optional[tuple[str, str]]   # (slug, category), or None
    failed: bool = False                # True: Apple could not be checked, so "not found" is NOT known
    retry_after: int = 0                # seconds until a failed look-up is tried again


def _slug_entry(cache_key: str) -> Optional[dict]:
    """The live cache entry for a name, dropping it if it has expired."""
    with _cache_lock:
        entry = _slug_cache.get(cache_key)
        if entry is None:
            return None
        if entry["expires"] is not None and time.monotonic() >= entry["expires"]:
            _slug_cache.pop(cache_key, None)
            return None
        return entry


def _as_lookup(entry: dict) -> SlugLookup:
    wait = 0
    if entry["failed"]:
        wait = max(1, math.ceil(entry["expires"] - time.monotonic()))
    return SlugLookup(entry["result"], entry["failed"], wait)


def discover_slug(product_name: str) -> SlugLookup:
    """Sync entry point — Cache 2 wraps the async resolver."""
    cache_key = product_name.strip().lower()
    entry = _slug_entry(cache_key)
    if entry is not None:
        return _as_lookup(entry)                    # Cache 2 hit

    result, unsure = asyncio.run(_async_resolve_slug(product_name))
    if result and not unsure:
        ttl = None                                  # certain: keep
    elif result:
        ttl = SLUG_TTL_UNSURE                       # a fallback found while a check failed
    elif not unsure:
        ttl = SLUG_TTL_NOT_FOUND                    # Apple answered: no such page
    else:
        ttl = SLUG_TTL_FAILED                       # Apple did not answer: unknown
    entry = {"result": result,
             "expires": None if ttl is None else time.monotonic() + ttl,
             "failed": result is None and unsure}
    with _cache_lock:
        _slug_cache.pop(cache_key, None)            # re-insert so it counts as newest
        _slug_cache[cache_key] = entry
        while len(_slug_cache) > SLUG_CACHE_MAX:    # drop the oldest names
            _slug_cache.pop(next(iter(_slug_cache)), None)
    return _as_lookup(entry)


def slug_is_known(product_name: str) -> bool:
    """True when resolving this name needs no request to apple.com."""
    return _slug_entry(product_name.strip().lower()) is not None


def _lookup_failed_payload(product: str, wait: int) -> dict:
    return {"error": f"Apple did not respond while looking up \"{product}\", so it could not be "
                     f"checked. Please try again in {_human_wait(wait)}.",
            "temporary": True, "retryAfterSeconds": wait}


# ---------------------------------------------------------------------------
# Price extraction helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def get_min_price(slug: str) -> float:
    """
    Lowest plausible price for a product family, in US DOLLARS. A number below
    it on a product page is something else (a monthly instalment, an accessory,
    a trade-in value). Compare prices against local_min_price(), which converts
    this into the store's currency — never against this figure directly.
    """
    s = slug.lower()
    if "mac-pro"           in s: return 5000
    if "mac-studio"        in s: return 1500
    if "imac"              in s: return 1000
    if "macbook"           in s: return 800
    if "mac-mini"          in s: return 400
    if "iphone"            in s: return 500
    if "ipad-pro"          in s: return 800
    if "ipad"              in s: return 250
    if "apple-watch-ultra" in s: return 700
    if "apple-watch"       in s: return 200
    if "airpods-max"       in s: return 300
    if "airpods"           in s: return 100
    if "apple-tv"          in s: return 100
    if "homepod"           in s: return 80
    if "airtag"            in s: return 20
    return 50


# Stores sometimes price a product below the US price once converted, so the
# floor is applied with some room under it. Instalments are a twelfth of the
# price or less, far below this.
PRICE_FLOOR_SLACK = 0.8


def local_min_price(slug: str, currency: str, rates: dict[str, float]) -> float:
    """
    The sanity floor for `slug` in a store's own currency.

    The floor is defined in dollars; a store's price is in its own currency.
    Comparing the two directly rejected valid prices in currencies worth more
    than a dollar (245 KWD is a real iPhone price, but 245 < 500) and accepted
    instalments in currencies worth much less (₹6,908 a month is not an iPhone
    price, but 6908 > 500). `rates` maps a currency to units per 1 USD.

    If the currency has no rate the dollar figure is returned unchanged, which
    is how every store was checked before; such a row cannot be ranked anyway.
    """
    floor_usd = get_min_price(slug)
    rate = 1.0 if currency == "USD" else (rates.get(currency) or 0)
    if not rate or rate <= 0:
        return floor_usd
    return floor_usd * rate * PRICE_FLOOR_SLACK


def extract_low_price(html: str, min_price: float) -> Optional[float]:
    """First price on the page that is at least `min_price` (in the page's own currency)."""
    for pattern in (r'"lowPrice"\s*:\s*([\d.]+)', r'"amount"\s*:\s*([\d.]+)'):
        m = re.search(pattern, html)
        if m:
            val = float(m.group(1))
            if val >= min_price:
                return val
    return None


def build_shop_url(prefix: str, category: str, slug: str) -> str:
    base = f"https://www.apple.com/{prefix}/" if prefix else "https://www.apple.com/"
    return f"{base}shop/buy-{category}/{slug}"


def build_product_url(prefix: str, slug: str) -> str:
    return f"https://www.apple.com/{prefix}/{slug}/" if prefix else f"https://www.apple.com/{slug}/"


# ---------------------------------------------------------------------------
# Async price fetching — all 50 countries fire simultaneously
# ---------------------------------------------------------------------------

async def _fetch_price_async(
    session: aiohttp.ClientSession,
    country: str,
    prefix: str,
    currency: str,
    symbol: str,
    slug: str,
    category: str,
    rates: dict[str, float],
) -> dict:
    min_price = local_min_price(slug, currency, rates)    # floor in this store's currency
    shop_url  = build_shop_url(prefix, category, slug)
    prod_url  = build_product_url(prefix, slug)
    flag      = COUNTRY_FLAGS.get(country, "🏳")
    timeout   = aiohttp.ClientTimeout(total=20)

    async def _fetch(url: str) -> tuple[Optional[float], str]:
        """
        Download one page once and return (price, outcome). Outcome is:
          "ok"      — a page for this product (the price may still be None)
          "missing" — 404, or redirected to a different page: Apple sends
                      products a country does not sell to the line-up page,
                      and a price found there would belong to another product
          "error"   — could not tell: timeout, network error, rate limit,
                      server error — anything that may not last
        """
        try:
            async with session.get(url, timeout=timeout, allow_redirects=True) as r:
                if r.status == 200:
                    if slug not in urlparse(str(r.url)).path:
                        return None, "missing"
                    html = await r.text()
                    return extract_low_price(html, min_price), "ok"
                return None, ("missing" if r.status == 404 else "error")
        except Exception:
            return None, "error"

    # The buy page normally carries the price, so it is fetched first and the
    # (much larger) product page only if the buy page had none. Each page is
    # downloaded at most once: what the product page answered also tells a
    # product this country does not sell from one whose price could not be read.
    price_val, shop_outcome = await _fetch(shop_url)
    if price_val is None:
        price_val, prod_outcome = await _fetch(prod_url)

    if price_val is None:
        if prod_outcome == "missing":
            return {"country": country, "flag": flag, "available": False,
                    "reason": "Not available in this country", "url": prod_url}
        row = {"country": country, "flag": flag, "available": False,
               "reason": "Price not found", "url": prod_url}
        if "error" in (shop_outcome, prod_outcome):
            # Internal marker, removed before the row is sent or cached
            # (see _pop_transient): this "no price" may be temporary.
            row["_transient"] = True
        return row

    rate      = rates.get(currency, 0)
    usd_price = round(price_val / rate, 2) if rate else None
    price_str = (f"{symbol}{price_val:,.0f}" if price_val >= 1000
                 else f"{symbol}{price_val:,.2f}")

    return {
        "country":             country,
        "flag":                flag,
        "available":           True,
        "currency":            currency,
        "symbol":              symbol,
        "localPrice":          price_val,
        "localPriceFormatted": price_str,
        "usdPrice":            usd_price,
        "url":                 prod_url,
    }


async def _fetch_all_prices(slug: str, category: str, rates: dict[str, float]) -> list[dict]:
    """
    Fire all 50 country requests simultaneously.
    Used by the non-streaming /api/prices route.
    """
    connector = _make_connector()
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
        tasks = [
            _fetch_price_async(session, country, prefix, currency, symbol,
                               slug, category, rates)
            for country, (prefix, currency, symbol) in COUNTRIES.items()
        ]
        return await asyncio.gather(*tasks)


_SENTINEL = object()  # signals the queue that all results have been produced
_FAILED   = object()  # signals that the fetch broke off before every country answered


def _fetch_failed_payload() -> dict:
    return {"error": "Something went wrong while fetching prices. Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


def _stream_prices_into_queue(
    product: str, slug: str, category: str, rates: dict[str, float],
    q: queue.Queue, slot: Optional[threading.BoundedSemaphore] = None,
) -> None:
    """
    Runs in a background thread with its own event loop.
    Puts each row into `q` as soon as its coroutine completes. When every
    country has answered it stores the result set in Cache 3 itself, so the
    fetch is not wasted if the visitor closed the page part-way. Then it puts
    _SENTINEL to signal the end (_FAILED if the fetch broke off, so the stream
    never waits forever) and releases `slot` (its fetch slot).
    """
    rows: list[dict] = []
    complete = True             # becomes False if any country failed temporarily

    async def _run():
        nonlocal complete
        connector = _make_connector()
        async with aiohttp.ClientSession(headers=HEADERS, connector=connector) as session:
            tasks = [
                asyncio.ensure_future(
                    _fetch_price_async(session, country, prefix, currency, symbol,
                                       slug, category, rates)
                )
                for country, (prefix, currency, symbol) in COUNTRIES.items()
            ]
            # as_completed yields each future the moment it finishes —
            # so q.put() fires for the fastest countries first.
            for coro in asyncio.as_completed(tasks):
                row = await coro
                if _pop_transient(row):
                    complete = False
                rows.append(row)
                q.put(row)
    finished = False
    try:
        asyncio.run(_run())
        _cache_put(slug, _build_payload(product, slug, category, rates, rows), complete)
        finished = True
    finally:
        q.put(_SENTINEL if finished else _FAILED)
        if slot is not None:
            slot.release()


# ---------------------------------------------------------------------------
# Results cache helpers (Cache 3)
# ---------------------------------------------------------------------------

def _pop_transient(row: dict) -> bool:
    """Strip the internal marker from a row; True if the row failed temporarily."""
    return bool(row.pop("_transient", False))


def _sorted_results(rows: list[dict]) -> list[dict]:
    """Available countries cheapest-first, then unavailable ones A→Z."""
    available   = sorted([r for r in rows if     r.get("available")],
                         key=lambda r: r.get("usdPrice") or 999999)
    unavailable = sorted([r for r in rows if not r.get("available")],
                         key=lambda r: r["country"])
    return available + unavailable


def _build_payload(product: str, slug: str, category: str,
                   rates: dict[str, float], rows: list[dict]) -> dict:
    return {"product": product, "slug": slug, "category": category,
            "ratesDate": "live", "rates": rates_for_client(rates),
            "results": _sorted_results(rows)}


def _cache_put(slug: str, payload: dict, complete: bool) -> int:
    """Store a result set and return the TTL (seconds) it was given.
    `complete` is False when any country failed for a temporary reason."""
    has_price = any(r.get("available") for r in payload["results"])
    ttl = RESULTS_TTL if (complete and has_price) else RESULTS_TTL_SHORT
    with _cache_lock:
        _results_cache.pop(slug, None)              # re-insert so it counts as newest
        _results_cache[slug] = {"ts": time.monotonic(), "ttl": ttl, "payload": payload}
        while len(_results_cache) > RESULTS_CACHE_MAX:  # drop the oldest result sets
            _results_cache.pop(next(iter(_results_cache)), None)
    return ttl


def _cache_get(slug: str) -> Optional[tuple[dict, int, int]]:
    """Return (payload, age_seconds, expires_in_seconds) for a live entry, else None."""
    with _cache_lock:
        entry = _results_cache.get(slug)
        if not entry:
            return None
        age = time.monotonic() - entry["ts"]
        ttl = entry.get("ttl", RESULTS_TTL_SHORT)
        if age >= ttl:
            _results_cache.pop(slug, None)          # expired — free the memory
            return None
        return entry["payload"], int(age), max(0, int(ttl - age))


def _with_current_rates(payload: dict, rates: dict[str, float]) -> dict:
    """
    Copy of a cached payload with USD prices re-derived from current exchange
    rates. Local prices are what stays valid for hours; rates are refreshed
    every 30 min (Cache 1), so conversions must not age with the cached rows.
    If no rates are available the cached conversions are returned unchanged.
    """
    if not rates:
        return payload
    rows = []
    for row in payload["results"]:
        rate = rates.get(row.get("currency"), 0) if row.get("available") else 0
        if rate:
            row = {**row, "usdPrice": round(row["localPrice"] / rate, 2)}
        rows.append(row)
    return {**payload, "rates": rates_for_client(rates), "results": _sorted_results(rows)}


def _cached_events(product: str, slug: str, category: str, hit: tuple[dict, int, int]):
    """SSE events that replay a Cache 3 hit: meta, every row, then done."""
    payload, age, expires_in = hit
    payload = _with_current_rates(payload, fetch_exchange_rates())
    meta = {"product": product, "slug": slug, "category": category,
            **match_info(product, slug),
            "total": len(payload["results"]), "cached": True,
            "ageSeconds": age, "expiresInSeconds": expires_in,
            "rates": payload.get("rates", {})}
    yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
    for row in payload["results"]:
        yield f"event: result\ndata: {json.dumps(row)}\n\n"
    yield f"event: done\ndata: {json.dumps({'product': product, 'cached': True})}\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/prices")
def get_prices():
    product = request.args.get("product", "").strip()
    if not product:
        return jsonify({"error": "Missing ?product= parameter"}), 400
    if len(product) > MAX_PRODUCT_LENGTH:
        return jsonify({"error": f"Product name is too long (max {MAX_PRODUCT_LENGTH} characters)."}), 400

    client, _ = _client_id()
    wait = _request_limiter.hit(client)
    if wait:
        return _limit_response(*_too_fast(wait))

    # Anything that needs apple.com is counted once per request: an unknown
    # name (slug look-up) and/or a product whose prices are not cached.
    charged = False
    if not slug_is_known(product):
        denied = _charge_fetch(client)
        if denied:
            return _limit_response(*denied)
        charged = True

    lookup = discover_slug(product)
    if lookup.failed:                                # Apple unreachable — not the same as "not found"
        resp = jsonify(_lookup_failed_payload(product, lookup.retry_after))
        resp.status_code = 503
        resp.headers["Retry-After"] = str(lookup.retry_after)
        return resp
    if not lookup.result:
        return jsonify({
            "error": f"Could not find '{product}' on apple.com. "
                     "Check the product name, e.g. 'MacBook Air', 'iPhone Air', 'AirPods Pro'."
        }), 404

    slug, category = lookup.result

    def cached_reply(hit):
        payload, age, expires_in = hit
        payload = _with_current_rates(payload, fetch_exchange_rates())
        return jsonify({**payload, "product": product, **match_info(product, slug),
                        "cached": True, "ageSeconds": age, "expiresInSeconds": expires_in})

    hit = _cache_get(slug)
    if hit:                                          # Cache 3 hit
        return cached_reply(hit)

    if not charged:
        denied = _charge_fetch(client)
        if denied:
            return _limit_response(*denied)

    # Wait for a fetch slot (see MAX_PARALLEL_FETCHES).
    if not _fetch_slots.acquire(timeout=FETCH_SLOT_WAIT):
        resp = jsonify(_busy_payload())
        resp.status_code = 503
        resp.headers["Retry-After"] = "10"
        return resp
    try:
        hit = _cache_get(slug)      # someone may have fetched this product while this request waited
        if hit:
            return cached_reply(hit)
        rates    = fetch_exchange_rates()            # Cache 1
        all_rows = asyncio.run(_fetch_all_prices(slug, category, rates))
    finally:
        _fetch_slots.release()
    failed     = [_pop_transient(r) for r in all_rows]   # strips the marker from every row

    payload = _build_payload(product, slug, category, rates, all_rows)
    ttl     = _cache_put(slug, payload, complete=not any(failed))
    return jsonify({**payload, **match_info(product, slug), "cached": False,
                    "ageSeconds": 0, "expiresInSeconds": ttl})


@app.route("/api/prices/stream")
def get_prices_stream():
    """SSE endpoint — results stream back as each country completes."""
    product = request.args.get("product", "").strip()
    if not product:
        return _sse_error({"error": "Missing ?product= parameter"})
    if len(product) > MAX_PRODUCT_LENGTH:
        return _sse_error({"error": f"Product name is too long (max {MAX_PRODUCT_LENGTH} characters)."})

    client, _ = _client_id()
    wait = _request_limiter.hit(client)
    if wait:
        return _sse_error(_limit_payload(*_too_fast(wait)))

    def generate():
        # Tell the UI we're working before the (potentially slow) slug resolution
        yield f"event: searching\ndata: {json.dumps({'product': product})}\n\n"

        # Anything that needs apple.com is counted once per request (see get_prices).
        charged = False
        if not slug_is_known(product):
            denied = _charge_fetch(client)
            if denied:
                yield f"event: error\ndata: {json.dumps(_limit_payload(*denied))}\n\n"
                return
            charged = True

        lookup = discover_slug(product)             # Cache 2 — instant on repeat
        if lookup.failed:                           # Apple unreachable — not the same as "not found"
            payload = _lookup_failed_payload(product, lookup.retry_after)
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
            return
        if not lookup.result:
            msg = (f"Could not find \"{product}\" on apple.com. "
                   "Try a different name, e.g. \"MacBook Air\", \"iPhone Air\", \"AirPods Pro\".")
            yield f"event: error\ndata: {json.dumps({'error': msg})}\n\n"
            return

        slug, category = lookup.result

        # Cache 3 hit — replay stored rows as fast SSE events
        hit = _cache_get(slug)
        if hit:
            yield from _cached_events(product, slug, category, hit)
            return

        if not charged:
            denied = _charge_fetch(client)
            if denied:
                yield f"event: error\ndata: {json.dumps(_limit_payload(*denied))}\n\n"
                return

        # Wait for a fetch slot (see MAX_PARALLEL_FETCHES).
        got_slot = yield from _wait_for_fetch_slot()
        if not got_slot:
            yield f"event: error\ndata: {json.dumps(_busy_payload())}\n\n"
            return

        # This generator holds the slot now. Nothing below yields until the
        # background thread has taken it over, so closing the page cannot leave
        # it held; anything that fails before then gives it back.
        hit = _cache_get(slug)      # someone may have fetched this product while this search waited
        if hit:
            _fetch_slots.release()
            yield from _cached_events(product, slug, category, hit)
            return
        try:
            rates = fetch_exchange_rates()           # Cache 1
            meta  = {"product": product, "slug": slug, "category": category,
                     **match_info(product, slug),
                     "total": len(COUNTRIES), "rates": rates_for_client(rates)}

            # ── Queue bridge ─────────────────────────────────────────────────
            # A background thread runs the asyncio event loop and puts each row
            # into `q` as soon as its coroutine resolves.  This generator pulls
            # from `q` immediately — Flask flushes each SSE event to the client
            # without waiting for all 50 countries to finish. The thread stores
            # the finished set in Cache 3 and releases the fetch slot.
            q = queue.Queue()
            t = threading.Thread(
                target=_stream_prices_into_queue,
                args=(product, slug, category, rates, q, _fetch_slots),
                daemon=True,
            )
            t.start()
        except BaseException:
            _fetch_slots.release()
            raise

        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"

        while True:
            row = q.get()           # blocks only until the next country finishes
            if row is _SENTINEL or row is _FAILED:
                break
            yield f"event: result\ndata: {json.dumps(row)}\n\n"

        t.join()                    # the results are in Cache 3 and the slot is free

        if row is _FAILED:          # nothing was cached; the visitor is told to try again
            yield f"event: error\ndata: {json.dumps(_fetch_failed_payload())}\n\n"
            return
        yield f"event: done\ndata: {json.dumps({'product': product})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/cache/status")
def cache_status():
    """
    Cache and rate-limit state. The public view has totals only. What people
    searched for (slug-cache keys, cached product slugs) is shown only to a
    request carrying ADMIN_TOKEN in an `X-Admin-Token` or
    `Authorization: Bearer` header.
    """
    client, source = _client_id()
    wait = _request_limiter.hit(client)
    if wait:
        return _limit_response(*_too_fast(wait))

    now  = time.monotonic()
    body = {
        "exchange_rates": {
            "cached":      bool(_rates_cache),
            "age_seconds": round(now - _rates_fetched_at) if _rates_cache else None,
            "ttl_seconds": RATES_TTL,
            "expires_in":  max(0, round(RATES_TTL - (now - _rates_fetched_at))) if _rates_cache else None,
        },
        "slug_cache": {
            "entries": len(_slug_cache),
            "max_entries": SLUG_CACHE_MAX,
            "not_found_ttl_seconds": SLUG_TTL_NOT_FOUND,
            "failed_lookup_ttl_seconds": SLUG_TTL_FAILED,
        },
        "results_cache": {
            "entries": len(_results_cache),
            "max_entries": RESULTS_CACHE_MAX,
            "ttl_seconds":            RESULTS_TTL,
            "ttl_seconds_incomplete": RESULTS_TTL_SHORT,
        },
        "rate_limits": {
            "requests_per_minute":             _request_limiter.limit,
            "apple_lookups_per_10_minutes":    _fetch_limiter.limit,
            "apple_lookups_per_10_minutes_all_visitors": _global_fetch_limiter.limit,
            "apple_lookups_used_all_visitors": _global_fetch_limiter.count("all"),
            "visitors_tracked": _request_limiter.tracked(),
        },
        "details": "shown",
    }
    if not _is_admin():
        body["details"] = "hidden — send the admin token to see search terms and product slugs"
        return jsonify(body)

    with _cache_lock:
        slug_keys = list(_slug_cache.keys())
        results   = list(_results_cache.items())
    body["slug_cache"]["keys"] = slug_keys
    body["results_cache"]["slugs"] = {
        slug: {
            "age_seconds": round(now - v["ts"]),
            "ttl_seconds": v.get("ttl", RESULTS_TTL_SHORT),
            "expires_in":  max(0, round(v.get("ttl", RESULTS_TTL_SHORT) - (now - v["ts"]))),
        }
        for slug, v in results
    }
    # How this server identified you — use it to confirm visitors are told apart correctly.
    body["you"] = {"address": client, "identified_by": source}
    return jsonify(body)


@app.route("/")
def index():
    return "Apple Products Global Price Tracker API — /api/prices?product=MacBook+Air"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
