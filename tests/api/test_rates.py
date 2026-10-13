"""Exchange rates: what counts as a usable rate, the 30-minute rate cache, and prices that cannot be converted."""
import pytest

import app as api
from support.client import cached_ttl

SIX_HOURS, FIVE_MINUTES = 6 * 3600, 5 * 60


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(1.38, 1.38), (150, 150.0), (None, None), (0, None), (-150, None), ("1.38", None), (True, None),
     (float("nan"), None), (float("inf"), None)],
    ids=["decimal", "whole-number", "missing", "zero", "negative", "text", "true", "nan", "infinity"],
)
def test_usd_rate(rate, expected):
    rates = {} if rate is None else {"X": rate}
    assert api.usd_rate(rates, "X") == expected


@pytest.mark.parametrize("rates", [{}, None])
def test_usd_rate_without_any_rates(rates):
    assert api.usd_rate(rates, "EUR") is None


def test_rates_sent_to_the_page_are_only_usable_ones_for_listed_currencies():
    rates = {"EUR": 0.92, "INR": 0, "JPY": -150, "CAD": "1.38", "XYZ": 2.0, "GBP": 0.78}
    assert api.rates_for_client(rates) == {"EUR": 0.92, "GBP": 0.78}


def rate_requests(apple) -> int:
    return sum("er-api.com" in u for u in apple.calls)


def test_rates_are_fetched_once_per_30_minutes(server, apple, clock):
    server.search("MacBook Air")
    server.search("iPhone 17")
    assert rate_requests(apple) == 1
    clock.advance(29 * 60)
    server.search("Mac mini")
    assert rate_requests(apple) == 1
    clock.advance(2 * 60)
    server.search("iMac")
    assert rate_requests(apple) == 2


def test_currency_missing_from_the_rate_service(server, apple, via):
    del apple.rates["INR"]
    result = server.search("MacBook Air", via=via)
    india = result.row("India")
    assert india["available"] and india["localPrice"] > 0 and india["usdPrice"] is None
    assert all(r["usdPrice"] > 0 for r in result.rows if r["available"] and r is not india)
    assert "INR" not in result.meta["rates"] and "EUR" in result.meta["rates"]
    assert "_transient" not in str(result.rows)
    assert cached_ttl("macbook-air") == FIVE_MINUTES                  # fetched again soon


def test_unconverted_price_comes_after_every_converted_one(server, apple):
    del apple.rates["INR"]
    available = [r for r in server.search("MacBook Air").rows if r["available"]]
    assert available[-1]["country"] == "India"


def expire_rate_cache(monkeypatch):
    monkeypatch.setattr(api, "_rates_fetched_at", -1e9)


def test_rate_coming_back(server, apple, clock, monkeypatch):
    rate = apple.rates.pop("INR")
    server.search("MacBook Air")
    apple.rates["INR"] = rate
    expire_rate_cache(monkeypatch)                                    # the next request fetches rates again
    cached = server.search("MacBook Air")
    india = cached.row("India")
    assert cached.cached and india["usdPrice"] == pytest.approx(india["localPrice"] / rate, abs=0.01)
    prices = [r["usdPrice"] for r in cached.rows if r["available"]]
    assert prices == sorted(prices)
    clock.advance(FIVE_MINUTES)
    fresh = server.search("MacBook Air")
    assert not fresh.cached and cached_ttl("macbook-air") == SIX_HOURS


def test_rate_service_down(server, apple):
    apple.stores["kw"] = ("KWD", 1.03)
    apple.rates_down = True
    result = server.search("iPhone 17")
    available = [r for r in result.rows if r["available"]]
    assert available and all(r["usdPrice"] is None for r in available)
    assert result.meta["rates"] == {}
    # Kuwait's 255 KWD could only be checked against the $500 floor, so it was missed…
    assert not result.row("Kuwait")["available"]
    assert cached_ttl("iphone-17") == FIVE_MINUTES


