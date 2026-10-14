"""The results cache: how long a result set is kept, what is shared between names and endpoints, and its size."""
import json

import time

import pytest

from support.client import cached_ttl
from tracker import config, lookup, results_cache

MINUTE, HOUR = 60, 3600
SIX_HOURS, FIVE_MINUTES = 6 * HOUR, 5 * MINUTE


def test_complete_result_is_kept_six_hours(server, apple, clock):
    first = server.search("MacBook Air")
    calls = len(apple.apple_calls())
    assert first.meta["cached"] is False and first.meta["ageSeconds"] == 0
    assert first.meta["expiresInSeconds"] == SIX_HOURS and calls > 50
    assert first.priced == 30 and len(first.rows) == 50

    clock.advance(10 * MINUTE)
    hit = server.search("MacBook Air")
    assert hit.cached and len(apple.apple_calls()) == calls
    assert hit.meta["ageSeconds"] == pytest.approx(600, abs=2)
    assert hit.meta["expiresInSeconds"] == pytest.approx(SIX_HOURS - 600, abs=2)
    assert sorted((r["country"], r.get("localPrice")) for r in hit.rows) == \
        sorted((r["country"], r.get("localPrice")) for r in first.rows)

    clock.advance(5 * HOUR + 49 * MINUTE)                              # 5 h 59 min
    assert server.search("MacBook Air").cached

    clock.advance(2 * MINUTE)                                          # 6 h 01 min
    again = server.search("MacBook Air")
    assert not again.cached and len(apple.apple_calls()) > calls and again.meta["expiresInSeconds"] == SIX_HOURS
    assert list(results_cache._entries) == ["macbook-air"]                # replaced, not duplicated


def test_spellings_of_one_product_share_its_entry(server, apple, clock):
    server.search("MacBook Air")
    calls = len(apple.apple_calls())
    clock.advance(HOUR)
    hit = server.search("macbook air")
    assert hit.cached and hit.meta["product"] == "macbook air"
    assert len(apple.apple_calls()) - calls <= 2                      # at most the name check


def test_each_product_has_its_own_clock(server, clock):
    server.search("MacBook Air")
    clock.advance(2 * HOUR)
    other = server.search("iPhone 17")
    assert not other.cached and other.meta["slug"] == "iphone-17" and other.row("United States")["localPrice"] == 799
    clock.advance(4 * HOUR + 30 * MINUTE)                             # MacBook Air 6.5 h old, iPhone 17 4.5 h old
    assert not server.search("MacBook Air").cached
    assert server.search("iPhone 17").cached


@pytest.mark.parametrize("failure", ["timeout", 503, 429, 403])
def test_result_with_a_failed_store_is_kept_five_minutes(server, apple, clock, via, failure):
    apple.store_failures["de"] = failure
    first = server.search("MacBook Air", via=via)
    germany = first.row("Germany")
    assert germany["available"] is False and germany["reason"] == "Price not found"
    assert set(germany) == {"country", "flag", "available", "reason", "url"}        # no internal marker
    assert cached_ttl("macbook-air") == FIVE_MINUTES
    calls = len(apple.apple_calls())
    clock.advance(4 * MINUTE)
    assert server.search("MacBook Air", via=via).cached and len(apple.apple_calls()) == calls
    apple.store_failures.clear()
    clock.advance(2 * MINUTE)
    retried = server.search("MacBook Air", via=via)
    assert not retried.cached and retried.row("Germany")["available"]
    assert cached_ttl("macbook-air") == SIX_HOURS


def test_result_without_any_price_is_kept_five_minutes(server, clock):
    result = server.search("AirTag")
    assert result.meta["slug"] == "airtag" and result.priced == 0 and len(result.rows) == 50
    assert result.meta["expiresInSeconds"] == FIVE_MINUTES and "_transient" not in json.dumps(result.rows)
    clock.advance(6 * MINUTE)
    assert not server.search("AirTag").cached


