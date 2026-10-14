"""
One search, from start to finish, for both price endpoints.

`run()` produces the search as a sequence of steps. /api/prices/stream sends
each step to the page as it happens; /api/prices waits for the last one and
answers with the whole result set. So both endpoints make the same checks, in
the same order, with the same messages:

  1. the product name: present, and not too long
  2. limit 1: requests per visitor                 (see limits.py)
  3. limits 2 and 3, if the name needs looking up on apple.com
  4. the name → Apple's page for it                (see lookup.py)
  5. the results cache: a hit is sent with the current exchange rates
  6. limits 2 and 3, if not counted at step 3 (the prices need apple.com)
  7. a fetch slot: wait up to config.FETCH_SLOT_WAIT seconds for one
  8. the results cache again: the search ahead may have fetched this product
  9. every store, on the shared event loop (web.py): rows are sent as they
     arrive, then the finished set is cached

The steps a search can produce, in order:

  Searching          the request is accepted; work starts
  Queued             (only if no fetch slot is free) the search waits for one
  StillQueued        …and is still waiting; repeats every FETCH_SLOT_NOTICE seconds
  Prices             what was found, and how many rows follow
  Row                one store's row (as many as Prices.total)
  Finished           every row has been sent
  Failed             the search ends here, at any point, with this error
"""
import concurrent.futures
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Generator, Iterator, Optional, Union

from . import config, exchange, limits, lookup, prices, results_cache, web
from .countries import COUNTRIES

log = logging.getLogger(__name__)

# Searches that fetch from apple.com at the same time (see config.MAX_PARALLEL_FETCHES).
fetch_slots = threading.BoundedSemaphore(config.MAX_PARALLEL_FETCHES)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Searching:
    product: str


@dataclass(frozen=True)
class Queued:
    max_wait: float                     # seconds the search will wait for a slot


@dataclass(frozen=True)
class StillQueued:
    pass


@dataclass(frozen=True)
class Prices:
    product: str                        # as typed
    slug: str
    category: str
    matched: dict                       # {"matchedName", "substituted"}, see lookup.match_info
    rates: dict                         # units per 1 USD, for the currencies listed
    total: int                          # rows that follow
    age: Optional[int] = None           # cache hit: seconds since the prices were fetched
    expires_in: Optional[int] = None    # cache hit: seconds until they are fetched again

    @property
    def cached(self) -> bool:
        return self.age is not None


@dataclass(frozen=True)
class Row:
    row: dict


@dataclass(frozen=True)
class Finished:
    expires_in: int                     # seconds until these prices are fetched again


@dataclass(frozen=True)
class Failed:
    status: int                         # what /api/prices answers with: 400, 404, 429 or 503
    payload: dict                       # {"error": message}, plus "rateLimited" or "temporary" and
                                        # "retryAfterSeconds" when trying again later can work


Step = Union[Searching, Queued, StillQueued, Prices, Row, Finished, Failed]


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def not_found_payload(product: str) -> dict:
    return {"error": f"Could not find \"{product}\" on apple.com. "
                     "Try a different name, e.g. \"MacBook Air\", \"iPhone Air\", \"AirPods Pro\"."}


def lookup_failed_payload(product: str, wait: int) -> dict:
    return {"error": f"Apple did not respond while looking up \"{product}\", so it could not be "
                     f"checked. Please try again in {limits.human_wait(wait)}.",
            "temporary": True, "retryAfterSeconds": wait}


