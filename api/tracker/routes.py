"""The HTTP endpoints."""
import asyncio
import json
import queue
import threading

from flask import Blueprint, Response, jsonify, request, stream_with_context

from . import config, exchange, limits, lookup, prices, results_cache, search
from .countries import COUNTRIES
from .lookup import discover_slug, match_info, slug_is_known

bp = Blueprint("api", __name__)


def _limit_response(payload: dict):
    """HTTP 429 for the JSON endpoints."""
    resp = jsonify(payload)
    resp.status_code = 429
    resp.headers["Retry-After"] = str(payload["retryAfterSeconds"])
    return resp


def _sse_error(payload: dict) -> Response:
    """A stream that reports one error. EventSource cannot read the body of a
    non-200 reply, so stream errors are sent as an event the page can show."""
    def _gen():
        yield f"event: error\ndata: {json.dumps(payload)}\n\n"
    return Response(stream_with_context(_gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _cached_events(product: str, slug: str, category: str, hit: tuple[dict, int, int]):
    """SSE events that replay a results-cache hit: meta, every row, then done."""
    payload, age, expires_in = hit
    payload = results_cache.with_current_rates(payload, exchange.get_rates())
    meta = {"product": product, "slug": slug, "category": category,
            **match_info(product, slug),
            "total": len(payload["results"]), "cached": True,
            "ageSeconds": age, "expiresInSeconds": expires_in,
            "rates": payload.get("rates", {})}
    yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
    for row in payload["results"]:
        yield f"event: result\ndata: {json.dumps(row)}\n\n"
    yield f"event: done\ndata: {json.dumps({'product': product, 'cached': True})}\n\n"


@bp.route("/api/prices")
def get_prices():
    product = request.args.get("product", "").strip()
    if not product:
        return jsonify({"error": "Missing ?product= parameter"}), 400
    if len(product) > config.MAX_PRODUCT_LENGTH:
        return jsonify({"error": f"Product name is too long (max {config.MAX_PRODUCT_LENGTH} characters)."}), 400

    client, _ = limits.client_id(request)
    denied = limits.check_request(client)
    if denied:
        return _limit_response(denied)

    # Anything that needs apple.com is counted once per request: an unknown
    # name (slug look-up) and/or a product whose prices are not cached.
    charged = False
    if not slug_is_known(product):
        denied = limits.charge_fetch(client)
        if denied:
            return _limit_response(denied)
        charged = True

    found = discover_slug(product)
    if found.failed:                                 # Apple unreachable — not the same as "not found"
        resp = jsonify(search.lookup_failed_payload(product, found.retry_after))
        resp.status_code = 503
        resp.headers["Retry-After"] = str(found.retry_after)
        return resp
    if not found.result:
        return jsonify({
            "error": f"Could not find '{product}' on apple.com. "
                     "Check the product name, e.g. 'MacBook Air', 'iPhone Air', 'AirPods Pro'."
        }), 404

    slug, category = found.result

    def cached_reply(hit):
        payload, age, expires_in = hit
        payload = results_cache.with_current_rates(payload, exchange.get_rates())
        return jsonify({**payload, "product": product, **match_info(product, slug),
                        "cached": True, "ageSeconds": age, "expiresInSeconds": expires_in})

    hit = results_cache.get(slug)
    if hit:                                          # results-cache hit
        return cached_reply(hit)

    if not charged:
        denied = limits.charge_fetch(client)
        if denied:
            return _limit_response(denied)

    # Wait for a fetch slot (see MAX_PARALLEL_FETCHES).
    if not search.fetch_slots.acquire(timeout=config.FETCH_SLOT_WAIT):
        resp = jsonify(search.busy_payload())
        resp.status_code = 503
        resp.headers["Retry-After"] = "10"
        return resp
    try:
        hit = results_cache.get(slug)   # someone may have fetched this product while this request waited
        if hit:
            return cached_reply(hit)
        rates    = exchange.get_rates()
        all_rows = asyncio.run(prices.fetch_all_prices(slug, category, rates))
    finally:
        search.fetch_slots.release()
    failed     = [prices.pop_transient(r) for r in all_rows]   # strips the marker from every row

    payload = results_cache.build_payload(product, slug, category, rates, all_rows)
    ttl     = results_cache.put(slug, payload, complete=not any(failed))
    return jsonify({**payload, **match_info(product, slug), "cached": False,
                    "ageSeconds": 0, "expiresInSeconds": ttl})


@bp.route("/api/prices/stream")
def get_prices_stream():
    """SSE endpoint — results stream back as each country completes."""
    product = request.args.get("product", "").strip()
    if not product:
        return _sse_error({"error": "Missing ?product= parameter"})
    if len(product) > config.MAX_PRODUCT_LENGTH:
        return _sse_error({"error": f"Product name is too long (max {config.MAX_PRODUCT_LENGTH} characters)."})

    client, _ = limits.client_id(request)
    denied = limits.check_request(client)
    if denied:
        return _sse_error(denied)

    def generate():
        # Tell the UI we're working before the (potentially slow) slug resolution
        yield f"event: searching\ndata: {json.dumps({'product': product})}\n\n"

        # Anything that needs apple.com is counted once per request (see get_prices).
        charged = False
        if not slug_is_known(product):
            denied = limits.charge_fetch(client)
            if denied:
                yield f"event: error\ndata: {json.dumps(denied)}\n\n"
                return
            charged = True

        found = discover_slug(product)              # instant on repeat
        if found.failed:                            # Apple unreachable — not the same as "not found"
            payload = search.lookup_failed_payload(product, found.retry_after)
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"
            return
        if not found.result:
            msg = (f"Could not find \"{product}\" on apple.com. "
                   "Try a different name, e.g. \"MacBook Air\", \"iPhone Air\", \"AirPods Pro\".")
            yield f"event: error\ndata: {json.dumps({'error': msg})}\n\n"
            return

        slug, category = found.result

        # Results-cache hit — replay stored rows as fast SSE events
        hit = results_cache.get(slug)
        if hit:
            yield from _cached_events(product, slug, category, hit)
            return

        if not charged:
            denied = limits.charge_fetch(client)
            if denied:
                yield f"event: error\ndata: {json.dumps(denied)}\n\n"
                return

        # Wait for a fetch slot (see MAX_PARALLEL_FETCHES).
        got_slot = yield from search.wait_for_fetch_slot()
        if not got_slot:
            yield f"event: error\ndata: {json.dumps(search.busy_payload())}\n\n"
            return

        # This generator holds the slot now. Nothing below yields until the
        # background thread has taken it over, so closing the page cannot leave
        # it held; anything that fails before then gives it back.
        hit = results_cache.get(slug)   # someone may have fetched this product while this search waited
        if hit:
            search.fetch_slots.release()
            yield from _cached_events(product, slug, category, hit)
            return
        try:
            rates = exchange.get_rates()
            meta  = {"product": product, "slug": slug, "category": category,
                     **match_info(product, slug),
                     "total": len(COUNTRIES), "rates": exchange.rates_for_client(rates)}

            # ── Queue bridge ─────────────────────────────────────────────────
            # A background thread runs the asyncio event loop and puts each row
            # into `q` as soon as its coroutine resolves.  This generator pulls
            # from `q` immediately — Flask flushes each SSE event to the client
            # without waiting for all 50 countries to finish. The thread stores
            # the finished set in the results cache and releases the fetch slot.
            q = queue.Queue()
            t = threading.Thread(
                target=prices.stream_prices_into_queue,
                args=(product, slug, category, rates, q, search.fetch_slots),
                daemon=True,
            )
            t.start()
        except BaseException:
            search.fetch_slots.release()
            raise

        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"

        while True:
            row = q.get()           # blocks only until the next country finishes
            if row is prices.SENTINEL or row is prices.FAILED:
                break
            yield f"event: result\ndata: {json.dumps(row)}\n\n"

        t.join()                    # the results are cached and the slot is free

        if row is prices.FAILED:    # nothing was cached; the visitor is told to try again
            yield f"event: error\ndata: {json.dumps(search.fetch_failed_payload())}\n\n"
            return
        yield f"event: done\ndata: {json.dumps({'product': product})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        return _limit_response(denied)

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
