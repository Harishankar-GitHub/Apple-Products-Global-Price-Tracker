"""Reading a store's price: the sanity floor, price extraction, what each store's answer means, and downloads."""
import json

import pytest

from fakes.apple import RATES, price_block, store_prefix
from support.client import cached_ttl
from tracker import config, prices, results_cache
from tracker.countries import COUNTRIES

SIX_HOURS, FIVE_MINUTES = 6 * 3600, 5 * 60


def instalment(amount: float) -> str:
    """A monthly-payment figure, which Apple shows as "amount"."""
    return f'<script>{{"financing":{{"monthly":{{"amount": {amount:.2f}}}}}}}</script>'


# ---------------------------------------------------------------------------
# The sanity floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("slug", "floor"),
    [("mac-pro", 5000), ("mac-studio", 1500), ("imac", 1000), ("macbook-air", 800), ("mac-mini", 400),
     ("iphone-17", 500), ("ipad-pro", 800), ("ipad", 250), ("apple-watch-ultra-4", 700), ("apple-watch-se-3", 200),
     ("airpods-max", 300), ("airpods-pro", 100), ("apple-tv-4k", 100), ("homepod-mini", 80), ("airtag", 20),
     ("apple-vision-pro", 50)],
)
def test_floor_in_dollars(slug, floor):
    assert prices.get_min_price(slug) == floor


@pytest.mark.parametrize(
    ("slug", "currency", "floor"),
    [
        ("iphone-17", "USD", 400),                       # the $500 family floor with 20% room under it
        ("iphone-17", "KWD", 500 * 0.31 * 0.8),          # about 124 KWD, not 500
        ("iphone-17", "INR", 33_600),
        ("iphone-17", "JPY", 60_000),
        ("iphone-17", "VND", 10_000_000),
        ("macbook-air", "GBP", 800 * 0.78 * 0.8),
    ],
)
def test_floor_in_the_store_currency(slug, currency, floor):
    assert prices.local_min_price(slug, currency, RATES) == pytest.approx(floor)


@pytest.mark.parametrize(
    ("currency", "rates"),
    [("XYZ", RATES), ("INR", {}), ("INR", {"INR": 0}), ("INR", {"INR": None}), ("INR", {"INR": -84}), ("INR", {"INR": "84"})],
    ids=["unknown-currency", "no-rates", "zero", "null", "negative", "text"],
)
def test_floor_without_a_usable_rate_stays_in_dollars(currency, rates):
    assert prices.local_min_price("iphone-17", currency, rates) == 500


def test_us_floor_needs_no_rate():
    assert prices.local_min_price("iphone-17", "USD", {}) == 400


# ---------------------------------------------------------------------------
# Picking the price out of a page
# ---------------------------------------------------------------------------

def accepted(html: str, slug: str, currency: str):
    return prices.extract_low_price(html, prices.local_min_price(slug, currency, RATES))


@pytest.mark.parametrize(
    ("slug", "currency", "price"),
    [("iphone-17", "KWD", 245), ("iphone-17", "BHD", 299), ("iphone-17", "OMR", 309), ("macbook-air", "KWD", 315),
     ("mac-mini", "KWD", 189), ("apple-watch-ultra-4", "KWD", 259), ("macbook-neo", "GBP", 699), ("ipad-pro", "CHF", 799),
     ("mac-mini", "GBP", 379)],
)
def test_real_price_in_a_strong_currency_is_accepted(slug, currency, price):
    assert accepted(price_block(price, currency), slug, currency) == price


@pytest.mark.parametrize(
    ("slug", "currency", "monthly"),
    [("iphone-17", "INR", 6908), ("iphone-17", "JPY", 4158), ("iphone-17", "KRW", 55_000), ("iphone-17", "VND", 1_041_000),
     ("macbook-air", "IDR", 1_500_000), ("ipad", "PHP", 1790), ("airpods-pro", "INR", 1075), ("mac-mini", "HUF", 19_990),
     ("apple-watch-se-3", "CLP", 2400)],
)
def test_monthly_instalment_is_not_taken_as_the_price(slug, currency, monthly):
    assert accepted(instalment(monthly), slug, currency) is None


