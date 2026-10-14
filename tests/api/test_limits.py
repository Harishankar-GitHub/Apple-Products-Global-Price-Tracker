"""Abuse protection: rate limits, what a look-up costs, telling visitors apart, input size and the private status view."""
import threading

import pytest

from support.client import LIMITERS
from tracker import config, limits, lookup, results_cache

A, B, C, D = "198.51.100.1", "198.51.100.2", "198.51.100.3", "198.51.100.4"


def codes(responses) -> set:
    return {r.status_code for r in responses}


# ---------------------------------------------------------------------------
# Requests per visitor
# ---------------------------------------------------------------------------

def test_requests_per_visitor(server, clock, limits_on):
    limits_on()
    answered = [server.get("MacBook Air", A) for _ in range(60)]
    refused = server.get("MacBook Air", A)
    body = refused.get_json()
    assert codes(answered) == {200}
    assert refused.status_code == 429 and body["rateLimited"] is True and "Too many requests" in body["error"]
    assert 1 <= body["retryAfterSeconds"] <= 60 and refused.headers["Retry-After"] == str(body["retryAfterSeconds"])
    assert server.get("MacBook Air", B).status_code == 200            # another visitor is not affected
    clock.advance(30)
    assert codes(server.get("MacBook Air", A) for _ in range(10)) == {429}   # refusals do not extend the wait…
    clock.advance(31)
    assert server.get("MacBook Air", A).status_code == 200            # …which ends a minute after the first


def test_window_slides(server, clock, limits_on):
    limits_on()
    for _ in range(30):
        server.get("MacBook Air", A)
    clock.advance(40)
    assert codes(server.get("MacBook Air", A) for _ in range(30)) == {200}
    refused = server.get("MacBook Air", A)
    assert refused.status_code == 429 and 18 <= refused.get_json()["retryAfterSeconds"] <= 21
    clock.advance(21)                                                  # the first 30 age out
    assert codes(server.get("MacBook Air", A) for _ in range(30)) == {200}
    assert server.get("MacBook Air", A).status_code == 429


# ---------------------------------------------------------------------------
# Apple look-ups
# ---------------------------------------------------------------------------

def test_look_ups_per_visitor(server, apple, clock, limits_on):
    limits_on()
    fetched = [server.get(f"prod{i}", A) for i in range(1, 21)]
    assert codes(fetched) == {200} and limits.fetch_limiter.count(A) == 20
    calls = len(apple.calls)
    refused = server.get("prod21", A)
    body = refused.get_json()
    assert refused.status_code == 429 and len(apple.calls) == calls             # Apple not contacted
    assert "prod21" not in lookup.names() and results_cache.get("prod21") is None
    assert "looked up a lot of products" in body["error"] and "minutes" in body["error"]
    assert 1 <= body["retryAfterSeconds"] <= 600 and refused.headers["Retry-After"] == str(body["retryAfterSeconds"])
    assert server.search("prod5", ip=A).cached                                 # cached products still served
    assert server.get("prod21", B).status_code == 200                          # another visitor can look it up…
    assert server.search("prod21", ip=A).cached                                # …and then everyone reads it
    clock.advance(601)
    assert server.get("prod22", A).status_code == 200


PRICES_DROPPED = None          # in a list of searches: the cached prices are dropped (the name stays known)


@pytest.mark.parametrize(
    ("searches", "cost"),
    [(["MacBook Air"], 1),                                      # name and prices: one look-up, not two
     (["MacBook Air", "MacBook Air", "macbook air"], 1),        # cached repeats are free
     (["MacBook Air", "iPhone 17"], 2),                         # a built-in name still costs one for its prices
     (["MacBook Air", PRICES_DROPPED, "MacBook Air"], 2)],      # a known name costs one when its prices are fetched
    ids=["new-product", "cached-repeats", "built-in-name", "known-name-prices-not-cached"],
)
def test_what_a_search_costs(server, limits_on, searches, cost):
    limits_on()
    for name in searches:
        if name is PRICES_DROPPED:
            results_cache.clear()
        else:
            server.get(name, A)
    assert limits.fetch_limiter.count(A) == cost and limits.global_fetch_limiter.count("all") == cost


