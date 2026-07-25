"""
Apple Products Global Price Tracker — Flask API
All outbound HTTP calls use aiohttp + asyncio so all 50 country requests
fire simultaneously in a single thread (no ThreadPoolExecutor).
"""

import re
import json
import time
import asyncio
import queue
import threading
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from flask import Flask, jsonify, request, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# In-memory caches
# ---------------------------------------------------------------------------

# Cache 1 — Exchange rates  (TTL: 30 min)
_rates_cache: dict[str, float] = {}
_rates_fetched_at: float = 0.0
RATES_TTL = 30 * 60

# Cache 2 — Slug resolution  (no TTL — valid for process lifetime)
_slug_cache: dict[str, Optional[tuple[str, str]]] = {}

# Cache 3 — Price results per slug  (TTL: 5 min)
_results_cache: dict[str, dict] = {}
RESULTS_TTL = 5 * 60

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

SLUG_OVERRIDES: dict[str, tuple[str, str]] = {
    "iphone 16 pro":       ("iphone-16-pro",      "iphone"),
    "iphone 16":           ("iphone-16",           "iphone"),
    "iphone 17":           ("iphone-17",           "iphone"),
    "apple watch ultra":   ("apple-watch-ultra-3", "watch"),
    "apple watch ultra 3": ("apple-watch-ultra-3", "watch"),
    "apple watch ultra 2": ("apple-watch-ultra-3", "watch"),
}


# ---------------------------------------------------------------------------
# Async HTTP helpers
# ---------------------------------------------------------------------------

def _make_connector() -> aiohttp.TCPConnector:
    """Shared connector with a generous limit — all 50 requests fire at once."""
    return aiohttp.TCPConnector(
        limit=100,          # total concurrent connections
        limit_per_host=10,  # per apple.com host (avoids triggering rate limits)
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


async def _async_probe(session: aiohttp.ClientSession, url: str) -> bool:
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
    except Exception:
        pass
    return False


async def _async_resolve_slug(product_name: str) -> Optional[tuple[str, str]]:
    """All apple.com probing runs concurrently inside one aiohttp session."""
    override_key = product_name.strip().lower()
    if override_key in SLUG_OVERRIDES:
        return SLUG_OVERRIDES[override_key]

    candidate = name_to_slug(product_name)
    category  = infer_category(candidate)

    async with aiohttp.ClientSession(headers=HEADERS,
                                     connector=_make_connector()) as session:
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
                                    if await _async_probe(session, f"https://www.apple.com/{slug}/"):
                                        return (slug, infer_category(slug))
            except Exception:
                pass
            return None

        direct_ok, suggestion_result = await asyncio.gather(
            _async_probe(session, f"https://www.apple.com/{candidate}/"),
            suggestions(),
        )

        if direct_ok:
            return (candidate, category)
        if suggestion_result:
            return suggestion_result

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
            _async_probe(session, f"https://www.apple.com/{v}/")
            for v in variations
        ]
        results = await asyncio.gather(*probe_tasks)
        for var, ok in zip(variations, results):
            if ok:
                return (var, infer_category(var))

    return None


def discover_slug(product_name: str) -> Optional[tuple[str, str]]:
    """Sync entry point — Cache 2 wraps the async resolver."""
    cache_key = product_name.strip().lower()
    if cache_key in _slug_cache:
        return _slug_cache[cache_key]               # Cache 2 hit
    result = asyncio.run(_async_resolve_slug(product_name))
    _slug_cache[cache_key] = result                 # store even if None
    return result


# ---------------------------------------------------------------------------
# Price extraction helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def get_min_price(slug: str) -> float:
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


def extract_low_price(html: str, min_price: float) -> Optional[float]:
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
    min_price = get_min_price(slug)
    shop_url  = build_shop_url(prefix, category, slug)
    prod_url  = build_product_url(prefix, slug)
    flag      = COUNTRY_FLAGS.get(country, "🏳")
    timeout   = aiohttp.ClientTimeout(total=20)

    async def _try(url: str) -> Optional[float]:
        try:
            async with session.get(url, timeout=timeout, allow_redirects=True) as r:
                if r.status == 200:
                    html = await r.text()
                    return extract_low_price(html, min_price)
        except Exception:
            pass
        return None

    # Try shop URL first; fall back to product URL.
    # Both run concurrently — whichever has price data wins.
    shop_price, prod_price = await asyncio.gather(_try(shop_url), _try(prod_url))
    price_val = shop_price or prod_price

    if price_val is None:
        # One more attempt to distinguish "404 not in this country" vs "page exists but no price"
        try:
            async with session.get(prod_url, timeout=aiohttp.ClientTimeout(total=10),
                                   allow_redirects=True) as r:
                if r.status == 404:
                    return {"country": country, "flag": flag, "available": False,
                            "reason": "Not available in this country", "url": prod_url}
        except Exception:
            pass
        return {"country": country, "flag": flag, "available": False,
                "reason": "Price not found", "url": prod_url}

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