@pytest.mark.parametrize(
    "html",
    [instalment(6908) + price_block(82_900), price_block(6908) + '<script>{"amount": 82900.00}</script>'],
    ids=["instalment-then-price", "instalment-under-lowPrice-then-price"],
)
def test_page_with_an_instalment_and_the_real_price(html):
    assert accepted(html, "iphone-17", "INR") == 82_900


US_PRICES = {"mac-pro": 6999, "mac-studio": 1999, "imac": 1299, "macbook-air": 999, "mac-mini": 599, "iphone-17": 799,
             "ipad-pro": 999, "ipad": 349, "apple-watch-ultra-4": 799, "apple-watch-se-3": 249, "airpods-max": 549,
             "airpods-pro": 249, "apple-tv-4k": 129, "homepod-mini": 99, "airtag": 29}


@pytest.mark.parametrize("country", sorted(COUNTRIES))
def test_every_store_accepts_real_prices_and_rejects_instalments(country):
    """Every product family, priced from 15% under the US price to double it; instalments over 12–36 months."""
    currency = COUNTRIES[country][1]
    rate = RATES[currency]
    digits = 3 if rate < 1 else 0
    for slug, usd in US_PRICES.items():
        for level in (0.85, 1.0, 1.3, 2.0):
            real = round(usd * level * rate, digits)
            assert accepted(price_block(real, currency, decimals=digits), slug, currency) == real, (slug, level)
            for months in (12, 24, 36):
                monthly = round(real / months, digits)
                assert accepted(f'<script>{{"amount": {monthly}}}</script>', slug, currency) is None, (slug, level, months)


def test_room_under_the_us_price_is_at_least_15_percent():
    for slug, usd in US_PRICES.items():
        assert accepted(price_block(round(usd * 0.85, 2)), slug, "USD") is not None, slug


# ---------------------------------------------------------------------------
# What each store's answer means
# ---------------------------------------------------------------------------

NOT_SOLD, NO_PRICE = "Not available in this country", "Price not found"


@pytest.mark.parametrize(
    ("setup", "country", "expected", "ttl"),
    [
        (lambda a: None, "Austria", NOT_SOLD, SIX_HOURS),                                          # both pages 404
        (lambda a: a.country_redirect.update({("de", "macbook-air"): "mac"}), "Germany", NOT_SOLD, SIX_HOURS),
        (lambda a: a.page_html.update({("de", "macbook-air"): "<html></html>"}), "Germany", NO_PRICE, SIX_HOURS),
        # (a store failing outright is covered, with the retry, in test_cache.py)
        (lambda a: a.url_failures.update({"apple.com/de/shop/": "timeout"}), "Germany", NO_PRICE, FIVE_MINUTES),
        (lambda a: a.url_failures.update({"apple.com/at/shop/": "timeout"}), "Austria", NOT_SOLD, SIX_HOURS),
        (lambda a: a.page_html.update({("de", "macbook-air"): instalment(90)}), "Germany", NO_PRICE, SIX_HOURS),
    ],
    ids=["not-sold-404", "redirected-to-line-up", "page-without-price",
         "buy-page-timeout-product-page-no-price", "buy-page-timeout-product-page-404", "instalment-only"],
)
def test_store_without_a_price(server, apple, setup, country, expected, ttl):
    setup(apple)
    result = server.search("MacBook Air")
    row = result.row(country)
    assert row == {"country": country, "flag": row["flag"], "available": False, "reason": expected, "url": row["url"]}
    assert cached_ttl("macbook-air") == ttl                 # a temporary failure is fetched again soon
    assert "99999" not in json.dumps(result.rows)           # a line-up page's price is never used


@pytest.mark.parametrize(
    ("setup", "price"),
    [
        (lambda a: (a.url_failures.update({"apple.com/de/shop/": 503}),
                    a.page_html.update({("de", "macbook-air"): price_block(1299)})), 1299),
        (lambda a: a.shop_long_url.add(("de", "macbook-air")), round(999 * 1.30 * 0.92)),
        (lambda a: a.page_html.update({("de", "macbook-air"): instalment(90) + price_block(1199)}), 1199),
    ],
    ids=["buy-page-fails-product-page-has-it", "buy-page-redirects-to-longer-url", "instalment-and-price"],
)
def test_store_priced_despite(server, apple, setup, price):
    setup(apple)
    result = server.search("MacBook Air")
    assert result.row("Germany")["available"] and result.row("Germany")["localPrice"] == price
    assert cached_ttl("macbook-air") == SIX_HOURS


