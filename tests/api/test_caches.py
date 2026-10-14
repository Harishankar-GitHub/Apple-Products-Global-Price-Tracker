"""The cache class both the name look-ups and the result sets are kept in (api/tracker/caches.py)."""
import threading

import pytest

from tracker.caches import TTLCache


@pytest.fixture
def cap():
    return {"size": 3}


@pytest.fixture
def cache(cap) -> TTLCache:
    return TTLCache(max_size=lambda: cap["size"])


def test_an_entry_is_kept_for_its_own_lifetime(cache, clock):
    cache.put("short", 1, ttl=60)
    cache.put("long", 2, ttl=3600)
    cache.put("forever", 3, ttl=None)
    entry = cache.get("short")
    assert entry.value == 1 and entry.ttl == 60 and entry.age(entry.stored_at + 10) == pytest.approx(10)
    assert entry.expires_in(entry.stored_at + 10) == pytest.approx(50) and entry.expires_in(entry.stored_at + 90) == 0
    assert cache.get("forever").expires_in(entry.stored_at + 10**9) is None

    clock.advance(60)                                                  # exactly its lifetime: gone
    assert cache.get("short") is None and cache.get("long").value == 2
    clock.advance(3600)
    assert cache.get("long") is None and cache.get("forever").value == 3
    assert cache.get("never stored") is None


def test_lists_and_counts_only_live_entries_oldest_first(cache, clock):
    cache.put("a", 1, ttl=60)
    cache.put("b", 2, ttl=None)
    cache.put("c", 3, ttl=120)
    assert cache.keys() == ["a", "b", "c"] and len(cache) == 3
    clock.advance(90)
    assert cache.keys() == ["b", "c"] and len(cache) == 2
    assert [(k, e.value) for k, e in cache.items()] == [("b", 2), ("c", 3)]


def test_storing_a_key_again_replaces_it_and_makes_it_the_newest(cache, clock):
    cache.put("a", 1, ttl=60)
    cache.put("b", 2, ttl=60)
    clock.advance(30)
    cache.put("a", 10, ttl=60)
    assert cache.keys() == ["b", "a"] and cache.get("a").value == 10
    clock.advance(45)                                                   # the first "a" would have expired
    assert cache.keys() == ["a"]


def test_beyond_the_cap_the_oldest_go_first(cache):
    for key in "abcde":
        cache.put(key, key, ttl=None)
    assert cache.keys() == ["c", "d", "e"]


def test_beyond_the_cap_expired_entries_go_before_older_live_ones(cache, clock):
    cache.put("old", 1, ttl=None)
    cache.put("brief", 2, ttl=10)
    cache.put("newer", 3, ttl=None)
    clock.advance(20)
    cache.put("newest", 4, ttl=None)
    assert cache.keys() == ["old", "newer", "newest"]


def test_the_cap_is_read_when_it_is_applied(cache, cap):
    for key in "abc":
        cache.put(key, key, ttl=None)
    cap["size"] = 1
    cache.put("d", "d", ttl=None)
    assert cache.keys() == ["d"]


def test_clear(cache):
    cache.put("a", 1, ttl=None)
    cache.clear()
    assert cache.keys() == [] and cache.get("a") is None


def test_many_threads_at_once(cap):
    cap["size"] = 20
    cache = TTLCache(max_size=lambda: cap["size"])
    errors = []

    def hammer(i):
        try:
            for j in range(2000):
                key = (i + j) % 50
                match j % 4:
                    case 0: cache.put(key, j, ttl=0 if j % 3 else None)
                    case 1: cache.get(key)
                    case 2: cache.items()
                    case 3: len(cache)
        except Exception as exc:                                         # noqa: BLE001 - collected for the assert
            errors.append(repr(exc))

    threads = [threading.Thread(target=hammer, args=(i,), daemon=True) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == [] and len(cache) <= 20