def _stream_prices_into_queue(
    slug: str, category: str, rates: dict[str, float], q: queue.Queue
) -> None:
    """
    Runs in a background thread with its own event loop.
    Puts each row into `q` as soon as its coroutine completes,
    then puts _SENTINEL to signal the end.
    """
    async def _run():
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
                q.put(row)
        q.put(_SENTINEL)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/prices")
def get_prices():
    product = request.args.get("product", "").strip()
    if not product:
        return jsonify({"error": "Missing ?product= parameter"}), 400

    result = discover_slug(product)
    if not result:
        return jsonify({
            "error": f"Could not find '{product}' on apple.com. "
                     "Check the product name, e.g. 'MacBook Air', 'iPhone Air', 'AirPods Pro'."
        }), 404

    slug, category = result

    cached = _results_cache.get(slug)
    if cached and (time.monotonic() - cached["ts"]) < RESULTS_TTL:
        return jsonify(cached["payload"])            # Cache 3 hit

    rates      = fetch_exchange_rates()              # Cache 1
    all_rows   = asyncio.run(_fetch_all_prices(slug, category, rates))

    available   = sorted([r for r in all_rows if     r.get("available")],
                         key=lambda r: r.get("usdPrice") or 999999)
    unavailable = sorted([r for r in all_rows if not r.get("available")],
                         key=lambda r: r["country"])

    payload = {"product": product, "slug": slug, "category": category,
               "ratesDate": "live", "results": available + unavailable}
    _results_cache[slug] = {"ts": time.monotonic(), "payload": payload}
    return jsonify(payload)


@app.route("/api/prices/stream")
def get_prices_stream():
    """SSE endpoint — results stream back as each country completes."""
    product = request.args.get("product", "").strip()
    if not product:
        def _err():
            yield f"event: error\ndata: {json.dumps({'error': 'Missing ?product= parameter'})}\n\n"
        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    def generate():
        # Tell the UI we're working before the (potentially slow) slug resolution
        yield f"event: searching\ndata: {json.dumps({'product': product})}\n\n"

        result = discover_slug(product)             # Cache 2 — instant on repeat
        if not result:
            msg = (f"Could not find \"{product}\" on apple.com. "
                   "Try a different name, e.g. \"MacBook Air\", \"iPhone Air\", \"AirPods Pro\".")
            yield f"event: error\ndata: {json.dumps({'error': msg})}\n\n"
            return

        slug, category = result

        # Cache 3 hit — replay stored rows as fast SSE events
        cached = _results_cache.get(slug)
        if cached and (time.monotonic() - cached["ts"]) < RESULTS_TTL:
            total = len(cached["payload"]["results"])
            yield f"event: meta\ndata: {json.dumps({'product': product, 'slug': slug, 'category': category, 'total': total, 'cached': True})}\n\n"
            for row in cached["payload"]["results"]:
                yield f"event: result\ndata: {json.dumps(row)}\n\n"
            yield f"event: done\ndata: {json.dumps({'product': product, 'cached': True})}\n\n"
            return

        yield f"event: meta\ndata: {json.dumps({'product': product, 'slug': slug, 'category': category, 'total': len(COUNTRIES)})}\n\n"

        rates    = fetch_exchange_rates()            # Cache 1

        # ── Queue bridge ─────────────────────────────────────────────────────
        # A background thread runs the asyncio event loop and puts each row
        # into `q` as soon as its coroutine resolves.  This generator pulls
        # from `q` immediately — Flask flushes each SSE event to the client
        # without waiting for all 50 countries to finish.
        q        = queue.Queue()
        all_rows = []

        t = threading.Thread(
            target=_stream_prices_into_queue,
            args=(slug, category, rates, q),
            daemon=True,
        )
        t.start()

        while True:
            row = q.get()           # blocks only until the next country finishes
            if row is _SENTINEL:
                break
            all_rows.append(row)
            yield f"event: result\ndata: {json.dumps(row)}\n\n"

        t.join()

        # Store in Cache 3
        available   = sorted([r for r in all_rows if     r.get("available")],
                             key=lambda r: r.get("usdPrice") or 999999)
        unavailable = sorted([r for r in all_rows if not r.get("available")],
                             key=lambda r: r["country"])
        payload = {"product": product, "slug": slug, "category": category,
                   "ratesDate": "live", "results": available + unavailable}
        _results_cache[slug] = {"ts": time.monotonic(), "payload": payload}

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
    now = time.monotonic()
    return jsonify({
        "exchange_rates": {
            "cached":      bool(_rates_cache),
            "age_seconds": round(now - _rates_fetched_at) if _rates_cache else None,
            "ttl_seconds": RATES_TTL,
            "expires_in":  max(0, round(RATES_TTL - (now - _rates_fetched_at))) if _rates_cache else None,
        },
        "slug_cache": {
            "entries": len(_slug_cache),
            "keys":    list(_slug_cache.keys()),
        },
        "results_cache": {
            "entries": len(_results_cache),
            "slugs": {
                slug: {
                    "age_seconds": round(now - v["ts"]),
                    "expires_in":  max(0, round(RESULTS_TTL - (now - v["ts"]))),
                }
                for slug, v in _results_cache.items()
            },
        },
    })


@app.route("/")
def index():
    return "Apple Products Global Price Tracker API — /api/prices?product=MacBook+Air"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