def test_rate_service_back_after_an_outage(server, apple, clock):
    apple.stores["kw"] = ("KWD", 1.03)
    apple.rates_down = True
    server.search("iPhone 17")
    apple.rates_down = False
    clock.advance(FIVE_MINUTES + 1)
    result = server.search("iPhone 17")
    assert result.row("Kuwait")["available"] and result.row("Kuwait")["usdPrice"] > 0
    assert cached_ttl("iphone-17") == SIX_HOURS


def test_nonsense_rates(server, apple):
    apple.rates.update({"INR": 0, "JPY": -150, "CAD": "1.38", "KRW": None})
    result = server.search("MacBook Air")
    available = [r for r in result.rows if r["available"]]
    unconverted = ["Canada", "India", "Japan", "South Korea"]
    assert result.status == 200 and len(available) == 30
    assert all(result.row(c)["usdPrice"] is None for c in unconverted)
    assert all(r["usdPrice"] is None or r["usdPrice"] > 0 for r in available)
    assert [r["country"] for r in available[-4:]] == unconverted       # last, A→Z
    assert not set(result.meta["rates"]) & {"INR", "JPY", "CAD", "KRW"}


# ---------------------------------------------------------------------------
# Cached results are converted with the current rates
# ---------------------------------------------------------------------------

def test_cache_hit_uses_current_rates(server, apple, clock, via):
    first = server.search("MacBook Air")
    clock.advance(2 * 3600)
    apple.rates.update({"EUR": 0.80, "JPY": 200.0})
    calls = len(apple.apple_calls())
    hit = server.search("MacBook Air", via=via)
    ireland, japan = hit.row("Ireland"), hit.row("Japan")
    assert hit.cached and len(apple.apple_calls()) == calls
    assert ireland["localPrice"] == first.row("Ireland")["localPrice"]
    assert ireland["localPriceFormatted"] == first.row("Ireland")["localPriceFormatted"]
    assert ireland["usdPrice"] == round(ireland["localPrice"] / 0.80, 2)
    assert japan["usdPrice"] == round(japan["localPrice"] / 200.0, 2)
    assert hit.meta["rates"]["EUR"] == 0.80 and hit.meta["rates"]["JPY"] == 200.0
    prices = [r["usdPrice"] for r in hit.rows if r["available"]]
    assert prices == sorted(prices) and len(hit.rows) == 50
    stored = api._results_cache["macbook-air"]["payload"]
    assert next(r for r in stored["results"] if r["country"] == "Ireland")["usdPrice"] == first.row("Ireland")["usdPrice"]


def test_cache_hit_while_the_rate_service_is_down(server, apple, monkeypatch):
    first = server.search("MacBook Air")
    apple.rates["EUR"] = 0.80
    expire_rate_cache(monkeypatch)
    second = server.search("MacBook Air")
    expire_rate_cache(monkeypatch)
    apple.rates_down = True
    apple.rates["EUR"] = 0.5
    last_known = server.search("MacBook Air")
    assert last_known.cached and last_known.row("Ireland")["usdPrice"] == second.row("Ireland")["usdPrice"]
    assert last_known.meta["rates"]["EUR"] == 0.80
    monkeypatch.setattr(api, "_rates_cache", {})                     # no rates at all
    unchanged = server.search("MacBook Air")
    assert unchanged.row("Ireland")["usdPrice"] == first.row("Ireland")["usdPrice"]


@pytest.mark.parametrize("bad_rate", [..., -1], ids=["missing", "negative"])
def test_cache_hit_keeps_the_stored_conversion_without_a_usable_rate(server, apple, monkeypatch, bad_rate):
    first = server.search("MacBook Air")
    if bad_rate is ...:
        del apple.rates["INR"]
    else:
        apple.rates["INR"] = bad_rate
    expire_rate_cache(monkeypatch)
    assert server.search("MacBook Air").row("India")["usdPrice"] == first.row("India")["usdPrice"]


def test_absurd_rate_never_gives_zero(server, apple, monkeypatch):
    server.search("MacBook Air")
    apple.rates["INR"] = 1e12
    expire_rate_cache(monkeypatch)
    hit = server.search("MacBook Air")
    assert hit.row("India")["usdPrice"] is None
    assert [r for r in hit.rows if r["available"]][-1]["country"] == "India"
