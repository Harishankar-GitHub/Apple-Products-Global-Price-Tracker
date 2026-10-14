"""
Searches that need apple.com: the fetch slots they wait for, and the messages
sent when one cannot go ahead.
"""
import json
import threading
import time

from . import config, limits

# Searches that fetch from apple.com at the same time (see config.MAX_PARALLEL_FETCHES).
fetch_slots = threading.BoundedSemaphore(config.MAX_PARALLEL_FETCHES)


def busy_payload() -> dict:
    return {"error": "The service is busy fetching prices for other visitors. "
                     "Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


def lookup_failed_payload(product: str, wait: int) -> dict:
    return {"error": f"Apple did not respond while looking up \"{product}\", so it could not be "
                     f"checked. Please try again in {limits.human_wait(wait)}.",
            "temporary": True, "retryAfterSeconds": wait}


def fetch_failed_payload() -> dict:
    return {"error": "Something went wrong while fetching prices. Please try again in a few seconds.",
            "temporary": True, "retryAfterSeconds": 10}


def wait_for_fetch_slot():
    """
    For the stream route (use with `yield from`): waits up to config.FETCH_SLOT_WAIT
    seconds for a fetch slot and returns True once it holds one, False if none
    came free. While waiting it tells the page (a `queued` event, then a comment
    line every few seconds). Writing to the connection also notices a visitor
    who has closed the page, which ends the wait instead of taking a slot that
    nobody needs any more.
    """
    if fetch_slots.acquire(blocking=False):
        return True
    queued = {"message": "Waiting for other searches to finish", "maxWaitSeconds": config.FETCH_SLOT_WAIT}
    yield f"event: queued\ndata: {json.dumps(queued)}\n\n"
    deadline = time.monotonic() + config.FETCH_SLOT_WAIT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if fetch_slots.acquire(timeout=min(config.FETCH_SLOT_NOTICE, remaining)):
            return True
        yield ": still waiting for a free fetch slot\n\n"
