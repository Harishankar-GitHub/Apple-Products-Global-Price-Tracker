"""
Prices: reading a price off a store's page, and fetching every store at once.

All 50 country requests fire simultaneously, on the shared event loop and
connections in web.py (no thread pool). Each store needs one page download
when its buy page has the price, two otherwise.
"""
import asyncio
import json
import math
import re
from typing import AsyncIterator, Iterator, NamedTuple, Optional
from urllib.parse import urlparse

import aiohttp

from . import config, web
from .countries import COUNTRIES, COUNTRY_FLAGS
from .exchange import usd_rate


# ---------------------------------------------------------------------------
# Reading prices (pure, no I/O)
# ---------------------------------------------------------------------------

# Lowest plausible price per product family, in US DOLLARS: the first entry
# whose name is part of the slug applies, so a more specific name comes before
# a more general one ("ipad-pro" before "ipad"). A number below it on a product
# page is something else (a monthly instalment, an accessory, a trade-in value).
PRICE_FLOORS_USD: tuple[tuple[str, float], ...] = (
    ("mac-pro",           5000),
    ("mac-studio",        1500),
    ("imac",              1000),
    ("macbook",            800),
    ("mac-mini",           400),
    ("iphone",             500),
    ("ipad-pro",           800),
    ("ipad",               250),
    ("apple-watch-ultra",  700),
    ("apple-watch",        200),
    ("airpods-max",        300),
    ("airpods",            100),
    ("apple-tv",           100),
    ("homepod",             80),
    ("airtag",              20),
)
OTHER_PRODUCTS_FLOOR_USD = 50


def get_min_price(slug: str) -> float:
    """
    The price floor for a product, in US DOLLARS (see PRICE_FLOORS_USD).
    Compare prices against local_min_price(), which converts this into the
    store's currency — never against this figure directly.
    """
    s = slug.lower()
    return next((floor for family, floor in PRICE_FLOORS_USD if family in s), OTHER_PRODUCTS_FLOOR_USD)


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


# The product's structured data (schema.org JSON-LD), which carries its price.
_JSON_LD = re.compile(r'<script\b[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script\s*>',
                      re.IGNORECASE | re.DOTALL)
# Anywhere in the page, in this order: a "lowPrice", then an "amount" (which is
# also what Apple calls a monthly instalment, hence the floor). Quoted or not.
_IN_THE_PAGE = (re.compile(r'"lowPrice"\s*:\s*"?([\d.]+)'), re.compile(r'"amount"\s*:\s*"?([\d.]+)'))


def _number(value) -> Optional[float]:
    """A price as a positive number: 999, 999.0 or "999.00"; None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not re.fullmatch(r"\d+(\.\d*)?", value.strip()):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _offer_prices(node) -> Iterator[float]:
    """Every offer's lowPrice (or else its price) in a JSON-LD document, in order."""
    if isinstance(node, dict):
        for key in ("lowPrice", "price"):
            if key in node:
                if (number := _number(node[key])) is not None:
                    yield number
                break
        for value in node.values():
            yield from _offer_prices(value)
    elif isinstance(node, list):
        for item in node:
            yield from _offer_prices(item)


def _structured_prices(html: str) -> Iterator[float]:
    for block in _JSON_LD.findall(html):
        try:
            document = json.loads(block)
        except ValueError:
            continue                    # not valid JSON: the search of the whole page below may still find it
        yield from _offer_prices(document)


def _prices_in_the_page(html: str, pattern: re.Pattern) -> Iterator[float]:
    for match in pattern.finditer(html):
        if (number := _number(match.group(1))) is not None:
            yield number


def extract_low_price(html: str, min_price: float) -> Optional[float]:
    """
    The product's price on a page (in the page's own currency): the first
    price of at least `min_price` in the page's structured data, or else the
    first "lowPrice", or else the first "amount", of at least `min_price`
    anywhere in the page. None if there is none.
    """
    for found in (_structured_prices(html), *(_prices_in_the_page(html, p) for p in _IN_THE_PAGE)):
        for price in found:
            if price >= min_price:
                return price
    return None


def build_shop_url(prefix: str, category: str, slug: str) -> str:
    base = f"https://www.apple.com/{prefix}/" if prefix else "https://www.apple.com/"
    return f"{base}shop/buy-{category}/{slug}"


def build_product_url(prefix: str, slug: str) -> str:
    return f"https://www.apple.com/{prefix}/{slug}/" if prefix else f"https://www.apple.com/{slug}/"


