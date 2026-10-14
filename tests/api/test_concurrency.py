"""
Serving visitors side by side: fetch slots, waiting, the busy reply, closed pages,
fetches that break off, and the caches under many threads.
"""
import sys
import threading
import time
from contextlib import contextmanager

import pytest
from werkzeug.test import EnvironBuilder

from app import app as flask_app
from support.client import Event, cached_ttl, parse_sse
from tracker import config, exchange, lookup, results_cache, search, web


class Connection:
    """One browser connection to the stream: read it event by event, or close it as a closed page would."""

    def __init__(self, product: str):
        environ = EnvironBuilder(path="/api/prices/stream", query_string={"product": product}).get_environ()
        self._body = flask_app(environ, lambda status, headers, exc_info=None: None)
        self._chunks = iter(self._body)
        self._buffer = ""
        self.events: list[Event] = []
        self.keepalives = 0

    def next_event(self):
        while "\n\n" not in self._buffer:
            chunk = next(self._chunks, None)
            if chunk is None:
                return None
            self._buffer += chunk.decode()
        block, self._buffer = self._buffer.split("\n\n", 1)
        if block.startswith(":"):
            self.keepalives += 1
            return self.next_event()
        event = parse_sse(block)[0]
        self.events.append(event)
        return event

    def read_until(self, name: str):
        while (event := self.next_event()) is not None:
            if event.name == name:
                return event
        return None

    def read_all(self) -> list[Event]:
        while self.next_event() is not None:
            pass
        return self.events

    def close(self):
        self._body.close()

    @property
    def names(self) -> list[str]:
        return [e.name for e in self.events]


def in_background(fn, *args) -> dict:
    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:          # noqa: BLE001 - reported by the test
            box["error"] = exc

    box["thread"] = threading.Thread(target=run, daemon=True)
    box["thread"].start()
    return box


def free_slots() -> int:
    return search.fetch_slots._value


def wait_until(condition, timeout: float = 10) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


@contextmanager
def all_slots_taken():
    """As if other visitors' fetches were running: every slot is taken until released (or the block ends)."""
    for _ in range(config.MAX_PARALLEL_FETCHES):
        assert search.fetch_slots.acquire(blocking=False)
    try:
        yield
    finally:
        while free_slots() < config.MAX_PARALLEL_FETCHES:
            search.fetch_slots.release()


def known(name: str) -> str:
    """Resolve a product name in advance, so the search under test only has prices to fetch."""
    return lookup.discover_slug(name).result[0]


@pytest.fixture
def short_waits(monkeypatch):
    monkeypatch.setattr(config, "FETCH_SLOT_WAIT", 1.5)
    monkeypatch.setattr(config, "FETCH_SLOT_NOTICE", 0.3)


# ---------------------------------------------------------------------------
# Fetch slots
# ---------------------------------------------------------------------------

def test_searches_run_side_by_side_two_fetches_at_a_time(server, apple, monkeypatch):
    names = [f"prod{i}" for i in range(1, 7)]
    expected = {}
    for name in names:
        expected[name] = sorted(server.search(name).rows, key=lambda r: r["country"])
    results_cache.clear()

    running, peak, lock = [0], [0], threading.Lock()
    real_fetch = search._fetch_every_store

    def counted(*args, **kwargs):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        try:
            return real_fetch(*args, **kwargs)
        finally:
            with lock:
                running[0] -= 1

    monkeypatch.setattr(search, "_fetch_every_store", counted)
    apple.delay = lambda url: 0.1
    searches = [in_background(server.search, name, "stream") for name in names]
    for s in searches:
        s["thread"].join(60)
    results = [s["value"] for s in searches]

    assert all(r.events[-1].name == "done" and len(r.rows) == 50 for r in results)
    assert peak[0] == config.MAX_PARALLEL_FETCHES == 2
    assert sum("queued" in [e.name for e in r.events] for r in results) >= 3
    for name, result in zip(names, results):
        assert sorted(result.rows, key=lambda r: r["country"]) == expected[name]
    assert free_slots() == 2


