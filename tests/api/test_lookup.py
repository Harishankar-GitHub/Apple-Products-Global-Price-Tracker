"""Turning what was typed into Apple's product page: names, closest matches, failed and stale look-ups."""
import pytest

import app as api
from fakes.apple import store_prefix

FIVE_MINUTES, HOUR = 5 * 60, 3600


def remembered(name: str):
    return api._slug_cache.get(name)


def store_requests(apple, slug_fragment: str) -> list[str]:
    """Requests to a country store (not the US look-up) for pages matching `slug_fragment`."""
    return [u for u in apple.apple_calls(slug_fragment) if store_prefix(u)]


# ---------------------------------------------------------------------------
# Names and matches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("slug", "name"),
    [("apple-watch-ultra-4", "Apple Watch Ultra 4"), ("macbook-air", "MacBook Air"), ("iphone-17", "iPhone 17"),
     ("iphone-17e", "iPhone 17e"), ("iphone-18-pro", "iPhone 18 Pro"), ("ipad-mini", "iPad mini"), ("mac-mini", "Mac mini"),
     ("imac", "iMac"), ("airpods-pro", "AirPods Pro"), ("airpods-max", "AirPods Max"), ("apple-tv-4k", "Apple TV 4K"),
     ("homepod-mini", "HomePod mini"), ("homepod-2nd-generation", "HomePod 2nd generation"),
     ("apple-watch-se-3", "Apple Watch SE 3"), ("airtag", "AirTag"), ("apple-vision-pro", "Apple Vision Pro"),
     ("studio-display-xdr", "Studio Display XDR"), ("mac-studio", "Mac Studio"), ("apple-watch-hermes", "Apple Watch Hermès"),
     ("", "")],
)
def test_display_name(slug, name):
    assert api.display_name(slug) == name


@pytest.mark.parametrize(
    ("typed", "slug"),
    [("MacBook Air", "macbook-air"), ("macbook air", "macbook-air"), ("  MacBook   Air ", "macbook-air"),
     ("macbook-air", "macbook-air"), ("MACBOOK AIR", "macbook-air"), ("iPhone17", "iphone-17"), ("i-phone 17", "iphone-17"),
     ("Watch Series 12", "apple-watch-series-12"), ("Apple Watch Series 12", "apple-watch-series-12"),
     ("Apple TV 4K", "apple-tv-4k"), ("apple vision pro", "apple-vision-pro"), ("Vision Pro", "apple-vision-pro"),
     ("AirTag", "airtag"), ("Mac mini!", "mac-mini")],
)
def test_same_product_is_not_flagged(typed, slug):
    assert api.match_info(typed, slug)["substituted"] is False


@pytest.mark.parametrize(
    ("typed", "slug"),
    [("Apple Watch Ultra 2", "apple-watch-ultra-4"), ("Apple Watch Ultra", "apple-watch-ultra-4"),
     ("Apple Watch Ultra 3", "apple-watch-ultra-4"), ("MacBook Air M4 15 inch", "macbook-air"),
     ("iPhone 17 Pro Max 256GB", "iphone-17-pro"), ("iPhone 16", "iphone-17"), ("Apple Watch SE", "apple-watch-se-3"),
     ("HomePod", "homepod-2nd-generation"), ("iPad Pro", "ipad-air"), ("apple", "apple-watch")],
)
def test_different_product_is_flagged(typed, slug):
    assert api.match_info(typed, slug)["substituted"] is True


@pytest.mark.parametrize("typed", ["Apple Watch Ultra 2", "Apple Watch Ultra", "Apple Watch Ultra 3"])
def test_older_model_is_priced_as_the_current_one_and_says_so(server, apple, via, typed):
    result = server.search(typed, via=via)
    assert result.meta["slug"] == "apple-watch-ultra-4"
    assert result.meta["matchedName"] == "Apple Watch Ultra 4" and result.meta["substituted"] is True
    assert result.meta["product"] == typed
    assert result.priced == 30 and result.row("United States")["localPrice"] == 799
    assert all("ultra-4" in r["url"] for r in result.rows)
    assert not store_requests(apple, "apple-watch-ultra-2") and not store_requests(apple, "apple-watch-ultra-3")


def test_flag_arrives_before_any_price(server):
    events = server.stream("Apple Watch Ultra 2")
    assert [e.name for e in events[:2]] == ["searching", "meta"]
    assert events[1].data["substituted"] is True and "cached" not in events[1].data


def test_names_for_the_same_product_share_the_cache_but_keep_their_own_flag(server):
    server.search("Apple Watch Ultra 2")
    by_name = server.search("Apple Watch Ultra 4")
    again = server.search("apple watch ultra 2", via="stream")
    assert by_name.cached and by_name.meta["substituted"] is False and by_name.meta["product"] == "Apple Watch Ultra 4"
    assert again.cached and again.meta["substituted"] is True and again.meta["matchedName"] == "Apple Watch Ultra 4"