def test_unknown_product_is_not_cached(server, via):
    result = server.search("Nonexistent Thing", via=via)
    assert result.error and results_cache._entries == {}


def test_endpoints_share_the_cache(server, apple, clock):
    streamed = server.search("MacBook Air", via="stream")
    calls = len(apple.apple_calls())
    clock.advance(3 * HOUR + 7 * MINUTE)
    replay = server.search("MacBook Air", via="stream")
    assert replay.cached and len(apple.apple_calls()) == calls and replay.events[-1].data.get("cached") is True
    assert replay.meta["ageSeconds"] == pytest.approx(11_220, abs=2)
    assert replay.meta["expiresInSeconds"] == pytest.approx(SIX_HOURS - 11_220, abs=2)
    assert sorted(json.dumps(r, sort_keys=True) for r in replay.rows) == \
        sorted(json.dumps(r, sort_keys=True) for r in streamed.rows)
    assert [r["country"] for r in replay.rows[:3]] == ["Japan", "Hong Kong", "United States"]   # replayed cheapest first
    from_json = server.search("MacBook Air")
    assert from_json.cached and from_json.meta["ageSeconds"] == pytest.approx(11_220, abs=2)

    server.search("iMac")
    clock.advance(HOUR)
    assert server.search("iMac", via="stream").meta["ageSeconds"] == pytest.approx(HOUR, abs=2)


def test_fresh_stream_is_not_marked_cached(server):
    meta = server.search("MacBook Air", via="stream").meta
    assert "cached" not in meta and meta["total"] == 50 and meta["rates"]["EUR"] == 0.92


# ---------------------------------------------------------------------------
# Size and memory
# ---------------------------------------------------------------------------

def test_result_cache_drops_the_oldest(server, clock, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_CACHE_MAX", 5)
    for i in range(1, 9):
        server.search(f"prod{i}")
    assert list(results_cache._entries) == ["prod4", "prod5", "prod6", "prod7", "prod8"]
    results_cache._entries["prod4"]["ts"] -= 7 * HOUR                     # expired: fetched again
    server.search("prod4")
    server.search("prod9")
    assert list(results_cache._entries) == ["prod6", "prod7", "prod8", "prod4", "prod9"]   # refreshed counts as newest


def test_name_cache_drops_the_oldest(server):
    for i in range(config.SLUG_CACHE_MAX + 20):
        server.get(f"zz{i}")
    assert len(lookup._entries) == config.SLUG_CACHE_MAX
    assert "zz19" not in lookup._entries and "zz20" in lookup._entries and f"zz{config.SLUG_CACHE_MAX + 19}" in lookup._entries


def test_entry_without_a_stored_lifetime_is_short_lived(clock):
    results_cache._entries["legacy"] = {"ts": time.monotonic(), "payload": {"results": []}}
    assert results_cache.get("legacy") is not None
    clock.advance(6 * MINUTE)
    assert results_cache.get("legacy") is None and "legacy" not in results_cache._entries


def test_status_reports_each_entry(server, apple, clock, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "test-token")
    server.search("MacBook Air")
    apple.store_failures["de"] = 503
    server.search("iPhone 17")
    clock.advance(2 * MINUTE)
    cache = server.status("test-token")["results_cache"]
    assert cache["ttl_seconds"] == SIX_HOURS and cache["ttl_seconds_incomplete"] == FIVE_MINUTES
    mac, iphone = cache["slugs"]["macbook-air"], cache["slugs"]["iphone-17"]
    assert (mac["ttl_seconds"], iphone["ttl_seconds"]) == (SIX_HOURS, FIVE_MINUTES)
    assert mac["age_seconds"] == pytest.approx(120, abs=2)
    assert mac["expires_in"] == pytest.approx(SIX_HOURS - 120, abs=2) and iphone["expires_in"] == pytest.approx(180, abs=2)
