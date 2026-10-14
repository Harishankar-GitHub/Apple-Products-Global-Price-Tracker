"""
Settings, in one place: everything read from the environment, how long apple.com
is given to answer, and how long answers are kept.

Other modules read these as `config.NAME` when they use them (never with
`from .config import NAME`), so a test can change one with
monkeypatch.setattr(config, "NAME", value).
"""
import os


def env_int(name: str, default: int) -> int:
    """A whole number from the environment; negative means 0 (off), anything unreadable means `default`."""
    try:
        return max(0, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Abuse protection (see limits.py)
# ---------------------------------------------------------------------------

MAX_PRODUCT_LENGTH = 80           # characters accepted in ?product=

# Each limit can be changed, or switched off with 0.
RATE_REQUESTS_PER_MIN         = env_int("RATE_LIMIT_REQUESTS_PER_MIN", 60)
RATE_FETCHES_PER_10MIN        = env_int("RATE_LIMIT_FETCHES_PER_10MIN", 20)
RATE_GLOBAL_FETCHES_PER_10MIN = env_int("RATE_LIMIT_GLOBAL_FETCHES_PER_10MIN", 60)

# Secret that unlocks the detailed view of /api/cache/status (search terms and
# product slugs). Unset → the detailed view is never available.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

# What the API writes to its log (standard error, which Render shows under
# Logs): DEBUG, INFO (the default: a line per look-up and per fetch), WARNING
# (only problems) or ERROR. Visitors' addresses are never written to it.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
if LOG_LEVEL not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
    LOG_LEVEL = "INFO"

# ---------------------------------------------------------------------------
# Talking to apple.com
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Requests one search has open to apple.com at the same time, which decides
# how many stores it actually fetches at once: 50 gives each of the 50 stores
# its own connection. It was 10, which made a search queue through five
# rounds. Lower it with the APPLE_MAX_CONNECTIONS environment variable if
# Apple starts refusing requests. (The connections themselves are pooled and
# shared by every search, see web.py.)
APPLE_MAX_CONNECTIONS = max(1, env_int("APPLE_MAX_CONNECTIONS", 50))

# Searches that fetch from apple.com at the same time. Visitors are served in
# parallel, but each such search has up to APPLE_MAX_CONNECTIONS requests open
# and holds those pages in memory, so a burst of visitors searching for new
# products is let through a couple at a time instead of multiplying both.
# Cached results, health checks and everything else are not limited by this.
# A search waits up to FETCH_SLOT_WAIT seconds for a free slot, then is told to
# try again.
MAX_PARALLEL_FETCHES = max(1, env_int("MAX_PARALLEL_FETCHES", 2))
FETCH_SLOT_WAIT   = 45        # seconds a search may wait for a slot
FETCH_SLOT_NOTICE = 5         # while a stream waits, it sends a line this often (seconds)

# Seconds apple.com is given to answer.
PAGE_TIMEOUT        = 20      # one store's buy page or product page, while fetching prices
CHECK_TIMEOUT       = 12      # one page check, while looking a product up
SUGGESTIONS_TIMEOUT = 10      # Apple's search suggestions, while looking a product up

# Stores sometimes price a product below the US price once converted, so the
# price floor (see prices.py) is applied with some room under it. Instalments
# are a twelfth of the price or less, far below this.
PRICE_FLOOR_SLACK = 0.8

# ---------------------------------------------------------------------------
# Exchange rates (see exchange.py)
# ---------------------------------------------------------------------------

EXCHANGE_API  = "https://open.er-api.com/v6/latest/USD"
RATES_TIMEOUT = 10            # seconds the exchange-rate service is given to answer
RATES_TTL     = 30 * 60       # rates are fetched again after 30 minutes

# ---------------------------------------------------------------------------
# How long answers are kept
# ---------------------------------------------------------------------------

# Product name → Apple's page for it (see lookup.py). Keyed by whatever was
# typed, so it is capped: the oldest names are dropped beyond SLUG_CACHE_MAX.
# A name found with every check answered is kept for the life of the process.
SLUG_CACHE_MAX     = 500
SLUG_TTL_NOT_FOUND = 60 * 60      # not found, every check answered: Apple adds products (1 hour)
SLUG_TTL_UNSURE    = 5 * 60       # a fallback page found while a check failed (5 minutes)
SLUG_TTL_FAILED    = 60           # Apple did not answer: only long enough to stop retry storms

# Prices per product (see results_cache.py). Apple changes prices rarely, so a
# complete result set is kept for hours. A set where any country failed to load
# (timeout, rate limit, server error, no exchange rate), or where no country
# returned a price, is kept only briefly so that a bad fetch is retried soon.
RESULTS_TTL       = 6 * 60 * 60   # complete result set  (6 hours)
RESULTS_TTL_SHORT = 5 * 60        # incomplete result set (5 minutes)
RESULTS_CACHE_MAX = 200           # most result sets held at once; oldest dropped first