def test_cached_results_and_health_do_not_wait_for_a_slot(server, client, short_waits):
    server.search("MacBook Air")
    with all_slots_taken():
        started = time.monotonic()
        assert server.search("MacBook Air", via="stream").cached
        assert server.search("MacBook Air").cached
        assert client.get("/api/health").status_code == 200
        assert time.monotonic() - started < 1                         # well under the 1.5 s wait


def test_busy_reply_in_the_stream(short_waits):
    known("prod7")
    with all_slots_taken():
        started = time.monotonic()
        connection = Connection("prod7")
        events = connection.read_all()
        waited = time.monotonic() - started
        assert free_slots() == 0                                      # the 'running' fetches keep theirs
    assert [e.name for e in events] == ["searching", "queued", "error"]
    assert events[1].data == {"message": "Waiting for other searches to finish", "maxWaitSeconds": 1.5}
    assert 3 <= connection.keepalives <= 6                            # a line every FETCH_SLOT_NOTICE seconds
    assert 1.4 < waited < 2.5
    assert events[2].data == search.busy_payload()
    assert events[2].data["temporary"] is True and events[2].data["retryAfterSeconds"] == 10
    assert "prod7" not in results_cache._entries


def test_busy_reply_from_the_json_endpoint(server, short_waits):
    known("prod7")
    with all_slots_taken():
        resp = server.get("prod7")
        assert free_slots() == 0
    assert resp.status_code == 503 and resp.headers["Retry-After"] == "10"
    assert resp.get_json() == search.busy_payload()


def test_waiting_search_starts_as_soon_as_a_slot_is_free():
    known("prod8")
    with all_slots_taken():
        connection = Connection("prod8")
        connection.read_until("queued")
        reader = in_background(connection.read_all)
        time.sleep(0.4)
        assert connection.names == ["searching", "queued"]
        search.fetch_slots.release()
        reader["thread"].join(10)
    assert connection.names[2] == "meta" and connection.names[-1] == "done" and connection.names.count("result") == 50


def test_waiting_search_gets_the_results_of_the_one_ahead_of_it(server, apple, via):
    server.get("prod9")
    stored = results_cache._entries.pop("prod9")
    with all_slots_taken():
        if via == "stream":
            connection = Connection("prod9")
            connection.read_until("queued")
            waiting = in_background(connection.read_all)
        else:
            waiting = in_background(server.get, "prod9")
            time.sleep(0.3)
        results_cache._entries["prod9"] = {**stored, "ts": time.monotonic()}   # the search ahead of it finished
        calls = len(apple.calls)
        search.fetch_slots.release()
        waiting["thread"].join(10)
        assert free_slots() == 1                                         # the slot it took was handed back
    if via == "stream":
        meta = next(e.data for e in connection.events if e.name == "meta")
        assert meta["cached"] is True and connection.names.count("result") == 50
    else:
        assert waiting["value"].get_json()["cached"] is True
    assert len(apple.calls) == calls                                     # not fetched a second time


def test_slot_is_handed_on_only_once_the_results_are_cached(server, apple, monkeypatch, via):
    """The search waiting for the slot finds the finished fetch in the cache, even if storing it is slow."""
    known("prod14")
    apple.delay = lambda url: 0.1
    store = results_cache.build_payload

    def slow_store(*args):
        time.sleep(0.3)
        return store(*args)

    monkeypatch.setattr(results_cache, "build_payload", slow_store)
    with all_slots_taken():
        search.fetch_slots.release()                                     # one slot left
        first = in_background(server.search, "prod14", via)
        assert wait_until(lambda: free_slots() == 0)                     # the first search has it
        second = in_background(server.search, "prod14", via)
        for s in (first, second):
            s["thread"].join(10)
    assert first["value"].priced == 30 and not first["value"].cached
    assert second["value"].priced == 30 and second["value"].cached      # not fetched a second time


