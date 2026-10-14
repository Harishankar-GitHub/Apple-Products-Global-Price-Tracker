"""The API's contract with the page: endpoints, event order and the shape of every answer."""
import pytest

AVAILABLE_ROW = {"country", "flag", "available", "currency", "symbol", "localPrice", "localPriceFormatted", "usdPrice", "url"}
UNAVAILABLE_ROW = {"country", "flag", "available", "reason", "url"}


def test_stream_events_in_order(server):
    events = server.stream("MacBook Air")
    names = [e.name for e in events]
    assert names == ["searching", "meta"] + ["result"] * 50 + ["done"]
    assert events[0].data == {"product": "MacBook Air"}
    meta = events[1].data
    assert {"product", "slug", "category", "matchedName", "substituted", "total", "rates"} <= set(meta)
    assert (meta["slug"], meta["category"], meta["total"]) == ("macbook-air", "mac", 50)
    assert events[-1].data == {"product": "MacBook Air"}


def test_json_answer(server):
    body = server.get("MacBook Air").get_json()
    assert set(body) == {"product", "slug", "matchedName", "substituted", "category", "ratesDate", "rates",
                         "cached", "ageSeconds", "expiresInSeconds", "results"}
    assert len(body["results"]) == 50


def test_row_shapes(server, via):
    rows = server.search("MacBook Air", via=via).rows
    assert all(set(r) == (AVAILABLE_ROW if r["available"] else UNAVAILABLE_ROW) for r in rows)


@pytest.mark.parametrize(
    ("product", "country", "formatted"),
    [("MacBook Air", "United States", "$999.00"), ("iMac", "United States", "$1,299"), ("MacBook Air", "Japan", "¥145,354")],
    ids=["under-1000-two-decimals", "thousands-no-decimals", "large-local-price"],
)
def test_local_price_formatting(server, product, country, formatted):
    assert server.search(product).row(country)["localPriceFormatted"] == formatted


@pytest.mark.parametrize(
    ("product", "outage", "status", "events"),
    [
        (None, None, 400, ["error"]),
        ("x" * 81, None, 400, ["error"]),
        ("Nonexistent Thing", None, 404, ["searching", "error"]),
        ("MacBook Air", "timeout", 503, ["searching", "error"]),
    ],
    ids=["missing-name", "name-too-long", "not-found", "apple-not-answering"],
)
def test_a_failed_search_ends_the_same_way_on_both_endpoints(server, apple, product, outage, status, events):
    apple.outage = outage
    resp = server.get(product)
    streamed = server.stream(product)
    assert resp.status_code == status
    assert [e.name for e in streamed] == events
    assert streamed[-1].data == resp.get_json()                       # the same message, word for word


def test_page_on_another_site_may_call_the_api(client):
    resp = client.get("/api/health", headers={"Origin": "https://harishankar-github.github.io"})
    assert resp.headers["Access-Control-Allow-Origin"] in ("*", "https://harishankar-github.github.io")


def test_health(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_home(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "/api/prices" in resp.get_data(as_text=True)