def test_unknown_names_count_but_known_wrong_names_are_free(server, apple, limits_on):
    limits_on()
    assert codes(server.get(f"zz nonsense {i}", A) for i in range(20)) == {404}
    calls = len(apple.calls)
    assert server.get("zz nonsense 20", A).status_code == 429 and len(apple.calls) == calls
    assert server.get("zz nonsense 3", A).status_code == 404 and len(apple.calls) == calls


def test_failed_look_up_costs_one_and_held_retries_are_free(server, apple, clock, limits_on):
    limits_on()
    apple.outage = "timeout"
    server.get("Mac mini", A)
    assert limits.fetch_limiter.count(A) == 1
    clock.advance(10)
    server.get("Mac mini", A)
    server.get("mac mini", A)
    assert limits.fetch_limiter.count(A) == 1
    clock.advance(55)
    server.get("Mac mini", A)
    assert limits.fetch_limiter.count(A) == 2


def test_look_ups_for_everyone_together(server, apple, clock, limits_on):
    limits_on()
    for ip, first in ((A, 1), (B, 21), (C, 41)):
        assert codes(server.get(f"prod{i}", ip) for i in range(first, first + 20)) == {200}
    assert limits.global_fetch_limiter.count("all") == 60
    calls = len(apple.calls)
    refused = server.get("prod61", D)
    assert refused.status_code == 429 and "busy fetching prices" in refused.get_json()["error"]
    assert len(apple.calls) == calls and limits.fetch_limiter.count(D) == 0      # not charged to that visitor
    assert server.search("prod7", ip=D).cached
    clock.advance(601)
    assert server.get("prod61", D).status_code == 200 and limits.fetch_limiter.count(D) == 1


def test_shared_limit_holds_against_changing_addresses(server, limits_on):
    limits_on()
    assert codes(server.get(f"prod{i}", f"203.0.113.{i}") for i in range(1, 61)) == {200}
    refused = server.get("prod61", "203.0.113.200")
    assert refused.status_code == 429 and "busy" in refused.get_json()["error"]


# ---------------------------------------------------------------------------
# The stream the page uses
# ---------------------------------------------------------------------------

def test_too_many_requests_in_the_stream(server, limits_on):
    limits_on()
    assert {server.stream("MacBook Air", A)[-1].name for _ in range(60)} == {"done"}
    events = server.stream("MacBook Air", A)
    assert [e.name for e in events] == ["error"]
    assert events[0].data["rateLimited"] is True and "Too many requests" in events[0].data["error"]


def test_look_up_limit_in_the_stream(server, apple, limits_on):
    limits_on()
    for i in range(1, 21):
        server.get(f"prod{i}", A)
    calls = len(apple.calls)
    events = server.stream("prod21", A)
    assert [e.name for e in events] == ["searching", "error"] and len(apple.calls) == calls
    assert events[1].data["rateLimited"] is True and "looked up a lot" in events[1].data["error"]
    assert events[1].data["retryAfterSeconds"] > 0
    cached = server.search("prod5", via="stream", ip=A)
    assert cached.cached and cached.events[-1].name == "done" and len(cached.rows) == 50
    assert server.stream("prod30", B)[-1].name == "done" and limits.fetch_limiter.count(B) == 1


def test_shared_limit_in_the_stream(server, limits_on):
    limits_on()
    for i in range(1, 61):
        server.get(f"prod{i}", f"203.0.113.{i}")
    events = server.stream("prod99", D)
    assert [e.name for e in events] == ["searching", "error"] and "busy" in events[1].data["error"]


