"""The shared event loop and connections (api/tracker/web.py)."""
import asyncio
import threading
import time

import aiohttp
import pytest

from tracker import config, lookup, results_cache, search, web


def test_one_connection_pool_for_every_search(server, apple, via):
    """Look-ups, exchange rates and fetches, for different products and visitors, all share one pool."""
    for product, ip in (("MacBook Air", "1.1.1.1"), ("iPhone 17", "2.2.2.2"), ("prod3", "1.1.1.1")):
        result = server.search(product, via=via, ip=ip)
        assert result.priced == 30 and not result.cached
    assert apple.calls[0].startswith("https://www.apple.com/")       # a look-up, a rate fetch and 3 price fetches…
    assert any("er-api.com" in u for u in apple.calls)
    assert len(apple.sessions) == len(apple.connectors) == 1         # …over one session and pool, opened once


def test_a_search_starts_no_thread(server, apple):
    server.search("MacBook Air")                                     # the loop has started
    threads = threading.active_count()
    apple.delay = lambda url: 0.2
    streaming = []
    reader = threading.Thread(target=lambda: streaming.append(server.search("prod5", via="stream")), daemon=True)
    reader.start()
    time.sleep(0.3)                                                  # mid-fetch
    assert threading.active_count() == threads + 1                   # the reader itself, nothing else
    reader.join(10)
    assert streaming[0].priced == 30


def test_each_fetch_keeps_its_own_connection_limit(server, apple, monkeypatch):
    """Two fetches at once share the pool, but each still keeps to APPLE_MAX_CONNECTIONS requests."""
    monkeypatch.setattr(config, "APPLE_MAX_CONNECTIONS", 10)
    for name in ("prod6", "prod7"):
        lookup.discover_slug(name)
    apple.delay = lambda url: 0.05
    apple.peak_connections = 0
    searches = [threading.Thread(target=server.search, args=(name,), daemon=True) for name in ("prod6", "prod7")]
    for s in searches:
        s.start()
    for s in searches:
        s.join(30)
    assert apple.peak_connections == 20
    assert {"prod6", "prod7"} <= set(results_cache._entries)


def test_waiting_on_the_loop_from_the_loop_is_refused():
    """It could only wait for itself forever, so it fails at once instead."""
    async def nested():
        return web.run(asyncio.sleep(0))

    with pytest.raises(RuntimeError, match="own thread"):
        within(5, web.run, nested())


def test_the_loop_starts_again_if_it_ever_stops(server, apple):
    """The next request replaces a loop that stopped; a fetch left on it ends with "try again"."""
    server.search("MacBook Air")
    lookup.discover_slug("prod8")
    apple.delay = lambda url: 1
    interrupted = []
    reader = threading.Thread(target=lambda: interrupted.append(server.stream("prod8")), daemon=True)
    reader.start()
    assert wait_until(lambda: apple.apple_calls("/prod8"))           # prod8 is being fetched…
    old_loop, old_thread = web._loop, web._thread
    old_loop.call_soon_threadsafe(old_loop.stop)                     # …when the loop stops
    old_thread.join(5)

    apple.delay = lambda url: 0
    assert within(10, server.search, "iPhone 17").priced == 30      # the next search starts a new loop
    reader.join(5)
    assert [e.name for e in interrupted[0]][-1] == "error"
    assert interrupted[0][-1].data == search.fetch_failed_payload()
    assert search.fetch_slots._value == config.MAX_PARALLEL_FETCHES   # its slot was given back
    assert old_loop.is_closed() and web._thread.is_alive()
    assert len(apple.connectors) == 2                                # a new pool on the new loop


def test_work_handed_over_as_the_loop_stops_is_not_lost():
    """Handed to a loop that stopped before it began: cancelled when the loop is tidied up, not dropped."""
    loop = asyncio.new_event_loop()                                  # not running, like a stopped loop
    ran, ended = [], []

    async def work():
        ran.append(True)

    handle = asyncio.run_coroutine_threadsafe(work(), loop)
    handle.add_done_callback(ended.append)
    web._close_stopped_loop(loop, None)
    assert loop.is_closed() and ended == [handle] and handle.done()  # it ended, so whoever waits is told


def within(seconds: float, fn, *args):
    """fn(*args), failing the test if it has not returned after `seconds` (instead of hanging the run)."""
    box: dict = {}

    def call():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:                                 # noqa: BLE001 - raised below
            box["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"still waiting after {seconds} s"
    if "error" in box:
        raise box["error"]
    return box["value"]


def wait_until(condition, timeout: float = 10) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


# aiohttp says enable_cleanup_closed is unnecessary on Python versions that fixed the
# underlying bug (3.12.7+, 3.13.1+); Render runs 3.11, where it still matters.
@pytest.mark.filterwarnings("ignore:enable_cleanup_closed ignored:DeprecationWarning")
def test_the_real_aiohttp_accepts_the_shared_session(monkeypatch):
    """Opened on the loop by the real aiohttp, with browser headers, and closed cleanly (no unclosed warning)."""
    monkeypatch.setattr(aiohttp, "ClientSession", aiohttp.client.ClientSession)
    monkeypatch.setattr(aiohttp, "TCPConnector", aiohttp.connector.TCPConnector)

    async def inspect():
        session = web.session()
        connector = session.connector
        return (session is web.session(), type(session).__module__, connector.limit, connector.limit_per_host,
                connector.use_dns_cache, session.headers["User-Agent"])

    same, module, limit, per_host, dns_cache, agent = web.run(inspect())
    assert same and module == "aiohttp.client"
    assert (limit, per_host, dns_cache) == (0, 0, True)               # each fetch sets its own limit
    assert agent.startswith("Mozilla/5.0")
    web.reset()