# ---------------------------------------------------------------------------
# Closed pages and failures
# ---------------------------------------------------------------------------

def test_closed_page_does_not_waste_the_fetch(server, apple):
    known("prod10")
    apple.delay = lambda url: 0.15
    connection = Connection("prod10")
    connection.read_until("meta")
    connection.read_until("result")
    connection.close()
    assert free_slots() == 1                                            # its fetch is still running
    assert wait_until(lambda: free_slots() == 2)
    assert len(results_cache._entries["prod10"]["payload"]["results"]) == 50 and cached_ttl("prod10") == 6 * 3600
    assert server.search("prod10", via="stream").cached


def test_closed_page_stops_waiting_without_taking_a_slot(apple):
    known("prod11")
    with all_slots_taken():
        connection = Connection("prod11")
        connection.read_until("queued")
        connection.close()
        calls = len(apple.calls)
    time.sleep(0.5)
    assert free_slots() == 2
    assert len(apple.calls) == calls and "prod11" not in results_cache._entries


def test_fetch_that_breaks_off_ends_with_try_again(server, monkeypatch, via):
    known("prod12")

    def broken():
        raise RuntimeError("simulated failure inside the fetch")

    monkeypatch.setattr(web, "make_connector", broken)
    monkeypatch.setattr(threading, "excepthook", lambda args: None)     # the thread's traceback is expected
    if via == "stream":
        events = server.stream("prod12")
        assert [e.name for e in events] == ["searching", "meta", "error"]
        assert events[-1].data == search.fetch_failed_payload()
    else:
        resp = server.get("prod12")
        assert resp.status_code == 503 and resp.headers["Retry-After"] == "10"
        assert resp.get_json() == search.fetch_failed_payload()
    assert "prod12" not in results_cache._entries and free_slots() == 2


def test_failure_before_the_fetch_starts_gives_the_slot_back(server, monkeypatch, via):
    known("prod13")

    def broken():
        raise RuntimeError("simulated failure before the fetch")

    with monkeypatch.context() as patch:
        patch.setattr(exchange, "get_rates", broken)
        if via == "stream":
            with pytest.raises(RuntimeError):
                server.stream("prod13")
        else:
            assert server.get("prod13").status_code == 500
    assert free_slots() == 2
    assert server.search("prod13", via=via).priced == 30              # the next search works normally


# ---------------------------------------------------------------------------
# The caches under many threads
# ---------------------------------------------------------------------------

def test_caches_under_many_threads(server, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_CACHE_MAX", 15)
    monkeypatch.setattr(config, "SLUG_CACHE_MAX", 15)
    monkeypatch.setattr(config, "ADMIN_TOKEN", "t0ken")
    payload = {k: v for k, v in server.get("MacBook Air").get_json().items()
               if k not in ("product", "matchedName", "substituted", "cached", "ageSeconds", "expiresInSeconds")}
    errors = []

    def hammer(i):
        try:
            for j in range(400):
                key = f"s{(i * 7 + j) % 40}"
                step = j % 5
                if step == 0:
                    results_cache.put(key, payload, complete=j % 2 == 0)
                elif step == 1:
                    results_cache.get(key)
                elif step == 2:
                    lookup._remember(key, ("macbook-air", "mac"), ttl=60 if j % 3 == 0 else 0, failed=False)
                elif step == 3:
                    lookup.slug_is_known(key)
                    lookup.discover_slug("macbook air")
                elif server.status("t0ken") is None:
                    errors.append("status page failed")
        except Exception as exc:                                         # noqa: BLE001 - collected for the assert
            errors.append(repr(exc))

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)                                          # switch threads as often as possible
    try:
        threads = [threading.Thread(target=hammer, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(interval)
    assert errors == []
    assert len(results_cache._entries) <= 15 and len(lookup._entries) <= 15
