"""
Exchange rates: units of each currency per 1 US dollar, from open.er-api.com.

They are kept for config.RATES_TTL (30 minutes). After that, the next search
still uses the rates held, so it does not wait for the exchange-rate service,
and starts one download in the background; the searches after it get the new
rates. Only when no rates are held at all (the first search after the server
starts) does a search wait for them.

If the service cannot be reached, the last rates fetched are used; if there
are none, prices are sent as listed, without a dollar figure.
"""
import concurrent.futures
import math
import threading
import time
from typing import NamedTuple, Optional

import aiohttp

from . import config, web
from .countries import COUNTRIES


class _Held(NamedTuple):
    rates: dict[str, float]
    fetched_at: float               # time.monotonic() when they arrived


# Swapped in as a whole, so readers on other threads need no lock.
_held = _Held({}, 0.0)
_lock = threading.Lock()            # for starting a download, and for storing what it brings
_download: Optional[concurrent.futures.Future] = None   # the download running, if any
_generation = 0                     # moves on with clear(), so a download started before it is not stored


async def _fetch(generation: int) -> dict[str, float]:
    """Download the rates and hold them. Runs on the shared event loop; returns the rates held after it."""
    global _held
    try:
        async with web.session().get(config.EXCHANGE_API,
                                     timeout=aiohttp.ClientTimeout(total=config.RATES_TIMEOUT)) as r:
            if r.status == 200:
                rates = (await r.json(content_type=None)).get("rates")
                if isinstance(rates, dict) and rates:
                    with _lock:
                        if generation == _generation:
                            _held = _Held(rates, time.monotonic())
    except Exception:
        pass  # keep the rates held, if any
    return _held.rates


def refresh() -> concurrent.futures.Future:
    """
    Start downloading the rates, unless a download is already running, and
    return it. Its result is the rates held once it is over (the old ones if it
    failed, {} if there are none).
    """
    global _download
    with _lock:
        if _download is None or _download.done():
            _download = web.submit(_fetch(_generation))
        return _download


def get_rates() -> dict[str, float]:
    """
    The current rates. Rates held for longer than config.RATES_TTL are still
    returned, while new ones are fetched in the background; with no rates held
    at all, this waits for the download.
    """
    held = _held
    if held.rates and time.monotonic() - held.fetched_at < config.RATES_TTL:
        return held.rates
    download = refresh()
    if held.rates:
        return held.rates           # a little old: the searches after this one get the new rates
    return download.result()


def clear() -> None:
    """Forget the rates held, so the next search fetches them again (and waits for them)."""
    global _held, _download, _generation
    with _lock:
        _generation += 1
        _held = _Held({}, 0.0)
        _download = None


def status() -> dict:
    """For /api/cache/status."""
    held, now = _held, time.monotonic()
    return {
        "cached":      bool(held.rates),
        "age_seconds": round(now - held.fetched_at) if held.rates else None,
        "ttl_seconds": config.RATES_TTL,
        "expires_in":  max(0, round(config.RATES_TTL - (now - held.fetched_at))) if held.rates else None,
    }


def usd_rate(rates: dict[str, float], currency: str) -> Optional[float]:
    """
    Units of `currency` per 1 USD, or None when there is no usable rate: the
    currency is missing (the exchange-rate service is down or leaves it out) or
    the value is not a positive number. A price without a rate is sent as
    listed with usdPrice null, so it is never converted to $0.00 (or less) and
    ranked as the cheapest.
    """
    rate = (rates or {}).get(currency)
    if isinstance(rate, bool) or not isinstance(rate, (int, float)):
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    return float(rate)


def rates_for_client(rates: dict[str, float]) -> dict[str, float]:
    """Subset of exchange rates (units per 1 USD) for the currencies we list.
    Sent to the browser so it can show prices in the visitor's own currency."""
    wanted = {currency for (_prefix, currency, _symbol) in COUNTRIES.values()}
    return {c: rates[c] for c in sorted(wanted) if usd_rate(rates, c)}
