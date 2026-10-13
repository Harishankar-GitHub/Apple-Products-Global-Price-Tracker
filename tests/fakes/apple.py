"""
An in-memory stand-in for apple.com and the exchange-rate service.

The API talks to both through ``aiohttp.ClientSession``. ``install()`` swaps
the session and connector classes for the fakes below, so every request the
API makes is answered from the catalogue here: no network, the same answers
every run, and switches to simulate failures.

What the fake knows about apple.com, as the site behaved in October 2026:

* A product has a product page ``/{store}/{slug}/`` and a buy page
  ``/{store}/shop/buy-{category}/{slug}``; the price is in a JSON-LD block.
* A store that does not sell a product answers 404 for both pages.
* Watch buy pages do not carry the model slug, so their price is on the
  product page (``price_on_product_page``).
* A retired model's product page redirects to the line-up page (which shows
  some other product's price) and its buy page is gone (``retired``).
* Some products are sold only through the buy page (``no_product_page``).
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Union
from urllib.parse import urlparse

import aiohttp

Failure = Union[str, int]           # "timeout", or an HTTP status such as 503

# Units per 1 USD. Apple's local prices are fixed when listed, so they are
# worked out from these figures even if a test changes `rates` later.
RATES: dict[str, float] = {
    "USD": 1, "JPY": 150, "CAD": 1.38, "KRW": 1380, "HKD": 7.8, "TWD": 32, "AED": 3.67,
    "CNY": 7.2, "PHP": 57, "THB": 35, "INR": 84, "SGD": 1.33, "MYR": 4.4, "AUD": 1.52,
    "NZD": 1.66, "GBP": 0.78, "EUR": 0.92, "SEK": 10.4, "NOK": 10.8, "DKK": 6.9, "PLN": 3.9,
    "TRY": 34, "MXN": 19, "BRL": 5.6, "SAR": 3.75, "VND": 25000, "IDR": 16000, "ILS": 3.7,
    "ZAR": 18, "CZK": 23, "HUF": 360, "RON": 4.6, "CHF": 0.86, "CLP": 950, "COP": 4100,
    "KWD": 0.31, "QAR": 3.64, "BHD": 0.376, "OMR": 0.385,
}

# Stores that sell the catalogue: URL prefix ("" is the US) → (currency, price relative to the US).
# The API lists 50 stores; the other 20 do not sell anything here.
STORES: dict[str, tuple[str, float]] = {
    "": ("USD", 1.0), "jp": ("JPY", .97), "ca": ("CAD", 1.02), "kr": ("KRW", 1.08), "hk": ("HKD", .99),
    "tw": ("TWD", 1.05), "ae": ("AED", 1.04), "cn": ("CNY", 1.03), "th": ("THB", 1.07), "in": ("INR", 1.19),
    "sg": ("SGD", 1.09), "my": ("MYR", 1.01), "au": ("AUD", 1.06), "nz": ("NZD", 1.12), "uk": ("GBP", 1.28),
    "de": ("EUR", 1.30), "fr": ("EUR", 1.30), "nl": ("EUR", 1.31), "es": ("EUR", 1.30), "it": ("EUR", 1.33),
    "ie": ("EUR", 1.32), "se": ("SEK", 1.36), "no": ("NOK", 1.34), "dk": ("DKK", 1.38), "pl": ("PLN", 1.35),
    "tr": ("TRY", 1.72), "mx": ("MXN", 1.22), "br": ("BRL", 1.95), "ch": ("CHF", 1.16), "vn": ("VND", 1.05),
}

# Product slug → US price (None: the page exists but shows no price anywhere).
# Any slug of the form "prod<N>" also exists, priced at 500 + N: an endless
# supply of distinct products for tests that need many.
PRODUCTS: dict[str, Optional[float]] = {
    "macbook-air": 999, "iphone-17": 799, "mac-mini": 599, "ipad-pro": 999, "imac": 1299,
    "airtag": None, "apple-watch-ultra-4": 799, "iphone-16": 729,
}

# A price that belongs to some other product, shown on line-up pages.
LINEUP_HTML = '<script type="application/ld+json">{"lowPrice": 99999.00}</script>'


def store_prefix(url: str) -> str:
    """The store an apple.com URL belongs to: "jp", "uk", … or "" for the US store."""
    first = url.split("apple.com/", 1)[1].split("/")[0]
    return first if len(first) == 2 else ""


def price_block(amount: float, currency: str = "USD", decimals: int = 2) -> str:
    """The JSON-LD block Apple puts on a page that has a price."""
    return f'<script type="application/ld+json">{{"lowPrice": {amount:.{decimals}f},"priceCurrency":"{currency}"}}</script>'


@dataclass
class Response:
    status: int
    body: str
    url: str

    async def text(self) -> str:
        return self.body

    async def json(self, content_type=None):
        return json.loads(self.body)


@dataclass
class FakeApple:
    """apple.com and the exchange-rate service. Every field can be changed by a test."""

    rates: dict = field(default_factory=lambda: dict(RATES))
    stores: dict = field(default_factory=lambda: dict(STORES))
    products: dict = field(default_factory=lambda: dict(PRODUCTS))
    price_on_product_page: set = field(default_factory=lambda: {"apple-watch-ultra-4"})
    retired: dict = field(default_factory=lambda: {
        "apple-watch-ultra-3": "watch", "apple-watch-ultra-2": "watch", "iphone-16-pro": "iphone"})
    no_product_page: dict = field(default_factory=lambda: {"iphone-16": "iphone"})

    # (store prefix, slug) → line-up page that store sends the product to (not sold there)
    country_redirect: dict = field(default_factory=dict)
    # (store prefix, slug) whose buy page redirects to a longer URL for the same product
    shop_long_url: set = field(default_factory=set)
    # (store prefix, slug) → HTML that store's pages show instead of the usual price block
    page_html: dict = field(default_factory=dict)
    # search text (lower case) → apple.com URL the suggestions service returns
    suggestions: dict = field(default_factory=dict)

    # ---- failure switches ----
    outage: Optional[Failure] = None            # every apple.com request fails this way
    store_failures: dict = field(default_factory=dict)   # store prefix → Failure (that store's pages)
    url_failures: dict = field(default_factory=dict)     # URL fragment → Failure
    suggestions_failure: Optional[Failure] = None
    rates_down: bool = False

    # Seconds each request takes, given its URL (0 by default: instant).
    delay: Callable[[str], float] = lambda url: 0

    # ---- what happened ----
    calls: list = field(default_factory=list)            # every URL requested, in order
    connectors: list = field(default_factory=list)       # keyword arguments of every connector created
    peak_connections: int = 0                            # most requests in flight at one moment

    def __post_init__(self):
        self.listing_rates = dict(self.rates)
        self._lock = threading.Lock()
        self._in_flight = 0

    # ---- prices as listed ----
    def local_price(self, prefix: str, slug: str) -> float:
        """What the store at `prefix` charges for `slug`, in its own currency."""
        currency, multiplier = self.stores[prefix]
        return round(self.products[slug] * multiplier * self.listing_rates[currency])

    def apple_calls(self, fragment: str = "") -> list[str]:
        return [u for u in self.calls if "apple.com" in u and fragment in u]

    # ---- answering requests ----
    def _known(self, slug: str) -> bool:
        m = re.fullmatch(r"prod(\d+)", slug)
        if m:
            self.products.setdefault(slug, 500 + int(m.group(1)))
        return slug in self.products

    @staticmethod
    def _fail(mode: Failure, url: str) -> Response:
        if mode == "timeout":
            raise asyncio.TimeoutError()
        return Response(int(mode), "", url)

    async def respond(self, url: str, params: Optional[dict] = None) -> Response:
        with self._lock:
            self.calls.append(url)
        await asyncio.sleep(self.delay(url))
        host, path = urlparse(url).netloc, urlparse(url).path

        if "er-api.com" in host:
            if self.rates_down:
                raise asyncio.TimeoutError()
            return Response(200, json.dumps({"rates": self.rates}), url)

        if "suggestions" in path:
            if self.outage or self.suggestions_failure:
                return self._fail(self.outage or self.suggestions_failure, url)
            hit = self.suggestions.get((params or {}).get("q", "").lower())
            return Response(200, json.dumps({"suggestions": [{"url": hit}] if hit else []}), url)

        if self.outage:
            return self._fail(self.outage, url)
        for fragment, mode in self.url_failures.items():
            if fragment in url:
                return self._fail(mode, url)

        parts = [p for p in path.split("/") if p]
        prefix = parts[0] if parts and len(parts[0]) == 2 else ""
        slug = parts[-1] if parts else ""
        is_shop = "shop" in parts
        base = "https://www.apple.com/" + (f"{prefix}/" if prefix else "")

        if not self._known(slug):
            return Response(404, "", url)
        if prefix in self.store_failures:
            return self._fail(self.store_failures[prefix], url)
        if slug in self.retired:
            return Response(404, "", url) if is_shop else Response(200, LINEUP_HTML, base + self.retired[slug] + "/")
        if (prefix, slug) in self.page_html and prefix in self.stores:
            return Response(200, self.page_html[(prefix, slug)], url)
        if (prefix, slug) in self.country_redirect:
            return Response(200, LINEUP_HTML, base + self.country_redirect[(prefix, slug)] + "/")
        if slug in self.no_product_page and not is_shop:
            return Response(200, LINEUP_HTML, base + self.no_product_page[slug] + "/")
        if prefix not in self.stores:
            return Response(404, "", url)                    # not sold in this country
        currency = self.stores[prefix][0]
        if slug in self.price_on_product_page:
            return Response(404, "", url) if is_shop else Response(200, price_block(self.local_price(prefix, slug), currency), url)
        if not is_shop or self.products[slug] is None:
            return Response(200, "<html>no price here</html>", url)
        final = url + "/13-inch-display" if (prefix, slug) in self.shop_long_url else url
        return Response(200, price_block(self.local_price(prefix, slug), currency), final)

    # ---- connection accounting (stands in for aiohttp's per-host limit) ----
    def _opened(self):
        with self._lock:
            self._in_flight += 1
            self.peak_connections = max(self.peak_connections, self._in_flight)

    def _closed(self):
        with self._lock:
            self._in_flight -= 1


class FakeConnector:
    def __init__(self, apple: FakeApple, **kwargs):
        self.kwargs = kwargs
        apple.connectors.append(kwargs)


class _Request:
    """`async with session.get(...) as response`: holds a connection, like aiohttp."""

    def __init__(self, session: "FakeSession", url: str, params: Optional[dict]):
        self.session, self.url, self.params = session, url, params
        self._held = False

    async def __aenter__(self) -> Response:
        await self.session._acquire()
        self._held = True
        self.session.apple._opened()
        try:
            return await self.session.apple.respond(self.url, self.params)
        except BaseException:
            self._release()
            raise

    async def __aexit__(self, *exc):
        self._release()
        return False

    def _release(self):
        if self._held:
            self._held = False
            self.session.apple._closed()
            self.session._release()


class FakeSession:
    """The part of aiohttp.ClientSession the API uses."""

    def __init__(self, apple: FakeApple, headers=None, connector: Optional[FakeConnector] = None):
        self.apple = apple
        kwargs = connector.kwargs if connector is not None else {}
        self._limit = kwargs.get("limit_per_host") or kwargs.get("limit") or 0
        self._slots: Optional[asyncio.Semaphore] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url: str, params: Optional[dict] = None, timeout=None, allow_redirects=True) -> _Request:
        return _Request(self, url, params)

    async def _acquire(self):
        if self._limit:
            if self._slots is None:
                self._slots = asyncio.Semaphore(self._limit)
            await self._slots.acquire()

    def _release(self):
        if self._slots is not None:
            self._slots.release()


def install(apple: FakeApple, patch=None) -> FakeApple:
    """
    Route the API's aiohttp sessions to `apple`. `patch(obj, name, value)` does
    the replacing; tests pass pytest's monkeypatch.setattr so it is undone after
    each test, a test server patches for the life of the process.
    """
    patch = patch or setattr
    patch(aiohttp, "ClientSession", lambda headers=None, connector=None: FakeSession(apple, headers, connector))
    patch(aiohttp, "TCPConnector", lambda **kwargs: FakeConnector(apple, **kwargs))
    return apple
