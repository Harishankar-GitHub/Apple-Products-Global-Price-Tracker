"""
Apple Products Global Price Tracker — Flask API
Exposes a single endpoint: GET /api/prices?product=MacBook+Air
Returns JSON with prices from all Apple country storefronts.
"""

import re
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Optional
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # allow the GitHub Pages frontend to call this API

# ---------------------------------------------------------------------------
# Exchange rates
# ---------------------------------------------------------------------------
EXCHANGE_API = "https://open.er-api.com/v6/latest/USD"

def fetch_exchange_rates() -> dict[str, float]:
    try:
        r = requests.get(EXCHANGE_API, timeout=10)
        r.raise_for_status()
        return r.json().get("rates", {})
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Country storefronts
# ---------------------------------------------------------------------------
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Slug discovery
# ---------------------------------------------------------------------------

def name_to_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")

def infer_category(slug: str) -> str:
    s = slug.lower()
    if "iphone" in s:        return "iphone"
    if "ipad" in s:          return "ipad"
    if "macbook" in s:       return "mac"
    if "mac" in s:           return "mac"
    if "airpods" in s:       return "airpods"
    if "apple-watch" in s:   return "watch"
    if "watch" in s:         return "watch"
    if "apple-tv" in s:      return "appletv"
    if "homepod" in s:       return "homepod"
    if "airtag" in s:        return "airtag"
    return s.split("-")[0]

def probe(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code == 200:
            return r
    except Exception:
        pass
    return None

def discover_slug(product_name: str) -> Optional[tuple[str, str]]:
    candidate = name_to_slug(product_name)
    category  = infer_category(candidate)

    resp = probe(f"https://www.apple.com/{candidate}/")
    if resp and candidate in resp.url:
        return (candidate, category)

    try:
        r = requests.get(
            "https://www.apple.com/search-services/suggestions/",
            params={"q": product_name, "locale": "en_US", "client": "global-search"},
            headers=HEADERS, timeout=10
        )
        if r.status_code == 200:
            for s in r.json().get("suggestions", []):
                url_hint = s.get("url", "")
                if "apple.com" in url_hint:
                    path = url_hint.rstrip("/").split("apple.com/")[-1].strip("/")
                    slug = path.split("/")[0]
                    if slug and slug not in ("shop", "store", "search"):
                        return (slug, infer_category(slug))
    except Exception:
        pass

    words = candidate.split("-")
    variations = [
        "apple-" + candidate,
        "-".join(words[:3]),
        "-".join(words[:2]),
    ]
    for suffix in ["2", "3", "4", "10", "11"]:
        variations += [f"{candidate}-{suffix}", f"apple-{candidate}-{suffix}"]

    for var in dict.fromkeys(variations):
        if not var or var == candidate:
            continue
        resp = probe(f"https://www.apple.com/{var}/")
        if resp and var in resp.url:
            return (var, infer_category(var))

    return None

# ---------------------------------------------------------------------------
# Price extraction
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
    m = re.search(r'"lowPrice"\s*:\s*([\d.]+)', html)
    if m:
        val = float(m.group(1))
        if val >= min_price:
            return val
    m = re.search(r'"amount"\s*:\s*([\d.]+)', html)
    if m:
        val = float(m.group(1))
        if val >= min_price:
            return val
    return None

def build_shop_url(prefix: str, category: str, slug: str) -> str:
    base = f"https://www.apple.com/{prefix}/" if prefix else "https://www.apple.com/"
    return f"{base}shop/buy-{category}/{slug}"

def build_product_url(prefix: str, slug: str) -> str:
    if prefix:
        return f"https://www.apple.com/{prefix}/{slug}/"
    return f"https://www.apple.com/{slug}/"

def fetch_price(
    country: str,
    prefix: str,
    currency: str,
    symbol: str,
    slug: str,
    category: str,
    rates: dict[str, float],
) -> dict:
    min_price   = get_min_price(slug)
    shop        = build_shop_url(prefix, category, slug)
    prod        = build_product_url(prefix, slug)
    flag        = COUNTRY_FLAGS.get(country, "🏳")

    def _try(url: str) -> Optional[float]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return extract_low_price(r.text, min_price)
        except Exception:
            pass
        return None

    price_val = _try(shop) or _try(prod)

    if price_val is None:
        try:
            r = requests.get(prod, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code == 404:
                return {"country": country, "flag": flag, "available": False,
                        "reason": "Not available in this country", "url": prod}
        except Exception:
            pass
        return {"country": country, "flag": flag, "available": False,
                "reason": "Price not found", "url": prod}

    rate      = rates.get(currency, 0)
    usd_price = round(price_val / rate, 2) if rate else None
    price_str = (
        f"{symbol}{price_val:,.0f}" if price_val >= 1000
        else f"{symbol}{price_val:,.2f}"
    )

    return {
        "country":     country,
        "flag":        flag,
        "available":   True,
        "currency":    currency,
        "symbol":      symbol,
        "localPrice":  price_val,
        "localPriceFormatted": price_str,
        "usdPrice":    usd_price,
        "url":         prod,
    }

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/prices")
def get_prices():
    product = request.args.get("product", "").strip()
    if not product:
        return jsonify({"error": "Missing ?product= parameter"}), 400

    # Discover slug
    result = discover_slug(product)
    if not result:
        return jsonify({
            "error": f"Could not find '{product}' on apple.com. "
                     "Check the product name, e.g. 'MacBook Air', 'iPhone Air', 'AirPods Pro'."
        }), 404

    slug, category = result

    # Exchange rates
    rates = fetch_exchange_rates()

    # Parallel fetch
    workers = 15
    all_results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_price, country, prefix, currency, symbol, slug, category, rates
            ): country
            for country, (prefix, currency, symbol) in COUNTRIES.items()
        }
        for future in as_completed(futures):
            all_results.append(future.result())

    # Sort: available first (by USD price), then unavailable alphabetically
    available   = sorted(
        [r for r in all_results if r.get("available")],
        key=lambda r: r.get("usdPrice") or 999999
    )
    unavailable = sorted(
        [r for r in all_results if not r.get("available")],
        key=lambda r: r["country"]
    )

    return jsonify({
        "product":   product,
        "slug":      slug,
        "category":  category,
        "ratesDate": "live",
        "results":   available + unavailable,
    })

@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/")
def index():
    return "Apple Products Global Price Tracker API. Use /api/prices?product=MacBook+Air"

if __name__ == "__main__":
    app.run(debug=True, port=5000)
