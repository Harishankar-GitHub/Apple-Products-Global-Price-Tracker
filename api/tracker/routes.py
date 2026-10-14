"""
The HTTP endpoints. Both price endpoints run the same search (search.py) and
differ only in how they send it: /api/prices/stream as server-sent events while
it happens, /api/prices as one JSON answer at the end.
"""
import json
from typing import Iterator

from flask import Blueprint, Response, jsonify, request, stream_with_context

from . import config, exchange, limits, lookup, results_cache, search

bp = Blueprint("api", __name__)


def _json_error(status: int, payload: dict) -> Response:
    """An error answer, with a Retry-After header when trying again later can work."""
    resp = jsonify(payload)
    resp.status_code = status
    if "retryAfterSeconds" in payload:
        resp.headers["Retry-After"] = str(payload["retryAfterSeconds"])
    return resp


@bp.route("/api/prices")
def get_prices():
    """The whole result set as JSON, once every store has answered."""
    client, _ = limits.client_id(request)
    found = None
    rows: list[dict] = []
    for step in search.run(request.args.get("product", ""), client):
        match step:
            case search.Failed(status, payload):
                return _json_error(status, payload)
            case search.Prices():
                found = step
            case search.Row(row):
                rows.append(row)
            case search.Finished(expires_in):
                return jsonify({
                    "product": found.product, "slug": found.slug, "category": found.category,
                    **found.matched,
                    "ratesDate": "live", "rates": found.rates,
                    "cached": found.cached, "ageSeconds": found.age or 0, "expiresInSeconds": expires_in,
                    "results": results_cache.sorted_results(rows),
                })
    raise RuntimeError("the search ended without an answer")      # search.run always ends with one


@bp.route("/api/prices/stream")
def get_prices_stream():
    """Server-sent events: each store's row as soon as it answers."""
    client, _ = limits.client_id(request)
    steps = search.run(request.args.get("product", ""), client)
    return Response(stream_with_context(_as_events(steps)), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _as_events(steps: Iterator[search.Step]) -> Iterator[str]:
    """
    The search as the page's EventSource receives it. Errors are sent as an
    `error` event too: EventSource cannot read the body of a non-200 reply.
    """
    found = None
    for step in steps:
        match step:
            case search.Searching(product):
                yield _event("searching", {"product": product})
            case search.Queued(max_wait):
                yield _event("queued", {"message": "Waiting for other searches to finish",
                                        "maxWaitSeconds": max_wait})
            case search.StillQueued():
                yield ": still waiting for a free fetch slot\n\n"    # a comment line: keeps the connection open
            case search.Prices():
                found = step
                meta = {"product": step.product, "slug": step.slug, "category": step.category,
                        **step.matched, "total": step.total}
                if step.cached:
                    meta.update(cached=True, ageSeconds=step.age, expiresInSeconds=step.expires_in)
                yield _event("meta", {**meta, "rates": step.rates})
            case search.Row(row):
                yield _event("result", row)
            case search.Finished():
                yield _event("done", {"product": found.product, "cached": True} if found.cached
                                     else {"product": found.product})
            case search.Failed(_, payload):
                yield _event("error", payload)


@bp.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@bp.route("/api/cache/status")
def cache_status():
    """
    Cache and rate-limit state. The public view has totals only. What people
    searched for (slug-cache keys, cached product slugs) is shown only to a
    request carrying ADMIN_TOKEN in an `X-Admin-Token` or
    `Authorization: Bearer` header.
    """
    client, source = limits.client_id(request)
    denied = limits.check_request(client)
    if denied:
        return _json_error(429, denied)

    body = {
        "exchange_rates": exchange.status(),
        "slug_cache": {
            "entries": lookup.size(),
            "max_entries": config.SLUG_CACHE_MAX,
            "not_found_ttl_seconds": config.SLUG_TTL_NOT_FOUND,
            "failed_lookup_ttl_seconds": config.SLUG_TTL_FAILED,
        },
        "results_cache": {
            "entries": results_cache.size(),
            "max_entries": config.RESULTS_CACHE_MAX,
            "ttl_seconds":            config.RESULTS_TTL,
            "ttl_seconds_incomplete": config.RESULTS_TTL_SHORT,
        },
        "rate_limits": {
            "requests_per_minute":             limits.request_limiter.limit,
            "apple_lookups_per_10_minutes":    limits.fetch_limiter.limit,
            "apple_lookups_per_10_minutes_all_visitors": limits.global_fetch_limiter.limit,
            "apple_lookups_used_all_visitors": limits.global_fetch_limiter.count("all"),
            "visitors_tracked": limits.request_limiter.tracked(),
        },
        "details": "shown",
    }
    if not limits.is_admin(request):
        body["details"] = "hidden — send the admin token to see search terms and product slugs"
        return jsonify(body)

    body["slug_cache"]["keys"] = lookup.names()
    body["results_cache"]["slugs"] = results_cache.status()
    # How this server identified you — use it to confirm visitors are told apart correctly.
    body["you"] = {"address": client, "identified_by": source}
    return jsonify(body)


@bp.route("/")
def index():
    return "Apple Products Global Price Tracker API — /api/prices?product=MacBook+Air"