# ---------------------------------------------------------------------------
# Telling visitors apart
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("first", "others", "same_visitor"),
    [
        # Cloudflare's header wins: changing X-Forwarded-For does not make a new visitor
        ({"CF-Connecting-IP": A}, [{"CF-Connecting-IP": A, "X-Forwarded-For": f"10.9.8.{i}"} for i in range(3)], True),
        # without it, the first X-Forwarded-For address is the visitor
        ({"X-Forwarded-For": "192.0.2.9, 10.0.0.1"},
         [{"X-Forwarded-For": "192.0.2.9 , 172.16.0.1"}, {"X-Forwarded-For": "192.0.2.9"}, {"X-Forwarded-For": "192.0.2.9, 1.2.3.4"}], True),
        ({"X-Forwarded-For": "192.0.2.9"}, [{"X-Forwarded-For": "192.0.2.10"}] * 3, False),
        ({}, [{}] * 3, True),                                  # neither header: the connection address
    ],
    ids=["cf-header-wins", "first-forwarded-address", "different-forwarded-address", "connection-address"],
)
def test_visitor_identity(server, limits_on, first, others, same_visitor):
    limits_on(requests=3)
    responses = [server.get("MacBook Air", headers=h) for h in [first, *others]]
    assert [r.status_code for r in responses] == ([200, 200, 200, 429] if same_visitor else [200, 200, 200, 200])


def test_odd_address_headers(server, limits_on):
    limits_on(requests=3)
    assert server.get("MacBook Air", "x" * 500).status_code == 200
    assert server.get("MacBook Air", "2001:db8::1").status_code == 200
    assert max(len(k) for k in limits.request_limiter._events) <= 64
    assert "2001:db8::1" in limits.request_limiter._events


def test_limits_set_to_zero_are_off(server):
    responses = [server.get("MacBook Air") for _ in range(150)] + [server.get(f"prod{i}") for i in range(1, 70)]
    assert codes(responses) == {200} and all(lim.tracked() == 0 for lim in LIMITERS)


# ---------------------------------------------------------------------------
# The limiter itself
# ---------------------------------------------------------------------------

def test_limiter_tracks_at_most_10000_visitors(clock):
    limiter = limits.SlidingWindowLimiter(5, 600)
    for i in range(10_050):
        limiter.hit(f"k{i}")
    assert limiter.tracked() <= 10_000 and limiter.hit("k10049") == 0
    clock.advance(601)
    limiter.hit("fresh")
    assert limiter.tracked() == 1                       # visitors with nothing recent are forgotten


def test_limiter_is_exact_under_concurrency():
    limiter = limits.SlidingWindowLimiter(500, 600)
    allowed = []

    def hammer():
        for _ in range(100):
            if limiter.hit("same") == 0:
                allowed.append(1)

    threads = [threading.Thread(target=hammer) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 500


# ---------------------------------------------------------------------------
# Input size
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("product", "message"), [("x" * 81, "too long"), (None, "Missing")], ids=["81-characters", "missing"])
def test_bad_product_parameter_is_refused_before_any_work(server, apple, limits_on, via, product, message):
    limits_on()
    if via == "json":
        resp = server.get(product, A)
        assert resp.status_code == 400 and message in resp.get_json()["error"]
    else:
        events = server.stream(product, A)
        assert [e.name for e in events] == ["error"] and message in events[0].data["error"]
    assert apple.calls == [] and lookup.size() == 0 and limits.fetch_limiter.count(A) == 0


def test_80_character_name_is_accepted(server):
    assert server.get("x" * 80).status_code == 404                    # simply not found


# ---------------------------------------------------------------------------
# /api/cache/status
# ---------------------------------------------------------------------------

@pytest.fixture
def searched(server, limits_on):
    """Three visitors have searched; limits are on, so the status page has counts to show."""
    limits_on()
    server.get("MacBook Air", A)
    server.get("zz secret gift idea", B)
    server.get("iPhone 17", C)


