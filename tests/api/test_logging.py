"""What the API writes to its log: a line per look-up and per fetch, every problem with its reason, never a visitor's address."""
import logging
import re

import pytest

from tracker import config, create_app, exchange, lookup, search

VISITOR = "203.0.113.77"


@pytest.fixture
def logged(caplog):
    caplog.set_level(logging.INFO, logger="tracker")
    return caplog


def lines(caplog, logger: str) -> list[tuple[str, str]]:
    """(level, message) of each line `logger` wrote."""
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == logger]


def fetch_line(caplog) -> tuple[str, str]:
    [line] = lines(caplog, "tracker.search")
    return line


def test_a_fetch_is_one_line(server, logged):
    server.search("MacBook Air")
    level, message = fetch_line(logged)
    assert level == "INFO"
    assert re.fullmatch(r"Fetched macbook-air from 50 stores in \d+\.\d s: 30 priced, 20 not sold there, "
                        r"0 with a problem; kept for 6 h", message), message


def test_each_store_with_a_problem_is_named_with_the_reason(server, apple, logged):
    apple.store_failures["de"] = 503
    apple.store_failures["jp"] = "timeout"
    del apple.rates["INR"]
    server.search("iPhone 17")
    level, message = fetch_line(logged)
    assert level == "WARNING"
    assert message.endswith("28 priced, 20 not sold there, 3 with a problem (Germany: HTTP 503; "
                            "India: no usable exchange rate for INR; Japan: timeout); kept for 5 min"), message


def test_a_page_without_a_price(server, logged):
    server.search("AirTag")
    level, message = fetch_line(logged)
    assert level == "WARNING" and "0 priced, 20 not sold there, 30 with a problem" in message
    assert "Ireland: no price on the page;" in message and message.endswith("kept for 5 min")


def test_a_cached_search_logs_nothing(server, logged):
    server.search("MacBook Air")
    logged.clear()
    assert server.search("MacBook Air").cached
    assert logged.records == []


def test_look_ups(server, apple, logged):
    server.get("MacBook Air")
    server.get("Nonexistent Thing")
    assert lines(logged, "tracker.lookup") == [
        ("INFO", "Looked up 'MacBook Air': macbook-air"),
        ("INFO", "Looked up 'Nonexistent Thing': no page on apple.com")]


@pytest.mark.parametrize(
    ("outage", "suggestions", "said"),
    [("timeout", "Apple's search suggestions failed for 'Mac Studio' (timeout)", "timeout"),
     (503, "Apple's search suggestions answered HTTP 503 for 'Mac Studio'", "HTTP 503")],
)
def test_a_look_up_apple_did_not_answer(server, apple, logged, outage, suggestions, said):
    apple.outage = outage
    assert server.get("Mac Studio").status_code == 503
    assert lines(logged, "tracker.lookup") == [
        ("WARNING", suggestions),
        ("WARNING", f"Could not look up 'Mac Studio', as 12 checks failed: https://www.apple.com/mac-studio/ ({said}), "
                    f"https://www.apple.com/apple-mac-studio/ ({said}), https://www.apple.com/mac-studio-2/ ({said}) "
                    "and 9 more")]


def test_a_fallback_found_while_a_check_failed(server, apple, logged):
    apple.products["iphone-17-pro-max"] = 1199
    apple.url_failures["apple.com/iphone-17-pro-max/"] = "timeout"
    server.get("iPhone 17 Pro Max")
    assert lines(logged, "tracker.lookup") == [
        ("WARNING", "Looked up 'iPhone 17 Pro Max': iphone-17 for now, as 1 check failed: "
                    "https://www.apple.com/iphone-17-pro-max/ (timeout); looked up again in 5 min")]


def test_exchange_rates(server, apple, logged):
    server.search("MacBook Air")
    assert lines(logged, "tracker.exchange") == [("INFO", f"Exchange rates updated: {len(apple.rates)} currencies")]
    logged.clear()
    apple.rates_down = True
    exchange.refresh().result(timeout=10)
    exchange.clear()
    exchange.refresh().result(timeout=10)
    assert lines(logged, "tracker.exchange") == [
        ("WARNING", "Exchange rates not updated (timeout); still using the ones from 0 min ago"),
        ("WARNING", "Exchange rates not updated (timeout); there are none, so prices are sent without a dollar figure")]


def test_refusals(server, limits_on, logged):
    limits_on(requests=1)
    assert server.get("MacBook Air", "198.51.100.1").status_code == 200
    assert server.get("MacBook Air", "198.51.100.1").status_code == 429     # a second request in the minute
    limits_on(lookups=1)
    assert server.get("iMac", "198.51.100.2").status_code == 200
    assert server.get("iPhone 17", "198.51.100.2").status_code == 429       # a second look-up
    limits_on(all_lookups=2)
    assert server.get("AirPods Pro", "198.51.100.3").status_code == 429     # the third look-up of all
    assert lines(logged, "tracker.limits") == [
        ("INFO", "Refused a visitor: over 1 requests a minute"),
        ("INFO", "Refused a visitor: over 1 look-ups in 10 minutes"),
        ("WARNING", "Refused a visitor: every visitor together is over 2 look-ups in 10 minutes; "
                    "new products can be looked up again in 10 minutes")]


def test_a_search_turned_away_for_want_of_a_slot(server, monkeypatch, logged):
    lookup.discover_slug("prod7")
    monkeypatch.setattr(config, "FETCH_SLOT_WAIT", 0.2)
    monkeypatch.setattr(config, "FETCH_SLOT_NOTICE", 0.1)
    for _ in range(config.MAX_PARALLEL_FETCHES):
        search.fetch_slots.acquire()
    try:
        assert server.get("prod7").status_code == 503
    finally:
        for _ in range(config.MAX_PARALLEL_FETCHES):
            search.fetch_slots.release()
    assert lines(logged, "tracker.search") == [
        ("WARNING", "Turned away a search for prod7: no fetch slot came free within 0.2 s")]


def test_no_visitor_address_is_ever_logged(server, apple, limits_on, logged, via):
    limits_on(requests=4, lookups=2, all_lookups=60)
    other_addresses = {"X-Forwarded-For": f"{VISITOR}, 10.0.0.1", "X-Real-IP": VISITOR}
    apple.store_failures["de"] = 503
    for product in ("MacBook Air", "Nonexistent Thing", "iMac", "MacBook Air", "iPhone 17"):
        server.search(product, via=via, ip=VISITOR, headers=other_addresses)
    server.search("iPhone 17", via=via, headers=other_addresses)          # only the forwarded address
    assert len(logged.records) >= 6 and {"tracker.lookup", "tracker.search", "tracker.limits"} <= {
        r.name for r in logged.records}
    assert VISITOR not in logged.text and "10.0.0.1" not in logged.text


def test_the_log_goes_to_standard_error_once():
    create_app()
    create_app()
    tracker = logging.getLogger("tracker")
    assert tracker.level == logging.INFO and len(tracker.handlers) == 1
    [handler] = tracker.handlers
    assert type(handler) is logging.StreamHandler                       # created without a stream: standard error
    record = logging.LogRecord("tracker.search", logging.WARNING, __file__, 1, "a %s line", ("test",), None)
    assert re.fullmatch(r"\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}\] \[\d+\] \[WARNING\] tracker.search: a test line",
                        handler.format(record))
