"""
Product name → the page Apple has for it: its slug ("macbook-air") and
category ("mac", used in buy-page URLs).

All apple.com checks for one name run at once, over the connections the
whole API shares (see web.py). Answers are cached by the name as typed. How long an answer is kept depends on how sure
it is, so that one Apple timeout cannot make a product "not found" (or pin it
to the wrong page) until the server restarts:

  found, every check answered           → kept for the life of the process
  found a fallback while a check failed → config.SLUG_TTL_UNSURE, then looked up again
  not found, every check answered       → config.SLUG_TTL_NOT_FOUND (Apple adds products)
  could not tell (Apple did not answer) → config.SLUG_TTL_FAILED, and reported as
                                          "try again", never as "not found"
"""
import asyncio
import math
import re
import threading
import time
from typing import NamedTuple, Optional
from urllib.parse import urlparse

import aiohttp

from . import config, web
from .prices import build_shop_url

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
# Names and slugs (pure, no I/O)
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


# ---------------------------------------------------------------------------
# Checking apple.com
# ---------------------------------------------------------------------------

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
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT),
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
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT),
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
    All apple.com probing runs concurrently, on the shared event loop and
    connections (see web.py). Returns (result, unsure). `unsure` is True when
    a page check failed for a temporary reason before the answer was reached,
    so the answer — a fallback page, or "not found" — might be different once
    Apple responds again. An exact match is never unsure. Failures of the
    suggestions service alone do not count: it is only a hint, and the page
    checks decide.
    """
    override  = SLUG_OVERRIDES.get(product_name.strip().lower())
    candidate = name_to_slug(product_name)
    category  = infer_category(candidate)
    failures: list = []

    session = web.session()

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
                timeout=aiohttp.ClientTimeout(total=config.SUGGESTIONS_TIMEOUT),
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


# ---------------------------------------------------------------------------
# The cache of answers, and the entry point
# ---------------------------------------------------------------------------

class SlugLookup(NamedTuple):
    """Outcome of resolving a product name."""
    result: Optional[tuple[str, str]]   # (slug, category), or None
    failed: bool = False                # True: Apple could not be checked, so "not found" is NOT known
    retry_after: int = 0                # seconds until a failed look-up is tried again


# name as typed (lower case) → {"result": (slug, category) or None,
#                               "expires": monotonic time or None, "failed": bool}
# Oldest first: a name stored again moves to the end.
_entries: dict[str, dict] = {}
_lock = threading.RLock()   # requests are served by several threads at once


def _entry(cache_key: str) -> Optional[dict]:
    """The live cache entry for a name, dropping it if it has expired."""
    with _lock:
        entry = _entries.get(cache_key)
        if entry is None:
            return None
        if entry["expires"] is not None and time.monotonic() >= entry["expires"]:
            _entries.pop(cache_key, None)
            return None
        return entry


def _remember(cache_key: str, result: Optional[tuple[str, str]], ttl: Optional[float], failed: bool) -> dict:
    """Store an answer as the newest entry (ttl None: keep), dropping the oldest names beyond the cap."""
    entry = {"result": result,
             "expires": None if ttl is None else time.monotonic() + ttl,
             "failed": failed}
    with _lock:
        _entries.pop(cache_key, None)               # re-insert so it counts as newest
        _entries[cache_key] = entry
        while len(_entries) > config.SLUG_CACHE_MAX:
            _entries.pop(next(iter(_entries)), None)
    return entry


def _as_lookup(entry: dict) -> SlugLookup:
    wait = 0
    if entry["failed"]:
        wait = max(1, math.ceil(entry["expires"] - time.monotonic()))
    return SlugLookup(entry["result"], entry["failed"], wait)


def discover_slug(product_name: str) -> SlugLookup:
    """The page for a product name: from the cache, or by checking apple.com."""
    cache_key = product_name.strip().lower()
    entry = _entry(cache_key)
    if entry is not None:
        return _as_lookup(entry)                    # cache hit

    result, unsure = web.run(_async_resolve_slug(product_name))
    if result and not unsure:
        ttl = None                                  # certain: keep
    elif result:
        ttl = config.SLUG_TTL_UNSURE                # a fallback found while a check failed
    elif not unsure:
        ttl = config.SLUG_TTL_NOT_FOUND             # Apple answered: no such page
    else:
        ttl = config.SLUG_TTL_FAILED                # Apple did not answer: unknown
    return _as_lookup(_remember(cache_key, result, ttl, failed=result is None and unsure))


def slug_is_known(product_name: str) -> bool:
    """True when resolving this name needs no request to apple.com."""
    return _entry(product_name.strip().lower()) is not None


def names() -> list[str]:
    """The names held, oldest first (for the admin view of /api/cache/status)."""
    with _lock:
        return list(_entries)


def size() -> int:
    return len(_entries)


def clear() -> None:
    with _lock:
        _entries.clear()
