"""
Exchange rates: units of each currency per 1 US dollar, from open.er-api.com.

They are kept for config.RATES_TTL (30 minutes). If the service cannot be
reached, the last rates fetched are used; if there are none, prices are sent
as listed, without a dollar figure.
"""
import asyncio
import math
import time
from typing import Optional

import aiohttp

from . import config
from .countries import COUNTRIES

# Swapped in as a whole new dict, so readers on other threads need no lock.
_rates: dict[str, float] = {}
_fetched_at: float = 0.0


async def _download() -> dict[str, float]:
    """Fetch the rates (only when the ones held are stale)."""
    global _rates, _fetched_at
    async with aiohttp.ClientSession(headers=config.HEADERS) as session:
        try:
            async with session.get(config.EXCHANGE_API,
                                   timeout=aiohttp.ClientTimeout(total=config.RATES_TIMEOUT)) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    _rates = data.get("rates", {})
                    _fetched_at = time.monotonic()
        except Exception:
            pass  # fall through — returns stale or empty below
    return _rates or {}


def get_rates() -> dict[str, float]:
    """The current rates: the ones held while they are fresh, otherwise fetched again."""
    if _rates and (time.monotonic() - _fetched_at) < config.RATES_TTL:
        return _rates
    return asyncio.run(_download())


def clear() -> None:
    """Forget the rates held, so the next search fetches them again."""
    global _rates, _fetched_at
    _rates, _fetched_at = {}, 0.0


def status() -> dict:
    """For /api/cache/status."""
    now = time.monotonic()
    return {
        "cached":      bool(_rates),
        "age_seconds": round(now - _fetched_at) if _rates else None,
        "ttl_seconds": config.RATES_TTL,
        "expires_in":  max(0, round(config.RATES_TTL - (now - _fetched_at))) if _rates else None,
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