@pytest.mark.parametrize("typed", ["MacBook Air", "macbook  air"])
def test_ordinary_search_is_not_flagged(server, via, typed):
    meta = server.search(typed, via=via).meta
    assert meta["substituted"] is False and meta["matchedName"] == "MacBook Air" and meta["product"] == typed


def test_product_without_a_product_page_is_found_through_its_buy_page(server):
    result = server.search("iPhone 16")
    assert result.meta["slug"] == "iphone-16" and result.meta["substituted"] is False
    assert result.priced == 30 and result.row("United States")["localPrice"] == 729


# ---------------------------------------------------------------------------
# The built-in name table
# ---------------------------------------------------------------------------

def test_built_in_name_is_checked_once_then_remembered(server, apple):
    server.search("iPhone 17")
    calls = len(apple.calls)
    server.search("iPhone 17")
    server.search("iphone 17")
    assert len(apple.calls) == calls


def test_retired_built_in_name_is_not_found(server):
    resp = server.get("iPhone 16 Pro")
    assert resp.status_code == 404 and api._results_cache == {}
    assert remembered("iphone 16 pro")["failed"] is False and remembered("iphone 16 pro")["expires"] is not None


def test_stale_table_entry_falls_back_to_discovery(server, apple, monkeypatch):
    monkeypatch.setitem(api.SLUG_OVERRIDES, "apple watch ultra", ("apple-watch-ultra-3", "watch"))
    result = server.search("Apple Watch Ultra")
    assert result.meta["slug"] == "apple-watch-ultra-4" and result.meta["substituted"] is True and result.priced == 30
    assert not store_requests(apple, "apple-watch-ultra-3")             # no store was asked for the retired model


def test_stale_table_entry_with_nothing_to_fall_back_on_is_not_found(server, monkeypatch):
    monkeypatch.setitem(api.SLUG_OVERRIDES, "apple watch ultra 2", ("apple-watch-ultra-3", "watch"))
    assert server.get("Apple Watch Ultra 2").status_code == 404


# ---------------------------------------------------------------------------
# Apple's suggestions service
# ---------------------------------------------------------------------------

def test_suggestion_that_checks_out_is_used_and_remembered(server, apple):
    apple.suggestions["big laptop"] = "https://www.apple.com/macbook-air/"
    result = server.search("big laptop")
    assert result.meta["slug"] == "macbook-air" and result.meta["substituted"] is True
    assert remembered("big laptop")["expires"] is None


def test_suggestion_whose_page_cannot_be_checked_is_a_temporary_failure(server, apple):
    apple.suggestions["big laptop"] = "https://www.apple.com/macbook-air/"
    apple.url_failures["apple.com/macbook-air/"] = 503
    resp = server.get("big laptop")
    assert resp.status_code == 503 and resp.get_json()["temporary"] is True


def test_suggestions_service_down_does_not_make_a_name_temporary(server, apple):
    apple.suggestions_failure = "timeout"
    assert server.get("Nonexistent Thing").status_code == 404
    assert remembered("nonexistent thing")["failed"] is False
    assert server.get("MacBook Air").status_code == 200 and remembered("macbook air")["expires"] is None


# ---------------------------------------------------------------------------
# When Apple does not answer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("failure", ["timeout", 500, 503, 429, 403])
def test_apple_not_answering_is_try_again_not_not_found(server, apple, clock, failure):
    apple.outage = failure
    resp = server.get("MacBook Air")
    body = resp.get_json()
    assert resp.status_code == 503 and body["temporary"] is True
    assert "Apple did not respond" in body["error"] and "MacBook Air" in body["error"] and "Could not find" not in body["error"]
    assert 1 <= body["retryAfterSeconds"] <= 60 and resp.headers["Retry-After"] == str(body["retryAfterSeconds"])
    assert api._results_cache == {}
    apple.outage = None
    clock.advance(61)
    result = server.search("MacBook Air")
    assert result.meta["slug"] == "macbook-air" and result.priced == 30
    assert remembered("macbook air") == {"result": ("macbook-air", "mac"), "expires": None, "failed": False}


def test_failed_look_up_is_held_for_one_minute(server, apple, clock):
    apple.outage = "timeout"
    server.get("MacBook Air")
    apple.outage = None
    calls = len(apple.apple_calls())
    clock.advance(20)
    held = server.get("MacBook Air")
    assert held.status_code == 503 and 38 <= held.get_json()["retryAfterSeconds"] <= 40
    clock.advance(39)
    assert server.get("MacBook Air").status_code == 503
    assert len(apple.apple_calls()) == calls                         # not asked again while held
    clock.advance(2)
    assert server.get("MacBook Air").status_code == 200


def test_failed_look_up_in_the_stream(server, apple, clock):
    apple.outage = 503
    events = server.stream("iPhone 17")
    assert [e.name for e in events] == ["searching", "error"]
    assert events[1].data["temporary"] is True and events[1].data["retryAfterSeconds"] > 0
    apple.outage = None
    clock.advance(61)
    assert server.stream("iPhone 17")[-1].name == "done"


