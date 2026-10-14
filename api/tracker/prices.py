"""
Prices: reading a price off a store's page, and fetching every store at once.

All 50 country requests fire simultaneously in one session on one event loop
(no thread pool). Each store needs one page download when its buy page has
the price, two otherwise.
"""
import asyncio
import queue
import re
import threading
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from . import config, results_cache, web
from .countries import COUNTRIES, COUNTRY_FLAGS
from .exchange import usd_rate


# ---------------------------------------------------------------------------
# Reading prices (pure, no I/O)
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
    rate = 1.0 if currency == "USD" else usd_rate(rates, currency)
    if not rate:
        return floor_usd
    return floor_usd * rate * config.PRICE_FLOOR_SLACK


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
    # No exchange rate for this store's currency: its price cannot be converted
    # (it is sent as listed, unranked) and the floor above could only be applied
    # in dollars. Its row is marked like a temporary failure, so the result set
    # is kept for minutes rather than hours and fetched again once rates are back.
    no_rate   = usd_rate(rates, currency) is None
    shop_url  = build_shop_url(prefix, category, slug)
    prod_url  = build_product_url(prefix, slug)
    flag      = COUNTRY_FLAGS.get(country, "🏳")
    timeout   = aiohttp.ClientTimeout(total=config.PAGE_TIMEOUT)

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
        if "error" in (shop_outcome, prod_outcome) or no_rate:
            # Internal marker, removed before the row is sent or cached
            # (see pop_transient): this "no price" may be temporary.
            row["_transient"] = True
        return row

    rate      = usd_rate(rates, currency)
    usd_price = (round(price_val / rate, 2) or None) if rate else None   # never 0.00
    price_str = (f"{symbol}{price_val:,.0f}" if price_val >= 1000
                 else f"{symbol}{price_val:,.2f}")

    row = {
        "country":             country,
        "flag":                flag,
        "available":           True,
        "currency":            currency,
        "symbol":              symbol,
        "localPrice":          price_val,
        "localPriceFormatted": price_str,
        "usdPrice":            usd_price,     # null: no exchange rate, so not ranked
        "url":                 prod_url,
    }
    if usd_price is None:
        row["_transient"] = True               # see no_rate above
    return row


async def fetch_all_prices(slug: str, category: str, rates: dict[str, float]) -> list[dict]:
    """
    Fire all 50 country requests simultaneously.
    Used by the non-streaming /api/prices route.
    """
    async with web.apple_session() as session:
        tasks = [
            _fetch_price_async(session, country, prefix, currency, symbol,
                               slug, category, rates)
            for country, (prefix, currency, symbol) in COUNTRIES.items()
        ]
        return await asyncio.gather(*tasks)


SENTINEL = object()  # signals the queue that all results have been produced
FAILED   = object()  # signals that the fetch broke off before every country answered


def stream_prices_into_queue(
    product: str, slug: str, category: str, rates: dict[str, float],
    q: queue.Queue, slot: Optional[threading.BoundedSemaphore] = None,
) -> None:
    """
    Runs in a background thread with its own event loop.
    Puts each row into `q` as soon as its coroutine completes. When every
    country has answered it stores the result set in the results cache itself, so the
    fetch is not wasted if the visitor closed the page part-way. Then it puts
    SENTINEL to signal the end (FAILED if the fetch broke off, so the stream
    never waits forever) and releases `slot` (its fetch slot).
    """
    rows: list[dict] = []
    complete = True             # becomes False if any country failed temporarily

    async def _run():
        nonlocal complete
        async with web.apple_session() as session:
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
                if pop_transient(row):
                    complete = False
                rows.append(row)
                q.put(row)
    finished = False
    try:
        asyncio.run(_run())
        results_cache.put(slug, results_cache.build_payload(product, slug, category, rates, rows), complete)
        finished = True
    finally:
        q.put(SENTINEL if finished else FAILED)
        if slot is not None:
            slot.release()


def pop_transient(row: dict) -> bool:
    """Strip the internal marker from a row; True if the row failed temporarily."""
    return bool(row.pop("_transient", False))
