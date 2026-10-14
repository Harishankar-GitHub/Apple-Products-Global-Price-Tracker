"""
One event loop and one connection pool for everything that talks to apple.com
and to the exchange-rate service.

Requests are served by ordinary threads (gunicorn's gthread worker), while the
network code is asyncio. Rather than each look-up and each fetch creating its
own event loop and its own connections, all of it runs on one event loop in a
background thread and shares one aiohttp session. Connections to
www.apple.com, with their TLS sessions and DNS answers, are then reused from a
look-up to the fetch that follows it, and from one search to the next.

  run(coro)     run a coroutine on the loop and wait for its result
                (from a request thread, never from the loop itself)
  submit(coro)  start a coroutine on the loop and carry on
  session()     the shared session, for code running on the loop
  describe(exc) a request's failure in a few words, for the log

The loop starts the first time it is needed, so in gunicorn it starts inside
the worker process, never in the master before the fork.
"""
import asyncio
import atexit
import concurrent.futures
import contextlib
import threading
from typing import Any, Coroutine, Optional, TypeVar

import aiohttp

from . import config

T = TypeVar("T")

_lock = threading.Lock()
_loop: Optional[asyncio.AbstractEventLoop] = None
_thread: Optional[threading.Thread] = None
_session: Optional[aiohttp.ClientSession] = None      # used only on the loop's thread


def make_connector() -> aiohttp.TCPConnector:
    """
    The shared connection pool. It sets no limit of its own: a fetch keeps
    itself to config.APPLE_MAX_CONNECTIONS requests at a time (see prices.py),
    at most config.MAX_PARALLEL_FETCHES fetches run at once, and a look-up
    makes about a dozen requests.
    """
    return aiohttp.TCPConnector(
        limit=0,                    # no overall limit (see above)
        ttl_dns_cache=300,          # cache DNS for 5 min
        enable_cleanup_closed=True,
    )


def session() -> aiohttp.ClientSession:
    """The shared session, opened on first use. Call it from code running on the loop."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(headers=config.HEADERS, connector=make_connector())
    return _session


def describe(exc: BaseException) -> str:
    """A failed request in a few words, for the log: "timeout", "ClientConnectorError", ..."""
    return "timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__


def _event_loop() -> asyncio.AbstractEventLoop:
    """The shared loop, started on first use (and started again should its thread ever stop)."""
    global _loop, _thread, _session
    with _lock:
        if _thread is None or not _thread.is_alive():
            if _loop is not None and not _loop.is_closed():
                with contextlib.suppress(Exception):     # a new loop starts whatever happens here
                    _close_stopped_loop(_loop, _session)
            _session = None                 # a session belongs to the loop that opened it
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, name="apple-web", daemon=True)
            _thread.start()
        return _loop


def _close_stopped_loop(loop: asyncio.AbstractEventLoop, stale: Optional[aiohttp.ClientSession]) -> None:
    """
    Tidy up after a loop whose thread has stopped. Its unfinished work is
    cancelled, so no search waits for it forever (a fetch that is cancelled
    still gives its slot back and ends with "try again"), then its session
    and the loop itself are closed.
    """
    try:
        loop.run_until_complete(asyncio.sleep(0))   # work handed over just before it stopped becomes tasks…
        unfinished = asyncio.all_tasks(loop)        # …so it is cancelled too, rather than lost
        if unfinished:
            for task in unfinished:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*unfinished, return_exceptions=True))
        if stale is not None:
            loop.run_until_complete(stale.close())
    finally:
        loop.close()


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run `coro` on the shared loop and wait for its result."""
    if threading.current_thread() is _thread:
        coro.close()
        raise RuntimeError("web.run() called on the event loop's own thread: it would wait for itself forever")
    return asyncio.run_coroutine_threadsafe(coro, _event_loop()).result()


def submit(coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
    """Start `coro` on the shared loop without waiting for it."""
    return asyncio.run_coroutine_threadsafe(coro, _event_loop())


async def _close_session() -> None:
    global _session
    if _session is not None:
        closing, _session = _session, None
        await closing.close()


def reset() -> None:
    """Close the shared session; the next request opens a new one. Tests use this between tests."""
    if _thread is not None and _thread.is_alive():
        asyncio.run_coroutine_threadsafe(_close_session(), _loop).result(timeout=5)


@atexit.register
def _shut_down() -> None:
    """Close the connections when the process exits, so nothing is left half open."""
    if _thread is not None and _thread.is_alive():
        with contextlib.suppress(Exception):            # exiting anyway
            asyncio.run_coroutine_threadsafe(_close_session(), _loop).result(timeout=5)
        _loop.call_soon_threadsafe(_loop.stop)