@pytest.mark.parametrize(
    ("failing", "typed", "slug_after"),
    [("apple.com/imac/", "iMac", "imac"), ("apple.com/apple-zzqq/", "zzqq", None)],
    ids=["exact-page", "a-guessed-variation"],
)
def test_one_failed_check_is_enough_to_say_try_again(server, apple, clock, failing, typed, slug_after):
    apple.url_failures[failing] = "timeout" if slug_after else 503
    assert server.get(typed).status_code == 503
    apple.url_failures.clear()
    clock.advance(61)
    resp = server.get(typed)
    assert (resp.get_json().get("slug") == slug_after) if slug_after else resp.status_code == 404


def test_outage_while_checking_a_built_in_name(server, apple, clock):
    apple.outage = "timeout"
    resp = server.get("Apple Watch Ultra 2")
    assert resp.status_code == 503 and resp.get_json()["temporary"] is True and api._results_cache == {}
    apple.outage = None
    clock.advance(61)
    result = server.search("Apple Watch Ultra 2")
    assert result.meta["slug"] == "apple-watch-ultra-4" and result.meta["substituted"] is True and result.priced == 30


def test_fallback_found_while_a_check_failed_is_kept_five_minutes(server, apple, clock):
    apple.products["iphone-17-pro-max"] = 1199
    apple.url_failures["apple.com/iphone-17-pro-max/"] = "timeout"
    fallback = server.search("iPhone 17 Pro Max")
    assert fallback.meta["slug"] == "iphone-17" and fallback.meta["substituted"] is True
    entry = remembered("iphone 17 pro max")
    assert entry["failed"] is False and 290 <= entry["expires"] - api.time.monotonic() <= FIVE_MINUTES
    apple.url_failures.clear()
    clock.advance(4 * 60)
    assert server.search("iPhone 17 Pro Max").meta["slug"] == "iphone-17"
    clock.advance(2 * 60)
    exact = server.search("iPhone 17 Pro Max")
    assert exact.meta["slug"] == "iphone-17-pro-max" and exact.meta["substituted"] is False
    assert remembered("iphone 17 pro max")["expires"] is None


def test_fallback_without_any_failure_is_remembered_for_good(server):
    assert server.search("iPhone 17 Pro Max").meta["slug"] == "iphone-17"
    assert remembered("iphone 17 pro max")["expires"] is None


# ---------------------------------------------------------------------------
# "Not found" is remembered for an hour
# ---------------------------------------------------------------------------

def test_not_found_is_remembered_for_an_hour(server, apple, clock):
    resp = server.get("Nonexistent Thing")
    body = resp.get_json()
    assert resp.status_code == 404 and "Could not find" in body["error"] and "temporary" not in body
    calls = len(apple.apple_calls())
    clock.advance(59 * 60)
    assert server.get("nonexistent thing").status_code == 404 and len(apple.apple_calls()) == calls
    clock.advance(2 * 60)
    assert server.get("Nonexistent Thing").status_code == 404 and len(apple.apple_calls()) > calls


def test_new_product_is_found_within_the_hour_without_a_restart(server, apple, clock):
    assert server.get("MacBook Neo 2").status_code == 404
    apple.products["macbook-neo-2"] = 899                              # Apple launches it
    clock.advance(30 * 60)
    assert server.get("MacBook Neo 2").status_code == 404
    clock.advance(31 * 60)
    result = server.search("MacBook Neo 2")
    assert result.meta["slug"] == "macbook-neo-2" and result.priced == 30


def test_known_name_lookup_is_normalised_and_expires(server, clock):
    server.get("Nonexistent Thing")
    assert api.slug_is_known("Nonexistent Thing") and api.slug_is_known("  NONEXISTENT thing ")
    clock.advance(HOUR + 1)
    assert not api.slug_is_known("Nonexistent Thing")
    assert "nonexistent thing" not in api._slug_cache


# ---------------------------------------------------------------------------
# Known products keep working while Apple is down
# ---------------------------------------------------------------------------

def test_cached_prices_are_served_during_an_outage(server, apple, clock, via):
    server.search("MacBook Air")
    calls = len(apple.apple_calls())
    apple.outage = "timeout"
    clock.advance(HOUR)
    result = server.search("macbook air", via=via)
    assert result.cached and result.priced == 30 and len(apple.apple_calls()) == calls


def test_prices_expire_during_an_outage(server, apple, clock):
    server.search("MacBook Air")
    apple.outage = "timeout"
    clock.advance(6 * HOUR)
    during = server.search("MacBook Air")
    assert during.meta["slug"] == "macbook-air" and during.priced == 0 and during.meta["expiresInSeconds"] == FIVE_MINUTES
    apple.outage = None
    clock.advance(6 * 60)
    assert server.search("MacBook Air").priced == 30