def busy_payload() -> dict:
    return {"error": "The service is busy fetching prices for other visitors. "
                     "Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


def fetch_failed_payload() -> dict:
    return {"error": "Something went wrong while fetching prices. Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------

def run(product: str, client: str) -> Iterator[Step]:
    """Search for `product` on behalf of `client` (the visitor's address, see limits.client_id)."""
    product = product.strip()
    if not product:
        yield Failed(400, {"error": "Missing ?product= parameter"})
        return
    if len(product) > config.MAX_PRODUCT_LENGTH:
        yield Failed(400, {"error": f"Product name is too long (max {config.MAX_PRODUCT_LENGTH} characters)."})
        return
    denied = limits.check_request(client)
    if denied:
        yield Failed(429, denied)
        return

    yield Searching(product)                # before the look-up, which can take a few seconds

    # Anything that needs apple.com is counted once per request: an unknown
    # name (the look-up) and/or a product whose prices are not cached.
    charged = False
    if not lookup.slug_is_known(product):
        denied = limits.charge_fetch(client)
        if denied:
            yield Failed(429, denied)
            return
        charged = True

    found = lookup.discover_slug(product)
    if found.failed:                        # Apple did not answer — not the same as "not found"
        yield Failed(503, lookup_failed_payload(product, found.retry_after))
        return
    if not found.result:
        yield Failed(404, not_found_payload(product))
        return
    slug, category = found.result
    matched = lookup.match_info(product, slug)

    hit = results_cache.get(slug)
    if hit:
        yield from _replay(product, slug, category, matched, hit)
        return

    if not charged:
        denied = limits.charge_fetch(client)
        if denied:
            yield Failed(429, denied)
            return

    slots = fetch_slots
    if not (yield from _wait_for_slot(slots)):
        log.warning("Turned away a search for %s: no fetch slot came free within %g s",
                    slug, config.FETCH_SLOT_WAIT)
        yield Failed(503, busy_payload())
        return

    # This search holds a slot now. Nothing below yields until the fetch has
    # taken it over, so a visitor who closes the page cannot leave it held;
    # anything that fails before then gives it back.
    hit = results_cache.get(slug)           # the search ahead may have fetched this product
    if hit:
        slots.release()
        yield from _replay(product, slug, category, matched, hit)
        return
    try:
        rates = exchange.get_rates()
        steps = _fetch_in_background(product, slug, category, rates, slots)
    except BaseException:
        slots.release()
        raise

    yield Prices(product, slug, category, matched, exchange.rates_for_client(rates), total=len(COUNTRIES))
    while True:
        step = steps.get()                  # waits only until the next store answers
        yield step
        if not isinstance(step, Row):       # Finished, or Failed if the fetch broke off
            return


def _replay(product: str, slug: str, category: str, matched: dict,
            hit: tuple[dict, int, int]) -> Iterator[Step]:
    """A results-cache hit, with dollar prices worked out from the current exchange rates."""
    payload, age, expires_in = hit
    payload = results_cache.with_current_rates(payload, exchange.get_rates())
    rows = payload["results"]
    yield Prices(product, slug, category, matched, payload.get("rates", {}), total=len(rows),
                 age=age, expires_in=expires_in)
    for row in rows:
        yield Row(row)
    yield Finished(expires_in)


def _wait_for_slot(slots: threading.BoundedSemaphore) -> Generator[Step, None, bool]:
    """
    Use with `yield from`: takes a slot from `slots` and returns True, or
    returns False if none came free within config.FETCH_SLOT_WAIT seconds.
    While waiting it yields Queued, then StillQueued every FETCH_SLOT_NOTICE
    seconds. Sending those to the page also notices a visitor who has closed
    it, which ends the wait instead of taking a slot nobody needs any more.
    """
    if slots.acquire(blocking=False):
        return True
    yield Queued(config.FETCH_SLOT_WAIT)
    deadline = time.monotonic() + config.FETCH_SLOT_WAIT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if slots.acquire(timeout=min(config.FETCH_SLOT_NOTICE, remaining)):
            return True
        yield StillQueued()


def _fetch_in_background(product: str, slug: str, category: str, rates: dict[str, float],
                         slot: threading.BoundedSemaphore) -> "queue.Queue[Step]":
    """
    Start fetching every store on the shared event loop (see web.py), which
    takes over `slot` (a fetch slot this search holds). Returns the queue the
    fetch puts its steps on: a Row per store as each one answers, then
    Finished or Failed.

    The fetch caches the finished set itself, so it is not wasted if the
    visitor closes the page part-way, and the slot is given back only after
    that: a search waiting for the slot then finds these prices in the cache
    instead of fetching them again.
    """
    steps: "queue.Queue[Step]" = queue.Queue()
    fetch = web.submit(_fetch_every_store(product, slug, category, rates, steps))
    fetch.add_done_callback(lambda done: _hand_back(done, slug, slot, steps))
    return steps


async def _fetch_every_store(product: str, slug: str, category: str, rates: dict[str, float],
                             steps: "queue.Queue[Step]") -> int:
    """Puts a Row on `steps` for each store, caches the finished set and returns how long it is kept."""
    started = time.monotonic()
    rows: list[dict] = []
    problems: list[str] = []
    complete = True                         # False once any store's answer may change soon
    async for answer in prices.fetch_every_store(slug, category, rates):
        complete = complete and not answer.transient
        rows.append(answer.row)
        if answer.problem:
            problems.append(f"{answer.row['country']}: {answer.problem}")
        steps.put(Row(answer.row))
    kept = results_cache.put(slug, results_cache.build_payload(product, slug, category, rates, rows), complete)
    _log_fetch(slug, rows, sorted(problems), time.monotonic() - started, kept)
    return kept


def _log_fetch(slug: str, rows: list[dict], problems: list[str], seconds: float, kept: int) -> None:
    """One line per fetch: how it went, and every store that had a problem and why."""
    priced = sum(1 for r in rows if r.get("available"))
    not_sold = sum(1 for r in rows if r.get("reason") == "Not available in this country")
    level = logging.INFO if kept == config.RESULTS_TTL else logging.WARNING
    log.log(level, "Fetched %s from %d stores in %.1f s: %d priced, %d not sold there, %d with a problem%s; "
            "kept for %s", slug, len(rows), seconds, priced, not_sold, len(problems),
            f" ({'; '.join(problems)})" if problems else "",
            f"{kept / 3600:g} h" if kept >= 3600 else f"{kept / 60:g} min")


def _hand_back(fetch: concurrent.futures.Future, slug: str, slot: threading.BoundedSemaphore,
               steps: "queue.Queue[Step]") -> None:
    """
    When a fetch ends, however it ends (even cancelled before it started):
    give the slot back, then send the search its last step.
    """
    last: Step = Failed(503, fetch_failed_payload())
    try:
        slot.release()
        if not fetch.cancelled():
            if fetch.exception() is None:
                last = Finished(fetch.result())
            else:
                log.error("Fetching the prices of %r broke off", slug, exc_info=fetch.exception())
    finally:
        steps.put(last)                     # the search never waits forever