def test_strong_currency_stores_are_priced(server, apple):
    apple.stores.update({"kw": ("KWD", 1.03), "bh": ("BHD", 1.05), "om": ("OMR", 1.05)})
    result = server.search("iPhone 17")
    kuwait = result.row("Kuwait")
    assert result.priced == 33
    assert all(result.row(c)["available"] for c in ("Bahrain", "Oman"))
    assert kuwait["localPrice"] == round(799 * 1.03 * 0.31) and kuwait["currency"] == "KWD"
    assert kuwait["usdPrice"] == pytest.approx(kuwait["localPrice"] / 0.31, abs=0.01)


def test_instalment_only_pages_never_become_the_cheapest(server, apple):
    for prefix, months in (("in", 12), ("jp", 24)):
        apple.page_html[(prefix, "iphone-17")] = instalment(apple.local_price(prefix, "iphone-17") / months)
    result = server.search("iPhone 17")
    assert not result.row("India")["available"] and not result.row("Japan")["available"]
    assert result.rows[0]["country"] == "Hong Kong" and result.rows[0]["usdPrice"] > 700
    assert result.priced == 28


@pytest.mark.parametrize(
    ("product", "us_price"),
    [("MacBook Air", 999), ("iPhone 17", 799), ("Mac mini", 599), ("iMac", 1299), ("iPad Pro", 999),
     ("Apple Watch Ultra 4", 799), ("iPhone 16", 729)],
)
def test_ordinary_search(server, product, us_price):
    result = server.search(product)
    assert result.priced == 30 and len(result.rows) == 50
    assert result.row("United States")["localPrice"] == us_price
    assert result.row("Ireland")["localPriceFormatted"].startswith("€")


def test_results_are_cheapest_first_then_unavailable_a_to_z(server):
    rows = server.search("MacBook Air").rows
    available = [r for r in rows if r["available"]]
    unavailable = [r["country"] for r in rows if not r["available"]]
    assert [r["usdPrice"] for r in available] == sorted(r["usdPrice"] for r in available)
    assert [r["country"] for r in available[:3]] == ["Japan", "Hong Kong", "United States"]
    assert rows[len(available):] and unavailable == sorted(unavailable)


# ---------------------------------------------------------------------------
# Downloads and connections
# ---------------------------------------------------------------------------

def price_downloads(server, apple, product: str) -> list[str]:
    server.search(product)                        # looks the name up (and fetches once)
    results_cache.clear()
    apple.calls.clear()
    server.search(product)
    return apple.apple_calls()


@pytest.mark.parametrize(
    ("product", "downloads"),
    [("MacBook Air", 30 * 1 + 20 * 2),           # price on the buy page in 30 stores; 20 do not sell it
     ("Apple Watch Ultra 4", 50 * 2),            # price only on the product page
     ("AirTag", 50 * 2)],                         # no price anywhere
)
def test_each_page_is_downloaded_at_most_once(server, apple, product, downloads):
    urls = price_downloads(server, apple, product)
    assert len(urls) == downloads
    assert len(set(urls)) == len(urls)


def test_store_with_a_price_on_the_buy_page_skips_the_product_page(server, apple):
    urls = price_downloads(server, apple, "MacBook Air")
    for prefix in apple.stores:                   # these stores show the price on the buy page
        assert [u for u in urls if store_prefix(u) == prefix] == [prices.build_shop_url(prefix, "mac", "macbook-air")]


@pytest.mark.parametrize("connections", [50, 10])
def test_stores_are_fetched_side_by_side_up_to_the_connection_limit(server, apple, monkeypatch, connections):
    monkeypatch.setattr(config, "APPLE_MAX_CONNECTIONS", connections)
    server.search("MacBook Air")
    results_cache.clear()
    apple.delay = lambda url: 0.05
    apple.peak_connections = 0
    server.search("MacBook Air", via="stream")
    assert apple.peak_connections == connections