# ---------------------------------------------------------------------------
# Fetching — all 50 stores at once
# ---------------------------------------------------------------------------

class StoreRow(NamedTuple):
    """One store's answer."""
    row: dict           # what is sent to the page and cached
    transient: bool     # True: this answer may change soon (Apple failed to answer, or no exchange
                        # rate), so the result set is kept for minutes rather than hours
    problem: Optional[str] = None   # for the log: what went wrong ("timeout", "HTTP 503", "no price
                                    # on the page", ...); None for a price, or a product not sold there


async def _fetch_store(
    session: aiohttp.ClientSession,
    connections: asyncio.Semaphore,
    country: str,
    prefix: str,
    currency: str,
    symbol: str,
    slug: str,
    category: str,
    rates: dict[str, float],
) -> StoreRow:
    min_price = local_min_price(slug, currency, rates)    # floor in this store's currency
    # No exchange rate for this store's currency: its price cannot be converted
    # (it is sent as listed, unranked) and the floor above could only be applied
    # in dollars. Its row counts as a temporary failure, so the result set is
    # kept for minutes rather than hours and fetched again once rates are back.
    no_rate   = usd_rate(rates, currency) is None
    shop_url  = build_shop_url(prefix, category, slug)
    prod_url  = build_product_url(prefix, slug)
    flag      = COUNTRY_FLAGS.get(country, "🏳")
    timeout   = aiohttp.ClientTimeout(total=config.PAGE_TIMEOUT)

    async def _fetch(url: str) -> tuple[Optional[float], str, str]:
        """
        Download one page once and return (price, outcome, what happened). Outcome is:
          "ok"      — a page for this product (the price may still be None)
          "missing" — 404, or redirected to a different page: Apple sends
                      products a country does not sell to the line-up page,
                      and a price found there would belong to another product
          "error"   — could not tell: timeout, network error, rate limit,
                      server error — anything that may not last
        """
        try:
            async with connections, session.get(url, timeout=timeout, allow_redirects=True) as r:
                if r.status == 200:
                    if slug not in urlparse(str(r.url)).path:
                        return None, "missing", "redirected away"
                    html = await r.text()
                    return extract_low_price(html, min_price), "ok", "no price on the page"
                return None, ("missing" if r.status == 404 else "error"), f"HTTP {r.status}"
        except Exception as exc:
            return None, "error", web.describe(exc)

    # The buy page normally carries the price, so it is fetched first and the
    # (much larger) product page only if the buy page had none. Each page is
    # downloaded at most once: what the product page answered also tells a
    # product this country does not sell from one whose price could not be read.
    price_val, shop_outcome, shop_said = await _fetch(shop_url)
    if price_val is None:
        price_val, prod_outcome, prod_said = await _fetch(prod_url)

    if price_val is None:
        if prod_outcome == "missing":
            return StoreRow({"country": country, "flag": flag, "available": False,
                             "reason": "Not available in this country", "url": prod_url}, transient=False)
        problem = (shop_said if shop_said == prod_said
                   else f"buy page: {shop_said}, product page: {prod_said}")
        if no_rate:
            problem += f"; no usable exchange rate for {currency}"
        return StoreRow({"country": country, "flag": flag, "available": False,
                         "reason": "Price not found", "url": prod_url},
                        transient="error" in (shop_outcome, prod_outcome) or no_rate, problem=problem)

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
    return StoreRow(row, transient=usd_price is None,          # see no_rate above
                    problem=None if usd_price else f"no usable exchange rate for {currency}")


async def fetch_every_store(slug: str, category: str, rates: dict[str, float]) -> AsyncIterator[StoreRow]:
    """
    Every store's answer, in the order they arrive. All 50 stores are asked at
    once over the shared connections (see web.py), with at most
    config.APPLE_MAX_CONNECTIONS of this fetch's requests in flight at a time.
    Run it on the shared event loop.
    """
    session = web.session()
    connections = asyncio.Semaphore(config.APPLE_MAX_CONNECTIONS)
    tasks = [
        asyncio.ensure_future(_fetch_store(session, connections, country, prefix, currency, symbol,
                                           slug, category, rates))
        for country, (prefix, currency, symbol) in COUNTRIES.items()
    ]
    try:
        for next_done in asyncio.as_completed(tasks):   # the fastest stores first
            yield await next_done
    finally:
        for task in tasks:              # if the fetch broke off part-way, stop asking the other stores
            task.cancel()
