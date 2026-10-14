"""
Finished result sets, one per product slug: how they are put together,
stored, and brought up to date with the current exchange rates.

A complete set is kept for config.RESULTS_TTL (6 hours). A set where any
country failed for a temporary reason, or where no country had a price, is
kept for config.RESULTS_TTL_SHORT (5 minutes), so a bad fetch is retried soon
instead of being served for hours.
"""
import time
from typing import Optional

from . import config
from .caches import TTLCache
from .exchange import rates_for_client, usd_rate

# Product slug → its result set (the payload build_payload makes). Capped at
# config.RESULTS_CACHE_MAX sets.
result_sets: TTLCache[dict] = TTLCache(max_size=lambda: config.RESULTS_CACHE_MAX)


def sorted_results(rows: list[dict]) -> list[dict]:
    """Available countries cheapest-first (any without a USD price after them), then unavailable ones A→Z."""
    available   = sorted([r for r in rows if     r.get("available")],     # no USD price: after the rest
                         key=lambda r: (r.get("usdPrice") is None, r.get("usdPrice") or 0, r["country"]))
    unavailable = sorted([r for r in rows if not r.get("available")],
                         key=lambda r: r["country"])
    return available + unavailable


def build_payload(product: str, slug: str, category: str,
                  rates: dict[str, float], rows: list[dict]) -> dict:
    return {"product": product, "slug": slug, "category": category,
            "ratesDate": "live", "rates": rates_for_client(rates),
            "results": sorted_results(rows)}


def put(slug: str, payload: dict, complete: bool) -> int:
    """Store a result set and return the TTL (seconds) it was given.
    `complete` is False when any country failed for a temporary reason."""
    has_price = any(r.get("available") for r in payload["results"])
    ttl = config.RESULTS_TTL if (complete and has_price) else config.RESULTS_TTL_SHORT
    result_sets.put(slug, payload, ttl)
    return ttl


def get(slug: str) -> Optional[tuple[dict, int, int]]:
    """Return (payload, age_seconds, expires_in_seconds) for a live entry, else None."""
    entry = result_sets.get(slug)
    if entry is None:
        return None
    now = time.monotonic()
    return entry.value, int(entry.age(now)), int(entry.expires_in(now))


def with_current_rates(payload: dict, rates: dict[str, float]) -> dict:
    """
    Copy of a cached payload with USD prices re-derived from current exchange
    rates. Local prices are what stays valid for hours; rates are refreshed
    every 30 min (see exchange.py), so conversions must not age with the cached
    rows. If no rates are available the cached conversions are returned unchanged.
    """
    if not rates:
        return payload
    rows = []
    for row in payload["results"]:
        rate = usd_rate(rates, row.get("currency")) if row.get("available") else None
        if rate:
            row = {**row, "usdPrice": round(row["localPrice"] / rate, 2) or None}
        rows.append(row)
    return {**payload, "rates": rates_for_client(rates), "results": sorted_results(rows)}


def status() -> dict[str, dict]:
    """slug → its age, lifetime and time left, in seconds (for the admin view of /api/cache/status)."""
    now = time.monotonic()
    return {
        slug: {"age_seconds": round(entry.age(now)),
               "ttl_seconds": entry.ttl,
               "expires_in":  round(entry.expires_in(now))}
        for slug, entry in result_sets.items()
    }


def size() -> int:
    return len(result_sets)


def clear() -> None:
    result_sets.clear()
