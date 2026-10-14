"""Connections to apple.com, shared by product look-ups (lookup.py) and price fetching (prices.py)."""
import aiohttp

from . import config


def make_connector() -> aiohttp.TCPConnector:
    """Connector that lets every store be fetched at once (see config.APPLE_MAX_CONNECTIONS)."""
    return aiohttp.TCPConnector(
        limit=config.APPLE_MAX_CONNECTIONS,           # total concurrent connections
        limit_per_host=config.APPLE_MAX_CONNECTIONS,  # all of them go to www.apple.com
        ttl_dns_cache=300,  # cache DNS for 5 min
        enable_cleanup_closed=True,
    )


def apple_session() -> aiohttp.ClientSession:
    """A session for requests to apple.com, sent with browser-like headers."""
    return aiohttp.ClientSession(headers=config.HEADERS, connector=make_connector())