def test_public_status_reveals_no_searches(client, searched):
    resp = client.get("/api/cache/status")
    body, text = resp.get_json(), resp.get_data(as_text=True).lower()
    assert resp.status_code == 200
    assert not any(term in text for term in ("macbook", "secret", "gift", "iphone", "zz ", "198.51.100"))
    assert "keys" not in body["slug_cache"] and "slugs" not in body["results_cache"] and "you" not in body
    assert body["slug_cache"]["entries"] == 3 and body["results_cache"]["entries"] == 2 and "hidden" in body["details"]
    assert body["results_cache"]["ttl_seconds"] == 6 * 3600
    assert set(body["rate_limits"]) == {"requests_per_minute", "apple_lookups_per_10_minutes",
                                        "apple_lookups_per_10_minutes_all_visitors", "apple_lookups_used_all_visitors",
                                        "visitors_tracked"}
    assert body["rate_limits"]["apple_lookups_used_all_visitors"] == 3


@pytest.mark.parametrize(
    "headers",
    [{"X-Admin-Token": ""}, {"X-Admin-Token": "anything"}, {"Authorization": "Bearer "}, {"Authorization": "Bearer x"}],
)
def test_nothing_unlocks_details_without_a_configured_token(server, searched, headers):
    assert "keys" not in server.status(headers=headers)["slug_cache"]


@pytest.mark.parametrize(
    "headers",
    [{"X-Admin-Token": "s3cret-token-12"}, {"X-Admin-Token": "s3cret-token-1234"}, {"X-Admin-Token": "S3CRET-TOKEN-123"},
     {"X-Admin-Token": ""}, {"Authorization": "Bearer nope"}, {"Authorization": "s3cret-token-123"},
     {"X-Admin-Token": "s3crét"}],
    ids=["short", "long", "case", "empty", "wrong-bearer", "bearer-missing", "non-ascii"],
)
def test_wrong_tokens_are_refused(server, searched, monkeypatch, headers):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret-token-123")
    body = server.status(headers=headers)
    assert "keys" not in body["slug_cache"] and "hidden" in body["details"]


@pytest.mark.parametrize(
    ("headers", "you"),
    [({"X-Admin-Token": "s3cret-token-123", "CF-Connecting-IP": D}, {"address": D, "identified_by": "CF-Connecting-IP"}),
     ({"Authorization": "Bearer s3cret-token-123"}, {"address": "127.0.0.1", "identified_by": "connection"}),
     ({"Authorization": "bearer s3cret-token-123"}, {"address": "127.0.0.1", "identified_by": "connection"}),
     ({"X-Admin-Token": "s3cret-token-123", "X-Forwarded-For": "192.0.2.77, 10.0.0.1"},
      {"address": "192.0.2.77", "identified_by": "X-Forwarded-For"})],
    ids=["x-admin-token", "bearer", "bearer-lower-case", "forwarded"],
)
def test_correct_token_shows_details(server, searched, monkeypatch, headers, you):
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret-token-123")
    body = server.status(headers=headers)
    assert body["details"] == "shown"
    assert body["slug_cache"]["keys"] == ["macbook air", "zz secret gift idea", "iphone 17"]
    assert sorted(body["results_cache"]["slugs"]) == ["iphone-17", "macbook-air"]
    assert body["you"] == you


def test_token_guessing_is_rate_limited(server, limits_on, monkeypatch):
    limits_on()
    monkeypatch.setattr(config, "ADMIN_TOKEN", "s3cret-token-123")
    statuses = [server.client.get("/api/cache/status", headers={"X-Admin-Token": f"guess{i}", "CF-Connecting-IP": A}).status_code
                for i in range(61)]
    assert statuses == [200] * 60 + [429]


def test_status_shows_how_long_names_are_remembered(server):
    names = server.status()["slug_cache"]
    assert names["not_found_ttl_seconds"] == 3600 and names["failed_lookup_ttl_seconds"] == 60


@pytest.mark.parametrize("path", ["/api/health", "/"])
def test_unlimited_endpoints(client, limits_on, path):
    limits_on()
    assert codes(client.get(path, headers={"CF-Connecting-IP": A}) for _ in range(300)) == {200}
